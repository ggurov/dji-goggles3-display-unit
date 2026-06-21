#!/usr/bin/env python3
"""goggles-tool — modular CLI for DJI Goggles 3 USB control (Assistant replacement)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .client import GogglesClient
from .protocol import templates
from .usb.transport import UsbTransport, list_devices


def _client(args) -> GogglesClient:
    return GogglesClient(
        transport=UsbTransport(timeout_ms=args.timeout_ms),
        verbose=args.verbose,
    )


def _connect(c: GogglesClient, args) -> dict:
    return c.connect(
        interface=args.interface,
        bus=getattr(args, "usb_bus", None),
        address=getattr(args, "usb_address", None),
    )


def cmd_devices(_args) -> int:
    devs = list_devices()
    if not devs:
        print("No Goggles 3 (2CA3:0020) found.")
        return 1
    bulk = sorted({(d["bus"], d["address"]) for d in devs if d.get("bulk_log")})
    if len(bulk) > 1:
        print(f"# {len(bulk)} bulk units: addr {bulk[0][1]}=donor plaintext, addr {bulk[-1][1]}=retail LOGH (heuristic)")
    for d in devs:
        eps = ",".join(d["endpoints"])
        tag = " BULK" if d.get("bulk_log") else ""
        print(
            f"bus={d['bus']} addr={d['address']} iface={d['interface']} "
            f"eps=[{eps}] backend={d['backend']} serial={d['serial']}{tag}"
        )
    return 0


def cmd_connect(args) -> int:
    c = _client(args)
    try:
        info = _connect(c, args)
        print(json.dumps(info, indent=2))
        if args.version:
            xml = c.get_version_xml()
            summary = c.parse_version_summary(xml)
            print(json.dumps(summary, indent=2))
            if args.dump_xml:
                Path(args.dump_xml).write_text(xml, encoding="utf-8")
    finally:
        c.close()
    return 0


def cmd_info(args) -> int:
    c = _client(args)
    try:
        _connect(c, args)
        xml = c.get_version_xml()
        summary = c.parse_version_summary(xml)
        print(json.dumps(summary, indent=2))
        if args.dump_xml:
            Path(args.dump_xml).write_text(xml, encoding="utf-8")
        elif args.verbose:
            print(xml[:2000])
    finally:
        c.close()
    return 0


def _logs_list_via_adb(args) -> int:
    import subprocess

    adb = args.adb
    remote = "/blackbox/info/export_list.json"
    out = Path(args.output) if args.output else Path("export_list.json")
    subprocess.check_call([adb, "pull", remote, str(out)])
    if args.parse_json:
        import json

        print(json.dumps(json.loads(out.read_text(encoding="utf-8")), indent=2))
    else:
        print(f"pulled {out}")
    return 0


def cmd_logs_list(args) -> int:
    if getattr(args, "via_adb", False):
        return _logs_list_via_adb(args)
    c = _client(args)
    try:
        _connect(c, args)
        raw = c.logs_list()
        out = Path(args.output) if args.output else None
        if args.parse_json:
            parsed = c.parse_export_list(raw)
            if parsed is not None:
                text = json.dumps(parsed, indent=2)
                if out:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(text, encoding="utf-8")
                    print(f"wrote JSON -> {out}")
                else:
                    print(text)
            else:
                print("warning: could not parse JSON from response", file=sys.stderr)
                if out:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(raw)
                else:
                    sys.stdout.buffer.write(raw)
        elif out:
            out.write_bytes(raw)
            print(f"wrote {len(raw):,} bytes -> {out}")
        else:
            sys.stdout.buffer.write(raw)
    finally:
        c.close()
    return 0


def cmd_duss_dump(args) -> int:
    from .tools.duss_dump import dump_frames

    n = dump_frames(Path(args.input), max_frames=args.max_frames, xml_only=args.xml_only)
    print(f"{n} frames", file=sys.stderr)
    return 0


def cmd_logs_download(args) -> int:
    c = _client(args)
    try:
        _connect(c, args)
        if args.list_first:
            raw = c.logs_list()
            parsed = c.parse_export_list(raw)
            if parsed and isinstance(parsed, dict) and parsed.get("log_list"):
                path = parsed["log_list"][0].get("path")
                if path:
                    args.path = path
                    print(f"using first log path: {path}")
        path = args.path
        n = c.logs_download(
            Path(args.output),
            path=path,
            max_bytes=args.max_bytes,
            strip_duss=not args.raw,
            expected_size=args.expected_size,
            timeout_s=args.timeout_s,
        )
        print(f"downloaded {n:,} bytes -> {args.output}")
    finally:
        c.close()
    return 0


def cmd_logs_pull(args) -> int:
    """Batch-download paths and optionally scan for crash strings."""
    import re

    paths: list[str] = []
    if args.paths_file:
        data = json.loads(Path(args.paths_file).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            paths = list(data.get("interesting_paths") or data.get("paths") or [])
        elif isinstance(data, list):
            paths = data
    if args.path:
        paths.extend(args.path)
    paths = [p for i, p in enumerate(paths) if p and p not in paths[:i]]

    if not paths and not args.skip_list:
        c = _client(args)
        try:
            _connect(c, args)
            raw = c.logs_list()
            paths = c.parse_export_list_paths(raw)
            if args.keywords:
                kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
                paths = [p for p in paths if any(k in p.lower() for k in kws)]
        finally:
            c.close()

    if not paths:
        print("no paths to download", file=sys.stderr)
        return 1

    out_root = Path(args.output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    crash_re = re.compile(
        args.crash_pattern,
        re.IGNORECASE,
    )
    manifest: list[dict] = []

    c = _client(args)
    try:
        _connect(c, args)
        for idx, path in enumerate(paths, 1):
            safe = path.removeprefix("/blackbox/").replace("/", "__")
            dest = out_root / safe
            print(f"[{idx}/{len(paths)}] {path}")
            try:
                n = c.logs_download(
                    dest,
                    path=path,
                    max_bytes=args.max_bytes,
                    strip_duss=not args.raw,
                    timeout_s=args.timeout_s,
                )
                hits: list[str] = []
                if n and dest.is_file():
                    sample = dest.read_bytes().decode("utf-8", errors="ignore")
                    hits = sorted({m.group(0) for m in crash_re.finditer(sample)})
                entry = {"path": path, "dest": str(dest), "bytes": n, "crash_hits": hits}
                manifest.append(entry)
                if hits:
                    print(f"  CRASH HITS: {hits[:5]}")
                else:
                    print(f"  {n:,} bytes")
            except Exception as e:
                manifest.append({"path": path, "error": str(e)})
                print(f"  error: {e}", file=sys.stderr)
            time.sleep(0.2)
    finally:
        c.close()

    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    crash_files = [e for e in manifest if e.get("crash_hits")]
    print(f"\nWrote {len(manifest)} entries -> {manifest_path}")
    print(f"Files with crash pattern hits: {len(crash_files)}")
    return 0


def cmd_firmware_upload(args) -> int:
    path = Path(args.image)
    if not path.is_file():
        print(f"not found: {path}", file=sys.stderr)
        return 1
    c = _client(args)
    try:
        _connect(c, args)
        if not args.skip_version:
            c.handshake()
        n = c.firmware_upload(path, chunk_size=args.chunk_size)
        print(f"sent {n:,} bytes from {path}")
        print("note: apply/flash may require additional DUSS commands not yet implemented")
    finally:
        c.close()
    return 0


def cmd_parse_pcap(args) -> int:
    """Offline: parse bulk from existing pcap via tshark (no USB)."""
    from .tools.pcap_bulk import extract_bulk_to_dir

    out = extract_bulk_to_dir(Path(args.pcap), Path(args.output))
    print(f"extracted bulk streams -> {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="goggles-tool",
        description="DJI Goggles 3 USB control CLI (research; replaces Assistant bulk path).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--timeout-ms", type=int, default=5000)
    p.add_argument("--interface", type=int, default=None, help="USB interface number (default: auto)")
    p.add_argument("--usb-bus", type=int, default=None, help="USB bus (when multiple goggles)")
    p.add_argument("--usb-address", type=int, default=None, help="USB device address (retail=10, donor bulk=2)")
    p.add_argument(
        "--adb",
        default=r"C:\Users\ggurov\Downloads\platform-tools-latest-windows\platform-tools\adb.exe",
        help="adb.exe for --via-adb fallbacks",
    )

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="List connected goggles USB devices").set_defaults(func=cmd_devices)

    c = sub.add_parser("connect", help="Claim bulk interface (+ optional version)")
    c.add_argument("--version", action="store_true", help="Also run get_version")
    c.add_argument("--dump-xml", metavar="FILE")
    c.set_defaults(func=cmd_connect)

    i = sub.add_parser("info", help="get_version / upgrade_center XML summary")
    i.add_argument("--dump-xml", metavar="FILE")
    i.set_defaults(func=cmd_info)

    ll = sub.add_parser("logs-list", help="Fetch /blackbox/info/export_list.json")
    ll.add_argument("-o", "--output", help="Write raw response (default: stdout)")
    ll.add_argument("--parse-json", action="store_true", help="Extract and print JSON if present")
    ll.add_argument(
        "--via-adb",
        action="store_true",
        help="Pull export_list.json via ADB (bulk path needs live CRC/session)",
    )
    ll.set_defaults(func=cmd_logs_list)

    ld = sub.add_parser("logs-download", help="Download log file over bulk")
    ld.add_argument("-o", "--output", required=True)
    ld.add_argument("--path", help="Device path (default: flight0360 GFLY or first from --list-first)")
    ld.add_argument("--list-first", action="store_true", help="Run logs-list and use first entry")
    ld.add_argument("--max-bytes", type=int, default=2_000_000_000)
    ld.add_argument("--expected-size", type=int, default=None, help="Stop when stripped payload reaches this size")
    ld.add_argument("--timeout-s", type=float, default=600.0, help="Max seconds per download")
    ld.add_argument("--raw", action="store_true", help="Write raw bulk without DUSS strip heuristic")
    ld.set_defaults(func=cmd_logs_download)

    lp = sub.add_parser("logs-pull", help="Batch download blackbox paths (+ crash grep)")
    lp.add_argument("--paths-file", help="JSON with paths / interesting_paths")
    lp.add_argument("--path", action="append", help="Single path (repeatable)")
    lp.add_argument("--keywords", default="diag,gfsk,sdrs,kmsg,lvmonitor,coredump,media_server,flight0210,flight0211")
    lp.add_argument("--skip-list", action="store_true", help="Do not bulk-fetch export_list")
    lp.add_argument("-o", "--output-dir", required=True)
    lp.add_argument("--max-bytes", type=int, default=50_000_000)
    lp.add_argument("--timeout-s", type=float, default=600.0)
    lp.add_argument("--raw", action="store_true")
    lp.add_argument(
        "--crash-pattern",
        default=r"iondma|media_server|Fatal signal|SIGSEGV|underflow|dma0chan3|coredump|tombstone|0x1[bB]200003",
    )
    lp.set_defaults(func=cmd_logs_pull)

    fu = sub.add_parser("firmware-upload", help="Upload firmware image over bulk (experimental)")
    fu.add_argument("image", help="Path to .cache / IM*H / raw image from firm_cache")
    fu.add_argument("--chunk-size", type=int, default=2048)
    fu.add_argument("--skip-version", action="store_true")
    fu.set_defaults(func=cmd_firmware_upload)

    pp = sub.add_parser("parse-pcap", help="Extract bulk streams from pcapng (offline)")
    pp.add_argument("pcap")
    pp.add_argument("-o", "--output", required=True)
    pp.set_defaults(func=cmd_parse_pcap)

    dd = sub.add_parser("duss-dump", help="List DUSS frames in a bulk .bin file")
    dd.add_argument("input", help="bulk_0x04.bin / bulk_0x85.bin from parse-pcap")
    dd.add_argument("--max-frames", type=int, default=200)
    dd.add_argument("--xml-only", action="store_true")
    dd.set_defaults(func=cmd_duss_dump)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        if getattr(args, "verbose", False):
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
