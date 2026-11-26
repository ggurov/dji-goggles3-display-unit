"""Rebuild the files a DJI Assistant 2 firmware update sent, from a USBPcap capture.

    python reconstruct.py CAPTURE.pcapng --addr 62 [--ep-out 0x04] [--tshark PATH] --outdir DIR

The PC sends each file with the general file transfer (cmd set 0x00, cmd 0x2a):
    payload[0] = 1  start:  size u32 | name_len u8 | name (NUL-terminated) | tail
    payload[0] = 4  data:   partno u32 | data (980 bytes, the last one shorter)
    payload[0] = 3  end:    MD5 of the whole file
so each file can be rebuilt byte for byte; the MD5 in the end frame proves it.
`--addr` is the unit's USB address before its reboot.
"""
import argparse
import hashlib
import os

from v1frames import Stream, find_tshark, payload, tshark_bulk_rows

PART_SIZE = 980
START, END, DATA = 1, 3, 4


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--addr", type=lambda x: int(x, 0), required=True, help="USB device address")
    ap.add_argument("--ep-out", default="0x04")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--tshark")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    files, cur, stream = [], None, Stream()
    ep_out = int(a.ep_out, 16)
    for t, _, data in tshark_bulk_rows(a.capture, a.addr, ep_out, ep_out | 0x80, find_tshark(a.tshark)):
        stream.add(data, t)
        for _, fr in stream.frames():
            if fr[9] != 0 or fr[10] != 0x2A:
                continue
            pl = payload(fr)
            if pl[0] == START and len(pl) >= 5:
                size = int.from_bytes(pl[1:5], "little")
                nlen = pl[5]
                cur = {"name": pl[6:6 + nlen].split(b"\0")[0].decode("ascii", "replace"), "size": size,
                       "buf": bytearray(size), "parts": 0, "got": 0, "digest": None}
                files.append(cur)
            elif pl[0] == DATA and cur is not None and len(pl) >= 5:
                partno, chunk = int.from_bytes(pl[1:5], "little"), pl[5:]
                off = partno * PART_SIZE
                if off + len(chunk) <= cur["size"]:
                    cur["buf"][off:off + len(chunk)] = chunk
                cur["got"] += len(chunk)
                cur["parts"] += 1
            elif pl[0] == END and cur is not None:
                cur["digest"] = pl[1:17]

    for f in files:
        raw = bytes(f["buf"])
        md5 = hashlib.md5(raw).digest()
        with open(os.path.join(a.outdir, f["name"].replace("/", "_")), "wb") as fh:
            fh.write(raw)
        print("%s size=%d parts=%d bytes=%d md5=%s digest=%s md5_match=%s sha256=%s" % (
            f["name"], f["size"], f["parts"], f["got"], md5.hex(), (f["digest"] or b"").hex(),
            md5 == f["digest"], hashlib.sha256(raw).hexdigest()))


if __name__ == "__main__":
    main()
