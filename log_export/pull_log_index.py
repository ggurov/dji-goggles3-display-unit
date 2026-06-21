#!/usr/bin/env python3
"""Pull one DJI Assistant Log Index (boot_index bundle) from retail bulk USB.

Assistant exports a log index as one bulk session: export_list once, log_open once,
then sequential 090104 file downloads without re-opening the session per file.

Usage:
  python pull_log_index.py --list
  python pull_log_index.py 82 [--no-decrypt] [--resume]
  python pull_log_index.py --flight 235 [--no-decrypt] [--resume]

Requires retail on USB. Close DJI Assistant first.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_EXPORT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "goggles_tool"))
sys.path.insert(0, str(LOG_EXPORT))

from goggles_tool.client import BundleDownloadItem, GogglesClient  # noqa: E402
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


def parse_export_list(raw: bytes) -> dict | None:
    parsed = duss.extract_json_blob(raw)
    if parsed is None:
        return None
    try:
        obj = json.loads(parsed.decode("utf-8"))
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def entries_from_raw(raw: bytes) -> list[dict]:
    obj = parse_export_list(raw)
    if obj and isinstance(obj.get("log_list"), list):
        return [e for e in obj["log_list"] if isinstance(e, dict) and e.get("path")]
    text = duss._collect_export_json_parts(raw).decode("utf-8", errors="replace")
    out: list[dict] = []
    seen: set[str] = set()
    for path, size_s, mtime_s in _ENTRY_RE.findall(text):
        if not _PATH_RE.match(path) or path in seen:
            continue
        seen.add(path)
        out.append({"path": path, "size": int(size_s), "mtime": int(mtime_s)})
    return out


def boot_indices(obj: dict | None) -> list[dict]:
    if not obj or not isinstance(obj.get("boot_list"), list):
        return []
    rows: list[dict] = []
    for row in obj["boot_list"]:
        if not isinstance(row, dict):
            continue
        bi = row.get("boot_index")
        if bi is None:
            continue
        rows.append(
            {
                "boot_index": int(bi),
                "ctime_s": row.get("ctime_s", ""),
                "mtime_s": row.get("mtime_s", ""),
                "latest_flight": row.get("latest_flight"),
            }
        )
    rows.sort(key=lambda r: r["boot_index"], reverse=True)
    return rows


def entries_for_index(entries: list[dict], boot_index: int) -> list[dict]:
    matched: list[dict] = []
    for ent in entries:
        bi = ent.get("boot_index")
        triggers = ent.get("trigger_index") or []
        if bi == boot_index or boot_index in triggers:
            matched.append(ent)
    matched.sort(key=lambda e: (e.get("path") or ""))
    return matched


def entries_for_flight(entries: list[dict], flight_num: int) -> list[dict]:
    needle = f"/blackbox/flight{flight_num:04d}/"
    matched = [e for e in entries if needle in (e.get("path") or "")]
    matched.sort(key=lambda e: (e.get("path") or ""))
    return matched


def enrich_entries_from_raw(raw: bytes, entries: list[dict]) -> list[dict]:
    if entries and entries[0].get("boot_index") is not None:
        return entries
    text = duss._collect_export_json_parts(raw).decode("utf-8", errors="replace")
    by_path: dict[str, dict] = {e["path"]: dict(e) for e in entries}
    block_re = re.compile(
        r'"path"\s*:\s*"([^"]+)"[^}]*?"boot_index"\s*:\s*(\d+)(?:[^}]*?"trigger_index"\s*:\s*\[([^\]]*)\])?',
        re.DOTALL,
    )
    for path, bi_s, triggers_s in block_re.findall(text):
        if path not in by_path:
            continue
        by_path[path]["boot_index"] = int(bi_s)
        if triggers_s:
            nums = [int(x.strip()) for x in triggers_s.split(",") if x.strip().isdigit()]
            by_path[path]["trigger_index"] = nums
    return list(by_path.values())


def safe_name(path: str) -> str:
    return path.removeprefix("/blackbox/").replace("/", "__")


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
    ap.add_argument("index", type=int, nargs="?", help="Log index / boot_index to export")
    ap.add_argument("--flight", type=int, metavar="N", help="Pull all paths under flightNNNN/")
    ap.add_argument("--list", action="store_true", help="List boot indices from export_list")
    ap.add_argument("--resume", action="store_true", help="Skip files already complete")
    ap.add_argument("--no-decrypt", action="store_true", help="Pull only; skip donor decrypt")
    ap.add_argument("-o", "--output-dir", help="Output folder (default: log_export/output/bulk_pull/...)")
    ap.add_argument("--bus", type=int, default=RETAIL_BUS)
    ap.add_argument("--address", type=int, default=None, help="USB device address (default: auto)")
    args = ap.parse_args()

    c = GogglesClient(verbose=True)
    c.connect(interface=4, bus=args.bus, address=args.address)
    try:
        print("Fetching export_list…", file=sys.stderr)
        c.get_version_xml()
        c._drain(0.15)
        c._prime_log_export_session()
        c._sess["primed"] = True
        raw = c.logs_list()
        obj = parse_export_list(raw)
        entries = enrich_entries_from_raw(raw, entries_from_raw(raw))
        extra_paths = duss.extract_log_paths(raw)
        known = {e["path"] for e in entries}
        for path in extra_paths:
            if path not in known:
                entries.append({"path": path, "size": 0, "mtime": 0})
        indices = boot_indices(obj)

        if args.list:
            print(f"boot_list entries: {len(indices)}  log_list entries: {len(entries)}\n")
            for row in indices[:30]:
                bi = row["boot_index"]
                n = len(entries_for_index(entries, bi))
                sz = sum(int(e.get("size") or 0) for e in entries_for_index(entries, bi))
                print(
                    f"  index {bi:4d}  files={n:3d}  ~{sz / 1_048_576:.1f} MB  "
                    f"mtime={row.get('mtime_s', '')}"
                )
            return 0

        if args.index is None and args.flight is None:
            ap.error("provide log index or --flight N (or use --list)")

        if args.flight is not None:
            pick = entries_for_flight(entries, args.flight)
            label = f"flight{args.flight:04d}"
        else:
            boot_index = args.index
            pick = entries_for_index(entries, boot_index)
            label = f"idx{boot_index}"
        if not pick:
            target = f"flight {args.flight:04d}" if args.flight else f"boot_index={args.index}"
            print(f"No export_list entries for {target}", file=sys.stderr)
            return 1

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = (
            Path(args.output_dir)
            if args.output_dir
            else OUTPUT_ROOT / f"pull_{stamp}_{label}"
        )
        files_dir = out_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "export_list.raw.bin").write_bytes(raw)
        (out_dir / "index_entries.json").write_text(json.dumps(pick, indent=2), encoding="utf-8")

        total_sz = sum(int(e.get("size") or 0) for e in pick)
        print(
            f"\nBundle {label}: {len(pick)} files, ~{total_sz / 1_048_576:.1f} MB",
            file=sys.stderr,
        )

        bundle_items: list[BundleDownloadItem] = []
        for ent in pick:
            path = ent["path"]
            size = int(ent.get("size") or 0)
            dest = files_dir / safe_name(path)
            if args.resume and is_complete(dest, size):
                print(f"  skip (complete) {path}", file=sys.stderr)
                continue
            bundle_items.append(
                BundleDownloadItem(path=path, dest=dest, expected_size=size)
            )

        if not bundle_items:
            print("All files already complete.", file=sys.stderr)
            manifest_path = out_dir / "manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            else:
                manifest = [{"path": e["path"], "skipped": True} for e in pick]
        else:
            print(
                f"Starting Assistant-style bundle ({len(bundle_items)} files)…",
                file=sys.stderr,
            )
            manifest = c.logs_bundle_download(bundle_items, idle_done_s=6.0)
            manifest_path = out_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        complete = sum(1 for m in manifest if m.get("complete"))
        short = sum(
            1 for m in manifest if m.get("bytes") and not m.get("complete") and not m.get("error")
        )
        print(f"\nManifest: {manifest_path}", file=sys.stderr)
        print(f"Complete: {complete}/{len(manifest)}  short: {short}", file=sys.stderr)

        if args.no_decrypt:
            return 0 if complete == len(manifest) else 1
        rc = run_decrypt(files_dir, out_dir)
        return 0 if complete == len(manifest) and rc == 0 else 1
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
