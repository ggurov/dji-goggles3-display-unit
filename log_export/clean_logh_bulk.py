#!/usr/bin/env python3
"""Remove embedded DUSS seam framing from LOGH bulk-download bodies."""
from __future__ import annotations

import struct
from pathlib import Path

LOGH = b"LOGH"
MARKER = b"\x2a\x04"
TRIM = 12
MARKER_LEN = 12
BULK_PRE12_TAIL = bytes([0x00, 0x00])


def is_bulk_seam(body: bytes, marker_off: int) -> bool:
    if marker_off < TRIM or marker_off + 2 > len(body):
        return False
    pre = body[marker_off - TRIM : marker_off]
    if pre.endswith(BULK_PRE12_TAIL) and b"\x55\xe2" in pre:
        return True
    return False


def clean_logh_body(body: bytes, trim: int = TRIM) -> bytes:
    out = bytearray()
    i = 0
    while i < len(body):
        j = i
        while j + 2 <= len(body) and body[j : j + 2] != MARKER:
            j += 1
        if j >= len(body):
            out += body[i:]
            break
        if not is_bulk_seam(body, j):
            out += body[i : j + 2]
            i = j + 2
            continue
        seg_end = max(i, j - trim)
        out += body[i:seg_end]
        i = j + MARKER_LEN
    return bytes(out)


def clean_logh_file(data: bytes, body_off: int = 0xB0) -> bytes:
    if not data.startswith(LOGH) or len(data) <= body_off:
        return data
    head = data[:body_off]
    body = clean_logh_body(data[body_off:])
    plain_hint = struct.unpack_from("<I", data, 16)[0] if len(data) >= 20 else 0
    if plain_hint:
        aligned = (plain_hint + 15) // 16 * 16
        if len(body) >= aligned:
            body = body[:aligned]
    return head + body


def main() -> int:
    import sys

    for arg in sys.argv[1:]:
        p = Path(arg)
        raw = p.read_bytes()
        cleaned = clean_logh_file(raw)
        out = p.with_suffix(p.suffix + ".clean")
        out.write_bytes(cleaned)
        print(f"{p.name}: {len(raw)} -> {len(cleaned)} -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
