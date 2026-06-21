#!/usr/bin/env python3
"""Batch LOGH decrypt via donor liblog_util harness.

Usage:
  python batch_decrypt.py bulk  log_export/output/pull_*/files
  python batch_decrypt.py file  path/to/file.logh

Requires rooted donor ADB and /blackbox/stage/logutil_decrypt (see log_export/README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "goggles_tool"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from clean_logh_bulk import clean_logh_file, is_bulk_seam  # noqa: E402
from goggles_tool.protocol.duss import _strip_internal_trans_framing  # noqa: E402

DEFAULT_ADB = os.environ.get("ADB", "adb")
HARNESS_REMOTE = "/blackbox/stage/logutil_decrypt"
OUT_DIR = Path(__file__).resolve().parent / "output" / "decrypted"


def adb(adb_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [adb_path, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def decrypt_logh(adb_path: str, local_logh: Path, out_dir: Path) -> tuple[int, Path | None]:
    remote_in = "/data/local/tmp/batch_in.logh"
    remote_out = "/data/local/tmp/batch_out.dec"
    local_dec = out_dir / (local_logh.name + ".dec")

    if adb(adb_path, "push", str(local_logh), remote_in).returncode != 0:
        return 0, None
    adb(adb_path, "shell", f"{HARNESS_REMOTE} {remote_in} {remote_out} 2>&1")
    if adb(adb_path, "pull", remote_out, str(local_dec)).returncode != 0:
        return 0, None
    if not local_dec.is_file() or local_dec.stat().st_size == 0:
        return 0, None
    return local_dec.stat().st_size, local_dec


def has_bulk_seams(body: bytes) -> bool:
    j = 0
    while j < len(body) - 1:
        j = body.find(b"\x2a\x04", j)
        if j < 0:
            break
        if is_bulk_seam(body, j):
            return True
        j += 1
    return False


def prepare_logh(raw: bytes) -> bytes:
    if not raw.startswith(b"LOGH"):
        return raw
    body = raw[0xB0 :]
    if has_bulk_seams(body):
        raw = clean_logh_file(raw)
        body = raw[0xB0 :]
    body = _strip_internal_trans_framing(body)
    plain_hint = struct.unpack_from("<I", raw, 16)[0] if len(raw) >= 20 else 0
    if plain_hint:
        aligned = (plain_hint + 15) // 16 * 16
        if len(body) > aligned:
            body = body[:aligned]
    return raw[:0xB0] + body


def validate_dec(dec: Path) -> dict:
    data = dec.read_bytes()
    ascii_ratio = sum(32 <= b < 127 or b in (9, 10, 13) for b in data) / max(len(data), 1)
    out: dict = {"bytes": len(data), "ascii_ratio": round(ascii_ratio, 3), "json_ok": False}
    for trim in (0, 8, 16, 32, 64, 128):
        n = len(data) - trim
        if n <= 0:
            continue
        try:
            json.loads(data[:n].decode("utf-8"))
            out["json_ok"] = True
            out["json_bytes"] = n
            break
        except json.JSONDecodeError as e:
            if "Extra data" in str(e) and e.pos:
                try:
                    json.loads(data[: e.pos].decode("utf-8"))
                    out["json_ok"] = True
                    out["json_bytes"] = e.pos
                    break
                except Exception:
                    pass
        except Exception:
            pass
    return out


def process_file(adb_path: str, path: Path, out_dir: Path) -> dict:
    raw = path.read_bytes()
    prepared = prepare_logh(raw)
    staging = out_dir / "staging" / path.name
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(prepared)
    plain_len, dec = decrypt_logh(adb_path, staging, out_dir)
    row = {"src": str(path), "prepared": len(prepared), "plain_out": plain_len, "ok": plain_len > 0}
    if dec:
        row.update(validate_dec(dec))
        row["dec"] = str(dec)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=("bulk", "file"), help="bulk: scan dirs; file: explicit paths")
    ap.add_argument("paths", nargs="*", help="Files or directories (bulk mode)")
    ap.add_argument("--adb", default=DEFAULT_ADB, help="adb executable (default: ADB env or adb)")
    ap.add_argument("-o", "--output-dir", type=Path, default=OUT_DIR, help="Decrypt output directory")
    args = ap.parse_args()

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    if args.mode == "file":
        targets = [Path(p) for p in args.paths]
    else:
        bases = [Path(p) for p in args.paths] if args.paths else [REPO_ROOT / "log_export" / "output"]
        targets = []
        for base in bases:
            if base.is_file():
                targets.append(base)
            else:
                targets.extend(p for p in sorted(base.rglob("*")) if p.is_file())

    for p in targets:
        if not p.is_file():
            continue
        if p.read_bytes()[:4] != b"LOGH":
            continue
        rows.append(process_file(args.adb, p, out_dir))

    report = out_dir / "batch_report.json"
    report.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    ok = sum(1 for r in rows if r.get("ok"))
    json_ok = sum(1 for r in rows if r.get("json_ok"))
    print(f"processed={len(rows)} decrypt_ok={ok} json_ok={json_ok} -> {report}")
    for r in rows:
        status = "JSON" if r.get("json_ok") else ("TEXT" if r.get("ok") else "FAIL")
        name = Path(r["src"]).name
        print(f"  [{status}] {name} out={r.get('plain_out', 0)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
