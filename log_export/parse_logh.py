#!/usr/bin/env python3
"""Parse LOGH export container header (retail bulk ciphertext wrapper)."""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

LOGH = b"LOGH"


def parse(data: bytes) -> dict:
    if not data.startswith(LOGH):
        return {"error": "not LOGH", "head": data[:16].hex()}
    hlen = min(len(data), 512)
    h = data[:hlen]
    out: dict = {
        "magic": "LOGH",
        "total_size": len(data),
        "u32_4": struct.unpack_from("<I", h, 4)[0],
        "u32_8": struct.unpack_from("<I", h, 8)[0],
        "u32_12": struct.unpack_from("<I", h, 12)[0],
        "u32_16": struct.unpack_from("<I", h, 16)[0] if len(h) > 16 else None,
    }
    strs = [m.group().decode("ascii", errors="replace") for m in re.finditer(rb"[\x20-\x7e]{4,}", h[:128])]
    out["header_strings"] = strs
    if len(h) >= 0x48:
        out["u32_0x40"] = struct.unpack_from("<I", h, 0x40)[0]
        out["u32_0x44"] = struct.unpack_from("<I", h, 0x44)[0]
        out["bytes_0x48_0x60"] = h[0x48:0x60].hex()
    body = data[128:] if len(data) > 128 else b""
    out["body_offset_guess"] = 128
    out["body_sample_hex"] = body[:64].hex() if body else ""
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: parse_logh.py file.logh [file2.logh ...]", file=sys.stderr)
        return 1
    rows = []
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.is_file():
            print(f"skip (missing): {path}", file=sys.stderr)
            continue
        rows.append({"file": str(path), **parse(path.read_bytes())})
    out = Path(__file__).resolve().parent / "output" / "logh_headers.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    for r in rows:
        print(Path(r["file"]).name)
        print(f"  version={r.get('u32_4')}  dev={r.get('header_strings')}")
        print(f"  @0x40={r.get('u32_0x40')} @0x44={r.get('u32_0x44')}")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
