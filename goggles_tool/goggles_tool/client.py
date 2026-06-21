"""High-level Goggles 3 client built from USBPcap-derived protocol knowledge."""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .protocol import duss
from .protocol.constants import EXPORT_LIST_PATH
from .protocol import upgrade as upgrade_fsm
from .usb.transport import UsbTransport

VERSION_CHUNK_SIZE = 278
VERSION_ACK_MAX = 24
SESSION_COUNTER_START = 0x4C
# Init capture: ack_prog = u32@TRANS+12 (window-relative); ack_done on tail or stall.
TRANS_PROG_BATCH = 1


@dataclass
class TransferAckState:
    seen_trans: set[int] = field(default_factory=set)
    data_open_sent: bool = False
    last_prog: int | None = None
    last_acked_prog: int | None = None
    last_meta: dict | None = None
    data_since_prog: int = 0
    ack_scan_pos: int = 0


@dataclass
class BundleDownloadItem:
    path: str
    dest: Path
    expected_size: int = 0


class GogglesClient:
    def __init__(self, transport: UsbTransport | None = None, verbose: bool = False):
        self.transport = transport or UsbTransport()
        self.verbose = verbose
        self._sess: dict = {}

    def connect(
        self,
        interface: int | None = None,
        *,
        bus: int | None = None,
        address: int | None = None,
    ) -> dict:
        eps = self.transport.open(interface=interface, bus=bus, address=address)
        info = {
            "interface": eps.interface,
            "ep_out": f"0x{eps.ep_out:02x}",
            "ep_in": f"0x{eps.ep_in:02x}",
            "bus": bus,
            "address": address,
        }
        if self.verbose:
            print(f"claimed USB iface {eps.interface} OUT=0x{eps.ep_out:02x} IN=0x{eps.ep_in:02x}")
        return info

    def close(self) -> None:
        self.transport.close()

    def _log(self, direction: str, data: bytes) -> None:
        if self.verbose:
            print(f"{direction} {len(data)} bytes: {data[:48].hex()}...", file=sys.stderr)

    def _alloc_session_hi(self) -> int:
        hi = self._sess.get("counter", SESSION_COUNTER_START)
        self._sess["counter"] = (hi + 1) & 0xFF
        return hi

    def _read_some(self, max_reads: int = 8, timeout_ms: int = 400) -> bytes:
        parts: list[bytes] = []
        for _ in range(max_reads):
            chunk = self.transport.read(65536, timeout_ms=timeout_ms)
            if not chunk:
                break
            self._log("<<", chunk)
            parts.append(chunk)
        return b"".join(parts)

    def _write(self, pkt: bytes) -> None:
        self._log(">>", pkt)
        self.transport.write(pkt)

    def _is_bulk_keepalive(self, chunk: bytes) -> bool:
        return len(chunk) <= 128 and chunk.startswith(b"\x55\x4d\x04\xa8")

    def _find_trans_setup(self, blob: bytes) -> bytes:
        """Return the 62-byte-class TRANS setup chunk (second chunk in Init capture)."""
        idx = 0
        found: list[bytes] = []
        while idx < len(blob):
            j = blob.find(duss.TRANS_MAGIC, idx)
            if j < 0:
                break
            nxt = blob.find(duss.TRANS_MAGIC, j + 4)
            chunk = blob[j:nxt] if nxt > 0 else blob[j : j + 128]
            if len(chunk) >= 38:
                found.append(chunk)
            idx = j + 4
        if len(found) >= 2:
            return found[1][:62]
        if found:
            return found[0][:62]
        return b""

    def _send_export_acks(self, setup: bytes) -> None:
        meta = duss.parse_trans_meta(setup) if len(setup) >= 24 else None
        ack_hi = meta["ack_session_hi"] if meta else 0
        ack_lo = meta["ack_session_lo"] if meta else 0
        time.sleep(0.02)
        self._write(duss.build_transfer_ack_open(ack_hi, ack_lo))
        time.sleep(0.08)
        prog = duss.ack_progress_from_trans(setup) or 0x19
        self._write(duss.build_transfer_ack_progress(prog))
        time.sleep(0.04)
        self._write(duss.build_transfer_ack_done(0x1B))

    def _finish_transfer_window(self, state: TransferAckState, *, open_next: bool = True) -> None:
        """Close one TRANS window: final ack_prog (if pending) then ack_done; optionally open next."""
        if not state.data_open_sent:
            return
        if state.last_prog is not None and state.last_acked_prog != state.last_prog:
            self._write(duss.build_transfer_ack_progress(state.last_prog))
            state.last_acked_prog = state.last_prog
        self._write(duss.build_transfer_ack_done())
        state.data_open_sent = False
        state.data_since_prog = 0
        state.last_acked_prog = None
        if open_next and state.last_meta:
            m = state.last_meta
            time.sleep(0.01)
            self._write(duss.build_transfer_ack_open(m["ack_session_hi"], m["ack_session_lo"]))
            state.data_open_sent = True

    def _ack_setup_phase(self, setup_chunk: bytes) -> None:
        """One open/prog/done after 38+62 B setup (capture: single cycle before data)."""
        meta = duss.parse_trans_meta(setup_chunk)
        if not meta:
            return
        hi, lo = meta["ack_session_hi"], meta["ack_session_lo"]
        self._write(duss.build_transfer_ack_open(hi, lo))
        time.sleep(0.02)
        prog = duss.ack_progress_from_trans(setup_chunk)
        if prog is not None:
            self._write(duss.build_transfer_ack_progress(prog))
        time.sleep(0.02)
        self._write(duss.build_transfer_ack_done())

    def _last_setup_chunk(self, blob: bytes) -> bytes:
        setups = [
            chunk
            for _, chunk in duss.iter_trans_chunks(blob)
            if not duss.is_trans_data_chunk(chunk)
        ]
        return setups[-1] if setups else b""

    def _drive_transfer_acks(self, blob: bytes, state: TransferAckState) -> None:
        """Ack data-phase TRANS chunks: ack_open once per window, ack_prog, ack_done on tail."""
        start = state.ack_scan_pos
        if start > len(blob):
            start = 0
        for off, chunk in duss.iter_trans_chunks(blob[start:]):
            abs_off = start + off
            if abs_off in state.seen_trans:
                continue
            state.seen_trans.add(abs_off)

            if not duss.is_trans_data_chunk(chunk):
                if state.data_open_sent and duss.is_trans_window_tail(chunk):
                    meta = duss.parse_trans_meta(chunk)
                    if meta:
                        state.last_meta = meta
                    prog = duss.trans_window_tail_progress(chunk)
                    if prog:
                        state.last_prog = prog
                    if prog and prog != state.last_acked_prog:
                        self._write(duss.build_transfer_ack_progress(prog))
                        state.last_acked_prog = prog
                        state.data_since_prog = 0
                    self._finish_transfer_window(state)
                continue

            meta = duss.parse_trans_meta(chunk)
            if not meta:
                continue

            if not state.data_open_sent:
                self._write(
                    duss.build_transfer_ack_open(meta["ack_session_hi"], meta["ack_session_lo"])
                )
                state.data_open_sent = True
                time.sleep(0.01)

            prog = duss.ack_progress_from_trans(chunk)
            if prog is None:
                continue
            state.last_prog = prog
            state.last_meta = meta
            state.data_since_prog += 1
            if state.data_since_prog >= TRANS_PROG_BATCH or prog != state.last_acked_prog:
                self._write(duss.build_transfer_ack_progress(prog))
                state.last_acked_prog = prog
                state.data_since_prog = 0
        state.ack_scan_pos = len(blob)

    def _has_file_transfer_start(self, blob: bytes) -> bool:
        """True once we have the 38+62 B setup pair or the first large data TRANS chunk."""
        setups: list[bytes] = []
        has_data = False
        for _, chunk in duss.iter_trans_chunks(blob):
            if duss.is_trans_data_chunk(chunk):
                has_data = True
            elif not duss.is_trans_data_chunk(chunk):
                setups.append(chunk)
        return has_data or len(setups) >= 2

    def _read_download_setup(self, timeout_s: float = 12.0) -> bytes:
        """Read 38 + 62 B TRANS setup (or until first data chunk) before acking."""
        blob = b""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            chunk = self.transport.read(65536, timeout_ms=600)
            if chunk:
                self._log("<<", chunk)
                blob += chunk
            if self._has_file_transfer_start(blob):
                break
            if not chunk:
                time.sleep(0.02)
        return blob

    def _ensure_log_export_session(self) -> None:
        if "list_done" not in self._sess and "primed" not in self._sess:
            self.get_version_xml()
            self._drain(0.15)
            self._prime_log_export_session()
            self._sess["primed"] = True

    def handshake(self) -> None:
        """Pre-version exchange (Init capture sequence)."""
        self._write(duss.build_handshake())
        self._read_some(5)
        for i in range(3):
            self._write(duss.build_pre_version(i))
            self._read_some(3)
        time.sleep(0.05)

    def _extract_version_xml(self, blob: bytes) -> str:
        pieces: list[bytes] = []
        i = 0
        while i + VERSION_CHUNK_SIZE <= len(blob):
            if blob[i] == 0x55 and blob[i + 1] == 0x16:
                chunk = blob[i : i + VERSION_CHUNK_SIZE]
                pieces.append(chunk[28:-2])
                i += VERSION_CHUNK_SIZE
            else:
                i += 1
        text = b"".join(pieces).decode("utf-8", errors="replace")
        m = re.search(r"<\?xml.*?</dji>", text, re.DOTALL)
        if m:
            return m.group(0)
        if "<dji>" in text and "</dji>" in text:
            start = text.find("<dji>")
            end = text.rfind("</dji>") + len("</dji>")
            return text[start:end]
        return text

    def get_version_xml(self, max_chunks: int = VERSION_ACK_MAX) -> str:
        """Run get_version flow; returns concatenated upgrade_center XML."""
        self.handshake()
        blob = b""
        for seq in range(max_chunks):
            self._write(duss.build_version_ack(seq))
            blob += self._read_some(4, timeout_ms=250) or self._drain(0.22)
            if b"</dji>" in blob:
                break
        return self._extract_version_xml(blob)

    def _drain(self, seconds: float = 0.35, poll_ms: int = 300) -> bytes:
        end = time.time() + seconds
        parts: list[bytes] = []
        while time.time() < end:
            chunk = self.transport.read(65536, timeout_ms=poll_ms)
            if chunk:
                self._log("<<", chunk)
                parts.append(chunk)
            else:
                time.sleep(0.01)
        return b"".join(parts)

    def parse_version_summary(self, xml: str) -> dict:
        rel = re.search(r'<release[^>]+version="([^"]+)"', xml)
        e3t = re.search(r'<module[^>]+id="2805"[^>]+version="([^"]+)"', xml)
        e3t_name = re.search(r'<module[^>]+id="2805"[^>]+name="([^"]+)"', xml)
        if not e3t:
            e3t = re.search(r'id="2805"[^>]*version="([^"]+)"', xml)
        return {
            "release": rel.group(1) if rel else None,
            "e3t_version": e3t.group(1) if e3t else None,
            "e3t_name": e3t_name.group(1) if e3t_name else None,
            "raw_len": len(xml),
        }

    def logs_list(self, path: str = EXPORT_LIST_PATH) -> bytes:
        """Request export_list.json over bulk (Init capture sequence)."""
        self.get_version_xml()
        self._drain(0.15)

        prep_hi = self._alloc_session_hi()
        self._write(duss.build_export_prep(prep_hi))
        self._read_some(3)

        req_hi = self._alloc_session_hi()
        self._write(duss.build_export_list_request(path, req_hi))

        setup = self._read_some(8, timeout_ms=500)
        trans_setup = self._find_trans_setup(setup)
        self._send_export_acks(trans_setup)
        setup_meta = duss.parse_trans_meta(trans_setup) if trans_setup else None
        last_progress = setup_meta["progress"] if setup_meta else None

        blob = setup
        idle_reads = 0
        deadline = time.time() + 90.0
        while time.time() < deadline:
            if duss.extract_json_blob(blob) is not None:
                break
            chunk = self.transport.read(65536, timeout_ms=800)
            if chunk:
                idle_reads = 0
                self._log("<<", chunk)
                blob += chunk
                for meta in self._iter_trans_metas(chunk):
                    prog = meta.get("progress")
                    if prog and prog != last_progress:
                        self._write(duss.build_transfer_ack_progress(prog))
                        last_progress = prog
            else:
                idle_reads += 1
                if idle_reads == 6 and last_progress is not None:
                    self._write(duss.build_transfer_ack_done())
                if idle_reads > 40:
                    break
                time.sleep(0.05)
        if duss.extract_json_blob(blob) is None and last_progress is not None:
            self._write(duss.build_transfer_ack_done())
            blob += self._drain(1.5, poll_ms=400)
        self._sess["list_done"] = True
        return blob

    def _iter_trans_metas(self, chunk: bytes) -> list[dict]:
        metas: list[dict] = []
        i = 0
        while i < len(chunk):
            j = chunk.find(duss.TRANS_MAGIC, i)
            if j < 0:
                break
            meta = duss.parse_trans_meta(chunk[j:])
            if meta:
                metas.append(meta)
            i = j + 4
        return metas

    def parse_export_list(self, raw: bytes) -> dict | list | None:
        js = duss.extract_json_blob(raw)
        if js is None:
            return None
        try:
            return json.loads(js.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def parse_export_list_paths(self, raw: bytes) -> list[str]:
        """Return log paths from bulk export_list (full JSON or partial stitch)."""
        parsed = self.parse_export_list(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("log_list"), list):
            return [e["path"] for e in parsed["log_list"] if isinstance(e, dict) and e.get("path")]
        return duss.extract_log_paths(raw)

    def _prime_log_export_session(self) -> None:
        """Run export_prep + export_list once (Init capture order before file pulls)."""
        prep_hi = self._alloc_session_hi()
        self._write(duss.build_export_prep(prep_hi))
        self._read_some(3)
        req_hi = self._alloc_session_hi()
        self._write(duss.build_export_list_request(EXPORT_LIST_PATH, req_hi))
        setup = self._read_some(12, timeout_ms=800)
        self._send_export_acks(self._find_trans_setup(setup))
        blob = setup
        deadline = time.time() + 25.0
        while time.time() < deadline:
            if duss.extract_json_blob(blob) is not None:
                break
            chunk = self.transport.read(65536, timeout_ms=500)
            if chunk:
                blob += chunk
                for meta in self._iter_trans_metas(chunk):
                    prog = meta.get("progress")
                    if prog:
                        self._write(duss.build_transfer_ack_progress(prog))
            else:
                time.sleep(0.05)
        self._write(duss.build_transfer_ack_done())
        self._drain(0.3)
        self._sess["list_done"] = True

    def _download_file_internal(
        self,
        dest: Path,
        path: str,
        *,
        max_bytes: int = 2_000_000_000,
        strip_duss: bool = True,
        expected_size: int | None = None,
        idle_done_s: float = 3.0,
        timeout_s: float = 600.0,
        use_log_open: bool = True,
        setup_timeout_s: float = 12.0,
    ) -> int:
        """Transfer one export_list path over an already-primed bulk session."""
        dest.parent.mkdir(parents=True, exist_ok=True)

        if use_log_open:
            open_hi = self._alloc_session_hi()
            self._write(duss.build_log_open(open_hi))
            self._read_some(2, timeout_ms=300)

        req_hi = self._alloc_session_hi()
        self._write(duss.build_file_download_request(path, req_hi))

        setup = self._read_download_setup(setup_timeout_s)
        if self.verbose:
            print(
                f"  setup: {len(setup):,} B, TRANS={setup.count(duss.TRANS_MAGIC)}",
                file=sys.stderr,
            )

        ack_state = TransferAckState()
        last_setup = self._last_setup_chunk(setup)
        if last_setup:
            self._ack_setup_phase(last_setup)
        self._drive_transfer_acks(setup, ack_state)

        raw = bytearray(setup)
        last_data_at = time.time()
        last_inner_len = 0
        stall_reads = 0
        read_timeout_ms = 500
        if expected_size and expected_size > 20_000_000:
            idle_done_s = max(idle_done_s, 15.0)
            timeout_s = max(timeout_s, expected_size / 25_000 + 300.0)
        deadline = time.time() + timeout_s

        def _progress() -> int:
            if strip_duss:
                return duss.sum_trans_data_inner_len(bytes(raw))
            return len(raw)

        def _is_complete() -> bool:
            if not expected_size:
                return False
            if strip_duss:
                return len(duss.strip_transfer_payload(bytes(raw))) >= int(expected_size * 0.98)
            return _progress() >= expected_size

        while time.time() < deadline:
            inner_now = _progress()
            if inner_now >= max_bytes:
                break

            chunk = self.transport.read(65536, timeout_ms=read_timeout_ms)
            if chunk:
                keepalive = self._is_bulk_keepalive(chunk)
                if keepalive:
                    self._log("<<", chunk)
                    stall_reads += 1
                else:
                    stall_reads = 0
                    last_data_at = time.time()
                    raw.extend(chunk)
                    self._log("<<", chunk)
                    if self.verbose:
                        large = sum(
                            1
                            for _, c in duss.iter_trans_chunks(chunk)
                            if duss.is_trans_data_chunk(c)
                        )
                        if large:
                            print(
                                f"  +{large} large TRANS chunk(s) in {len(chunk):,} B read",
                                file=sys.stderr,
                            )
                    self._drive_transfer_acks(bytes(raw), ack_state)
                inner_now = _progress()
                if not keepalive and inner_now != last_inner_len:
                    last_inner_len = inner_now
                if _is_complete():
                    break
                if keepalive and expected_size and inner_now < expected_size * 0.98:
                    if stall_reads % 8 == 0 and ack_state.data_open_sent:
                        self._finish_transfer_window(ack_state)
                    read_timeout_ms = min(3000, read_timeout_ms + 50)
                    time.sleep(0.03)
                    continue
            else:
                stall_reads += 1
                inner_now = _progress()
                if expected_size and inner_now < expected_size * 0.98:
                    if stall_reads % 4 == 0 and ack_state.last_prog is not None:
                        self._write(duss.build_transfer_ack_progress(ack_state.last_prog))
                    if stall_reads % 12 == 0 and ack_state.data_open_sent:
                        self._finish_transfer_window(ack_state)
                    if stall_reads % 20 == 0 and ack_state.last_meta and not ack_state.data_open_sent:
                        m = ack_state.last_meta
                        self._write(
                            duss.build_transfer_ack_open(m["ack_session_hi"], m["ack_session_lo"])
                        )
                        ack_state.data_open_sent = True
                    read_timeout_ms = min(3000, read_timeout_ms + 50)
                    time.sleep(0.03)
                    continue
                if inner_now > 0 and inner_now == last_inner_len:
                    if stall_reads * (read_timeout_ms / 1000.0) >= idle_done_s:
                        break
                if time.time() - last_data_at >= idle_done_s * 2:
                    break
                time.sleep(0.01)

            if self.verbose and inner_now > 0 and inner_now % (1024 * 1024) < 65536:
                pct = f" ({100 * inner_now / expected_size:.0f}%)" if expected_size else ""
                print(f"  inner {inner_now:,} bytes (raw {len(raw):,}){pct}", file=sys.stderr)

        if ack_state.data_open_sent:
            self._finish_transfer_window(ack_state, open_next=False)
        raw.extend(self._drain(0.35, poll_ms=250))

        payload = duss.strip_transfer_payload(bytes(raw)) if strip_duss else bytes(raw)
        if max_bytes and len(payload) > max_bytes:
            payload = payload[:max_bytes]
        if expected_size and len(payload) > expected_size:
            payload = payload[:expected_size]
        dest.write_bytes(payload)
        if self.verbose:
            note = ""
            if expected_size and len(payload) < expected_size * 0.95:
                note = f" SHORT expected={expected_size:,}"
            print(
                f"  wrote {len(payload):,} bytes payload ({len(raw):,} raw){note}",
                file=sys.stderr,
            )
        return len(payload)

    def logs_download(
        self,
        dest: Path,
        path: str | None = None,
        max_bytes: int = 2_000_000_000,
        strip_duss: bool = True,
        expected_size: int | None = None,
        idle_done_s: float = 3.0,
        timeout_s: float = 600.0,
    ) -> int:
        """Download a blackbox file over bulk (path from export_list.json)."""
        if path is None:
            path = "/blackbox/flight0360/gls_flyctrl/GFLY-0360-01.DAT"
        self._ensure_log_export_session()
        return self._download_file_internal(
            dest,
            path,
            max_bytes=max_bytes,
            strip_duss=strip_duss,
            expected_size=expected_size,
            idle_done_s=idle_done_s,
            timeout_s=timeout_s,
            use_log_open=True,
        )

    def logs_bundle_download(
        self,
        items: list[BundleDownloadItem],
        *,
        strip_duss: bool = True,
        idle_done_s: float = 4.0,
        timeout_s: float | None = None,
    ) -> list[dict]:
        """Download many files in one Assistant-style session (one log_open, chained 090104).

        Matches DJI Assistant Log Index export: prime export_list once, log_open once,
        then sequential per-path downloads with ack_done between files (no log_open repeat).
        """
        if not items:
            return []

        self._ensure_log_export_session()
        open_hi = self._alloc_session_hi()
        self._write(duss.build_log_open(open_hi))
        self._read_some(2, timeout_ms=300)
        self._sess["bundle_open"] = True

        results: list[dict] = []
        total_bytes = sum(max(0, it.expected_size) for it in items)
        bundle_timeout = timeout_s
        if bundle_timeout is None:
            bundle_timeout = max(600.0, total_bytes / 30_000 + 120.0)

        for i, item in enumerate(items):
            if i > 0:
                self._drain(0.2, poll_ms=120)
            size = item.expected_size or None
            per_timeout = bundle_timeout
            if size and size > 5_000_000:
                per_timeout = max(per_timeout, size / 30_000 + 180.0)
            per_idle = idle_done_s
            if size and size > 20_000_000:
                per_idle = max(per_idle, 12.0)
            max_bytes = min((size + 131_072) if size else 50_000_000, 500_000_000)
            row: dict = {"path": item.path, "dest": str(item.dest), "size_hint": size or 0}
            if self.verbose:
                print(
                    f"\n[bundle {i + 1}/{len(items)}] {item.path}  size={size or '?'}",
                    file=sys.stderr,
                )
            try:
                got = self._download_file_internal(
                    item.dest,
                    item.path,
                    max_bytes=max_bytes,
                    strip_duss=strip_duss,
                    expected_size=size,
                    idle_done_s=per_idle,
                    timeout_s=per_timeout,
                    use_log_open=False,
                    setup_timeout_s=8.0 if i == 0 else 5.0,
                )
                row["bytes"] = got
                row["complete"] = (got >= int(size * 0.95)) if size else got > 0
                row["logh"] = (
                    item.dest.is_file() and item.dest.read_bytes()[:4] == b"LOGH"
                )
            except Exception as exc:
                row["error"] = str(exc)
                row["complete"] = False
            results.append(row)
        return results

    def firmware_upload(self, image_path: Path, chunk_size: int = 2048) -> int:
        """Stream firmware file (experimental)."""
        data = image_path.read_bytes()
        if not data:
            raise ValueError("empty firmware file")
        self.get_version_xml(max_chunks=16)
        for frame in upgrade_fsm.PRE_UPLOAD_OUT_FRAMES:
            self._write(frame)
            self._read_some(3)
        sent = 0
        hdr = upgrade_fsm.FIRMWARE_FIRST_CHUNK_HEADER
        seq = 0
        while sent < len(data):
            chunk = data[sent : sent + chunk_size]
            if sent == 0:
                if chunk.startswith(b"IM*H") or chunk.startswith(b"IM\x2aH"):
                    pkt = hdr + chunk
                elif hdr[:12] in chunk[:32]:
                    pkt = chunk
                else:
                    pkt = hdr + chunk
            else:
                pkt = chunk
            self.transport.write(pkt)
            sent += len(chunk)
            seq += 1
            if seq % 500 == 0 and self.verbose:
                print(f"  uploaded {sent:,} / {len(data):,}", file=sys.stderr)
            ack = self.transport.read(4096, timeout_ms=400)
            if ack and self.verbose:
                self._log("<<", ack)
        return sent
