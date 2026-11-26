"""Read-only USB descriptor dump of every DJI device (VID 0x2CA3) currently attached.

    python usbdesc.py [--vid 0x2ca3]

Only GET_DESCRIPTOR / GET_CONFIGURATION control transfers are issued; no interface is claimed.
It needs the `goggles_tool` package from this repository and DJI Assistant's `libusb0.dll`
(which `goggles_tool.usb.backend._try_libusb0` locates). With the libusb-win32 driver every
bound vendor interface shows up as its own pseudo-device, each listing only that interface.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "goggles_tool")))

import usb.core  # noqa: E402
import usb.util  # noqa: E402
from goggles_tool.usb.backend import _try_libusb0  # noqa: E402

TYPES = {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}


def string(dev, index):
    return usb.util.get_string(dev, index) if index else ""


def dump(dev):
    print("DEVICE bus %d addr %d VID %04x PID %04x" % (dev.bus, dev.address, dev.idVendor, dev.idProduct))
    print("  bcdUSB %04x  class %02x/%02x/%02x  maxpacket0 %d  bcdDevice %04x  configs %d" % (
        dev.bcdUSB, dev.bDeviceClass, dev.bDeviceSubClass, dev.bDeviceProtocol, dev.bMaxPacketSize0,
        dev.bcdDevice, dev.bNumConfigurations))
    print("  iManufacturer %r" % string(dev, dev.iManufacturer))
    print("  iProduct      %r" % string(dev, dev.iProduct))
    cfg = dev.get_active_configuration()
    print("  CONFIG %d: %d interfaces  bmAttributes 0x%02x  %d mA  iConfiguration %r" % (
        cfg.bConfigurationValue, cfg.bNumInterfaces, cfg.bmAttributes, cfg.bMaxPower * 8,
        string(dev, cfg.iConfiguration)))
    for itf in cfg:
        print("    INTERFACE %d alt %d  class %02x/%02x/%02x  endpoints %d  %r" % (
            itf.bInterfaceNumber, itf.bAlternateSetting, itf.bInterfaceClass, itf.bInterfaceSubClass,
            itf.bInterfaceProtocol, itf.bNumEndpoints, string(dev, itf.iInterface)))
        for ep in itf:
            print("      EP 0x%02x %-3s %-11s maxpacket %d  interval %d" % (
                ep.bEndpointAddress, "in" if usb.util.endpoint_direction(ep.bEndpointAddress) else "out",
                TYPES.get(usb.util.endpoint_type(ep.bmAttributes), "?"), ep.wMaxPacketSize, ep.bInterval))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vid", type=lambda x: int(x, 0), default=0x2CA3)
    a = ap.parse_args()
    backend = _try_libusb0()
    if backend is None:
        raise SystemExit("no libusb0 backend (DJI Assistant's libusb0.dll)")
    n = 0
    for dev in usb.core.find(find_all=True, idVendor=a.vid, backend=backend):
        n += 1
        try:
            dump(dev)
        except Exception as e:  # noqa: BLE001
            print("  error: %s: %s" % (type(e).__name__, e))
    print("devices: %d" % n)


if __name__ == "__main__":
    main()
