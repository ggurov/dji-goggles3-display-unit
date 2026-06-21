"""Frame templates extracted from USBPcap Init/Upgrade captures (2026-06-17/18).

These are replayed byte-for-byte where possible; CRC16 tail bytes are kept from capture
until we reverse the checksum algorithm.
"""
from __future__ import annotations

from .constants import EXPORT_LIST_PATH

# Minimal pre-version handshake (Init t=26.11s)
HANDSHAKE_OPEN = bytes.fromhex("550d04332a1f1027400001c24a")

# Pre-version OUT sequence before first 0x4f01 ack (Init t=26.44–26.68s)
PRE_VERSION_OUT: tuple[bytes, ...] = (
    bytes.fromhex("550e04662a5c112740005104988e"),
    bytes.fromhex("550e04662a9c12274200320091f3"),
    bytes.fromhex("551204c72a9c132742003231310000005f9f"),
)

# 278-byte get_version IN/OUT chunk size on wire.
VERSION_CHUNK_SIZE = 278

# Triggers 278-byte version/XML chunk stream; use captured frames (CRC/session byte).
VERSION_CHUNK_ACK = bytes.fromhex(
    "551604fc2abc142740004f0100000000e80300005a6f"
)

# First get_version session: exact 22-byte OUT acks from Init USBPcap (seq 0..17).
VERSION_ACK_FRAMES: tuple[bytes, ...] = (
    bytes.fromhex("551604fc2abc142740004f0100000000e80300005a6f"),
    bytes.fromhex("551604fc2abc152740004f0100010000e8030000658e"),
    bytes.fromhex("551604fc2abc162740004f0100020000e803000035a5"),
    bytes.fromhex("551604fc2abc172740004f0100030000e80300000a44"),
    bytes.fromhex("551604fc2abc182740004f0100040000e8030000f61c"),
    bytes.fromhex("551604fc2abc192740004f0100050000e8030000c9fd"),
    bytes.fromhex("551604fc2abc1a2740004f0100060000e803000099d6"),
    bytes.fromhex("551604fc2abc1b2740004f0100070000e8030000a637"),
    bytes.fromhex("551604fc2abc1c2740004f0100080000e8030000d55e"),
    bytes.fromhex("551604fc2abc1d2740004f0100090000e8030000eabf"),
    bytes.fromhex("551604fc2abc1e2740004f01000a0000e8030000ba94"),
    bytes.fromhex("551604fc2abc1f2740004f01000b0000e80300008575"),
    bytes.fromhex("551604fc2abc202740004f01000c0000e8030000115e"),
    bytes.fromhex("551604fc2abc212740004f01000d0000e80300002ebf"),
    bytes.fromhex("551604fc2abc222740004f01000e0000e80300007e94"),
    bytes.fromhex("551604fc2abc232740004f01000f0000e80300004175"),
    bytes.fromhex("551604fc2abc242740004f0100100000e8030000fba9"),
    bytes.fromhex("551604fc2abc252740004f0100110000e8030000c448"),
)

_EXPORT_LIST_OUT_HEX = (
    "559204e80a5d4d2740002a08802f626c61636b626f782f696e666f2f6578706f"
    "72745f6c6973742e6a736f6e0000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000901000256"
)


def build_export_list_request_from_capture() -> bytes:
    """Exact 146-byte Init capture OUT frame (export_list.json request)."""
    return bytes.fromhex(_EXPORT_LIST_OUT_HEX)


# IN echo of same request (not used for PC→device).
EXPORT_LIST_REQUEST_IN_ECHO = bytes.fromhex(
    "559204e85d0a4c27c000ea000a0101002f626c61636b626f782f696e666f2f"
    "6578706f72745f6c6973742e6a736f6e00000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000008b99"
)


def build_export_list_request(path: str = EXPORT_LIST_PATH) -> bytes:
    """Build export list request; only exact default path is validated today."""
    if path != EXPORT_LIST_PATH:
        raise NotImplementedError(
            f"only default path supported until CRC is reversed: {EXPORT_LIST_PATH}"
        )
    return build_export_list_request_from_capture()


# Log download open (Init t=60.58s, 16 bytes OUT) — may precede per-file request
LOG_DOWNLOAD_OPEN = bytes.fromhex("551004560a5d5f270000ea0a0105f00a")

# Per-file download (Init t=60.58s, 67 bytes OUT) — flight0360 GFLY log from capture.
LOG_FILE_DOWNLOAD_FLIGHT0360 = bytes.fromhex(
    "554304740a5d602740002a08312f626c61636b626f782f666c6967687430333630"
    "2f676c735f666c796374726c2f47464c592d303336302d30312e444154090104249e"
)

# Other paths seen in same capture (67-byte OUT, for future path builder):
# /blackbox/flight0361/gls_flyctrl/GFLY-0361-01.DAT
# /blackbox/camera//log/duss_object_ref_history.log

# Upgrade IM*H chunk header start (Upgrade t=49.96s, first 2048 B OUT) — partial
FIRMWARE_CHUNK_PREFIX = bytes.fromhex(
    "55e607872abc692740002a0400000000494d2a48"
)


def build_version_ack(seq: int) -> bytes:
    """PC ack for each 278-byte get_version fragment (seq = 0..N)."""
    if seq < len(VERSION_ACK_FRAMES):
        return VERSION_ACK_FRAMES[seq]
    buf = bytearray(VERSION_CHUNK_ACK)
    buf[8] = (0x14 + seq) & 0xFF
    buf[12:16] = seq.to_bytes(4, "little")
    return bytes(buf)
