#!/usr/bin/env python3
"""Enable ADB (root shell) on a locked retail DJI Goggles 3 from the host.

This is the toolya method (https://toolya.dev/app, grom-labs/toolya core/src/lib.rs)
replayed with pyusb instead of WebUSB. MI_04 on DJI Assistant's libusb-win32 driver goes
through libusb0, MI_04 rebound to WinUSB (Zadig, what Chrome needs) through libusb-1.0.
See RETAIL_ROOT.md next to this directory.

The goggles must have booted with the cable attached: after a host-side re-enumeration
while they run (a driver swap) the DUML pipe stays silent until a power cycle.

Transport: vendor iface 4, bulk EP_OUT 0x04 / EP_IN 0x85, VID 2CA3 PID 0020.
Frame: 0x55 | len | ver/flags | crc8 | HOST dst seq(2) ack cmd_set cmd_id payload | crc16(LE)

  handshake  Assistant init frames (read-only get_version stream, ends in </dji>)
  enable     DUML 0x2A->0x1B (dji_network) cmd_set 0x07 cmd_id 0x64 payload [01]
             = "engpc mode" start: sys.usb.config none -> rndis,mass_storage,bulk,acm
             -> acm,adb. Runtime only; stock USB returns after a power cycle.
  scan       fallback cmd_id 0x60..0x6F (toolya order), stop at first re-enumeration.

Needs pyusb + libusb-package (same as goggles_tool). `adb` is taken from --adb, the ADB
environment variable or PATH.

  python retail_root/enable_adb.py            # handshake only, print identity (read-only)
  python retail_root/enable_adb.py --enable   # + primary 07/64, waits for adb, prints uid/build
  python retail_root/enable_adb.py --enable --scan          # + 0x60..0x6F fallback
  python retail_root/enable_adb.py --enable --wait 3600     # poll until DUML answers
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import usb.core
import usb.util

try:
    from goggles_tool.protocol.duss import pack_duml
except ImportError:  # not pip-installed: use the checkout next to this directory
    _here = Path(__file__).resolve()
    # A cwd that holds a plain "goggles_tool/" folder shadows the package as a namespace package.
    sys.modules.pop("goggles_tool", None)
    sys.path.insert(0, str(next(p / "goggles_tool" for p in (_here.parent.parent, _here.parents[2])
                                   if (p / "goggles_tool" / "goggles_tool").is_dir())))
    from goggles_tool.protocol.duss import pack_duml

from goggles_tool.usb.backend import _try_libusb0  # DJI Assistant's libusb0.dll for libusb-win32 MI_03..07

VID, PID = 0x2CA3, 0x0020
HOST, WMS, CMDSET_WMS = 0x2A, 0x1B, 0x07
EP_OUT, EP_IN = 0x04, 0x85
EXPECT = b"</dji>"
ADB = os.environ.get("ADB") or shutil.which("adb") or "adb"
_OPEN: list = []  # opened pyusb handles, disposed at exit


def _libusb1():
    import libusb_package
    from usb.backend import libusb1

    return libusb1.get_backend(find_library=libusb_package.find_library)


def backends() -> list:
    """MI_04 on DJI's libusb-win32 driver -> libusb0; MI_04 rebound to WinUSB (Zadig, for toolya) -> libusb-1.0."""
    out = []
    for make in (_try_libusb0, _libusb1):
        try:
            if (be := make()) is not None:
                out.append(be)
        except Exception:
            pass
    return out


def pipes() -> list:
    """(dev, iface, endpoint-addresses) for every 2CA3:0020 interface, from the first backend that sees the
    DUML pair (EP 0x04/0x85); else from the first that lists anything.

    libusb-win32 exposes one pyusb device per interface, libusb-1.0 one per composite device."""
    fallback = []
    for be in backends():
        try:
            devs = list(usb.core.find(find_all=True, idVendor=VID, idProduct=PID, backend=be))
        except Exception:
            continue
        out = []
        for dev in devs:
            try:
                cfg = dev.get_active_configuration()
            except Exception:
                continue
            for intf in cfg:
                out.append((dev, intf.bInterfaceNumber, {e.bEndpointAddress for e in intf}))
        if any(EP_OUT in eps and EP_IN in eps for _, _, eps in out):
            return out
        fallback = fallback or out
    return fallback


def make_pkt(dst: int, cmd_set: int, cmd_id: int, payload: bytes, ack: int, seq: int) -> bytes:
    return pack_duml(bytes([HOST, dst, seq & 0xFF, (seq >> 8) & 0xFF, ack, cmd_set, cmd_id]) + payload)


def handshake_plan() -> list[bytes]:
    init = [
        bytes([0x2A, 0x1F, 0x10, 0x27, 0x40, 0x00, 0x01]),
        bytes([0x2A, 0x5C, 0x11, 0x27, 0x40, 0x00, 0x51, 0x04]),
        bytes([0x2A, 0x9C, 0x12, 0x27, 0x42, 0x00, 0x32, 0x00]),
        bytes([0x2A, 0x9C, 0x13, 0x27, 0x42, 0x00, 0x32, 0x31, 0x31, 0x00, 0x00, 0x00]),
    ]
    plan = [pack_duml(b) for b in init]
    for i in range(24):
        plan.append(pack_duml(bytes([0x2A, 0xBC, 0x14 + i, 0x27, 0x40, 0x00, 0x4F, 0x01,
                                     0x00, i, 0x00, 0x00, 0xE8, 0x03, 0x00, 0x00])))
    return plan


CANDIDATES = [0x64, 0x65, 0x66, 0x63, 0x67, 0x60, 0x61, 0x62,
              0x68, 0x69, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F]


def selftest() -> None:
    assert make_pkt(WMS, CMDSET_WMS, 0x64, b"\x01", 0x40, 0x2711).hex() == "550e04662a1b112740076401349d"
    assert make_pkt(WMS, 0x00, 0x01, b"", 0x40, 0x2711).hex() == "550d04332a1b11274000012a51"
    assert handshake_plan()[0].hex() == "550d04332a1f1027400001c24a"
    assert handshake_plan()[4].hex() == "551604fc2abc142740004f0100000000e80300005a6f"


def adb_state() -> str:
    r = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=15)
    return "\n".join(l for l in r.stdout.splitlines()[1:] if l.strip())


def find_pipe(bus: int | None, addr: int | None, want_iface: int) -> tuple[object, int]:
    """Pick the interface exposing bulk EP 0x04 OUT / 0x85 IN (iface 4 on retail 29020)."""
    found = [(d, i) for d, i, eps in pipes() if EP_OUT in eps and EP_IN in eps]
    if not found:
        hint = ("\nnote: the adb server is holding the WinUSB ADB interface; libusb-1.0 opens every WinUSB "
                "interface of the composite and gets Access denied on that one. `adb kill-server` first "
                "if you really need the DUML pipe.") if adb_state() else ""
        raise SystemExit(f"no {VID:04x}:{PID:04x} interface with EP {EP_OUT:#04x}/{EP_IN:#04x} "
                         "(powered off / charger mode / already in acm,adb mode / no libusb or WinUSB driver?)"
                         + hint)
    if bus is not None:
        found = [(d, i) for d, i in found if int(d.bus) == bus and int(d.address) == addr]
        if not found:
            raise SystemExit(f"no pipe at bus={bus} addr={addr}")
    units = {(int(d.bus), int(d.address)) for d, _ in found}
    if len(units) > 1 and bus is None:
        raise SystemExit(f"{len(units)} goggles on USB share VID:PID and serial; pass --bus/--address "
                         f"({sorted(units)})")
    dev, iface = found[0]
    if want_iface != iface:
        print(f"note: EP {EP_OUT:#04x}/{EP_IN:#04x} is on iface {iface}, not {want_iface}")
    _OPEN.append(dev)
    return dev, iface


def write(dev, data: bytes) -> bool:
    try:
        dev.write(EP_OUT, data, 2000)
        return True
    except usb.core.USBError as e:
        print(f"  OUT failed ({e}) -- pipe gone")
        return False


def read(dev, size: int, timeout_ms: int) -> bytes | None:
    """bytes on data, b'' on timeout, None on any other error (device gone)."""
    try:
        return bytes(dev.read(EP_IN, size, timeout_ms))
    except usb.core.USBError as e:
        return b"" if re.search(r"timeout|timed out", str(e), re.I) else None


def reassembled(blob: bytes) -> str:
    """Concatenate DUML frame payloads (drop 0x55 hdr + crc16) so fragmented XML joins up."""
    out, i = bytearray(), 0
    while i + 4 <= len(blob):
        if blob[i] != 0x55:
            i += 1
            continue
        n = blob[i + 1] | ((blob[i + 2] & 0x03) << 8)
        if n < 6 or i + n > len(blob):
            i += 1
            continue
        out += blob[i + 4:i + n - 2]
        i += n
    return "".join(chr(c) if 0x20 <= c < 0x7F else " " for c in out)


def attr(s: str, key: str) -> str | None:
    m = re.search(re.escape(key) + r'"([^"]*)"', s)
    return m.group(1) if m and m.group(1).strip() else None


def handshake(dev, log_raw) -> bytes:
    blob = b""
    plan = handshake_plan()
    for i, pkt in enumerate(plan):
        if not write(dev, pkt):
            break
        time.sleep(0.05 if i < 4 else 0.06)
        chunk = read(dev, 65536, 60)
        if chunk is None:
            break
        blob += chunk
        if EXPECT in blob:
            break
    for _ in range(20):
        if EXPECT in blob:
            break
        chunk = read(dev, 65536, 50)
        if not chunk:
            break
        blob += chunk
    if log_raw:
        open(log_raw, "wb").write(blob)
    return blob


def layout() -> list[str]:
    """Current USB interface classes of every 2CA3:0020 pipe (for before/after diff)."""
    return sorted({f"iface {i} class {u.bInterfaceClass:02x}/{u.bInterfaceSubClass:02x}/{u.bInterfaceProtocol:02x} "
                   f"eps={[hex(e.bEndpointAddress) for e in u]}"
                   for d, i, _ in pipes() for u in d.get_active_configuration() if u.bInterfaceNumber == i})


def wait_gone(dev, seconds: float) -> bool:
    """True once the pipe errors out (gadget torn down) = the enable took."""
    end = time.time() + seconds
    while time.time() < end:
        if read(dev, 1024, 250) is None:
            return True
    return False


def send_enable(dev, cmd_id: int, seq: int) -> bool:
    pkt = make_pkt(WMS, CMDSET_WMS, cmd_id, b"\x01", 0x40, seq)
    print(f"-> 07/{cmd_id:02x} [01]  {pkt.hex()}")
    if not write(dev, pkt):
        return True
    t0 = time.time()
    ack = read(dev, 1024, 300)
    if ack:
        print(f"<- ack in {time.time() - t0:.2f}s  {ack.hex()}")
    gone = wait_gone(dev, 5.0)
    print(f"   {'USB torn down after %.1fs' % (time.time() - t0) if gone else 'still enumerated after 5s'}")
    return gone


def watch_adb(seconds: float = 25.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        r = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=15)
        if re.search(r"^\S+\s+device\b", r.stdout, re.M):
            return True
        if re.search(r"^\S+\s+(unauthorized|offline)\b", r.stdout, re.M):
            print(r.stdout.strip())
        time.sleep(2)
    return False


def adb_identity() -> None:
    cmd = ("echo uid=$(id -u); for p in ro.build.version.incremental ro.dji.build.version ro.build.type "
           "ro.debuggable ro.boot.slot_suffix sys.usb.config; do echo $p=$(getprop $p); done; "
           "echo selinux=$(getenforce); tr ' ' '\\n' < /proc/cmdline | grep '^androidboot.mode='")
    r = subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, timeout=40)
    print("root shell: " + " | ".join(l.strip() for l in (r.stdout or r.stderr).splitlines() if l.strip()))


def attempt(a) -> tuple[object | None, int, bytes]:
    """Open the pipe and run the handshake. dev is None unless </dji> came back."""
    dev, iface = find_pipe(a.bus, a.address, a.iface)
    try:
        usb.util.claim_interface(dev, iface)
    except usb.core.USBError as e:
        raise SystemExit(f"cannot claim iface {iface}: {e} (DJI Assistant / another tool holding it?)")
    for _ in range(15):  # drain stale IN data
        if not read(dev, 65536, 100):
            break
    blob = handshake(dev, None)
    if EXPECT in blob:
        return dev, iface, blob
    _OPEN.remove(dev)
    usb.util.dispose_resources(dev)
    return None, iface, blob


def main() -> int:
    global ADB
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--enable", action="store_true", help="send the primary 07/64 enable after the handshake")
    ap.add_argument("--scan", action="store_true", help="after --enable failed: scan cmd_id 0x60..0x6F")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="poll until the goggles answer DUML (up to N seconds), then continue")
    ap.add_argument("--settle", type=float, default=20.0,
                    help="seconds to let boot finish before --enable when --wait got the hit")
    ap.add_argument("--iface", type=int, default=4)
    ap.add_argument("--bus", type=int)
    ap.add_argument("--address", type=int)
    ap.add_argument("--adb", help=f"adb executable (default: $ADB, PATH, then {ADB!r})")
    ap.add_argument("--raw", help="write the handshake IN blob to this file")
    a = ap.parse_args()
    if a.adb:
        ADB = a.adb

    selftest()
    if a.scan and not a.enable:
        ap.error("--scan requires --enable")

    deadline, n, prev, last_note = time.time() + a.wait, 0, None, 0.0
    while True:
        n += 1
        try:
            dev, iface, blob = attempt(a)
            state = "answered" if dev else "silent"
        except SystemExit:
            if a.wait <= 0:
                raise
            dev, iface, blob, state = None, a.iface, b"", "absent"
        if dev:
            break
        if time.time() >= deadline:
            text = reassembled(blob)
            print(f"handshake: {len(blob)} bytes, NO </dji>")
            print("diag: " + (text.strip()[:300] or "device silent -- dji_network not running "
                                                    "(charger mode / powered off) or wrong pipe"))
            return 2
        seen = adb_state()
        if seen:
            raise SystemExit("adb already sees a device, not sending anything to another unit:\n" + seen)
        if state != prev or time.time() - last_note > 300:
            print(f"[{time.strftime('%H:%M:%S')}] waiting: goggles {state} (attempt {n})")
            prev, last_note = state, time.time()
        time.sleep(5)

    text = reassembled(blob)
    print(f"pipe: iface {iface} EP {EP_OUT:#04x}/{EP_IN:#04x} at bus={dev.bus} addr={dev.address}")
    print("before: " + " | ".join(layout()))
    print(f"handshake: {len(blob)} bytes, </dji> seen, dev={attr(text, 'id=')!r} "
          f"formal={attr(text, 'formal=')!r} version={attr(text, 'version=')!r}")
    if a.raw:
        Path(a.raw).write_bytes(blob)
    if not a.enable:
        return 0

    if n > 1:  # came up during --wait: let boot finish before touching sys.usb.config
        print(f"letting boot settle for {a.settle:.0f}s")
        time.sleep(a.settle)
        if not write(dev, handshake_plan()[0]) or read(dev, 65536, 800) is None:
            raise SystemExit("DUML pipe went away during settle -- rerun")

    time.sleep(0.2)
    for _ in range(15):
        if not read(dev, 65536, 100):
            break

    winner = None
    if send_enable(dev, 0x64, 0x2711):
        winner = 0x64
    elif a.scan:
        print("primary did not switch -- scanning")
        for i, cid in enumerate(c for c in CANDIDATES if c != 0x64):
            if send_enable(dev, cid, 0x2712 + i):
                winner = cid
                break
            time.sleep(0.2)
    if winner is None:
        print("FAILED: no cmd_id triggered a USB re-enumeration" + ("" if a.scan else " (no --scan: fallback not tried)"))
        return 3
    print(f"adb enabled by cmd_id 0x{winner:02x}; waiting for Windows to bind the ADB interface...")
    if watch_adb():
        print("adb: device online")
        adb_identity()
        return 0
    print("after: " + " | ".join(layout()))
    print("WARN: gadget switched but adb sees no device after 25s (driver for the ADB interface?)")
    return 4


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in _OPEN:
            try:
                usb.util.dispose_resources(d)
            except Exception:
                pass
