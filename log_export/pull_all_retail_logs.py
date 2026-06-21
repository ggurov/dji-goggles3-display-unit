#!/usr/bin/env python3
"""Pull all export_list logs from retail bulk USB and decrypt on donor.

Usage:
  python pull_all_retail_logs.py [--limit N] [--resume] [--decrypt-only DIR]
  python pull_all_retail_logs.py --no-decrypt

Requires retail goggles on USB (donor ADB for decrypt). Close DJI Assistant.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_EXPORT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "goggles_tool"))
sys.path.insert(0, str(LOG_EXPORT))

from goggles_tool.client import GogglesClient  # noqa: E402
from goggles_tool.protocol import duss  # noqa: E402

RETAIL_BUS = 0
RETAIL_ADDR: int | None = None
BATCH = LOG_EXPORT / "batch_decrypt.py"
OUTPUT_ROOT = LOG_EXPORT / "output" / "bulk_pull"
_PATH_RE = re.compile(r"^/blackbox/[A-Za-z0-9_./-]+$")
_ENTRY_RE = re.compile(
    r'"path"\s*:\s*"([^"]+)"[^}]*?"size"\s*:\s*(\d+)[^}]*?"mtime"\s*:\s*(\d+)',
    re.DOTALL,
)


def entries_from_raw(raw: bytes) -> list[dict]:
    parsed = duss.extract_json_blob(raw)
    if parsed is not None:
        try:
            obj = json.loads(parsed.decode("utf-8"))
            if isinstance(obj, dict) and isinstance(obj.get("log_list"), list):
                return [e for e in obj["log_list"] if isinstance(e, dict) and e.get("path")]
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    text = duss._collect_export_json_parts(raw).decode("utf-8", errors="replace")
    out: list[dict] = []
    seen: set[str] = set()
    for path, size_s, mtime_s in _ENTRY_RE.findall(text):
        if not _PATH_RE.match(path) or path in seen:
            continue
        seen.add(path)
        out.append({"path": path, "size": int(size_s), "mtime": int(mtime_s)})
    if not out:
        for path in duss.extract_log_paths(raw):
            if path not in seen:
                out.append({"path": path, "size": 0, "mtime": 0})
    return out


def safe_name(path: str) -> str:
    return path.removeprefix("/blackbox/").replace("/", "__")


def timeout_for(size: int) -> float:
    if size > 50_000_000:
        return max(900.0, size / 35_000 + 180.0)
    if size > 5_000_000:
        return 600.0
    return 300.0


def max_bytes_for(size: int) -> int:
    if size > 0:
        return min(size + 131_072, 200_000_000)
    return 50_000_000


def is_complete(dest: Path, size_hint: int) -> bool:
    if not dest.is_file():
        return False
    data = dest.read_bytes()
    if not data.startswith(b"LOGH"):
        return size_hint <= 0 or len(data) >= int(size_hint * 0.95)
    if size_hint <= 0:
        return len(data) > 0xB0
    return len(data) >= int(size_hint * 0.95)


def run_decrypt(files_dir: Path, out_dir: Path) -> int:
    print("\nRunning batch_decrypt on donor…", file=sys.stderr)
    r = subprocess.run(
        [sys.executable, str(BATCH), "bulk", str(files_dir)],
        capture_output=True,
        text=True,
    )
    print(r.stdout)
    if r.stderr:
        print(r.stderr, file=sys.stderr)
    (out_dir / "decrypt_stdout.txt").write_text(r.stdout + (r.stderr or ""), encoding="utf-8")
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="Max files (0 = all)")
    ap.add_argument("--resume", action="store_true", help="Skip files already complete in manifest")
    ap.add_argument("--decrypt-only", metavar="DIR", help="Only decrypt LOGH in DIR")
    ap.add_argument("--retries", type=int, default=2, help="Retries per short file")
    ap.add_argument("--no-decrypt", action="store_true", help="Skip donor batch_decrypt (pull only)")
    ap.add_argument("-o", "--output-dir", help="Output folder under log_export/output/bulk_pull/")
    ap.add_argument("--bus", type=int, default=RETAIL_BUS)
    ap.add_argument("--address", type=int, default=None, help="USB device address (default: auto)")
    args = ap.parse_args()

    if args.decrypt_only:
        d = Path(args.decrypt_only)
        return run_decrypt(d / "files" if (d / "files").is_dir() else d, d)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = (
        Path(args.output_dir)
        if args.output_dir
        else OUTPUT_ROOT / f"pull_{stamp}_all"
    )
    files_dir = out_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest: list[dict] = []
    if args.resume and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    c = GogglesClient(verbose=True)
    c.connect(interface=4, bus=args.bus, address=args.address)
    try:
        print("Priming export session…", file=sys.stderr)
        c.get_version_xml()
        c._drain(0.15)
        c._prime_log_export_session()
        c._sess["primed"] = True
        raw = c.logs_list()
        (out_dir / "export_list.raw.bin").write_bytes(raw)
        entries = entries_from_raw(raw)
        entries.sort(key=lambda e: int(e.get("mtime") or 0), reverse=True)
        if args.limit > 0:
            entries = entries[: args.limit]
        print(f"export_list: {len(entries)} files to pull", file=sys.stderr)
        (out_dir / "export_list_entries.json").write_text(
            json.dumps(entries, indent=2), encoding="utf-8"
        )

        done_paths = {m["path"] for m in manifest if m.get("complete")}
        for i, ent in enumerate(entries, 1):
            path = ent["path"]
            size = int(ent.get("size") or 0)
            dest = files_dir / safe_name(path)
            if args.resume and path in done_paths and is_complete(dest, size):
                print(f"[{i}/{len(entries)}] skip (complete) {path}", file=sys.stderr)
                continue
            print(f"\n[{i}/{len(entries)}] {path}  size={size:,}", file=sys.stderr)
            row: dict = {"path": path, "size_hint": size, "dest": str(dest)}
            ok = False
            for attempt in range(1 + args.retries):
                if attempt:
                    print(f"  retry {attempt}/{args.retries}…", file=sys.stderr)
                    time.sleep(1.0)
                t0 = time.time()
                try:
                    got = c.logs_download(
                        dest,
                        path=path,
                        max_bytes=max_bytes_for(size),
                        expected_size=size if size else None,
                        timeout_s=timeout_for(size),
                        idle_done_s=8.0 if size > 20_000_000 else 4.0,
                        strip_duss=True,
                    )
                    row["bytes"] = got
                    row["elapsed_s"] = round(time.time() - t0, 1)
                    row["logh"] = dest.read_bytes()[:4] == b"LOGH" if dest.is_file() else False
                    row["complete"] = is_complete(dest, size)
                    ok = row["complete"]
                    print(
                        f"  -> {got:,} B complete={row['complete']} logh={row['logh']} "
                        f"({row['elapsed_s']}s)",
                        file=sys.stderr,
                    )
                    if ok:
                        break
                except Exception as e:
                    row["error"] = str(e)
                    print(f"  ERROR: {e}", file=sys.stderr)
            manifest = [m for m in manifest if m.get("path") != path]
            manifest.append(row)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            time.sleep(0.3)
    finally:
        c.close()

    complete = sum(1 for m in manifest if m.get("complete"))
    short = sum(
        1
        for m in manifest
        if m.get("bytes") and not m.get("complete") and not m.get("error")
    )
    print(f"\nManifest: {manifest_path}", file=sys.stderr)
    print(f"Complete: {complete}/{len(manifest)}  short/incomplete: {short}", file=sys.stderr)

    if args.no_decrypt:
        print("Skipping decrypt (--no-decrypt)", file=sys.stderr)
        return 0 if complete == len(manifest) else 1

    rc = run_decrypt(files_dir, out_dir)
    return 0 if complete == len(manifest) and rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
