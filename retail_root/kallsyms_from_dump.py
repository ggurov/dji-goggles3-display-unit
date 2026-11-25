#!/usr/bin/env python3
"""Recover the kallsyms symbol table from a raw arm64 Linux kernel memory/image dump.

Works on an unencrypted Image file or on physical RAM dumped with
`dd if=/dev/mem` from the kernel load address (no vmlinux, no /proc/kallsyms).
Assumes CONFIG_KALLSYMS_BASE_RELATIVE (+ ABSOLUTE_PERMS), little-endian, 64-bit:
tables sit consecutively in .rodata as offsets[] | relative_base | num_syms | names |
markers[] | token_table[] | token_index[], each 8-aligned.

  python kallsyms_from_dump.py <dump.bin> [--load-phys 0x80000] [--grep REGEX] [--write syms.txt]
"""
from __future__ import annotations

import argparse
import re
import struct
import sys


def u16(d, o):
    return struct.unpack_from("<H", d, o)[0]


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def s32(d, o):
    return struct.unpack_from("<i", d, o)[0]


def u64(d, o):
    return struct.unpack_from("<Q", d, o)[0]


def parse_names(d, p, num):
    """kallsyms_names: num records of [len][token indices]. Returns (end, ok)."""
    for _ in range(num):
        if p >= len(d) or d[p] == 0 or d[p] > 0x80:
            return None
        p += 1 + d[p]
    return p


def parse_tokens(d, t):
    """kallsyms_token_table (256 NUL-terminated strings) then, 8-aligned, kallsyms_token_index."""
    toks, q = [], t
    for _ in range(256):
        e = d.find(b"\0", q)
        if e < 0 or e - q > 32:
            return None
        toks.append(d[q:e])
        q = e + 1
    want, off = [], 0
    for tk in toks:
        want.append(off)
        off += len(tk) + 1
    for pad in range(8):
        p = q + pad
        if p % 2 or p + 512 > len(d):
            continue
        if [u16(d, p + 2 * i) for i in range(256)] == want:
            return toks, p + 512
    return None


def locate(d):
    """Find (offsets_off, base, num, names_off, tokens) in the dump."""
    for o in range(0, len(d) - 16, 8):
        base = u64(d, o)
        if base < 0xFFFFFF8000000000 or base & 0xFFF:  # kernel half of the VA space, page-aligned _text
            continue
        num = u64(d, o + 8)
        if not 0x1000 <= num <= 0x400000:
            continue
        names_end = parse_names(d, o + 16, num)
        if names_end is None:
            continue
        m = (names_end + 7) & ~7
        if m + 8 * ((num >> 8) + 1) > len(d) or u32(d, m) != 0 or u32(d, m + 4) == 0:
            continue
        markers_end = m + 4 * ((num >> 8) + 1)
        tok = None
        for t in range(markers_end, markers_end + 16, 4):
            tok = parse_tokens(d, t)
            if tok:
                break
        if not tok:
            continue
        for pad in (4, 0):  # every kallsyms table is 8-aligned: try the 8-aligned array start first
            offs = o - 4 * num - pad
            if offs >= 0 and 0 <= s32(d, offs) <= 0x400000:
                return offs, base, num, o + 16, tok[0]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump")
    ap.add_argument("--load-phys", default="0x80000", help="physical address the dump starts at")
    ap.add_argument("--grep", help="only print symbols whose name matches this regex")
    ap.add_argument("--write", help="write 'type vaddr phys name' for every symbol to this file")
    a = ap.parse_args()

    d = open(a.dump, "rb").read()
    hit = locate(d)
    if not hit:
        print("kallsyms tables not found", file=sys.stderr)
        return 1
    offs, base, num, names_off, toks = hit
    phys_base = int(a.load_phys, 16)
    print(f"relative_base={base:#x} num_syms={num} kallsyms_offsets@dump+{offs:#x} "
          f"names@dump+{names_off:#x} load_phys={phys_base:#x}")

    rx = re.compile(a.grep) if a.grep else None
    rows, out = [], []
    p = names_off
    for i in range(num):
        n = d[p]
        name = b"".join(toks[b] for b in d[p + 1:p + 1 + n]).decode("latin1")
        p += 1 + n
        off = s32(d, offs + 4 * i)
        vaddr = base + off if off >= 0 else base - 1 - off
        phys = vaddr - (base - phys_base) if off >= 0 else -1
        if a.write:
            out.append(f"{name[0]} {vaddr:#x} {phys:#x} {name[1:]}\n")
        if rx is None or rx.search(name[1:]):
            rows.append((vaddr, phys, name))
    for vaddr, phys, name in rows:
        print(f"{vaddr:#018x} phys {phys:#010x} {name}")
    if a.write:
        open(a.write, "w").write("".join(out))
        print(f"wrote {num} symbols to {a.write}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
