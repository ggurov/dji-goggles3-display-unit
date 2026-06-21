# Blackbox log encryption — research findings

**Status:** June 2026. Donor (engineering, root ADB) + retail (no ADB, bulk USB only).

---

## Summary

| Unit | On-disk `/blackbox` | Bulk USB export |
|------|---------------------|-----------------|
| Engineering donor (`secure_debug=1`) | **Plaintext** | **Plaintext** (no LOGH wrapper) |
| Retail consumer | Plaintext (if you had ADB) | **LOGH + AES ciphertext** |

Logs are **not encrypted at rest**. Encryption runs only when `dji_blackbox` serves a file
over the PC export path (`export_list` / opcode `090104`). DJI Assistant and `goggles_tool`
receive the same wire format.

---

## Pipeline

```
/blackbox/...  (plaintext on eMMC)
       │
       ▼  read(2) in dji_blackbox log_exporter
bb_misc_encrypt_file()  ──►  bb_misc_log_need_encrypt()
       │
       ▼
log_encrypt_fragment()  in liblog_util.so
       │   AES-CBC or AES-CTR (kcapi / mbedtls)
       │   key: amt_get_derive_log_key()
       ▼
log_gen_file_header()  ──►  LOGH container
       │
       ▼
DUSS TRANS chunks  ──►  USB bulk MI_04  ──►  PC
```

Relevant binaries (on device): `dji_blackbox`, `liblog_util.so`.

---

## When encryption is skipped (donor)

`liblog_util.so` strings and logcat confirm bypass when:

| Condition | Effect |
|-----------|--------|
| `secure_debug=1` in kernel cmdline | Skip encrypt — donor engineering builds |
| `mp_state` not production | Skip encrypt |
| `/tmp/skip_encrypt_state_check` exists | Skip state check |
| `/tmp/enable_log_export_sd_noenc` | SD export without encrypt |

Engineering donors export **plaintext** over bulk. Useful for validating TRANS parsing
without decrypt. **Not** useful for key recovery against retail LOGH.

---

## LOGH container (retail)

Magic `LOGH`, fixed metadata (~176 B), then AES ciphertext body (16-byte aligned).

Typical header layout (retail pulls):

| Offset | Content |
|--------|---------|
| 0 | `LOGH` |
| 4 | version `2` (u32 LE) |
| 8 | `0xa0` — layout hint |
| 16 | plaintext size hint (u32) |
| 24+ | `e3t_zv902`, device serial (ASCII) |
| 0x40 | u32 (often `7`) |
| 0x44 | per-file u32 |
| 0x48+ | 16 B — IV / key id / slice header |
| ~0xB0+ | ciphertext |

Cipher: **AES-CBC or AES-CTR** (`kcapi_cipher_enc_aes_cbc`, `aes_ctr` in strings).

Key path: `amt_get_derive_log_key()` + factory/AMT calibration material
(`/etc/logutil_pubkey_label_id.cfg`, RSA keyfiles in image).

---

## Decrypt strategy (what works)

There is **no** standalone `/system/bin/log_decrypt` on goggles. Decrypt API lives in
`liblog_util.so`: `log_recognize_file_enc_type`, `log_read_decrypt_ctx`,
`log_decrypt_fragment`.

### Donor harness (recommended)

Build `logutil_decrypt/` with Android NDK, push to donor `/blackbox/stage/`:

```powershell
cd log_export\logutil_decrypt
.\build.ps1 -NdkRoot "C:\path\to\android-ndk-r27c"
adb push libs\arm64-v8a\logutil_decrypt /blackbox/stage/logutil_decrypt
adb shell chmod 755 /blackbox/stage/logutil_decrypt
```

Batch decrypt from host:

```powershell
pip install -e ..\goggles_tool
python log_export\batch_decrypt.py bulk log_export\output\pull_*\files
```

The harness uses **the donor unit's** derived log key. It decrypts retail LOGH files
pulled from a **retail** unit when the retail serial is embedded in the LOGH header and
the key material matches (same product line — confirmed working for ZV902 retail exports
via rooted donor).

### Retail LOGH on donor — API behaviour

| Step | Retail LOGH on donor | Notes |
|------|---------------------|-------|
| `log_recognize_file_enc_type` | Returns **2** (LOGH v2) | Header parsed |
| `log_read_decrypt_ctx` | **0** on cleaned LOGH | Context OK |
| `log_decrypt_fragment` | **-1** if wrong unit/key | Wrong AMT material |

If decrypt fails: check LOGH body still has embedded DUSS TRANS seams — run
`clean_logh_bulk.py` first ( `batch_decrypt.py` does this automatically).

### What does not work

- Decrypting retail LOGH **without** a rooted donor running `logutil_decrypt`
- Expecting donor bulk pulls to be LOGH (they are plaintext)
- Brute-forcing `/etc/ftp.conf` or FTP for logs (separate closed avenue)

---

## Bulk-download framing cleanup

Retail LOGH files pulled over USB bulk often contain **embedded DUSS TRANS seams**
(`\x2a\x04` markers with `\x55\xe2` prefix) inside the ciphertext body. Assistant strips
these internally; our path must too.

`clean_logh_bulk.py` / `batch_decrypt.py` `prepare_logh()`:

1. Detect bulk seams in body (offset ≥ 0xB0)
2. Strip 12-byte TRANS framing per seam
3. Trim body to 16-byte aligned length from header size hint @+16

Without this step, `log_decrypt_fragment` returns -1 even with the correct key.

---

## Assistant DAT oracle (optional)

DJI Assistant `.DAT` exports contain decrypted payloads for the same indexed paths.
Useful for validating bulk pulls without decrypt, or for building a plaintext size index
(`dat_logh_index.json`) to extract LOGH blobs from DAT by offset.

Retail Assistant export (3.9 GB sample, Jun 2026): 450 paths, mostly `.enc` entries;
crash strings (`iondma`, `media_server`) **not** present in plaintext layer — crash
evidence may live inside encrypted diag/GFSK/lvmonitor blobs only.

---

## Tools in this repo

| Script | Purpose |
|--------|---------|
| `batch_decrypt.py` | Push LOGH to donor, run harness, pull `.dec` |
| `clean_logh_bulk.py` | Strip TRANS seams from LOGH body |
| `parse_logh.py` | Dump LOGH header fields |
| `pull_log_index.py` | Assistant-style bundle pull (one USB session) |
| `pull_all_retail_logs.py` | Full export_list pull + decrypt |

See [README.md](README.md) for usage.
