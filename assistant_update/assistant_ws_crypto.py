"""Keys and message crypto of the channel between the DJI Assistant 2 UI and its engine.

The Electron UI (`DJIApp/app.asar`) talks to `DJIService.exe` over WebSocket
(`ws://localhost:19870/...`). Each message is

    base64( AES-256-CBC( PKCS#7( utf8(JSON) ), key, iv = 16 zero bytes ) )

Requests (UI -> engine) and the UI log `DJIApp/ui_ass2.log` use one key, responses and pushes
(engine -> UI) the other. Both are derived at run time by `utils.genrpivate` in the UI bundle
from two obfuscated literals. This module does the same on a local installation; no key
material is stored here.

    python assistant_ws_crypto.py keys                  [--asar PATH]
    python assistant_ws_crypto.py encrypt   --asar PATH '{...json...}'
    python assistant_ws_crypto.py decrypt   --asar PATH BASE64
    python assistant_ws_crypto.py decrypt-log --asar PATH ui_ass2.log OUT.txt

Message shapes: requests `{SEQ, CMD, VALUE}`, responses `{SEQ, ERROR, VALUE}`, pushes
`{EVENT, VALUE}`. Needs `pycryptodome` or `cryptography` for AES.
"""
import argparse
import base64
import binascii
import mmap
import os
import re
import sys

DEFAULT_ASAR = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                            "DJI Product", "DJI Assistant 2 (Consumer Drones Series)",
                            "DJIApp", "app.asar")
IV = b"\x00" * 16
CALL = {"request": re.compile(rb"secret_key_enc\s*=\s*utils\.genrpivate\(\s*\"([^\"]+)\""),
        "response": re.compile(rb"secret_key_dec\s*=\s*utils\.genrpivate\(\s*\"([^\"]+)\"")}
LOG_LINE = re.compile(rb"^\[([\d\- :]+)\]\[(\w+)\] ([A-Za-z0-9+/=]+)\s*$")


def js_unescape(s):
    """JavaScript `unescape`: %uXXXX -> one UTF-16 unit, %XX -> one byte."""
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == "%" and i + 1 < n:
            if s[i + 1] == "u" and i + 6 <= n:
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
            try:
                out.append(chr(int(s[i + 1:i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(c)
        i += 1
    return "".join(out)


def genrpivate(literal):
    """Port of `utils.genrpivate`: `*$`-separated chunks, each delta-decoded."""
    parts = []
    for t, chunk in enumerate(literal.split("*$")):
        e = js_unescape(chunk)
        r = chr((ord(e[0]) - len(e) - (2 * t + 1)) & 0xFFFF)
        for o in range(1, len(e)):
            r += chr((ord(e[o]) - ord(r[o - 1])) & 0xFFFF)
        parts.append(r)
    return "".join(parts)


def keys(asar_path=DEFAULT_ASAR):
    """(request_key, response_key), each 32 bytes, derived from the installed UI bundle."""
    out = {}
    with open(asar_path, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        for name, rx in CALL.items():
            m = rx.search(mm)
            if not m:
                raise SystemExit("genrpivate literal for the %s key not found in %s" % (name, asar_path))
            key = genrpivate(m.group(1).decode("ascii")).encode("latin-1")
            if len(key) != 32:
                raise SystemExit("%s key is %d bytes, expected 32" % (name, len(key)))
            out[name] = key
    return out["request"], out["response"]


def _aes(key):
    try:
        from Crypto.Cipher import AES  # pycryptodome
        return AES.new(key, AES.MODE_CBC, IV).encrypt, AES.new(key, AES.MODE_CBC, IV).decrypt
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # cryptography
        enc = Cipher(algorithms.AES(key), modes.CBC(IV)).encryptor()
        dec = Cipher(algorithms.AES(key), modes.CBC(IV)).decryptor()
        return enc.update, dec.update
    except ImportError:
        raise SystemExit("install pycryptodome or cryptography for AES") from None


def pad(data):
    n = 16 - len(data) % 16
    return data + bytes([n]) * n


def unpad(data):
    if not data or len(data) % 16:
        raise ValueError("bad ciphertext length")
    n = data[-1]
    if not 1 <= n <= 16 or data[-n:] != bytes([n]) * n:
        raise ValueError("bad PKCS#7 padding")
    return data[:-n]


def encrypt(plaintext, key):
    return base64.b64encode(_aes(key)[0](pad(plaintext.encode("utf-8")))).decode("ascii")


def decrypt(b64, key):
    if not b64:
        return ""
    return unpad(_aes(key)[1](base64.b64decode(b64))).decode("utf-8")


def decrypt_log(src, dst, key):
    """`ui_ass2.log`: one `[timestamp][level] <base64>` per line -> plaintext lines."""
    n = ok = 0
    with open(src, "rb") as f, open(dst, "w", encoding="utf-8", newline="\n") as o:
        for raw in f.read().split(b"\n"):
            raw = raw.rstrip(b"\r")
            m = LOG_LINE.match(raw)
            if not m:
                continue
            n += 1
            try:
                text = decrypt(m.group(3).decode("ascii"), key)
            except Exception:  # noqa: BLE001 - other key or damaged line
                continue
            ok += 1
            o.write("[%s][%s] %s\n" % (m.group(1).decode("ascii"), m.group(2).decode("ascii"), text))
    return n, ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["keys", "encrypt", "decrypt", "decrypt-log"])
    ap.add_argument("args", nargs="*", help="TEXT (encrypt/decrypt) or LOG OUT (decrypt-log)")
    ap.add_argument("--asar", default=DEFAULT_ASAR)
    a = ap.parse_args()
    request_key, response_key = keys(a.asar)
    if a.command == "keys":
        print("request  key (UI -> engine, UI log):", binascii.hexlify(request_key).decode())
        print("response key (engine -> UI):       ", binascii.hexlify(response_key).decode())
    elif a.command == "encrypt" and len(a.args) == 1:
        print(encrypt(a.args[0], request_key))
    elif a.command == "decrypt" and len(a.args) == 1:
        print(decrypt(a.args[0], response_key))
    elif a.command == "decrypt-log" and len(a.args) == 2:
        print("lines=%d decrypted=%d" % decrypt_log(a.args[0], a.args[1], request_key))
    else:
        ap.error("wrong number of arguments for %s" % a.command)


if __name__ == "__main__":
    sys.exit(main())
