# How DJI Assistant 2 updates an O4 Air Unit over USB

Measured in November 2026 on hardware we own, with **DJI Assistant 2 (Consumer Drones
Series) V2.1.39** on Windows: an **O4 Air Unit Pro** (retail V01.00.06.00, upgraded to
V01.00.07.00) and an **O4 Air Unit** (the Lite; retail V01.00.03.00, shown as "DJI O4 Air
Unit"). Four updates were captured with USBPcap and decoded frame by frame — two Refreshes
and one Upgrade on the Pro, one Refresh on the Lite — and the framing was confirmed against
the engine DLL and against every frame. The scripts that did the decoding are in
[`assistant_update/`](assistant_update/README.md).

Everything here is the PC side of the protocol. The units themselves were not modified
beyond what Assistant's own update does.

---

## 1. The two units on USB

They are indistinguishable from each other (and from a retail Goggles 3) on the bus except
for one string:

| | O4 Air Unit (Lite) | O4 Air Unit Pro |
|---|---|---|
| Name in Assistant | DJI O4 Air Unit | DJI O4 Air Unit Pro |
| Name the engine uses | `za530` | `za5305` |
| `BusReportedDeviceDesc` | `O4-<serial>` | `O4 Pro-<serial>` |
| VID:PID, gadget serial | `2CA3:0020`, `123456789ABCDEF` | same |
| bcdDevice, strings | `0x0504`, `DJI`, `BULK Interface` | same |
| Configuration string | `rndis,mass_storage,bulk,acm` | same |
| Interfaces | MI_00 RNDIS, MI_02 mass storage, MI_03–MI_07 `ff/43/01` | same |
| Bulk pairs (512-byte packets) | `0x03/0x84` … `0x07/0x88` | same |
| ADB or ACM interface | none | none |

Swapped on one port they even reuse the same Windows instance ID. The **DUML command pipe is
interface 4** (`0x04` out, `0x85` in), as on the Goggles 3.

## 2. The V1 frame as Assistant builds it

From `format_packet` in the engine's `fs_dbus_lib.dll`:

```
off  size  field        value
0    1     SOF          0x55
1    2     length (LE)  (payload_len + 13) & 0x3ff | 0x400     byte 2 = 0x04 | len >> 8
3    1     crc8         CRC-8 over bytes 0..2, poly 0x8C (reflected), seed 0x77
4    1     sender       sender_num << 5 | sender_type          5-bit type, 3-bit number
5    1     receiver     receiver_num << 5 | receiver_type
6    2     seq (LE)     one counter on the PC, wrapping; replies echo the request's value
8    1     flags        bit 7 = reply, bits 6..5 = ack type, bits 4..1 = encrypt type
9    1     cmd_set
10   1     cmd_id
11   n     payload      n <= 1011
n+11 2     crc16 (LE)   CRC-16 over bytes 0..len-3, poly 0x8408, seed 0x3692
```

- The sender and receiver bytes are **packed pairs**, not types: `2a` is `0x0a01` (the PC,
  type `0x0a` number 1) and `48` is `0x0802`. Reading byte 5 as a plain type is off by the
  `num << 5` shift.
- Assistant sends requests with `flags 0x40` (ack after exec); the unit answers `0xc0` with
  a result byte first. The unit's pushes use `0x00`. The heartbeat is started by the unit:
  `0802 → 0a01` with `0x40`, the PC answers `0x80`. The meaning of the flag bits is the one
  the dji-firmware-tools dissector uses; every value seen fits it.
- Both CRCs are the ones `goggles_tool.protocol.duss` already implements; a MSB-first table
  built from `0x8C` does **not** match the captures, the reflected one does.
- Checked on real frames: 7,122 frames of a Goggles 3 capture and every frame of the four
  air-unit update captures (about 172,000 each); the only bytes that are not frames are the
  64 KB zero block described in section 9.

A request and its reply from a captured session (the Lite's upgrade centre):

```
55 0d 04 33 2a 48 3a 33 40 00 01 06 8b
       PC 0a01 -> 0802, seq 333a, flags 40, cmd 0/1 (get_version), no payload
55 2c 04 36 48 2a 3a 33 c0 00 01 00 12 "ZA530 AC Ver.01" 00 2d 0e 00 0a 2d 0e 00 0a 01 00 00 c0 00 0a af
       reply: same seq, flags c0, result 00, then 12, the NUL-terminated text and trailing fields
```

## 3. Hosts on the air units

| Host | Role | Seen as |
|---|---|---|
| `0x0802` | **upgrade centre**, module `0802`, also starts the heartbeat | `get_version` → `ZA5305 AC Ver.0` + module version (Pro) / `ZA530 AC Ver.01` + module version (Lite) |
| `0x1f00` | version | `ZA5305 AC Ver.A` / `ZA530 AC Ver.A` |
| `0x0803` | serial number | `cmd 0x51 [04]` → 16 characters |
| `0x0801` | set time (`cmd 0x4a`, 7 bytes), status pushes | |
| `0x0804` | takes the empty `cmd 0x0e` once a second | |
| `0x0300`, `0x1d00`, `0x0900`, `0x0904`, `0x1105`, `0x0306` | polled, mostly unanswered | |

The module version in the `0x0802` reply is in reverse byte order: `14 10 00 0a` is
10.00.16.20, `06 11 00 0a` is 10.00.17.06, `2d 0e 00 0a` is 10.00.14.45.

Assistant also reads the unit's own upgrade descriptor with `cmd 0x4f`: requests
`01 00 | n | 00 e8 03 00 | 00` for `n` = 0…7, replies `00 | chunk_len | 20 | 7-n | 00 00 | data`.
It is the `cfg.sig` of the installed version (section 8), but only 1,824 of its 2,080 bytes
arrive: the chunk at offset 1792 is never returned.

After any update, the serial-number query gets no answer for the first seconds (Assistant
gives up after six tries); it works again on the next attach.

## 4. The update, step by step

All commands go to `0x0802`, in **command set `0x00`**. The older per-module path
(`0x07`–`0x0c`: enter loader, update confirm, transmit, finish, reboot chip, get device
state) exists in the engine and was not used by either unit.

| Step | PC sends | Unit answers |
|---|---|---|
| enter upgrade mode | `0x83 [04]` | `0x83 [00 17 00]` after ~0.9 s |
| announce the update | `0x84 [00 \| size u32 \| 00 00 00 00 \| 02 00 01]` | `0x84 [00]` |
| manifest, then firmware | `0x2a` file transfer (section 5) | per file: start reply, part acks, end reply |
| start flashing | `0x85 [00 ×16]` | `0x85 [06]` |
| progress | — | push `0x42` once a second |
| reboot | USB disappears; the unit comes back with a new USB address | |
| result | `0x4f [04 00 00 00 00 ff ff ff ff]`, `0x41 [04]` | `0x4f [00 04 00 00 00 00 00 00 00 00 xx 00 01]`, `0x41 [00]` |

`size` in `0x84` is the sum of the two files: `0x0A01AE80` = 167,880,288 + 2,080 for the Pro
on V01.00.06.00, `0x09FA6B60` = 167,404,352 + 2,080 on V01.00.07.00, `0x09EB4F60` =
166,414,144 + 2,080 for the Lite.

The progress pushes (`0802 → 0a01`, no ack wanted, one per second):

```
Refresh, both units     03 03 00 ×9…10   03 07 02 00 01 00 00 00 00 31 07 28 00 00 00 00 00 31 00 ×2
                        03 57 00 ×2      -> USB drops; after the reboot 03 64 00, 04 01 00
Upgrade, Pro            03 03 00 ×10     03 07 00   03 09 ... ×2
                        03 SS 02 00 01 00 00 00 00 31 SS 28 ... ×2 per step, SS = 25, 26, ... 31
                        03 54 00 ×2      -> USB drops; after the reboot 03 54 00 ×2, one 27-byte 03 57 ..., 03 64 00, 04 01 00
```

A Refresh flashes in 13–15 s, the Pro's version change took 47 s. `0x64` is 100 %, the first
byte `3` means running and `4` finished. The `xx` in the result record was `06` on the Pro's
Refreshes, `07` on its Upgrade and `03` on the Lite's Refresh: it is not a Refresh/Upgrade
code, and its meaning is unknown.

## 5. The file transfer (`cmd 0x2a`, "FileTrans General Trans")

| Phase byte | Request payload | Reply (`flags 0xc0`, same `seq`) |
|---|---|---|
| `01` start | `01 \| size u32 \| name_len u8 \| name incl. NUL \| 00 01 01` | `00 \| d4 03 \| 88 13 \| 01 01` → part size 980 |
| `04` data | `04 \| partno u32 \| data` (980 bytes, the last one shorter) | none per frame |
| part ack | — (sent by the unit) | `00 \| partno u32`, with its own `seq` counter |
| `03` end | `03 \| MD5 of the whole file` | `00` once the unit has verified it |

- Parts go out back to back, one V1 packet of 998 bytes per part, written to the USB pipe in
  2048-byte transfers (frames are not aligned to them). About 50 parts are in flight beyond
  the last acked one, up to ~360.
- Part acks are not one per part: the unit reports the **highest contiguous part** every
  49–151 ms (median 121 ms). No part was lost in any of the four runs, so the engine's
  retransmission path (`DJIGeneralFileTransferLostList`) was never exercised.
- The end frame carries the plain MD5 of the file; every file rebuilt from the captures
  matched it.

| | Pro Refresh 1 | Pro Refresh 2 | Pro Upgrade | Lite Refresh |
|---|---|---|---|---|
| firmware parts | 171,307 | 171,307 | 170,821 | 169,811 |
| transfer | 16.95 s, 9.90 MB/s | 16.83 s, 9.98 MB/s | 16.54 s, 10.12 MB/s | 16.55 s, 10.05 MB/s |
| part acks | 174 | 172 | 169 | 170 |
| ack interval min / median / max | 50 / 121 / 150 ms | 49 / 121 / 145 ms | 49 / 121 / 135 ms | 49 / 121 / 151 ms |
| most parts sent but unacked | 358 | 331 | 356 | 265 |
| pushes before the reboot | 15 | 15 | 47 | 13 |

Between the two Pro Refreshes the control frames were byte-identical apart from `seq` and
timing (one single `03 06 00` push did not recur).

## 6. What the UI sends

The Electron UI is a client of the engine (`DJIService.exe`) over an encrypted WebSocket on
`localhost:19870`; it has no USB code. For both units the page `wm170.html#/upgrade` does:

1. `book_device_list {status:1}` → `push_device_list` (`device_id` 72, `device_name`
   `za5305` or `za530`)
2. `get_device_firm_pack_list {device_id, product_id, …}` → `latest_version`, `local_version`,
   `pack_list`
3. `upgrade_firm_pack {type:0, version, moduleId:72, device_id:72, device_name, position:0}`
4. pushes `push_download_progress`, `push_transfer_progress`, `push_upgrade_progress`, then
   `push_upgrade_result {stage:"upgrade", status:"success"}`

Messages are `base64(AES-256-CBC(PKCS#7(JSON), key, iv = zeros))`; requests and the UI log
use one key, responses another, both derived by `utils.genrpivate` from obfuscated literals
in the bundle.
[`assistant_update/assistant_ws_crypto.py`](assistant_update/assistant_ws_crypto.py) derives
them from a local installation and decrypts `DJIApp/ui_ass2.log`, which is the quickest way
to see which commands a given page really sends.

## 7. Where the packages come from

The engine fetches from `https://mydjiflight.dji.com`: `/getfile/getallfile` (list for a
product), `/getfile/download` (package), `/getfile/firmware` (module file). It works without
a DJI login; requests carry `product_id`, a `signature` (hex MD5 of an engine-held string
plus the `product_id`), `account`, and flags for engineering devices and account roles.
We only ever used what Assistant itself requested.

| Product | Packages offered (all `formal`) |
|---|---|
| `za5305` (Pro) | 01.00.0700 (latest), 01.00.0600 |
| `za530` (Lite) | 01.00.0400 (latest), 01.00.0300, 01.00.0200, 01.00.0100 (the last two as Downgrade) |

Each firmware file sent was byte-identical to an entry in `DJIEngine/DJIData/firm_cache/`.

## 8. The two files

| File | Size | Readable |
|---|---|---|
| `<product>.cfg.sig` | 2,080 B | all of it |
| `<product>_0802_v<module version>_<date>.ar2.pro.fw.sig` (Pro) / `…ar0.pro.fw.sig` (Lite) | 166–168 MB | header only |

`cfg.sig` is a 224-byte `IM*H` header, a 384-byte signature and 1.5 KB of XML: the module,
its version and size, the updater settings, the firmware file name, the `md5` of the
firmware file (the value sent in the end frame) and an `md5_unsign` of the decrypted image.

```xml
<device id="za5305"><firmware formal="01.00.0600">
  <release version="01.00.0600" antirollback="2" …>
    <module id="0802" version="10.00.16.20" size="167880288" name="ZA5305_E3T"
            is_upgrade_center="true" op_lib_name="libeagle_md_up.so" com_method="V1" …
            md5_unsign="…" md5="…">za5305_0802_v10.00.16.20_20260313.ar2.pro.fw.sig</module>
```

The Lite's V01.00.03.00 has `antirollback="0"`; the Pro's builds have `2`.

| Firmware file | Bytes | MD5 |
|---|---|---|
| `za5305_0802_v10.00.16.20_20260313.ar2.pro.fw.sig` | 167,880,288 | `eed2de81076623f36cbfe07d9b023165` |
| `za5305_0802_v10.00.17.06_20260623.ar2.pro.fw.sig` | 167,404,352 | `3e6d950e8daa602a1a3094fee8a169ae` |
| `za530_0802_v10.00.14.45_20250528.ar0.pro.fw.sig` | 166,414,144 | `87a8a1bd71d400cab860289dcf58d967` |

The firmware container is `IM*H` format 2018, type `E3T`, module `0802`, no compression,
auth key `PRAK` with algorithm `0x40003`, encryption key `UFIE`, one chunk, then a 384-byte
RSA signature and the encrypted payload (7.95 bits/byte, no file magic anywhere). **What is
inside is not known.** On the Pro's V01.00.07.00 file the signature does not verify with
`PRAK-2021-09`, the only published key of the right length, and all six published `UFIE` keys
give output that fails the plaintext checksum; the same six keys fail on the Lite's file.
See `FIRMWARE_CONTAINERS_AND_DUML.md` for the container classes.

## 9. Reproduce it

See [`assistant_update/README.md`](assistant_update/README.md): capture with USBPcap while
Assistant performs the update, find the unit's USB address with tshark (it changes on the
reboot, so decode both addresses), then `v1stream.py`, `reconstruct.py` and
`compare_runs.py`. Two capture artefacts to know about: USBPcap records one 64 KB zero-filled
block on the IN endpoint at the moment of the USB disconnect, and the file cannot be read
while `USBPcapCMD` is running.

## 10. Open questions

- What the encrypted firmware contains (by analogy with the Goggles 3's module: an Android
  OTA image; not verified).
- The meaning of the result-record byte (`03` / `06` / `07`) and of most progress-push fields.
- The lost-part retransmission path and a failed MD5 check.
- Whether the older Lite packages (01.00.0100, 01.00.0200) behave differently; the unit's
  anti-rollback level is 0 and Assistant itself offers them as Downgrade. Not tried.
