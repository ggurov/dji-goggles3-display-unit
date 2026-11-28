"""Pull every crash artifact the O3's file service will give, wrapped as it serves them, and parse
the clear part of each LOGH header.

    python pull_crash.py [--host 1d00] [--out crash_pull] [--max-mb 200] [--tree-only]

The file service serves only /blackbox; plain reads are refused for everything except
/blackbox/info/export_list.json and list.json, so these come back LOGH-wrapped (AES-128-CBC over a
per-file TEE key) and stay unreadable without the unit's TEE. The LOGH header's body length gives the
plaintext size; the MD5 of the received bytes is checked against the unit's end frame.
"""
from __future__ import annotations

import argparse
import json
import os
import struct

from o3_fileio import Pipe

TREE = [
    "/blackbox/system/tombstones",
    "/blackbox/system/coredump",
    "/blackbox/system/crash_log",
    "/blackbox/system/event_track",
    "/blackbox/info",
]


def list_dir(p: Pipe, d: str) -> list[str]:
    db = d.encode()
    reply, _ = p.request(bytes([0x06, len(db)]) + db)
    if not reply or reply[:1] != b"\x00" or b"/" not in reply:
        return []
    path = reply[reply.find(b"/"):].split(b"\0")[0].decode("ascii", "replace")
    r = p.pull(path, 4 << 20)
    raw = r.get("raw") or b""
    i = raw.find(b"{")
    if i < 0:
        return []
    try:
        obj = json.loads(raw[i:].decode("utf-8", "replace"))
    except Exception:
        return []
    return [f["path"] for f in obj.get("target_path_list") or [] if f.get("type") == 1 and f.get("path")]


def walk(p: Pipe, root: str, depth: int = 0) -> list[str]:
    files = []
    for f in list_dir(p, root):
        files.append(f)
        if depth < 4:
            files.extend(walk(p, f, depth + 1))     # descending into a file just returns nothing
    return sorted(set(files))


def parse_logh(raw: bytes) -> dict:
    if raw[:4] != b"LOGH" or len(raw) < 0xB0:
        return {}
    body = struct.unpack_from("<I", raw, 0x10)[0]
    return {
        "ver": raw[4],
        "hdr_len": struct.unpack_from("<H", raw, 8)[0],
        "body_len": body,
        "plain_est": body - 16 if body else None,
        "product": raw[0x18:0x28].split(b"\x00")[0].decode("latin1"),
        "tag": raw[0x48:0x60].hex(" "),
        "iv": raw[0xA0:0xB0].hex(),
        "ct_len": len(raw) - 0xB0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", type=lambda x: int(x, 16), default=0x1D00)
    ap.add_argument("--out", default="crash_pull")
    ap.add_argument("--max-mb", type=float, default=200.0)
    ap.add_argument("--tree-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    p = Pipe(4, a.host)
    rows, total = [], 0
    try:
        paths = []
        for t in TREE:
            paths.extend(walk(p, t))
        paths = sorted(set(paths))
        print("candidate files: %d" % len(paths))
        for path in paths:
            if a.tree_only:
                continue
            done = False
            for tail in (b"\x09\x01\x04", b"\x09\x01\x00"):     # wrapped first, then plain where allowed
                r = p.pull(path, 64 << 20, tail=tail)
                if "error" in r:
                    continue
                raw = r.get("raw") or b""
                if not raw:
                    continue
                name = path.strip("/").replace("/", "__")
                with open(os.path.join(a.out, name), "wb") as fh:
                    fh.write(raw)
                head = parse_logh(raw)
                rows.append({"path": path, "plain_read": tail.endswith(b"\x00"), "wrapped": len(raw),
                             "md5": "OK" if r.get("md5_ok") else "MISMATCH", **head})
                total += len(raw)
                print("  %-64s %8d B  %s  plain~%-8s %s%s" % (
                    path.replace("/blackbox/", ""), len(raw), "md5 OK" if r.get("md5_ok") else "md5 BAD",
                    head.get("plain_est", "?"), head.get("product", "not LOGH"),
                    " (plain read)" if tail.endswith(b"\x00") else ""))
                done = True
                break
            if not done:
                print("  %-64s refused or empty" % path.replace("/blackbox/", ""))
            if total > a.max_mb * (1 << 20):
                print("stopped at the %.0f MB limit" % a.max_mb)
                break
    finally:
        p.close()
    with open(os.path.join(a.out, "_index.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1)
    print("pulled %d files, %d bytes -> %s" % (len(rows), total, a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
