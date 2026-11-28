# Probing an O3 Air Unit over USB: the blackbox file service, the crashes it silently leaves, and the control requests that kill the port

Measured in November 2026 on an **unactivated retail DJI O3 Air Unit** (DUML name `WM1695 VT`,
software `V01.02.0000`, module `0802` `WM1695_E3T` `50.00.51.50`, package dated 2022-12-29),
Windows host, with DJI Assistant 2's own `libusb0.dll` through `goggles_tool`. Everything here is
the PC side. The unit's storage was not written to; the only state-changing things that happened
were its own export flow (it rewrites `/blackbox/info/list.json` when asked for a listing, exactly
as its Log Export does), one `07/64` frame to a host that does not answer it, and one anonymous FTP
login attempt — and, unintentionally, the crashes in §6 and the USB deaths in §7.

Tools that reproduce the read-only parts are in [`air_unit_probe/`](air_unit_probe/README.md). For
the O4 units and Assistant's firmware-update path see
[`AIR_UNIT_FIRMWARE_UPDATE.md`](AIR_UNIT_FIRMWARE_UPDATE.md); for the Goggles 3 side of LOGH see
[`log_export/LOG_ENCRYPTION.md`](log_export/LOG_ENCRYPTION.md).

---

## 1. The unit on the bus

| | O3 Air Unit |
|---|---|
| VID:PID | `2CA3:0020`, gadget serial is the shared `123456789ABCDEF` |
| Interfaces | `MI_00/01` RNDIS, `MI_02` mass storage, `MI_03`–`MI_07` vendor `ff/43/01` bulk pairs `0x03/0x84` … `0x07/0x88` |
| Command pipe | interface 4, OUT `0x04`, IN `0x85` (the only interface that carries DUML) |
| `bcdDevice` | `0x0409` |
| RNDIS | DHCP, host `192.168.42.1/24`, unit `192.168.42.2`; TCP 21 and 8901–8904 accept, nothing on UDP answers |
| Mass storage | LUN 0 `InternalStorage`, 20.7 GiB exFAT, empty; LUN 1 is the SD slot (no card) |

Assistant holds interface 4 with an exclusive claim, so anything of our own needs it closed. A
libusb-win32 binding on `MI_03`–`MI_07` is what our tools use; the unit keeps working with any of
those drivers, but only one process can claim interface 4.

## 2. Who answers on DUML

`00/01` (get_version) to every host `0x00`–`0xff`, then each answer followed up:

| host | answer |
|---|---|
| `0x1f` | `WM1695 VT Ver.A` + binary |
| `0x28`, `0xe0` | routed to `08:01`: `WM1695 VT Ver.1.23.223.2` |
| `0x48` | routed to `08:02` (upgrade centre) |
| `0x68` | `08:03`, answers `e0` to `00/01` (it answers other ids) |
| `0x88` | `08:04`, 31-byte version record with an empty name |
| `0x89` | `09:04`, `e0` to `00/01` |
| `0x0f` | `0f00`, 31 bytes `00 10 … 01 00 00 00 00 01 00 00 00 00` |
| `0x04` | nothing |
| `0x0a`, `0x2a`, `0x4a`, `0x6a`, `0x8a`, `0xea` | loopback of the PC's own addresses |
| `0x1b` | nothing — there is no `dji_network` host, so the Goggles 3 ADB frame is a no-op here |

Build string, `00/ff` to `0x1f` or `08:01`: `E3T WM1695 VT Dec 29 2022|12:35:20`.

## 3. Commands worth knowing (and one that reboots the unit)

Every command of every set `0x01`–`0xee` answers `e0` ("unsupported") at once on all eight hosts,
with five exceptions. Sets `0xef`–`0xff` and a few ids (e.g. `2f`, `aa` on some hosts) are never
answered, and an unanswered command blocks the channel for about a second — they queue, so eight
in a row stopped it for about eight seconds.

| host | command | reply (empty payload unless noted) |
|---|---|---|
| all | `00/00` | `00`; `00/01` version record |
| `0x1f`, `08:01` | `0c`, `95` | get/set a byte: `00 bb 01 00 00 00`; payload `bb` sets it and returns `0x0100 + bb` |
| `0x1f`, `08:01` | `37`, `59`, `5a`, `76`, `9a`, `9b`, `fa` | `00`-family answers / statistics by type byte |
| `0x1f` | `73` | echo with a timestamp: payload back, then a u32 that grows ~20,000 per 0.17 s |
| `08:02` | `07`, `0a` | `01`; `81` the 64-byte heartbeat record; `96` → `01 00` |
| `08:02` | `4f` | size by type: 1 → 2080 (`cfg.sig`), 5 → 452 (JSON in clear), 4 → the result record |
| `08:02` | `08`, `89`, `93`, `94`, `96`, `aa` | boot-age dependent (see below) |
| `08:04` | `32` | `00 03`; `[31 31 00 00 00]` serial record; `0e` 161 zero bytes (Assistant's 1 Hz heartbeat) |
| `08:04` | `e1`, `e6` | 39 / 66-byte records starting `00 0e 00 <serial>` / `00 0e <serial>` |
| `08:04` | `e3`, `e4`, `e5`, `36` | `00 f1 00 00` / 115 bytes / type-selected records / `e4`·`e3`·`c0` |
| `1d:00` | `21/05` | `00` (file-service ping) |
| `1d:00` | `2f [01]` | 1009 bytes `00 f0 03` + 1000 underscores (an empty fixed-size text field) |
| `1d:00` | `e7`, `e9` | `01`; `e8` → `02`/`03`; `eb`, `ee`, `f9` → `ff`; `ed` → `ff`, payload 01 → `00 04` |
| `08:01` | `01/40` | `01`; `4e/10` → `d6`; `21/05` → `00 00` |

- **`00/0b` to `08:01` reboots the unit**, unauthenticated: USB drops at once, RNDIS with it, open
  handles die, and the unit is back answering within about a minute. Its own boot list shows the
  two times it was sent. Do not send it.
- **Boot-age dependent answers.** Several getters answer only for roughly the first half hour after
  a boot and stop later: on `08:02` ids `08`, `89`, `93`, `94`, `96`, `aa`; on `08:04` `89`; on
  `09:04` `0b`, `fa`; on `08:03` `fa`; on `0f00` `89`. They all came back right after a reboot and
  none did 40 minutes in. Assistant's activation queries and the heartbeat are not boot-age gated.
- **`00/0c` is not a stored setting**: it returns `0x0100 + the first payload byte`, an empty
  payload later returned the last-seen values (`1f00` 00, `08:01` 0e, `08:02` 00), so it reads as
  "last parameter byte seen by that host".
- **`m004f` type 5 on `08:02` is JSON in clear** (452 bytes, read as `05 00 | chunk u16 |
  00 e8 03 00 | 00`): device name, version `01.02.00.00`, one module `WM1695_E3T` `50.00.51.50`
  online, and a backup package `wm1695_0802_v50.00.51.50_20221229.pro.fw.sig`, 158,197,024 B.
  Types 0, 2 and 6 answer `ce 00 00 00 00 04 00 00 00`.

## 4. The file service at `0x1d00`

Same command set as the Goggles 3 blackbox service, other host and simpler framing (no TRANS
layer; the PC is always sender `0a00`). `AIR_UNIT_FIRMWARE_UPDATE.md` describes how Assistant talks
the same framing for firmware; this is the Log Export half.

- `00/2a [06 | len | dir]` → `00 | len | /blackbox/info/list.json`: the unit writes a listing of
  `dir` into `list.json`, which is then read. Accepted for anything under `/blackbox`, with or
  without a trailing slash.
- `00/2a [08 | len | path | 09 01 <flag>]` → `00`, then the unit sends start `01 | size u32 |
  name_len | name | 00 01 01` (flags `0x40`, the PC acks with the start frame's sequence), data
  `04 | partno u32 | 976 B + 12 B zero pad`, end `03 | MD5` (the PC acks `00`).
- **Flow control:** the unit streams the whole file at once (~11 MB/s into Assistant, a 7.5 MB
  file in 0.61 s) and then waits for a progress ack `00 | highest contiguous part` that names its
  last part. Without an ack it restarts about a second later at the last acked part; an ack lower
  than its last sent part makes it resend from `ack+1`. A Python parser costs throughput in acks,
  not correctness.
- **The flag is a bit test, not an enum.** `09 01 00` (plain) is accepted only for
  `/blackbox/info/export_list.json` and `/blackbox/info/list.json`. Everything else needs bit 2 set
  (`09 01 04`) and comes back LOGH-wrapped; asking plain gives `d6`. Values with bit 2 clear are
  refused, and `05`, `ff` return the same wrapped bytes as `04`. There is no plaintext mode for
  other files.
- **Reply codes:** `00` accepted; `df` path does not exist; `e3` exists but empty or not a regular
  file (directories, every `/proc` file); `d6` a regular non-empty file outside `/blackbox`, a
  path without a leading slash, or the wrong flag; `e0` unknown command.
- **Confined to `/blackbox`**, but the codes make it an existence oracle for the rest of the file
  system: `/system/build.prop`, `/vendor/build.prop`, `/etc/ftp.conf`, `/system/etc/ftp.conf`,
  `/init.rc`, `/default.prop`, `/system/bin/sh`, `/proc/device-tree/model` all exist and are
  refused; `/etc/passwd`, `/sbin/adbd`, `/data/local/tmp`, `/lk`, `/persist` do not exist.
  `/proc/kcore` was not tried.
- **Path spellings do not bypass the allow-list.** `..` segments, `.` segments, `//`, trailing `/.`
  and `/`, uppercase (`/BLACKBOX`), and `/blackbox/info/../info/export_list.json` were all refused
  (`d6`, or `df` for the last two forms). The check is on the resolved path and the exact name;
  prefixes and suffixes do not help.
- **The parent listing can be incomplete.** `/blackbox/system` came back with 245 entries but only
  8 of the 28 tombstone files (§6); listing `tombstones/tombstone_0` and `tombstones/tombstone_1`
  themselves gave the full set (00–25 and 26). Always list the directory you care about.

**The export prepare** is `00/ea [0a 01 01]` (flags `0x40`) → 133 bytes
`00 0a 01 01 00 /blackbox/info/export_list.json` + zero padding. The reply also comes back as
34 bytes starting `ff` when it cannot run (see §8), and as `fe …` for a wrong version or a
payload longer than `0x103`. Assistant's export then sends `00/ea [0a 01 0N]` eight times
(notify log index; no reply).

**The exported list** (`export_list.json`, plain) is the unit's own boot history: `product_info`
(type `WM169 VT`, `drone_type` 124), `log_list` (the modules and their sizes), `boot_list` (every
boot with `ctime`/`mtime`) and `addr_list` (`U-E3T`, host_type 29). The unit's clock reads about
9 s early at boot, and a boot record's `mtime` is stamped 40–60 s into the *next* boot, so read
the `ctime` values as boot times.

## 5. What the unit hands out, and how it is wrapped

Everything except the two allow-listed files is LOGH v2, the same layout the Goggles 3 exports use:

| offset | content |
|---|---|
| `0x00` | `LOGH`, version `2` |
| `0x08` | header length `0xa0` (u16) |
| `0x10` | body length (u32) = 16 + padded plaintext |
| `0x18` | product string, `e3t_wm169` here |
| `0x29` | unit serial (not reproduced) |
| `0x48` | key label `07 00 00 00` |
| `0x4c` | 16 per-file bytes that feed the key derivation |
| `0x5c` | 4 bytes, not part of the derivation |
| `0xa0` | 16-byte IV |
| `0xb0` | AES-128-CBC ciphertext, plaintext padded to 16 |

- **The service re-encrypts on every read.** The same file pulled twice gave a different IV,
  different 16 bytes at `0x4c` and different ciphertext, with the same body length. So the source
  at rest is plaintext and the wrapping is done per read, with a fresh tag in the key derivation.
- **The key never leaves the unit.** `log_read_decrypt_ctx` in `liblog_util.so` calls
  `amt_get_derive_log_key(header[0x18:0x5c], 68)`, which forwards to a TEE app — the same call the
  Goggles 3 uses, see [`log_export/LOG_ENCRYPTION.md`](log_export/LOG_ENCRYPTION.md). The secret it
  mixes in is inside the TEE. On a retail Goggles 3 donor, a Goggles 3 file decrypts and the derived
  key reproduces its first ciphertext block, but 71 candidate inputs built from the O3 headers
  produced only noise. The secret is [INFERRED] provisioned per product line, so opening O3 files
  needs an O3's own TEE (code execution on the air unit) or DJI's side.
- **Sizes survive encryption**, and the listing's `size` field is the exact plaintext size. That is
  all the metadata there is: the header's clear fields, the sizes, and repeat detection
  (two tombstones with the same padded size are probably the same crash twice).

## 6. The crash artifacts: a read-only sweep is not side-effect free

A sweep of about 27,000 one-frame commands (every set `0x01`–`0xee`, ids and 34-payload probes on
chosen commands, across the eight hosts) left the unit **crashing its own processes without the
host noticing**:

- `/blackbox/system/crash_log/` held **11 timestamped collections, 115 files, 61.5 MB**. Each is a
  copy of the unit's tombstone directory at that moment, and the count only grew:

  | collection (unit time) | tombstones present | new |
  |---|---|---|
  | 16:02:18 | 00–02 (3) | first collection |
  | 16:18:59 | 5 | 03, 04 |
  | 16:21:14 | 6 | 05 |
  | 16:21:24 | 7 | 06 |
  | 16:21:34 | 8 | 07 |
  | 16:21:39 | 9 | 08 |
  | 16:22:04 | 10 | 09 |
  | 16:26:42 | 13 | 10–12 |
  | 16:26:47 | 20 | 13–19 |
  | 16:43:17 | 26 | 20–25 |
  | 16:56:12 (start of the next boot) | includes 26 | 26 |

- `/blackbox/system/coredump/`: **five** `core.event_task.<pid>.<time>.tar.gz` (2.7 MB) at
  16:44:33, 16:48:22, 16:48:29, 16:48:37 and 16:59:20, from five different pids.
- `/blackbox/system/tombstones/`: the 27 tombstones themselves (00–26) plus an `index`.
- **None of this existed at 12:17** in the same session's log export (34 entries, no `crash_log`,
  `tombstones` or `coredump`), so at least 24 tombstones were written during the sweeps. The 16:21
  and 16:26 clusters fall inside the `1f00` payload sweep; 16:43–16:44 in the `0801` one; 16:48 and
  16:59:20 are between runs and are not attributable from our logs.
- **The host side sees nothing**: the DUSS pipe never reset (`reopened=0` in every sweep log), so
  the crashed processes are daemons behind the router, restarted by init; the unit kept answering
  throughout. This is why the sweep looked harmless.
- **A 168-file pull** of the crash and info trees (76,784,224 B, every file MD5-verified against its
  end frame) is what `air_unit_probe/pull_crash.py` does. The tombstones' plaintext sizes range
  from 95,808 to 856,336 B (padded); the only repeated size is 142,720 B, on `tombstone_18` and
  `tombstone_23`.
- **What this means:** the tombstone set is the audit trail of any probing, and any log export sent
  to DJI includes it. Check for it after a sweep — and do not assume a command that answers `e0` is
  harmless, because the crash may be in whatever handled it before the router did.

Which commands did it is **not recorded**: the sweep logs carry no time per command, and narrowing
it means sending them again and crashing the unit again.

## 7. USB vendor control requests: the ones that kill the port

Vendor control requests on this unit are far less forgiving than its DUML channel. `wValue` 0, no
data stage, one request at a time with a health check after each:

| request | result |
|---|---|
| IN to the device, `0xC0`, wIndex 0, 64 bytes (all 256 bRequests) | all refused ("device attached to the system is not functioning"), no effect |
| IN to interface 4, `0xC1`, wIndex 4 (bRequest 0–255) | 252 refused, 4 "aborted", then the port was gone |
| OUT to the device, `0x40`, wIndex 0 (all 256) | all refused, no effect |
| OUT to interface 4, `0x41`, wIndex 4, bRequest `0x00` | **accepted**, USB dead at once |
| OUT to endpoint `0x04`, `0x42`, wIndex 4, bRequest `0x01` | **accepted**, USB dead at once |
| OUT to endpoint `0x04`, `0x42`, wIndex 4, bRequest `0x02` | **accepted**, USB dead at once |

A dead port looks like `Unknown USB Device (Device Descriptor Request Failed)`, with RNDIS, both
disks and the libusb nodes gone; `pnputil /restart-device` does not help. **Recovery is
unpredictable** — of the drops observed:

| drop | what happened |
|---|---|
| read-side (`0xC1`) | a boot ~5 min later |
| write-side 1 | a boot 48 s later |
| write-side 2 | USB back **by itself, no reboot**, in under 4.5 min |
| write-side 3 | nothing for 93 min, until the unit was replugged |

The best guess [INFERRED] is that the function's user-space owner gets an unexpected ep0 setup
packet and takes the gadget down; a reboot is only one of the ways back. Do not send these
requests, and if you must, one at a time with a health check and a note of which request killed it.

## 8. Export prepare can be late after a hard boot

`00/ea [0a 01 01]` normally answers the 133-byte path record in about 10 ms. In a boot that
followed a 99-minute session with 93 minutes of dead USB it answered 34 bytes starting `ff` for
the first ~16 minutes: the old `export_list.json` stayed in place, the unit rebuilt its own list
13.6 minutes after boot, and prepares succeeded from ~17 minutes on. No ping or other command is
needed before it.

For orientation, in the Goggles 3 `dji_blackbox` (decompiled) the exporter task answers `ff` when
the list-generation callback fails and `fe` for a wrong version or length, both in 133 bytes, and
sends nothing at all while busy — so the 34-byte `ff` is the O3's older code, not the same path.
Give a hard-booted unit 15–20 minutes before calling its export broken.

## 9. FTP: closed, and where the credentials live

Port 21 is `dji_ftpd` (`220 Hello!`). The PASS handler of the Goggles 3 binary (same server family)
shows how it authenticates: it opens `/etc/ftp.conf`, reads lines of at most 60 characters, splits
each at the first `:`, and accepts the session when USER equals the left part and PASS the right
part (`strcmp` on both). There is no default account and nothing compiled in. The USER command
alone always answers `331 Please specify password`, so users cannot be enumerated; anonymous and
`root` are refused.

- `/etc/ftp.conf` **exists on the O3** (the file service answers `d6` for it) and **does not exist
  on any Goggles 3 image** (none of the pulled engineering trees has it), which is why FTP login
  never worked on the goggles.
- **DJI Assistant carries no credentials.** Searching all 1,092 files of the installation and
  decompiling `DJIUavService.dll`: `DJIFtpFileGetter` logs in with the user name and password
  embedded in a `QUrl` (`ftp://user:pass@host/path`), and `LogDownloaderWithCfg` fills those from
  `ftp_user` / `ftp_pwd` keys of an info file the product hands over (alongside `ip_map`,
  `log_path`, `sortie_path`, `all_export_path`). The firmware-upgrade negotiation only yields
  `ftp_ip` and `ftp_path`.
- The O3 does not hand that info file over in clear: its `info00N.json`, `log_list.json`, `latest`
  and `boot_list.json` come back LOGH-wrapped, and the firmware image that holds `/etc/ftp.conf`
  is an encrypted container.

So the credentials exist only inside the unit, reachable through nothing we found. Brute force is
out by policy.

## 10. Hazards checklist

- Close DJI Assistant 2 before touching interface 4 (it holds an exclusive claim).
- Under Git Bash use `MSYS_NO_PATHCONV=1`, or `/blackbox/...` arguments become `C:/Program
  Files/Git/blackbox/...`.
- Never send `00/0b` to `08:01` (reboot), the upgrade-start commands (`00/83`, `00/84`, `00/85`,
  `00/41`), engineering mode (`07/64`, `07/65`) or anything with a data stage to interface 4 or its
  endpoint, unless you have decided to risk the port.
- After any command sweep, list `/blackbox/system/`, then `crash_log/`, `coredump/` and
  `tombstones/` **themselves**, and count: that is the sweep's real footprint.
- Expect the export prepare to lag after a hard boot; `air_unit_probe/export_timing.py` tells you in
  two seconds whether it is up.
- The verb `00/2a` is the file service; do not send phase bytes you have not verified — several
  phases exist that our tools do not use.

## 11. What is still open

- Which commands crashed the processes in §6 (needs a re-run that crashes the unit again).
- A plaintext path for `/blackbox`: the family's "SD export does not need encryption" marker exists
  in the Goggles 3 `dji_blackbox`, but using it means making the unit write a log export to
  storage — a write-side decision, not taken here.
- Whether the O4's `1d00` also serves phase 06/08 (Assistant shows no Log Export there, but the
  ping is answered).
- Whether `Log Export` on the O3 is a product trait or an activation trait.
- The five O3 TCP listeners (21, 8901–8904): 8901–8904 were silent to 13 payloads each. The
  activated O4 Pro had no open port at all in a full scan.
