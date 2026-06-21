"""USB backend selection for DJI Goggles (libusb-win32 on Windows)."""
from __future__ import annotations

import platform
import sys
from pathlib import Path

_backend = None
_backend_name: str | None = None

# Goggles MI_03–MI_07 use libusb-win32 (libusb0 API). 64-bit Python needs amd64 DLL.
_LIBUSB0_CANDIDATES = (
    Path(r"C:\Program Files (x86)\DJI Product\DJI Assistant 2 (Consumer Drones Series)")
    / "Drivers"
    / "Drivers_Win10"
    / "DJI_BULK"
    / "bulk_amd64"
    / "libusb0.dll",
    Path(r"C:\Program Files (x86)\DJI Product\DJI Assistant 2 (Consumer Drones Series)")
    / "DJIEngine"
    / "libusb0.dll",
    Path(r"C:\Windows\System32\libusb0.dll"),
)


def _find_libusb0_dll() -> str | None:
    for path in _LIBUSB0_CANDIDATES:
        if path.is_file():
            return str(path)
    return None


def _try_libusb0():
    dll = _find_libusb0_dll()
    if not dll:
        return None
    try:
        import usb.backend.libusb0

        return usb.backend.libusb0.get_backend(find_library=lambda _name, dll=dll: dll)
    except Exception:
        return None


def _try_libusb1():
    try:
        import libusb_package
        import usb.backend.libusb1

        return usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    except ImportError:
        import usb.backend.libusb1

        return usb.backend.libusb1.get_backend()


def get_backend():
    global _backend, _backend_name
    if _backend is not None:
        return _backend

    if platform.system() == "Windows":
        _backend = _try_libusb0()
        if _backend is not None:
            _backend_name = "libusb0"
            return _backend

    _backend = _try_libusb1()
    if _backend is not None:
        _backend_name = "libusb1"
    return _backend


def backend_name() -> str:
    get_backend()
    return _backend_name or "none"


def require_backend():
    be = get_backend()
    if be is None:
        raise RuntimeError(
            "No USB backend. Run: pip install -r requirements.txt\n"
            "On Windows with libusb-win32 goggles: install DJI Assistant (amd64 libusb0.dll) "
            "or place libusb0.dll on PATH. Close DJI Assistant before claiming bulk MI."
        )
    return be
