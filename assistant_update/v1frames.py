"""Validated DJI DUML "V1" frames from a USBPcap capture: shared pieces for the tools here.

Frame layout (confirmed against the framing code in DJI Assistant 2's fs_dbus_lib.dll and
against every frame of several captured sessions):

    off  size  field
    0    1     SOF              0x55
    1    2     length (LE)      (payload_len + 13) & 0x3ff | 0x400   -> byte 2 is 0x04 | len >> 8
    3    1     crc8             CRC-8 over bytes 0..2, poly 0x8C (reflected table), seed 0x77
    4    1     sender           sender_num << 5 | sender_type       (5-bit type, 3-bit num)
    5    1     receiver         receiver_num << 5 | receiver_type
    6    2     seq (LE)
    8    1     flags            bit 7 = reply, bits 6..5 = ack type, bits 4..1 = encrypt type
    9    1     cmd_set
    10   1     cmd_id
    11   n     payload          n <= 1011
    n+11 2     crc16 (LE)       CRC-16 over bytes 0 .. len-3, poly 0x8408, seed 0x3692

`goggles_tool.protocol.duss` has the same CRCs and a builder.
"""
import bisect
import os
import shutil

TSHARK_DEFAULT = r"C:\Program Files\Wireshark\tshark.exe"


def find_tshark(override=None):
    """tshark path: override, $TSHARK, PATH, then the default Windows install location."""
    for cand in (override, os.environ.get("TSHARK"), shutil.which("tshark"), TSHARK_DEFAULT):
        if cand and os.path.isfile(cand):
            return cand
    raise SystemExit("tshark not found: install Wireshark or set TSHARK / --tshark")


def _mk8(poly=0x8C):
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c >> 1) ^ poly) & 0xFF if c & 1 else (c >> 1) & 0xFF
        table.append(c)
    return table


def _mk16(poly=0x8408):
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c >> 1) ^ poly) & 0xFFFF if c & 1 else (c >> 1) & 0xFFFF
        table.append(c)
    return table


T8 = _mk8()
T16 = _mk16()


def crc8(buf, seed=0x77):
    c = seed
    for b in buf:
        c = T8[(c ^ b) & 0xFF]
    return c


def crc16(buf, seed=0x3692):
    c = seed
    for b in buf:
        c = (c >> 8) ^ T16[(c ^ b) & 0xFF]
    return c


def frame_len_at(buf, pos):
    """Length of a validated frame at pos; 0 if the bytes there are not one; -1 if incomplete."""
    n = len(buf)
    if pos + 13 > n:
        return -1
    if buf[pos] != 0x55:
        return 0
    ln = (buf[pos + 1] | (buf[pos + 2] << 8)) & 0x3FF
    if ln < 13:
        return 0
    if pos + ln > n:
        return -1
    if crc8(buf[pos:pos + 3]) != buf[pos + 3]:
        return 0
    if crc16(buf[pos:pos + ln - 2]) != (buf[pos + ln - 2] | (buf[pos + ln - 1] << 8)):
        return 0
    return ln


def iter_frames(data, with_pos=False):
    """Yield validated frames (or (offset, frame)) from a byte stream; other bytes are skipped."""
    i = 0
    n = len(data)
    while i < n - 12:
        r = frame_len_at(data, i)
        if r == -1:
            return
        if r == 0:
            i += 1
            continue
        yield (i, bytes(data[i:i + r])) if with_pos else bytes(data[i:i + r])
        i += r


class Stream:
    """Byte stream of one endpoint, fed packet by packet; yields frames as soon as they are complete."""

    def __init__(self):
        self.buf = bytearray()
        self.base = 0
        self.pos = 0
        self.marks = []
        self.garbage = 0
        self.total = 0

    def add(self, data, t):
        self.marks.append((self.base + len(self.buf), t))
        self.buf += data
        self.total += len(data)

    def time_at(self, abs_off):
        i = bisect.bisect_right(self.marks, (abs_off, float("inf"))) - 1
        return self.marks[i][1]

    def frames(self):
        while True:
            r = frame_len_at(self.buf, self.pos)
            if r == -1:
                break
            if r == 0:
                self.pos += 1
                self.garbage += 1
                continue
            fr = bytes(self.buf[self.pos:self.pos + r])
            yield self.time_at(self.base + self.pos), fr
            self.pos += r
        if self.pos > (1 << 20):
            del self.buf[:self.pos]
            self.base += self.pos
            self.pos = 0


def address(fr):
    """(sender, receiver) as 4-hex strings, e.g. ('0a01', '0802')."""
    return "%02x%02x" % (fr[4] & 0x1F, fr[4] >> 5), "%02x%02x" % (fr[5] & 0x1F, fr[5] >> 5)


def payload(fr):
    return fr[11:len(fr) - 2]


def tshark_bulk_rows(capture, addr, ep_out, ep_in, tshark):
    """Yield (time, 'OUT'|'IN', data) for every bulk packet with data on the two endpoints."""
    cmd = [tshark, "-r", capture, "-Y",
           "usb.device_address == %d && usb.transfer_type == 0x03 && usb.capdata && "
           "(usb.endpoint_address == 0x%02x || usb.endpoint_address == 0x%02x)" % (addr, ep_out, ep_in),
           "-T", "fields", "-e", "frame.time_relative", "-e", "usb.endpoint_address", "-e", "usb.capdata"]
    import subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="replace")
    for line in proc.stdout:
        p = line.rstrip("\n").split("\t")
        if len(p) < 3 or not p[2]:
            continue
        try:
            yield float(p[0]), "OUT" if int(p[1], 16) == ep_out else "IN", bytes.fromhex(p[2].replace(":", ""))
        except ValueError:
            continue
    proc.wait()
