"""Dump DUSS 0x55 frames from bulk .bin files (offline)."""
from __future__ import annotations

import sys
from pathlib import Path

from ..protocol import duss


def dump_frames(path: Path, max_frames: int = 200, xml_only: bool = False) -> int:
    blob = path.read_bytes()
    n = 0
    for fr in duss.iter_frames(blob):
        if xml_only and not fr.is_xml:
            continue
        tags: list[str] = []
        if fr.is_xml:
            tags.append("xml")
        if fr.is_imh:
            tags.append("IM*H")
        p = fr.path
        if p:
            tags.append(p)
        for name in (
            "get_version",
            "request_upgrade",
            "transfer_data",
            "transfer_complete",
            "reboot",
            "export_list",
        ):
            if name.encode() in fr.raw:
                tags.append(name)
        text = ""
        if fr.is_xml:
            xml = duss.reassemble_xml([fr])
            text = xml[:120].replace("\n", " ")
        tag_s = " ".join(tags) if tags else "-"
        print(f"off={blob.find(fr.raw):#x} len={fr.length} [{tag_s}]")
        if text:
            print(f"  {text}")
        elif len(fr.raw) <= 64:
            print(f"  {fr.raw.hex()}")
        else:
            print(f"  {fr.raw[:48].hex()}...")
        n += 1
        if n >= max_frames:
            print(f"... truncated at {max_frames} frames", file=sys.stderr)
            break
    return n
