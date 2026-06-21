# Log export & decrypt (retail bulk USB)

Pull blackbox logs from **retail** DJI Goggles 3 over USB bulk (no ADB), decrypt on a
**rooted engineering donor** using `liblog_util.so`.

This replaces DJI Assistant's log export for automation and pairs with the firmware
upgrade kit in the repo root.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Windows + Python 3.10+ | 64-bit |
| `pip install -e goggles_tool` | From repo root |
| Retail goggles on USB | Consumer unit, Assistant **closed** |
| Rooted donor on USB (decrypt only) | Engineering display unit with ADB |
| Android NDK (once) | Build `logutil_decrypt` harness |

Optional: set `ADB` env var or pass `--adb` if `adb` is not on PATH.

---

## One-time: build decrypt harness on donor

```powershell
cd log_export\logutil_decrypt
.\build.ps1 -NdkRoot "C:\Android\android-ndk-r27c"
adb push libs\arm64-v8a\logutil_decrypt /blackbox/stage/logutil_decrypt
adb shell chmod 755 /blackbox/stage/logutil_decrypt
```

Verify:

```powershell
adb shell id   # uid=0
adb shell /blackbox/stage/logutil_decrypt
```

---

## Quick start

### 1. List log indices (retail connected, Assistant closed)

```powershell
python log_export\pull_log_index.py --list
```

### 2. Pull one flight bundle (Assistant-style single session)

```powershell
# Pull flight0235 logs (~700 MB), decrypt on donor when done
python log_export\pull_log_index.py --flight 235

# Pull only (donor offline) — decrypt later
python log_export\pull_log_index.py --flight 235 --no-decrypt

# Resume interrupted pull
python log_export\pull_log_index.py --flight 235 --no-decrypt --resume
```

Output: `log_export/output/pull_<timestamp>_flight0235/files/`

### 3. Decrypt pulled LOGH files

```powershell
python log_export\batch_decrypt.py bulk log_export\output\pull_*\files
```

Decrypted files: `log_export/logutil_decrypt/kpa_results/decrypted/` (configurable via
script; see `--help` in future or edit `OUT_DIR` in script).

### 4. Full export_list (all paths)

```powershell
python log_export\pull_all_retail_logs.py --resume
python log_export\pull_all_retail_logs.py --limit 20   # smoke test
```

---

## Lower-level CLI (`goggles_tool`)

```powershell
python -m goggles_tool devices
python -m goggles_tool info
python -m goggles_tool logs-list -o log_export\output\export_list.raw
python -m goggles_tool -v logs-download --path "/blackbox/system/df00.log" `
  --expected-size 12345 -o log_export\output\df00.logh
```

Engineering donor with ADB can use `--via-adb` on `logs-list` for complete JSON.

---

## Utilities

```powershell
# LOGH header inspection
python log_export\parse_logh.py log_export\output\pull_*\files\system__df00.log

# Strip TRANS seams from a LOGH file (usually automatic in batch_decrypt)
python log_export\clean_logh_bulk.py path\to\file.logh
```

---

## Two-unit setup

```
┌─────────────────┐     bulk USB      ┌──────────────┐
│ Retail goggles  │ ─────────────────►│  Windows PC  │
│ (LOGH ciphertext)│                   │ goggles_tool │
└─────────────────┘                   └──────┬───────┘
                                             │ adb push/pull
┌─────────────────┐                          │
│ Donor goggles   │ ◄────────────────────────┘
│ logutil_decrypt │
└─────────────────┘
```

USB gadget serial is `987654321ABCDEF` on **both** units — confirm which device answered
via `export_list` product serial or `python -m goggles_tool info`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `could not claim interface` | Close DJI Assistant; kill stale `python` processes |
| Pull stalls mid-file | See [BULK_PROTOCOL.md](BULK_PROTOCOL.md) — window ack sequencing |
| `decrypt_fragment -1` | Run `batch_decrypt.py` (auto seam clean); confirm donor root |
| Partial export_list | Normal on bulk; use `--flight N` or `--list` boot indices |
| Plaintext on donor bulk | Expected — donor skips encryption (`secure_debug=1`) |

---

## Documentation

- [LOG_ENCRYPTION.md](LOG_ENCRYPTION.md) — LOGH format, key derive, decrypt API
- [BULK_PROTOCOL.md](BULK_PROTOCOL.md) — TRANS ack rules, USB session flow
- [../goggles_tool/README.md](../goggles_tool/README.md) — package architecture

---

## Safety

- **Read-only** on retail — no writes to retail unit.
- Donor harness writes only to `/data/local/tmp/` and `/blackbox/stage/`.
- Do not publish pulled logs unredacted (serials, keys, GNSS, flight data).
