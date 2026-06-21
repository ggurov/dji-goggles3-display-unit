"""USB bulk transport for Goggles 3 (VID 2CA3:PID 0020)."""
from __future__ import annotations

import sys
from dataclasses import dataclass

from ..protocol.constants import EP_IN, EP_OUT, PID_GOGGLES3, VID_DJI
from .backend import backend_name, require_backend


@dataclass
class UsbEndpoints:
    ep_out: int
    ep_in: int
    interface: int


@dataclass
class _DeviceBinding:
    dev: object
    endpoints: UsbEndpoints


class UsbTransport:
    """Bulk transport via libusb0 (libusb-win32) or libusb-1.0. Close Assistant first."""

    def __init__(self, timeout_ms: int = 5000):
        self.timeout_ms = timeout_ms
        self._dev = None
        self._claimed: int | None = None
        self.endpoints: UsbEndpoints | None = None

    def open(
        self,
        interface: int | None = None,
        *,
        bus: int | None = None,
        address: int | None = None,
    ) -> UsbEndpoints:
        import usb.core
        import usb.util

        backend = require_backend()
        devs = list(
            usb.core.find(
                find_all=True,
                idVendor=VID_DJI,
                idProduct=PID_GOGGLES3,
                backend=backend,
            )
        )
        if not devs:
            raise RuntimeError(
                "Goggles not found (VID 2CA3 PID 0020). USB connected? Driver installed?"
            )

        if bus is not None or address is not None:
            filtered = [
                d
                for d in devs
                if (bus is None or int(d.bus) == bus)
                and (address is None or int(d.address) == address)
            ]
            if not filtered:
                raise RuntimeError(
                    f"No goggles at bus={bus} address={address}; "
                    f"seen={sorted({(int(d.bus), int(d.address)) for d in devs})}"
                )
            devs = filtered

        bindings = self._enumerate_bindings(devs, interface)
        if not bindings:
            raise RuntimeError("No bulk IN/OUT pair found on goggles USB interfaces")

        binding = bindings[0]
        self._dev = binding.dev
        eps = binding.endpoints

        if self._claimed is not None:
            try:
                usb.util.release_interface(self._dev, self._claimed)
            except Exception:
                pass
        usb.util.claim_interface(self._dev, eps.interface)
        self._claimed = eps.interface
        self.endpoints = eps
        return eps

    def close(self) -> None:
        if self._dev is None:
            return
        import usb.util

        if self._claimed is not None:
            try:
                usb.util.release_interface(self._dev, self._claimed)
            except Exception:
                pass
        usb.util.dispose_resources(self._dev)
        self._dev = None
        self._claimed = None
        self.endpoints = None

    def write(self, data: bytes) -> int:
        if not self._dev or not self.endpoints:
            raise RuntimeError("USB not open")
        return self._dev.write(self.endpoints.ep_out, data, self.timeout_ms)

    def read(self, size: int = 65536, timeout_ms: int | None = None) -> bytes:
        if not self._dev or not self.endpoints:
            raise RuntimeError("USB not open")
        to = self.timeout_ms if timeout_ms is None else timeout_ms
        try:
            return bytes(self._dev.read(self.endpoints.ep_in, size, to))
        except Exception as e:
            err = str(e).lower()
            if "timeout" in err or "timed out" in err or "timedout" in err:
                return b""
            raise

    def _enumerate_bindings(
        self, devs: list, want_iface: int | None
    ) -> list[_DeviceBinding]:
        import usb.util

        bindings: list[_DeviceBinding] = []
        for dev in devs:
            try:
                dev.set_configuration()
            except Exception:
                continue
            try:
                cfg = dev.get_active_configuration()
            except Exception:
                continue
            for intf in cfg:
                ep_out = ep_in = None
                for ep in intf:
                    addr = ep.bEndpointAddress
                    if usb.util.endpoint_direction(addr) == usb.util.ENDPOINT_OUT:
                        ep_out = addr
                    else:
                        ep_in = addr
                if ep_out is None or ep_in is None:
                    continue
                bindings.append(
                    _DeviceBinding(
                        dev=dev,
                        endpoints=UsbEndpoints(
                            ep_out=ep_out, ep_in=ep_in, interface=intf.bInterfaceNumber
                        ),
                    )
                )

        if want_iface is not None:
            bindings = [b for b in bindings if b.endpoints.interface == want_iface]
            if not bindings:
                ifaces = sorted({b.endpoints.interface for b in self._enumerate_bindings(devs, None)})
                raise RuntimeError(
                    f"Interface {want_iface} not found; available: {ifaces}"
                )

        # Prefer capture endpoints 0x04 OUT / 0x85 IN (MI_04 / Assistant bulk).
        bulk = [b for b in bindings if b.endpoints.ep_out == EP_OUT and b.endpoints.ep_in == EP_IN]
        if bulk:
            if len(bulk) > 1:
                # Two goggles on USB share serial 987654321ABCDEF; higher address = retail LOGH.
                bulk.sort(key=lambda b: int(b.dev.address), reverse=True)
            return [bulk[0]]
        for b in bindings:
            if b.endpoints.interface == 4:
                return [b]
        return bindings[:1]

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()


def list_devices() -> list[dict]:
    import usb.core
    import usb.util

    backend = require_backend()
    out: list[dict] = []
    seen: set[tuple[int, int, int]] = set()
    for dev in usb.core.find(
        find_all=True, idVendor=VID_DJI, idProduct=PID_GOGGLES3, backend=backend
    ):
        try:
            dev.set_configuration()
            cfg = dev.get_active_configuration()
        except Exception:
            continue
        try:
            serial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else ""
        except Exception:
            serial = ""
        for intf in cfg:
            key = (dev.bus, dev.address, intf.bInterfaceNumber)
            if key in seen:
                continue
            seen.add(key)
            eps = []
            for ep in intf:
                eps.append(f"0x{ep.bEndpointAddress:02x}")
            out.append(
                {
                    "bus": dev.bus,
                    "address": dev.address,
                    "interface": intf.bInterfaceNumber,
                    "endpoints": eps,
                    "serial": serial,
                    "backend": backend_name(),
                    "bulk_log": intf.bInterfaceNumber == 4
                    and any(
                        usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT
                        and ep.bEndpointAddress == EP_OUT
                        for ep in intf
                    ),
                }
            )
    return out
