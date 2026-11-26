"""List every V1 frame of a small capture (discovery sessions) in one readable file.

    python v1dump.py CAPTURE.pcapng --addr 62 [--ep-out 0x04 --ep-in 0x85] [--max-hex 400]
                                    [--tshark PATH] [--out frames.txt] [--summary summary.txt]

Use --max-hex 400 when the payloads matter (for example the 265-byte descriptor reads).
Large captures (firmware transfers) are better served by v1stream.py.
"""
import argparse
import bisect
import collections
import csv

from v1frames import Stream, address, find_tshark, payload, tshark_bulk_rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--addr", type=lambda x: int(x, 0), required=True, help="USB device address")
    ap.add_argument("--ep-out", default="0x04")
    ap.add_argument("--ep-in", default="0x85")
    ap.add_argument("--max-hex", type=int, default=48, help="payload bytes printed per frame")
    ap.add_argument("--out", help="frame listing (default: stdout)")
    ap.add_argument("--summary", help="histogram per direction / addresses / flags / command (.txt, plus .csv)")
    ap.add_argument("--tshark")
    a = ap.parse_args()

    ep_out, ep_in = int(a.ep_out, 16), int(a.ep_in, 16)
    streams = {"OUT": Stream(), "IN": Stream()}
    events = []
    for t, d, data in tshark_bulk_rows(a.capture, a.addr, ep_out, ep_in, find_tshark(a.tshark)):
        streams[d].add(data, t)
        for t2, fr in streams[d].frames():
            events.append((t2, d, fr))
    for d in streams:
        for t2, fr in streams[d].frames():
            events.append((t2, d, fr))
    events.sort(key=lambda e: e[0])

    hist = collections.OrderedDict()
    out = open(a.out, "w", encoding="utf-8") if a.out else None
    for t, d, fr in events:
        pl = payload(fr)
        src, dst = address(fr)
        seq = fr[6] | (fr[7] << 8)
        cmd = "m%02x%02x" % (fr[9], fr[10])
        h = hist.setdefault((d, src, dst, "%02x" % fr[8], cmd), [0, 0])
        h[0] += 1
        h[1] += len(pl)
        text = "".join(chr(c) if 32 <= c < 127 else "." for c in pl[:60])
        line = "%10.3f %s len=%4d %s -> %s seq=%04x fl=%s %s plen=%3d %s |%s|\n" % (
            t, d, len(fr), src, dst, seq, "%02x" % fr[8], cmd, len(pl), pl[:a.max_hex].hex(' '), text)
        if out:
            out.write(line)
    if out:
        out.close()
    if a.summary:
        with open(a.summary, "w", encoding="utf-8") as sh, \
                open(a.summary.rsplit(".", 1)[0] + ".csv", "w", newline="", encoding="utf-8") as cs:
            w = csv.writer(cs)
            w.writerow(["dir", "src", "dst", "flags", "cmd", "frames", "payload_bytes"])
            for k in sorted(hist, key=lambda k: -hist[k][0]):
                sh.write("%5d frames %8d bytes  %s  %s -> %s  fl=%s  %s\n" % (
                    hist[k][0], hist[k][1], k[0], k[1], k[2], k[3], k[4]))
                w.writerow([k[0], k[1], k[2], k[3], k[4], hist[k][0], hist[k][1]])
    print("frames: %d (OUT %d, IN %d)" % (len(events), sum(e[1] == "OUT" for e in events), sum(e[1] == "IN" for e in events)))


if __name__ == "__main__":
    main()
