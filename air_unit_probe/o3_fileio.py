"""Read-only probe of a DJI unit's file service (general file transfer, cmd 0x00/0x2a) on the iface-4 pipe.

    python o3_fileio.py dir  DIR [DIR ...]                # phase-06 "make a listing of DIR" -> reads the list file it names
    python o3_fileio.py read PATH [PATH ...] [--out DIR]  # phase-08 file read, MD5-checked against the end frame
    python o3_fileio.py raw  CS CI HEXPAYLOAD [--host 1d00] [--flags 40]

PC -> unit traffic is limited to read requests (phases 06 / 08) and the acks of what the unit sends
back; nothing is pushed to the unit. Interface 4 must be free: close DJI Assistant first. Frames that
are not ours (pushes to other PC addresses) are ignored, never answered.

Under Git Bash pass device paths with MSYS_NO_PATHCONV=1, or "/blackbox/..." becomes "C:/Program Files/Git/blackbox/...".
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "goggles_tool"))       # the goggles_tool package root
sys.path.insert(0, os.path.join(REPO, "assistant_update"))   # v1frames.py

import usb.core  # noqa: E402
import usb.util  # noqa: E402

from goggles_tool.protocol.duss import pack_duml  # noqa: E402
from goggles_tool.usb.backend import _try_libusb0  # noqa: E402
from v1frames import Stream, address, payload  # noqa: E402

VID, PID = 0x2CA3, 0x0020
PART = 976            # data bytes per part frame; the frame carries 12 more spare bytes
SN14 = re.compile(rb"[0-9A-Z]{14}")
PC = "0a00"

if sys.platform == "win32":  # no "Python has stopped working" box if the libusb0 DLL ever dies on us
    ctypes.windll.kernel32.SetErrorMode(0x0002)


def timeout(e: Exception) -> bool:
    return "timed out" in str(e).lower() or "timeout" in str(e).lower()


class Pipe:
    """I/O on one vendor interface through DJI Assistant's libusb0.dll, used exactly like sweep_frames.py does."""

    def __init__(self, iface: int, host: int):
        be = _try_libusb0()
        if be is None:
            raise SystemExit("no libusb0 backend (DJI Assistant's libusb0.dll)")
        found = None
        for dev in usb.core.find(find_all=True, idVendor=VID, idProduct=PID, backend=be):
            for itf in dev.get_active_configuration():
                eps = sorted(e.bEndpointAddress for e in itf)
                if itf.bInterfaceNumber == iface and len(eps) == 2:
                    found = (dev, eps[0], eps[1])
        if not found:
            raise SystemExit("pipe not found on interface %d" % iface)
        self.dev, self.ep_out, self.ep_in = found      # keep the Device alive: its handle dies with it
        try:
            usb.util.claim_interface(self.dev, iface)
        except usb.core.USBError as e:
            usb.util.dispose_resources(self.dev)
            raise SystemExit("interface %d is claimed by another program (close DJI Assistant first): %s" % (
                iface, str(e).strip().splitlines()[-1][:100]))
        self.stream, self.host, self.seq = Stream(), host, 0x3100
        self.trace = []
        self.host_s = "%02x%02x" % ((host >> 8) & 0x1F, host & 0xFF)   # host is written "type,num", e.g. 0x1D00
        for _ in range(10):
            if not self.read(80):
                break

    def read(self, ms: int) -> bytes:
        try:
            return bytes(self.dev.read(self.ep_in, 1 << 16, ms))
        except usb.core.USBError as e:
            if timeout(e):
                return b""
            raise

    def send(self, seq: int, flags: int, pl: bytes, cmd: tuple[int, int] = (0x00, 0x2A)) -> None:
        body = bytes([0x0A, ((self.host & 0xFF) << 5) | ((self.host >> 8) & 0x1F), seq & 0xFF, (seq >> 8) & 0xFF,
                      flags, cmd[0], cmd[1]]) + pl
        self.dev.write(self.ep_out, pack_duml(body), 1500)

    def pump(self, ms: int):
        """Read once; yield (seq, flags, payload) of every frame from the unit's file host."""
        chunk = self.read(ms)
        if chunk:
            self.stream.add(chunk, 0)
        for _, fr in self.stream.frames():
            src, dst = address(fr)
            if src == self.host_s and dst == PC:
                yield fr[6] | (fr[7] << 8), fr[8], payload(fr)

    def request(self, pl: bytes, wait: float = 2.0):
        """Send one PC -> unit request (flags 0x40); return (reply payload, flags) of the frame with our seq."""
        self.seq += 1
        seq = self.seq
        self.send(seq, 0x40, pl)
        t0 = time.time()
        while time.time() - t0 < wait:
            for fseq, flags, rp in self.pump(100):
                if fseq == seq and flags & 0x80:
                    return rp, flags
        return None, None

    def pull(self, path: str, max_bytes: int, stall_s: float = 3.0, tail: bytes = b"\x09\x01\x00", abort_after: int = 0):
        """Read one file: request, ack the start, collect parts, ack the end. Returns a dict.

        tail = the request's last bytes: `09 01 04` asks for the LOGH-encrypted form Assistant uses
        for logs, `09 01 00` for the plain form it uses for the info JSON files.
        """
        pb = path.encode()
        reply, _ = self.request(bytes([0x08, len(pb)]) + pb + tail)
        out = {"path": path, "reply": reply, "tail": tail.hex()}
        if reply is None:
            out["error"] = "no reply"
            return out
        if reply != b"\x00":
            out["error"] = "refused"
            return out
        buf, digest, name, size, got_end, parts, maxpart = bytearray(), None, None, None, False, 0, -1
        last_ack, t_last, started, seen, contig = 0.0, time.time(), False, set(), 0
        while time.time() - t_last < stall_s:
            got, got_data = False, False
            for fseq, flags, pl in self.pump(150):
                got = True
                if pl[:1] == b"\x01" and flags & 0x40:                       # start
                    started = True
                    size = int.from_bytes(pl[1:5], "little")
                    name = pl[6:6 + pl[5]].split(b"\0")[0].decode("ascii", "replace")
                    self.send(fseq, 0x80, bytes([0x00, 0xD0, 0x03, 0xA0, 0x0F, 0x01, 0x01]))
                    self.trace.append((time.time(), "start", fseq, size))
                elif pl[:1] == b"\x04":                                      # data part
                    part = int.from_bytes(pl[1:5], "little")
                    self.trace.append((time.time(), "data", fseq, part))
                    off = part * PART
                    parts, maxpart, got_data = parts + 1, max(maxpart, part), True
                    seen.add(part)
                    while contig in seen:
                        contig += 1
                    if off + PART <= max_bytes:
                        if len(buf) < off + PART:
                            buf.extend(bytes(off + PART - len(buf)))
                        buf[off:off + PART] = pl[5:5 + PART]
                elif pl[:1] == b"\x03" and flags & 0x40:                     # end
                    digest = pl[1:17]
                    self.send(fseq, 0x80, b"\x00")
                    got_end = True
                    self.trace.append((time.time(), "end", fseq))
            if got:
                t_last = time.time()
            # Progress ack = highest contiguous part. The unit sends the whole file at once and then waits
            # for an ack that names its last part before it sends the end frame; about a second without
            # one and it starts again at the last acked part.
            nparts = -(-size // PART) if size else 0
            if got_data and (contig >= nparts or time.time() - last_ack > 0.1):
                self.send(0, 0x80, b"\x00" + (contig - 1).to_bytes(4, "little"))
                last_ack = time.time()
                self.trace.append((last_ack, "ack", contig - 1))
            if got_end:
                break
            if abort_after and contig * PART >= abort_after:                   # enough of a huge file: stop acking
                out["aborted"] = True
                break
            if not started and time.time() - t_last > 1.5:
                break
        out.update(name=name, size=size, digest=digest, end=got_end, parts=parts, maxpart=maxpart)
        if size is not None:
            raw = bytes(buf[:size])
            out["raw"] = raw
            out["md5_ok"] = (digest == hashlib.md5(raw).digest()) if digest is not None else None
        return out

    def close(self):
        usb.util.dispose_resources(self.dev)


def show(r: dict, out_dir: str | None, lines: int) -> None:
    tag = "%-46s" % r["path"]
    if "error" in r:
        print("%s %s (reply %s)" % (tag, r["error"], (r["reply"] or b"").hex(" ")))
        return
    raw = r.get("raw", b"")
    print("%s size=%-9s got=%-9s md5 %s end=%s%s parts=%d tail=%s" % (
        tag, r.get("size"), len(raw), "OK" if r.get("md5_ok") else "MISMATCH/none", r.get("end"),
        " ABORTED" if r.get("aborted") else "", r.get("parts", 0), r.get("tail")))
    if out_dir and raw:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, r["path"].strip("/").replace("/", "_")), "wb") as fh:
            fh.write(raw)
    if not raw:
        print("    (empty)")
    elif raw[:1] == b"{" or all(32 <= c < 127 or c in (9, 10, 13) for c in raw[:200]):
        for ln in SN14.sub(b"<SN>", raw[:40000]).decode("utf-8", "replace").splitlines()[:lines]:
            print("    " + ln[:200])
    else:
        print("    " + SN14.sub(b"<SN>", raw[:96]).hex(" "))
        print("    |" + "".join(chr(c) if 32 <= c < 127 else "." for c in SN14.sub(b"<SN>", raw[:96])) + "|")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dir", "read", "raw"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--host", type=lambda x: int(x, 16), default=0x1D00)
    ap.add_argument("--iface", type=int, default=4)
    ap.add_argument("--out")
    ap.add_argument("--max", type=lambda x: int(x, 0), default=64 << 20)
    ap.add_argument("--lines", type=int, default=40)
    ap.add_argument("--flags", type=lambda x: int(x, 0), default=0x40)
    ap.add_argument("--tail", default="090100", help="last bytes of a read request: 090100 plain, 090104 as Assistant reads logs")
    ap.add_argument("--trace", help="append the timing of every frame of each read to this file")
    ap.add_argument("--abort-after", type=lambda x: int(x, 0), default=0, help="stop a read once this many bytes have arrived (very large files)")
    a = ap.parse_args()
    p = Pipe(a.iface, a.host)
    try:
        if a.cmd == "read":
            for path in a.args:
                p.trace = []
                r = p.pull(path, a.max, tail=bytes.fromhex(a.tail), abort_after=a.abort_after)
                show(r, a.out, a.lines)
                if a.trace and p.trace:
                    t0 = p.trace[0][0]
                    with open(a.trace, "a", encoding="utf-8") as tf:
                        for ev in p.trace:
                            tf.write("%s %7.4f %s %s\n" % (path, ev[0] - t0, ev[1], " ".join(str(x) for x in ev[2:])))
                    print("trace: %d events -> %s" % (len(p.trace), a.trace))
        elif a.cmd == "dir":
            for d in a.args:
                db = d.encode()
                reply, _ = p.request(bytes([0x06, len(db)]) + db)
                if reply is None:
                    print("%-46s no reply" % d)
                    continue
                print("%-46s -> %s |%s|" % (d, SN14.sub(b"<SN>", reply[:60]).hex(" "),
                                          "".join(chr(c) if 32 <= c < 127 else "." for c in reply[:60])))
                if reply[:1] == b"\x00" and b"/" in reply:                  # reply: 00 | len | path of the list file
                    show(p.pull(reply[reply.find(b"/"):].split(b"\0")[0].decode("ascii", "replace"), a.max), a.out, a.lines)
        else:
            cs, ci = int(a.args[0], 16), int(a.args[1], 16)
            pl = bytes.fromhex(a.args[2]) if len(a.args) > 2 else b""
            p.seq += 1
            p.send(p.seq, a.flags, pl, cmd=(cs, ci))
            t0, n = time.time(), 0
            while time.time() - t0 < 2.0:
                for fseq, flags, rp in p.pump(100):
                    n += 1
                    print("%04x fl=%02x [%3d] %s |%s|" % (
                        fseq, flags, len(rp), SN14.sub(b"<SN>", rp[:120]).hex(" "),
                        "".join(chr(c) if 32 <= c < 127 else "." for c in SN14.sub(b"<SN>", rp[:120]))))
                    if fseq == p.seq and flags & 0x80:
                        t0 = 0
            if not n:
                print("no frames")
    finally:
        p.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
