"""DUSS / DJI DUML framing (0x55 SOF) — parse and build with CRC."""
from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from typing import Iterable

# DJI DUML CRC tables (DUMLrub / phantom-firmware-tools / Guidance SDK).
_CRC16_TABLE = (
    0x0000, 0x1189, 0x2312, 0x329B, 0x4624, 0x57AD, 0x6536, 0x74BF,
    0x8C48, 0x9DC1, 0xAF5A, 0xBED3, 0xCA6C, 0xDBE5, 0xE97E, 0xF8F7,
    0x1081, 0x0108, 0x3393, 0x221A, 0x56A5, 0x472C, 0x75B7, 0x643E,
    0x9CC9, 0x8D40, 0xBFDB, 0xAE52, 0xDAED, 0xCB64, 0xF9FF, 0xE876,
    0x2102, 0x308B, 0x0210, 0x1399, 0x6726, 0x76AF, 0x4434, 0x55BD,
    0xAD4A, 0xBCC3, 0x8E58, 0x9FD1, 0xEB6E, 0xFAE7, 0xC87C, 0xD9F5,
    0x3183, 0x200A, 0x1291, 0x0318, 0x77A7, 0x662E, 0x54B5, 0x453C,
    0xBDCB, 0xAC42, 0x9ED9, 0x8F50, 0xFBEF, 0xEA66, 0xD8FD, 0xC974,
    0x4204, 0x538D, 0x6116, 0x709F, 0x0420, 0x15A9, 0x2732, 0x36BB,
    0xCE4C, 0xDFC5, 0xED5E, 0xFCD7, 0x8868, 0x99E1, 0xAB7A, 0xBAF3,
    0x5285, 0x430C, 0x7197, 0x601E, 0x14A1, 0x0528, 0x37B3, 0x263A,
    0xDECD, 0xCF44, 0xFDDF, 0xEC56, 0x98E9, 0x8960, 0xBBFB, 0xAA72,
    0x6306, 0x728F, 0x4014, 0x519D, 0x2522, 0x34AB, 0x0630, 0x17B9,
    0xEF4E, 0xFEC7, 0xCC5C, 0xDDD5, 0xA96A, 0xB8E3, 0x8A78, 0x9BF1,
    0x7387, 0x620E, 0x5095, 0x411C, 0x35A3, 0x242A, 0x16B1, 0x0738,
    0xFFCF, 0xEE46, 0xDCDD, 0xCD54, 0xB9EB, 0xA862, 0x9AF9, 0x8B70,
    0x8408, 0x9581, 0xA71A, 0xB693, 0xC22C, 0xD3A5, 0xE13E, 0xF0B7,
    0x0840, 0x19C9, 0x2B52, 0x3ADB, 0x4E64, 0x5FED, 0x6D76, 0x7CFF,
    0x9489, 0x8500, 0xB79B, 0xA612, 0xD2AD, 0xC324, 0xF1BF, 0xE036,
    0x18C1, 0x0948, 0x3BD3, 0x2A5A, 0x5EE5, 0x4F6C, 0x7DF7, 0x6C7E,
    0xA50A, 0xB483, 0x8618, 0x9791, 0xE32E, 0xF2A7, 0xC03C, 0xD1B5,
    0x2942, 0x38CB, 0x0A50, 0x1BD9, 0x6F66, 0x7EEF, 0x4C74, 0x5DFD,
    0xB58B, 0xA402, 0x9699, 0x8710, 0xF3AF, 0xE226, 0xD0BD, 0xC134,
    0x39C3, 0x284A, 0x1AD1, 0x0B58, 0x7FE7, 0x6E6E, 0x5CF5, 0x4D7C,
    0xC60C, 0xD785, 0xE51E, 0xF497, 0x8028, 0x91A1, 0xA33A, 0xB2B3,
    0x4A44, 0x5BCD, 0x6956, 0x78DF, 0x0C60, 0x1DE9, 0x2F72, 0x3EFB,
    0xD68D, 0xC704, 0xF59F, 0xE416, 0x90A9, 0x8120, 0xB3BB, 0xA232,
    0x5AC5, 0x4B4C, 0x79D7, 0x685E, 0x1CE1, 0x0D68, 0x3FF3, 0x2E7A,
    0xE70E, 0xF687, 0xC41C, 0xD595, 0xA12A, 0xB0A3, 0x8238, 0x93B1,
    0x6B46, 0x7ACF, 0x4854, 0x59DD, 0x2D62, 0x3CEB, 0x0E70, 0x1FF9,
    0xF78F, 0xE606, 0xD49D, 0xC514, 0xB1AB, 0xA022, 0x92B9, 0x8330,
    0x7BC7, 0x6A4E, 0x58D5, 0x495C, 0x3DE3, 0x2C6A, 0x1EF1, 0x0F78,
)

_CRC_HDR_TABLE = (
    0x00, 0x5E, 0xBC, 0xE2, 0x61, 0x3F, 0xDD, 0x83, 0xC2, 0x9C, 0x7E, 0x20, 0xA3, 0xFD, 0x1F, 0x41,
    0x9D, 0xC3, 0x21, 0x7F, 0xFC, 0xA2, 0x40, 0x1E, 0x5F, 0x01, 0xE3, 0xBD, 0x3E, 0x60, 0x82, 0xDC,
    0x23, 0x7D, 0x9F, 0xC1, 0x42, 0x1C, 0xFE, 0xA0, 0xE1, 0xBF, 0x5D, 0x03, 0x80, 0xDE, 0x3C, 0x62,
    0xBE, 0xE0, 0x02, 0x5C, 0xDF, 0x81, 0x63, 0x3D, 0x7C, 0x22, 0xC0, 0x9E, 0x1D, 0x43, 0xA1, 0xFF,
    0x46, 0x18, 0xFA, 0xA4, 0x27, 0x79, 0x9B, 0xC5, 0x84, 0xDA, 0x38, 0x66, 0xE5, 0xBB, 0x59, 0x07,
    0xDB, 0x85, 0x67, 0x39, 0xBA, 0xE4, 0x06, 0x58, 0x19, 0x47, 0xA5, 0xFB, 0x78, 0x26, 0xC4, 0x9A,
    0x65, 0x3B, 0xD9, 0x87, 0x04, 0x5A, 0xB8, 0xE6, 0xA7, 0xF9, 0x1B, 0x45, 0xC6, 0x98, 0x7A, 0x24,
    0xF8, 0xA6, 0x44, 0x1A, 0x99, 0xC7, 0x25, 0x7B, 0x3A, 0x64, 0x86, 0xD8, 0x5B, 0x05, 0xE7, 0xB9,
    0x8C, 0xD2, 0x30, 0x6E, 0xED, 0xB3, 0x51, 0x0F, 0x4E, 0x10, 0xF2, 0xAC, 0x2F, 0x71, 0x93, 0xCD,
    0x11, 0x4F, 0xAD, 0xF3, 0x70, 0x2E, 0xCC, 0x92, 0xD3, 0x8D, 0x6F, 0x31, 0xB2, 0xEC, 0x0E, 0x50,
    0xAF, 0xF1, 0x13, 0x4D, 0xCE, 0x90, 0x72, 0x2C, 0x6D, 0x33, 0xD1, 0x8F, 0x0C, 0x52, 0xB0, 0xEE,
    0x32, 0x6C, 0x8E, 0xD0, 0x53, 0x0D, 0xEF, 0xB1, 0xF0, 0xAE, 0x4C, 0x12, 0x91, 0xCF, 0x2D, 0x73,
    0xCA, 0x94, 0x76, 0x28, 0xAB, 0xF5, 0x17, 0x49, 0x08, 0x56, 0xB4, 0xEA, 0x69, 0x37, 0xD5, 0x8B,
    0x57, 0x09, 0xEB, 0xB5, 0x36, 0x68, 0x8A, 0xD4, 0x95, 0xCB, 0x29, 0x77, 0xF4, 0xAA, 0x48, 0x16,
    0xE9, 0xB7, 0x55, 0x0B, 0x88, 0xD6, 0x34, 0x6A, 0x2B, 0x75, 0x97, 0xC9, 0x4A, 0x14, 0xF6, 0xA8,
    0x74, 0x2A, 0xC8, 0x96, 0x15, 0x4B, 0xA9, 0xF7, 0xB6, 0xE8, 0x0A, 0x54, 0xD7, 0x89, 0x6B, 0x35,
)

PROTOCOL_V1 = 1 << 2  # upper bits of length byte 2


@dataclass
class DussFrame:
    raw: bytes
    length: int
    flags: int
    payload: bytes

    @property
    def is_xml(self) -> bool:
        return b"<?xml" in self.payload or b"<dji>" in self.payload

    @property
    def is_imh(self) -> bool:
        return b"IM*H" in self.raw or b"IM\x2aH" in self.raw

    @property
    def path(self) -> str | None:
        i = self.raw.find(b"/")
        if i < 0:
            return None
        j = self.raw.find(b"\x00", i)
        if j < 0:
            j = self.raw.find(b"\x09", i)  # file frames end path before 0x09 suffix
        if j < 0:
            return None
        try:
            return self.raw[i:j].decode("ascii")
        except UnicodeDecodeError:
            return None


def crc_hdr(data: bytes) -> int:
    crc = 0x77
    for b in data:
        crc = _CRC_HDR_TABLE[(crc ^ b) & 0xFF]
    return crc & 0xFF


def crc16(data: bytes) -> int:
    crc = 0x3692
    for b in data:
        crc = ((crc >> 8) & 0xFF) ^ _CRC16_TABLE[(crc ^ b) & 0xFF]
    return crc & 0xFFFF


def pack_length(total_len: int) -> tuple[int, int]:
    """DUML length encoding in bytes 1-2 (protocol v1 in upper bits of byte 2)."""
    if total_len > 1023:
        raise ValueError(f"DUML length {total_len} > 1023")
    return total_len & 0xFF, PROTOCOL_V1 | ((total_len >> 8) & 0x03)


def pack_duml(body: bytes) -> bytes:
    """Build a complete 0x55 DUML packet (4-byte hdr + body + CRC16)."""
    total = 4 + len(body) + 2
    b1, b2 = pack_length(total)
    hdr = bytes([0x55, b1, b2, crc_hdr(bytes([0x55, b1, b2]))])
    partial = hdr + body
    return partial + struct.pack("<H", crc16(partial))


def verify_packet(pkt: bytes) -> bool:
    if len(pkt) < 6 or pkt[0] != 0x55:
        return False
    total = pkt[1] + (pkt[2] & 0x03) * 256
    if total != len(pkt):
        return False
    if crc_hdr(pkt[0:3]) != pkt[3]:
        return False
    return crc16(pkt[:-2]) == struct.unpack_from("<H", pkt, len(pkt) - 2)[0]


def build_handshake() -> bytes:
    body = bytes([0x2A, 0x1F, 0x10, 0x27, 0x40, 0x00, 0x01])
    return pack_duml(body)


def build_pre_version(seq: int) -> bytes:
    """Pre-version OUT frames (Init capture); seq 0..2."""
    templates = (
        bytes([0x2A, 0x5C, 0x11, 0x27, 0x40, 0x00, 0x51, 0x04]),
        bytes([0x2A, 0x9C, 0x12, 0x27, 0x42, 0x00, 0x32, 0x00]),
        bytes([0x2A, 0x9C, 0x13, 0x27, 0x42, 0x00, 0x32, 0x31, 0x31, 0x00, 0x00, 0x00]),
    )
    if seq < len(templates):
        return pack_duml(templates[seq])
    raise IndexError(seq)


def build_version_ack(seq: int, session_base: int = 0x14) -> bytes:
    body = bytearray(
        [
            0x2A,
            0xBC,
            (session_base + seq) & 0xFF,
            0x27,
            0x40,
            0x00,
            0x4F,
            0x01,
            0x00,
            seq & 0xFF,
            0x00,
            0x00,
            0xE8,
            0x03,
            0x00,
            0x00,
        ]
    )
    return pack_duml(bytes(body))


def build_export_prep(session_hi: int, session_lo: int = 0x27) -> bytes:
    """16-byte open before export_list (Init: 0a5d XX 27 40 00 ea 0a 01 01)."""
    body = bytes([0x0A, 0x5D, session_hi & 0xFF, session_lo & 0xFF, 0x40, 0x00, 0xEA, 0x0A, 0x01, 0x01])
    return pack_duml(body)


def build_log_open(session_hi: int, session_lo: int = 0x27) -> bytes:
    """16-byte open before file download (Init: 0a5d XX 27 00 00 ea 0a 01 05)."""
    body = bytes([0x0A, 0x5D, session_hi & 0xFF, session_lo & 0xFF, 0x00, 0x00, 0xEA, 0x0A, 0x01, 0x05])
    return pack_duml(body)


def build_transfer_ack_open(session_hi: int = 0, session_lo: int = 0) -> bytes:
    """20-byte TRANS ack stage 1 (after initial 38/62 B IN)."""
    body = bytes(
        [
            0x0A,
            0x5D,
            session_hi & 0xFF,
            session_lo & 0xFF,
            0x80,
            0x00,
            0x2A,
            0x00,
            0xD0,
            0x03,
            0xA0,
            0x0F,
            0x01,
            0x01,
        ]
    )
    return pack_duml(body)


def build_transfer_ack_progress(progress: int) -> bytes:
    """18-byte TRANS ack — progress dword echoed from device IN (Init capture)."""
    body = bytes([0x0A, 0x5D, 0x00, 0x00, 0x80, 0x00, 0x2A, 0x00]) + struct.pack("<I", progress & 0xFFFFFFFF)
    return pack_duml(body)


def build_transfer_ack_done(session_hi: int = 0x1B) -> bytes:
    """14-byte TRANS ack stage 3 (export_list tail)."""
    body = bytes([0x0A, 0x5D, session_hi & 0xFF, 0x00, 0x80, 0x00, 0x2A, 0x00])
    return pack_duml(body)


def build_export_list_request(path: str, session_hi: int, session_lo: int = 0x27) -> bytes:
    """146-byte fixed export_list.json request (Init capture layout)."""
    body = bytearray(140)
    body[0:8] = bytes([0x0A, 0x5D, session_hi & 0xFF, session_lo & 0xFF, 0x40, 0x00, 0x2A, 0x08])
    body[8] = 0x80
    path_b = path.encode("ascii") + b"\x00"
    if len(path_b) > 128:
        raise ValueError(f"path too long for export frame: {path}")
    body[9 : 9 + len(path_b)] = path_b
    body[137:140] = bytes([0x09, 0x01, 0x00])
    return pack_duml(bytes(body))


def build_file_download_request(path: str, session_hi: int, session_lo: int = 0x27) -> bytes:
    """Variable-length blackbox file download (090104 read).

    Byte after 0x2a 0x08 is path length (retail capture 2026-06-20), not a fixed 0x31.
    """
    if not path.startswith("/"):
        path = "/" + path
    path_b = path.encode("ascii")
    if not path_b or len(path_b) > 250:
        raise ValueError(f"path length out of range: {len(path_b)}")
    body = bytearray(
        [
            0x0A,
            0x5D,
            session_hi & 0xFF,
            session_lo & 0xFF,
            0x40,
            0x00,
            0x2A,
            0x08,
            len(path_b) & 0xFF,
        ]
    )
    body += path_b
    body += bytes([0x09, 0x01, 0x04])
    return pack_duml(bytes(body))


def trans_declared_len(chunk: bytes) -> int:
    """Declared inner payload length from a 2112adde TRANS header."""
    if len(chunk) < 24 or not chunk.startswith(TRANS_MAGIC):
        return 0
    return struct.unpack_from("<I", chunk, 20)[0]


def is_trans_data_chunk(chunk: bytes) -> bool:
    return trans_declared_len(chunk) > 1000


def is_trans_window_tail(chunk: bytes) -> bool:
    """Short TRANS payload chunk closing a ~4 KiB download window (declared len 1..1000)."""
    declared = trans_declared_len(chunk)
    return 0 < declared <= 1000 and len(chunk) >= 24


def trans_window_tail_progress(chunk: bytes) -> int:
    """Progress dword for ack_prog after a window tail (Init: u32 @ TRANS+12)."""
    if len(chunk) >= 16:
        seq = struct.unpack_from("<I", chunk, 12)[0]
        if seq:
            return seq
    return ack_progress_from_trans(chunk) or 0


def scan_session(blob: bytes) -> tuple[int, int] | None:
    """Find latest 0a5d SESSION 27 marker in bulk IN blob."""
    last: tuple[int, int] | None = None
    i = 0
    while i + 4 < len(blob):
        if blob[i : i + 2] == b"\x0a\x5d" and blob[i + 3] == 0x27:
            last = (blob[i + 2], blob[i + 3])
        i += 1
    return last


def scan_session_bc(blob: bytes) -> tuple[int, int] | None:
    """Find latest 2abc SESSION 27 marker (version ack family)."""
    last: tuple[int, int] | None = None
    i = 0
    while i + 4 < len(blob):
        if blob[i : i + 2] == b"\x2a\xbc" and blob[i + 3] == 0x27:
            last = (blob[i + 2], blob[i + 3])
        i += 1
    return last


def parse_frame(buf: bytes) -> DussFrame | None:
    if len(buf) < 6 or buf[0] != 0x55:
        return None
    total_len = buf[1] + (buf[2] & 0x03) * 256
    if total_len < 6 or len(buf) < total_len:
        return None
    frame = buf[:total_len]
    return DussFrame(
        raw=frame,
        length=total_len,
        flags=frame[2],
        payload=frame[4:-2],
    )


def iter_packets(blob: bytes) -> Iterable[bytes]:
    """Yield complete validated DUML packets from a bulk stream."""
    i = 0
    while i < len(blob):
        if blob[i] != 0x55:
            i += 1
            continue
        if i + 4 > len(blob):
            break
        total = blob[i + 1] + (blob[i + 2] & 0x03) * 256
        if total < 6 or i + total > len(blob):
            i += 1
            continue
        pkt = blob[i : i + total]
        if verify_packet(pkt):
            yield pkt
            i += total
        else:
            i += 1


def iter_frames(blob: bytes) -> Iterable[DussFrame]:
    for pkt in iter_packets(blob):
        fr = parse_frame(pkt)
        if fr:
            yield fr


def reassemble_xml(frames: Iterable[DussFrame]) -> str:
    parts: list[str] = []
    for fr in frames:
        if not fr.is_xml:
            continue
        raw = fr.raw
        start = raw.find(b"<?xml")
        if start < 0:
            start = raw.find(b"<dji>")
        if start < 0:
            continue
        parts.append(raw[start : fr.length - 2].decode("utf-8", errors="replace"))
    return "".join(parts)


TRANS_MAGIC = b"\x21\x12\xad\xde"
TRANS_DATA_CHUNK = 31832


def parse_trans_meta(chunk: bytes) -> dict | None:
    """Parse leading 2112adde TRANS header from bulk IN (38/62 B setup or data chunk)."""
    if len(chunk) < 24 or not chunk.startswith(TRANS_MAGIC):
        return None
    return {
        "ack_session_hi": chunk[12],
        "ack_session_lo": chunk[13],
        "seq": struct.unpack_from("<I", chunk, 12)[0] if len(chunk) >= 16 else 0,
        "progress": struct.unpack_from("<I", chunk, 20)[0] if len(chunk) >= 24 else 0,
    }


def ack_progress_from_trans(chunk: bytes) -> int | None:
    """Progress dword echoed in OUT ack_prog.

    Init GFLY capture: matches u32 @ TRANS+12 (seq/session field) on ~31 KiB data chunks.
    """
    meta = parse_trans_meta(chunk)
    if not meta:
        return None
    if len(chunk) >= TRANS_DATA_CHUNK:
        seq = struct.unpack_from("<I", chunk, 12)[0]
        if seq:
            return seq
    if meta["progress"]:
        return meta["progress"]
    return meta["seq"] or None


def iter_trans_chunks(blob: bytes, min_size: int = 24) -> Iterable[tuple[int, bytes]]:
    """Yield (offset, chunk_bytes) for each 2112adde TRANS segment."""
    i = 0
    while i < len(blob):
        j = blob.find(TRANS_MAGIC, i)
        if j < 0:
            break
        seg_len = struct.unpack_from("<I", blob, j + 20)[0] if j + 24 <= len(blob) else 0
        if seg_len > 1000:
            span = min(TRANS_DATA_CHUNK, len(blob) - j)
        elif seg_len:
            span = min(seg_len + 24, len(blob) - j)
        else:
            span = min(128, len(blob) - j)
        chunk = blob[j : j + span]
        if len(chunk) >= min_size:
            yield j, chunk
        i = j + max(span, 4)


def iter_trans_segments(blob: bytes) -> Iterable[bytes]:
    """Yield inner payload spans from 2112adde TRANS wrappers."""
    i = 0
    while i < len(blob):
        j = blob.find(TRANS_MAGIC, i)
        if j < 0:
            if i < len(blob):
                yield blob[i:]
            break
        if j > i:
            yield blob[i:j]
        if j + 24 > len(blob):
            break
        seg_len = struct.unpack_from("<I", blob, j + 20)[0]
        inner_start = j + 24
        inner_end = inner_start + seg_len if seg_len else len(blob)
        if inner_end > len(blob):
            inner_end = len(blob)
        yield blob[inner_start:inner_end]
        i = inner_end


def reassemble_trans_payload(blob: bytes) -> bytes:
    """Concatenate TRANS segment payloads; unwrap nested 0x55 where present."""
    out = bytearray()
    for seg in iter_trans_segments(blob):
        if not seg:
            continue
        if seg[0] == 0x55:
            for pkt in iter_packets(seg):
                body = pkt[4:-2]
                if b"[L-DBG" in body or b"sys_time" in body:
                    continue
                if body[:2] in (b"\x5d\x0a", b"\x0a\x5d"):
                    continue
                if len(body) > 16:
                    out += body[16:] if body[:4] == TRANS_MAGIC else body
        elif TRANS_MAGIC not in seg[:4]:
            out += seg
    if not out:
        out = bytearray(blob)
    return bytes(out)


def _collect_export_json_parts(raw: bytes) -> bytes:
    """Stitch export_list JSON fragments from interleaved TRANS/DUML packets."""
    out = bytearray()
    i = 0
    while i < len(raw):
        j = raw.find(b"\x55", i)
        if j < 0:
            break
        if j + 4 > len(raw):
            break
        total = raw[j + 1] + (raw[j + 2] & 0x03) * 256
        if total < 8 or j + total > len(raw):
            i = j + 1
            continue
        body = raw[j + 4 : j + total - 2]
        if b"[L-DBG" in body or b"sys_time" in body:
            i = j + total
            continue
        anchor = body.find(b"\x2a\x04")
        if anchor >= 0:
            if out:
                piece = body[anchor + 6 :]
            else:
                sub = body[anchor:]
                k = sub.find(b"{")
                if k < 0:
                    k = sub.find(b'"')
                piece = sub[k:] if k >= 0 else body[anchor + 6 :]
        else:
            piece = body
        cut = piece.find(b"\x55")
        if cut >= 0:
            piece = piece[:cut]
        if not piece:
            i = j + total
            continue
        if out:
            lead = piece.lstrip()
            if not lead or lead[0:1] not in b"{[\"0123456789\t\n\r}":
                i = j + total
                continue
        if b"[L-DBG" in piece or b"sys_time" in piece:
            i = j + total
            continue
        out += piece
        i = j + total
    for marker in (b"[L-DBG", b"\x00Y\n", b"\x00\x0ew"):
        idx = out.find(marker)
        if idx > 0:
            del out[idx:]
            break
    start = out.find(b"{")
    if start > 0:
        out = out[start:]
    cleaned = bytearray()
    for b in out:
        if b in (9, 10, 13) or 32 <= b < 127:
            cleaned.append(b)
    return bytes(cleaned)


_BLACKBOX_PATH_RE = re.compile(rb'"/blackbox/[A-Za-z0-9_./-]+"')


def extract_log_paths(raw: bytes) -> list[str]:
    """Best-effort path list from full or partial export_list bulk capture."""
    js = extract_json_blob(raw)
    if js is not None:
        try:
            obj = json.loads(js.decode("utf-8"))
            if isinstance(obj, dict) and isinstance(obj.get("log_list"), list):
                return [e["path"] for e in obj["log_list"] if isinstance(e, dict) and e.get("path")]
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    flat = _collect_export_json_parts(raw)
    seen: set[str] = set()
    out: list[str] = []
    for m in _BLACKBOX_PATH_RE.finditer(flat):
        p = m.group(0)[1:-1].decode("ascii", errors="ignore")
        if p.startswith("/blackbox/") and p not in seen and "\n" not in p and "\t" not in p:
            seen.add(p)
            out.append(p)
    return out


def extract_json_blob(raw: bytes) -> bytes | None:
    """Pull JSON object from DUSS-wrapped export_list response."""
    blob = _collect_export_json_parts(raw)
    js = _extract_json_from_flat(blob)
    if not js:
        return None
    try:
        json.loads(js.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return js


def _extract_json_from_flat(raw: bytes) -> bytes | None:
    """Extract export_list JSON object from a flat or reassembled buffer."""
    m = re.search(rb"\{\s*\"product_info\"", raw)
    if not m:
        m = re.search(rb"\{\s*\"log_list\"", raw)
    if not m:
        return None
    start = m.start()
    depth = 0
    for j in range(start, len(raw)):
        if raw[j] == ord("{"):
            depth += 1
        elif raw[j] == ord("}"):
            depth -= 1
            if depth == 0:
                return raw[start : j + 1]
    return None


def _is_bulk_trans_seam(body: bytes, marker_off: int) -> bool:
    trim = 12
    if marker_off < trim or marker_off + 2 > len(body):
        return False
    pre = body[marker_off - trim : marker_off]
    return pre.endswith(b"\x00\x00") and b"\x55\xe2" in pre


def _strip_embedded_duss_markers(body: bytes) -> bytes:
    """Remove bulk TRANS \\x2a\\x04 seam framing from LOGH ciphertext."""
    out = bytearray()
    i = 0
    trim = 12
    while i < len(body):
        j = i
        while j + 2 <= len(body) and body[j : j + 2] != b"\x2a\x04":
            j += 1
        if j >= len(body):
            out += body[i:]
            break
        if not _is_bulk_trans_seam(body, j):
            out += body[i : j + 2]
            i = j + 2
            continue
        out += body[i : max(i, j - trim)]
        i = j + 12
    return bytes(out)


def _concat_duml_payloads(segment: bytes) -> bytes:
    """Walk concatenated 0x55 DUML packets; keep raw spans between them."""
    out = bytearray()
    i = 0
    while i < len(segment):
        if segment[i] != 0x55:
            j = i
            while j < len(segment) and segment[j] != 0x55:
                j += 1
            out += segment[i:j]
            i = j
            continue
        total = segment[i + 1] + (segment[i + 2] & 0x03) * 256
        if total < 8 or i + total > len(segment):
            out.append(segment[i])
            i += 1
            continue
        pkt = segment[i : i + total]
        if not verify_packet(pkt):
            out.append(segment[i])
            i += 1
            continue
        body = pkt[4:-2]
        out += _strip_chunk_framing(body)
        i += total
    return bytes(out)


def _extract_inner_file_payload(segment: bytes) -> bytes:
    """Reassemble file bytes from a TRANS inner segment (one or many DUML packets)."""
    merged = _concat_duml_payloads(segment)
    logh = merged.find(b"LOGH")
    return merged[logh:] if logh >= 0 else merged


def _unwrap_duml_segment(segment: bytes) -> bytes:
    """Payload of the leading 0x55 DUML packet in a TRANS inner segment."""
    if not segment or segment[0] != 0x55:
        return segment
    total = segment[1] + (segment[2] & 0x03) * 256
    if total < 8 or total > len(segment):
        return segment
    return segment[4 : total - 2]


def _strip_internal_trans_framing(body: bytes) -> bytes:
    """Remove repeated progress + \\x2a\\x04 + 4-byte chunk headers inside ciphertext."""
    out = bytearray()
    i = 0
    while i < len(body):
        j = body.find(b"\x2a\x04", i)
        if j < 0:
            out += body[i:]
            break
        if j >= 4 and j + 6 <= len(body):
            prog = struct.unpack_from("<I", body, j - 4)[0]
            if prog < 0x1000000:
                out += body[i : j - 4]
                i = j + 6
                continue
        out.append(body[i])
        i += 1
    return bytes(out)


def _strip_chunk_framing(body: bytes) -> bytes:
    """Drop leading TRANS chunk prefix at each DUML packet boundary (packet start only)."""
    if len(body) >= 12 and body[:2] == b"\x2a\x04":
        return body[12:]
    # Retail LOGH export: 5d0aPP0000002a04NN000000 (12 B; \\x2a\\x04 at offset 6).
    if len(body) >= 12 and body[6:8] == b"\x2a\x04":
        return body[12:]
    if len(body) >= 10 and body[4:6] == b"\x2a\x04":
        prog = struct.unpack_from("<I", body, 0)[0]
        if prog < 0x1000000:
            # Outer chunk prefix: prog + \\x2a\\x04 + 10 zero pad (16 B total).
            if len(body) >= 16 and body[6:16] == b"\x00" * 10:
                return body[16:]
            # Inner sub-chunk header at a DUML packet boundary (10 B).
            return body[10:]
    logh = body.find(b"LOGH")
    if logh > 0:
        return body[logh:]
    return body


def _extract_file_chunk_payload(chunk: bytes) -> bytes:
    """Pull file bytes from one 2112adde data chunk (LOGH/.enc or plain)."""
    if not chunk.startswith(TRANS_MAGIC) or len(chunk) < 24:
        return b""
    seg_len = trans_declared_len(chunk)
    if seg_len <= 0:
        return b""
    end = min(24 + seg_len, len(chunk))
    segment = chunk[24:end]
    if not segment:
        return b""
    if segment.find(b"LOGH") >= 0:
        return _extract_inner_file_payload(segment)
    if segment[:1] == 0x55 or (len(segment) > 32 and b"\x55" in segment[:32]):
        return _concat_duml_payloads(segment)
    anchor = segment.find(b"\x2a\x04")
    if anchor >= 4:
        return segment[anchor + 12 :]
    return _strip_chunk_framing(_unwrap_duml_segment(segment))


def transfer_progress_bytes(blob: bytes) -> int:
    """Cumulative extracted payload bytes — matches Init capture ack_prog offsets."""
    total = 0
    data_started = False
    for _, chunk in iter_trans_chunks(blob):
        if is_trans_data_chunk(chunk):
            data_started = True
            total += len(_extract_file_chunk_payload(chunk))
        elif data_started and is_trans_window_tail(chunk):
            total += len(_extract_file_chunk_payload(chunk))
    return total


def sum_trans_data_inner_len(blob: bytes) -> int:
    """Sum declared inner lengths of large TRANS data chunks (download progress metric)."""
    total = 0
    for _, chunk in iter_trans_chunks(blob):
        if is_trans_data_chunk(chunk):
            total += trans_declared_len(chunk)
    return total


def _has_internal_trans_framing(body: bytes) -> bool:
    j = 0
    while j + 6 <= len(body):
        j = body.find(b"\x2a\x04", j)
        if j < 0:
            return False
        if j >= 4 and struct.unpack_from("<I", body, j - 4)[0] < 0x1000000:
            return True
        j += 1
    return False


def strip_transfer_payload(blob: bytes) -> bytes:
    """Extract file bytes from DUSS TRANS download stream."""
    out = bytearray()
    data_started = False
    for _, chunk in iter_trans_chunks(blob):
        if is_trans_data_chunk(chunk):
            data_started = True
            piece = _extract_file_chunk_payload(chunk)
        elif data_started and is_trans_window_tail(chunk):
            piece = _extract_file_chunk_payload(chunk)
        else:
            continue
        if piece:
            out += piece
    if out:
        if out.startswith(b"LOGH") and len(out) > 0xB0:
            head = bytes(out[:0xB0])
            body = bytes(out[0xB0:])
            if _has_internal_trans_framing(body):
                body = _strip_internal_trans_framing(_strip_embedded_duss_markers(body))
            plain_hint = struct.unpack_from("<I", out, 16)[0] if len(out) >= 20 else 0
            if plain_hint:
                aligned = (plain_hint + 15) // 16 * 16
                if len(body) > aligned:
                    body = body[:aligned]
            out = head + body
        return bytes(out)
    payload = reassemble_trans_payload(blob)
    return payload if payload else b""
