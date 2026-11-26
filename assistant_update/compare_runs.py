"""Compare two captures decoded with v1stream.py: control frames, progress pushes, transfer statistics.

    python compare_runs.py TAG_A_before TAG_A_after TAG_B_before TAG_B_after

Tags are v1stream.py output prefixes: TAG_ctrl.txt, TAG_parts.csv and TAG_acks.csv must exist
for the unit's address before the reboot and for the one after it. The control frames from the
first command of the update to the reply of the "start flashing" command are compared
normalised (direction, sender, receiver, flags, command, payload), so only sequence numbers,
timings, the USB address and version-specific frames show up as differences.
"""
import argparse
import bisect
import os
import re
import statistics

HEARTBEAT = ("m0081", "m0082", "m000e", "m2106", "m2108")  # periodic traffic, left out of the comparison
LINE = re.compile(r"\s*([\d.]+) (IN|OUT) len=\s*(\d+) (\S+) -> (\S+) seq=\S+ fl=(\S+) (m\S+) plen=\s*(\d+) ([0-9a-f ]*)\|")


def load(path):
    rows = []
    for ln in open(path, encoding="utf-8"):
        m = LINE.match(ln)
        if not m:
            continue
        t, d, _, src, dst, fl, cmd, plen, hx = m.groups()
        if cmd in HEARTBEAT:
            continue
        rows.append((float(t), d, src, dst, fl, cmd, int(plen), hx.strip()))
    return rows


def key(r):
    return (r[1], r[2], r[3], r[4], r[5], r[7])


def core(rows):
    """From the first m0083 (enter upgrade mode) to the reply of m0085 (start flashing)."""
    i0 = next(k for k, r in enumerate(rows) if r[5] == "m0083")
    i1 = next(k for k, r in enumerate(rows) if k > i0 and r[5] == "m0085" and r[1] == "IN")
    return rows[i0:i1 + 1]


def rows_csv(path, conv):
    return [tuple(f(c) for f, c in zip(conv, ln.split(","))) for ln in open(path).read().splitlines()[1:]]


def stats(tag, parts, acks, cc):
    fw = parts[3:]  # the first three parts belong to the 2 KB manifest
    big = [a for a in acks if a[2] > 100]
    times = [x[0] for x in parts]
    lag = [bisect.bisect_right(times, t) - 3 - pn - 1 for t, pn in ((a[0], a[2]) for a in big)]
    dt = [b[0] - a[0] for a, b in zip(big, big[1:])]
    ms = lambda a, b: (cc[b][0] - cc[a][0]) * 1000  # noqa: E731
    return (tag, len(fw), fw[-1][0] - fw[0][0], len(fw) * 980 / (fw[-1][0] - fw[0][0]) / 1e6, len(big),
            min(dt) * 1000, statistics.median(dt) * 1000, max(dt) * 1000, max(lag), lag[0],
            ms(0, 1), ms(2, 3), ms(4, 6), ms(10, 11), ms(12, 13))


HEADER = ("run", "fw parts", "transfer s", "MB/s", "fw acks", "ack min ms", "ack med ms", "ack max ms",
          "unacked max", "unacked at first ack", "m0083 reply ms", "m0084 reply ms", "manifest start-to-end ms",
          "fw end ms", "m0085 reply ms")


def run(a, b):
    A, A2, B, B2 = (load(t + "_ctrl.txt") for t in (a[0], a[1], b[0], b[1]))
    ca, cb = core(A), core(B)
    ka, kb = [key(r) for r in ca], [key(r) for r in cb]
    print("control frames (m0083 .. m0085 reply): A=%d B=%d, identical normalised: %d" % (
        len(ka), len(kb), sum(x == y for x, y in zip(ka, kb))))
    for i, (x, y) in enumerate(zip(ka, kb)):
        if x != y:
            print("  [%d] A %-3s %-5s %s" % (i, x[0], x[4], x[5]))
            print("      B %-3s %-5s %s" % (y[0], y[4], y[5]))

    def result(rows):
        i = next(k for k, r in enumerate(rows) if r[5] == "m004f")
        return rows[i:i + 4]

    ra, rb = result(A2), result(B2)
    print("frames after the reboot (result read, push control) identical: %s" % ([key(r) for r in ra] == [key(r) for r in rb]))
    for r in rb:
        print("   B %s %-5s %s" % (r[1], r[5], r[7]))

    def pushes(rows):
        return [(r[0], r[7]) for r in rows if r[5] == "m0042"]

    def show(tag, ps, t0):
        out, last, n, first = [], None, 0, 0.0
        for t, hx in ps + [(None, None)]:
            if hx != last:
                if last is not None:
                    out.append("%s x%d @%.0fs" % (last, n, first - t0))
                last, n, first = hx, 1, (t - t0 if t is not None else 0.0)
            else:
                n += 1
        print("%s: %d progress pushes before the reboot: %s" % (tag, len(ps), " | ".join(out)))

    show("A", pushes(A), ca[0][0])
    show("B", pushes(B), cb[0][0])
    print("pushes after the reboot: A", [h for _, h in pushes(A2)], "B", [h for _, h in pushes(B2)])
    sa = stats("A", rows_csv(a[0] + "_parts.csv", (float, lambda x: int(x, 16), int, int)), a[0] + "_acks.csv", ca)
    sb = stats("B", rows_csv(b[0] + "_parts.csv", (float, lambda x: int(x, 16), int, int)), b[0] + "_acks.csv", cb)
    for h, x, y in zip(HEADER, sa, sb):
        print("  %-24s A=%-12s B=%s" % (h, round(x, 2) if isinstance(x, float) else x, round(y, 2) if isinstance(y, float) else y))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tags", nargs=4, metavar="TAG")
    a = ap.parse_args()
    t = [x if os.path.isabs(x) else os.path.join(os.getcwd(), x) for x in a.tags]
    run(t[0:2], t[2:4])


if __name__ == "__main__":
    main()
