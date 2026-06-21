"""Offline pcap helpers."""
from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path


def find_tshark() -> str:
    for p in (
        r"C:\Program Files\Wireshark\tshark.exe",
        r"C:\Program Files (x86)\Wireshark\tshark.exe",
    ):
        if Path(p).is_file():
            return p
    hit = shutil.which("tshark")
    if hit:
        return hit
    raise RuntimeError("tshark not found")


def extract_bulk_to_dir(pcap: Path, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    tshark = find_tshark()
    fields = ["usb.endpoint_address", "usb.capdata"]
    cmd = [
        tshark,
        "-r",
        str(pcap),
        "-Y",
        "usb.capdata && usb.transfer_type == 0x03",
        "-T",
        "fields",
        "-E",
        "header=y",
        "-E",
        "separator=|",
        "-E",
        "quote=d",
    ] + [f"-e{f}" for f in fields]
    out = subprocess.check_output(cmd, text=True, errors="replace")
    rows = csv.DictReader(out.splitlines(), delimiter="|")
    by_ep: dict[str, bytearray] = {}
    for row in rows:
        cap = (row.get("usb.capdata") or "").replace(":", "")
        if not cap:
            continue
        ep = row["usb.endpoint_address"].replace("0x", "ep")
        by_ep.setdefault(ep, bytearray()).extend(bytes.fromhex(cap))
    for ep, blob in by_ep.items():
        (outdir / f"bulk_{ep}.bin").write_bytes(blob)
    return outdir
