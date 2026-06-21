"""Session byte tracking for DUSS 0a5d / 2abc families."""
from __future__ import annotations

from . import duss


def ingest_session_blob(state: dict, data: bytes) -> None:
    """Update rolling session counters from bulk IN data."""
    s = duss.scan_session(data)
    if s:
        state["transfer"] = s
    s2 = duss.scan_session_bc(data)
    if s2:
        state["version"] = s2


def transfer_session_hi(state: dict, default: int = 0x5F) -> int:
    """Session hi byte for export/file 0a5d requests."""
    if "transfer" in state:
        return state["transfer"][0]
    if "version" in state:
        # Capture gap: file/export session often > version session base.
        return (state["version"][0] + 0x48) & 0xFF
    return default


def transfer_session_lo(state: dict, default: int = 0x27) -> int:
    if "transfer" in state:
        return state["transfer"][1]
    return default
