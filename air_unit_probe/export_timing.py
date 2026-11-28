"""Timing of the file service's answers on the O3: ping, unknown command, get_version, export prepare.

    python export_timing.py [--host 1d00] [--rounds 3]

Only requests the unit already gets during a normal export session (ping, export prepare) plus
get_version and one unknown command (answered e0). Interface 4 must be free: close DJI Assistant first.
"""
from __future__ import annotations

import argparse
import time

from o3_fileio import Pipe


def timed(p: Pipe, cmd: tuple[int, int], pl: bytes, wait: float = 3.0):
    p.seq += 1
    seq = p.seq
    t0 = time.perf_counter()
    p.send(seq, 0x40, pl, cmd=cmd)
    while time.perf_counter() - t0 < wait:
        for fseq, flags, rp in p.pump(50):
            if fseq == seq and flags & 0x80:
                return (time.perf_counter() - t0) * 1000.0, len(rp), rp[:6].hex(" ")
    return None, 0, "no reply"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", type=lambda x: int(x, 16), default=0x1D00)
    ap.add_argument("--rounds", type=int, default=3)
    a = ap.parse_args()
    p = Pipe(4, a.host)
    try:
        for r in range(a.rounds):
            for name, cmd, pl in (("ping 21/05 [01]", (0x21, 0x05), b"\x01"),
                                  ("get_version 00/01", (0x00, 0x01), b""),
                                  ("unknown 00/fd", (0x00, 0xFD), b""),
                                  ("export prepare 00/ea [0a 01 01]", (0x00, 0xEA), b"\x0a\x01\x01")):
                ms, n, head = timed(p, cmd, pl)
                print("round %d  %-30s %s  len=%-3d  %s" % (
                    r + 1, name, ("%.1f ms" % ms) if ms is not None else "TIMEOUT", n, head))
            time.sleep(0.5)
    finally:
        p.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
