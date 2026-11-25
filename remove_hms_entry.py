#!/usr/bin/env python3
"""Remove an exact HMS code line from hms_errorcode_list.txt, preserving byte format.
Usage: remove_hms_entry.py <src> <dst> <CODE>
"""
import sys
src, dst, code = sys.argv[1], sys.argv[2], sys.argv[3]
raw = open(src, "rb").read()
eol = b"\r\n" if b"\r\n" in raw else b"\n"
# Split keeping structure; compare each line stripped of CR/LF/space.
lines = raw.split(eol)
target = code.strip().lower()
kept, removed = [], 0
for ln in lines:
    if ln.strip().decode("latin1", "replace").lower() == target:
        removed += 1
        continue
    kept.append(ln)
out = eol.join(kept)
open(dst, "wb").write(out)
print(f"eol={'CRLF' if eol==b'\\r\\n' else 'LF'} removed={removed} "
      f"orig_bytes={len(raw)} new_bytes={len(out)}")
# sanity: code must be gone
assert target.encode() not in out.lower(), "code still present!"
print("verified: code no longer present in output")
