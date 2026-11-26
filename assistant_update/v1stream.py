"""Streaming V1 frame decoder for USBPcap captures, sized for firmware transfers (hundreds of MB).

    python v1stream.py CAPTURE.pcapng --addr 62 --tag refresh_before [--ep-out 0x04 --ep-in 0x85]
                                      [--max-hex 80] [--tshark PATH] [--outdir .]

`--addr` is the unit's USB device address (tshark: `usb.idVendor == 0x2ca3` shows it in the
injected descriptor packet). A reboot gives the unit a new address: decode both.

Output files (TAG_parts.csv, TAG_acks.csv, TAG_ctrl.txt, TAG_summary.txt):
  parts.csv  file-data parts sent by the PC: time, seq, partno, data length
  acks.csv   part acks from the unit: time, seq, partno (the highest contiguous part)
  ctrl.txt   every other frame: time, direction, addresses, seq, flags, command, payload
             (first --max-hex bytes of the payload, then the printable text)
  summary.txt  frame counts per direction / addresses / flags / command
"""
import argparse
import collections
import os

from v1frames import Stream, address, find_tshark, payload, tshark_bulk_rows

DATA_PHASE, END_PHASE, START_PHASE = 4, 3, 1  # payload[0] of the general file transfer (cmd 0x00/0x2a)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--addr", type=lambda x: int(x, 0), required=True, help="USB device address")
    ap.add_argument("--ep-out", default="0x04")
    ap.add_argument("--ep-in", default="0x85")
    ap.add_argument("--tag", required=True, help="output file prefix")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--max-hex", type=int, default=80, help="payload bytes kept per control frame")
    ap.add_argument("--tshark")
    a = ap.parse_args()

    ep_out, ep_in = int(a.ep_out, 16), int(a.ep_in, 16)
    streams = {"OUT": Stream(), "IN": Stream()}
    prefix = os.path.join(a.outdir, a.tag)
    hist = collections.OrderedDict()
    counts = collections.Counter()
    ctrl = open(prefix + "_ctrl.txt", "w", encoding="utf-8")
    parts = open(prefix + "_parts.csv", "w", encoding="utf-8", newline="")
    parts.write("time,seq,partno,data_len\n")
    acks = open(prefix + "_acks.csv", "w", encoding="utf-8", newline="")
    acks.write("time,seq,partno\n")

    def handle(t, direction, fr):
        pl = payload(fr)
        src, dst = address(fr)
        seq = fr[6] | (fr[7] << 8)
        cmd = "m%02x%02x" % (fr[9], fr[10])
        h = hist.setdefault((direction, src, dst, "%02x" % fr[8], cmd), [0, 0])
        h[0] += 1
        h[1] += len(pl)
        counts[direction] += 1
        if fr[9] == 0 and fr[10] == 0x2A and direction == "OUT" and len(pl) >= 5 and pl[0] == DATA_PHASE:
            parts.write("%.3f,%04x,%d,%d\n" % (t, seq, int.from_bytes(pl[1:5], "little"), len(pl) - 5))
            return
        if fr[9] == 0 and fr[10] == 0x2A and direction == "IN" and len(pl) == 5 and pl[0] == 0:
            acks.write("%.3f,%04x,%d\n" % (t, seq, int.from_bytes(pl[1:5], "little")))
            return
        text = "".join(chr(c) if 32 <= c < 127 else "." for c in pl[:96])
        ctrl.write("%10.3f %s len=%4d %s -> %s seq=%04x fl=%02x %s plen=%4d %s |%s|\n" % (
            t, direction, len(fr), src, dst, seq, fr[8], cmd, len(pl), pl[:a.max_hex].hex(' '), text))

    for t, d, data in tshark_bulk_rows(a.capture, a.addr, ep_out, ep_in, find_tshark(a.tshark)):
        streams[d].add(data, t)
        for t2, fr in streams[d].frames():
            handle(t2, d, fr)
    for d in ("OUT", "IN"):
        for t2, fr in streams[d].frames():
            handle(t2, d, fr)
    for fh in (ctrl, parts, acks):
        fh.close()
    with open(prefix + "_summary.txt", "w", encoding="utf-8") as sh:
        sh.write("frames OUT=%d IN=%d skipped bytes OUT=%d IN=%d stream bytes OUT=%d IN=%d\n" % (
            counts["OUT"], counts["IN"], streams["OUT"].garbage, streams["IN"].garbage,
            streams["OUT"].total, streams["IN"].total))
        for k in sorted(hist, key=lambda k: (k[0], -hist[k][0])):
            sh.write("%5d frames %9d bytes  %s  %s -> %s  fl=%s  %s\n" % (
                hist[k][0], hist[k][1], k[0], k[1], k[2], k[3], k[4]))
    print("frames OUT=%d IN=%d skipped bytes OUT=%d IN=%d -> %s_{ctrl.txt,parts.csv,acks.csv,summary.txt}" % (
        counts["OUT"], counts["IN"], streams["OUT"].garbage, streams["IN"].garbage, prefix))


if __name__ == "__main__":
    main()
