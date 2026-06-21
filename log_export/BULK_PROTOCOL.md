# Bulk USB log download — protocol notes

Reverse-engineered from USBPcap captures of DJI Assistant 2 on Goggles 3 (E3T ZV902).
Implemented in `goggles_tool/` (`client.py`, `protocol/duss.py`).

**Status:** June 2026. Small/medium files verified on retail; large bundle pulls (~20 MB+)
require correct TRANS window ack sequencing (see below).

---

## USB access

| | Engineering donor | Retail |
|---|------------------|--------|
| ADB | Yes (root) | **No** |
| Bulk MI_04 | Yes | Yes (only path) |
| VID:PID | 2CA3:0020 | 2CA3:0020 |
| Claim interface | Close Assistant first | Same |

Windows: bulk uses **libusb-win32** (libusb0). The tool loads DJI Assistant's
`bulk_amd64/libusb0.dll`. Use **64-bit Python**.

When **both** units are connected, bulk auto-detect picks the non-donor (retail) address.
Pass `--address N` to override (`python -m goggles_tool devices`).

---

## Session flow (matches Assistant)

1. **get_version** — handshake + XML chunks (`upgrade_center` module list)
2. **export_list** — opcode path `/blackbox/info/export_list.json`
3. Per bundle or file:
   - `log_open(session_hi)` — dynamic session counter
   - `090104` + path length byte + path — file download request
   - IN: 38 B + 62 B TRANS setup, then 31832 B data chunks
   - OUT: `ack_open` → `ack_prog` (×N) → `ack_done` → `ack_open` (next window)
4. Assistant bundles many files in **one USB session** (one `log_open`, sequential `090104`).

---

## TRANS download ack rules [CONFIRMED]

Init/Assistant captures (GFLY ~87 MB, multi-file exports):

| Ack | Rule |
|-----|------|
| `ack_open` | Once per TRANS window; session bytes from TRANS header @+12/+13 |
| `ack_prog` | **Window-relative** u32 @ TRANS+12 (not file-wide cumulative bytes) |
| `ack_done` | After window tail chunk OR when device stops sending data |
| Next window | Client sends **`ack_open` immediately after `ack_done`** |

Window tail: short TRANS chunk (declared inner len 1–1000 B, ~54 B total) after a run
of 31832 B chunks. Must ack tail prog + `ack_done` before next window.

Keepalive frames (`554d04a8…`, 77 B) must **not** reset stall detection — they arrive
while waiting for the next data chunk.

---

## Payload extraction

Each 31832 B TRANS data chunk packs ~32 inner DUML (`0x55`) bodies. Extract with
`_concat_duml_payloads`, not first-packet-only unwrap — otherwise ~2% of file received.

Retail encrypted exports wrap file bytes in **LOGH** inside TRANS payloads.
Donor exports are plaintext (no LOGH).

---

## export_list quirks

Bulk `export_list` JSON is often **partial** (~25–40 `log_list` entries, `boot_list`
sometimes empty). Scripts merge:

- `duss.extract_json_blob()` when parse succeeds
- Regex fallback for `"path"` / `"size"` / `"mtime"` tuples
- `duss.extract_log_paths()` for path-only recovery

Use `--list` on `pull_log_index.py` to see available boot indices.

---

## CLI quick reference

```powershell
pip install -e goggles_tool

# Device discovery
python -m goggles_tool devices
python -m goggles_tool info

# Single file (retail)
python -m goggles_tool -v logs-download --usb-address 10 `
  --path "/blackbox/flight0233/gls_gfsk/GFSK-0233-01.log" `
  --expected-size 258143 -o test.logh

# export_list via bulk
python -m goggles_tool logs-list -o export_list.raw
```

For production pulls use `pull_log_index.py` (bundle) or `pull_all_retail_logs.py`.
