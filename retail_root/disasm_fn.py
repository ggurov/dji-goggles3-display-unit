#!/usr/bin/env python3
"""Disassemble a kernel function out of the physical-memory dump (capstone, arm64).

  python disasm_fn.py <dump.bin> <symbol> [--kallsyms kallsyms_ab29020.txt] [--max 400]
"""
from __future__ import annotations

import argparse
import struct
import sys

import capstone

TEXT_BASE_VIRT = 0xffffffc010080800  # _stext
LOAD_PHYS = 0x80000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump")
    ap.add_argument("symbol")
    ap.add_argument("--kallsyms", default="kallsyms_ab29020.txt")
    ap.add_argument("--load-phys", default=hex(LOAD_PHYS))
    ap.add_argument("--text-virt", default=hex(TEXT_BASE_VIRT))
    ap.add_argument("--max", type=lambda x: int(x, 0), default=0x200)
    a = ap.parse_args()

    d = open(a.dump, "rb").read()
    load, text_virt = int(a.load_phys, 16), int(a.text_virt, 16)
    rows = []
    for l in open(a.kallsyms):
        t, v, p, n = l.split(maxsplit=3)
        rows.append((int(p, 16), int(v, 16), t, n.strip()))
    rows.sort()
    cands = [r for r in rows if r[3] == a.symbol]
    if len(cands) != 1:
        raise SystemExit(f"{a.symbol}: {len(cands)} matches: {cands[:4]}")
    pa = cands[0][0]
    end = next((r[0] for r in rows if r[0] > pa), pa + a.max)
    end = min(end, pa + a.max)
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    by_addr = {r[1]: r[3] for r in rows}
    for ins in md.disasm(d[pa - load:end - load], cands[0][1]):
        note = ""
        for tok in ins.op_str.replace("[", " ").replace("]", " ").replace(",", " ").split():
            if tok.startswith("#0x"):
                try:
                    v = int(tok, 16)
                except ValueError:
                    continue
                if v in by_addr:
                    note += f"   ; &{by_addr[v]}"
                elif ins.mnemonic in ("bl", "b") and v in by_addr:
                    note = f"   ; {by_addr[v]}"
        print(f"{ins.address:#x}  {ins.bytes.hex()}  {ins.mnemonic:8s} {ins.op_str}{note}")
    print(f"; {a.symbol}: {pa:#x}..{end:#x} ({end - pa:#x} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
