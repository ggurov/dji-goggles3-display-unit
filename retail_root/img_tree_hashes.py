#!/usr/bin/env python3
"""List sha1 + size of every regular file inside an ext4 image (pyext4), to diff an
image against a live partition listing such as `cd /vendor && find . -type f -exec sha1sum {} +`.

  python img_tree_hashes.py <image.ext4> [--prefix /vendor] [--offset N] > tree.txt
"""
from __future__ import annotations

import argparse
import hashlib
import sys

import ext4

FT_DIR, FT_FILE, FT_SYMLINK = 2, 1, 7


def walk(vol, path, out, prefix):
    d = vol.root if not path else vol.inode_at(path)
    for de, ftype in d.opendir():
        name = de.name_str
        if name in (".", ".."):
            continue
        p = f"{path}/{name}"
        node = vol.inode_at(p)
        t = int(ftype.value)  # 1 regular, 2 dir, 7 symlink, 0 unknown
        if t == FT_DIR or getattr(node, "is_dir", False):
            walk(vol, p, out, prefix)
        elif t == FT_FILE or (t == 0 and getattr(node, "is_file", False)):
            data = node.open("rb").read()
            out.append(f"{hashlib.sha1(data).hexdigest()}  {prefix}{p}\n")
        # symlinks and special files are not hashed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--offset", default="0")
    a = ap.parse_args()
    out = []
    with open(a.image, "rb") as f:
        walk(ext4.Volume(f, offset=int(a.offset, 0)), "", out, a.prefix)
    sys.stdout.write("".join(sorted(out, key=lambda l: l.split("  ", 1)[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
