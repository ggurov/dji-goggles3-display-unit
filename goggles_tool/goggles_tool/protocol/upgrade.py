"""Upgrade FSM phase names and captured control frames (USBPcap 2026-06-18)."""
from __future__ import annotations

# Matches upgrade.json + DJIGlsService.dll + wire strings in Upgrade capture.
PHASES = (
    "get_version",
    "request_upgrade",
    "check_status",
    "request_accept_data",
    "transfer_data",
    "transfer_complete",
    "reboot",
)

# Pre-upload control burst before first 2048 B IM*H OUT (Upgrade t≈49.96s).
# Extracted from 20260618_061541_Upgrade.pcapng; replay order matters.
PRE_UPLOAD_OUT_FRAMES: tuple[bytes, ...] = (
    bytes.fromhex("550d04332a1f1027400001c24a"),  # same session open as Init
)

# First firmware chunk header (2048 B total in capture; prefix is DUSS + IM*H start).
FIRMWARE_FIRST_CHUNK_HEADER = bytes.fromhex(
    "55e607872abc692740002a0400000000494d2a48"
)
