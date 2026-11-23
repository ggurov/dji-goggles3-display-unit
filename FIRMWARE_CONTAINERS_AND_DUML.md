# Firmware containers, `dji_fw_verify` acceptance, and DUML on the Goggles 3

Notes from a November 2026 session helping another researcher decode a **Goggles 2**
("zv900") main module on a rooted **Goggles 3** (E3T/zv902). Everything below was measured
on hardware we own; nothing here requires flashing.

Device state used for all tests: retail **v01.00.1300 / build 29020** on slot 2, root ADB,
engineering build on slot 1 untouched.

---

## 1. `dji_fw_verify` is not a universal decryptor

The stock tool (`/system/bin/dji_fw_verify`) verifies **and** decrypts IM\*H containers, but
only for container classes the Trusted Application (TA) knows. A failure is not evidence of a
bad file — always run a control:

```bash
# control: a genuine Goggles 3 goggle module (engineering build), same device, same flags
dji_fw_verify -n 2805 -c 2805 -o /blackbox/ctl.zip <zv902_2805_....ar0.pro.fw.sig>
# -> verify pass, exit 0, output starting "PK\x03\x04"

# the third-party file
dji_fw_verify -n 2805 -c 2805 -o /blackbox/g2.zip /blackbox/upgrade/zv900-module-2805.imah
# -> verify fail, fw_util_verify_update failed, exit 255
```

`dmesg` names the failing step:

```
FW_LOAD[fw_util_verify_final:912] TEEC_InvokeCommand failed with code 0xffff0007 origin 0x4
```

`0xFFFF0007` = `TEEC_ERROR_BAD_STATE`, origin 4 = trusted app. `verify_final` opens a session
and sends command 5 (`fw_invoke_verify`) with empty parameters — the TA decides from state
accumulated during `verify_init`/`verify_update`.

Useful error codes seen here:

| code | meaning | typical cause |
|---|---|---|
| `0xFFFF0006` | `BAD_PARAMETERS` | passing `-d/-D` at all (fails at `verify_init`) |
| `0xFFFF0007` | `BAD_STATE` | container class / key not supported by this TA |

### Flags

```
-h  help            -n/--name      image name (from the header `name`)
-c/--chunk          chunk id      -s/--size   ION size in MB (default 32)
-o/--output=FILE    output        -d/--symkey / -D   symmetric key name/version
-v/--pubkey / -V    pubkey name/version
```

- **Goggle modules:** `-n 2805 -c 2805` (name and chunk id are both `2805`).
- **Modem images:** `-n cp` (or `ap`/`dsp`/`scp`) and **no `-c`** works. `-c` is **not** a
  chunk selector: a value that names a chunk which actually exists in the container (e.g.
  `-c BLLK` on `wa520/cp.img`) makes a passing verify fail, while a value naming something
  absent (`-c RTOS`, `-c cp`) is ignored and the verify still passes. Measured 2026-11-23.
- `-d/-D` is not a key-existence oracle on this build: every form tried
  (`-d UFIE`, `-d UFIE-2021-08`, `-d TBIE-2021-08`, `-d UFIE -D 2021-08`) fails at
  `fw_util_verify_init` with `ret:-65530`.

### Output notes

- Genuine `ZV90` goggle modules decrypt to a real zip (`PK\x03\x04`), not zero-filled.
- **Every modem/boot-chain container the TA accepts writes an all-zero output file.** Measured
  2026-11-23 on build 29020, byte-exact: `wa520/cp.img` → 441,720 B out, **0** non-zero, while
  the source `BLLK` chunk is 99.6 % non-zero; `ap` 325,436 / `dsp` 244,800 / `scp` 46,188 /
  boot-chain `scp` 81,344 — all 0 non-zero. `verify pass` here means signature check only, so
  treat exit code 0 as meaningless for these classes and measure the output.

---

## 2. Reading an IM\*H header

Header layout (v2): 192/224/256-byte package header, then `chunk_num` × 32-byte chunk headers,
then `signature_size` bytes of signature, then payloads at `header_size + signature_size +
chunk.offset`.

The parser from `tools/dji-firmware-tools/dji_imah_fwsig.py` (`ImgPkgHeader`, `ImgChunkHeader`)
is the quickest way to dump the fields that matter:

| field | meaning |
|---|---|
| `auth_key` / `enc_key` | key names, e.g. `PRAK`, `TBIE`, `UFIE` (empty = plaintext) |
| `auth_alg` | signature scheme: `0x3` (legacy) or `0x40003` (current) |
| `type` | container class: `ZV90` (goggle module), `TKRN`/`TSCP` (boot images), `TBLD` (modem) |
| `name` | image name for `-n` (e.g. `2805`, `cp`) |
| `version` | **plain byte-packed, not BCD**: `0x0A003B28` = `10.00.59.40` |
| `date` | **BCD**: `0x20260811` = 2026-08-11 |
| `chunk_num` / chunk `id` | e.g. one `2805` chunk, or `BLLK` + `CP2` for some modems |

### What verifies on a Goggles 3

| container | type | auth_alg | enc_key | chunks | result |
|---|---|---|---|---|---|
| G3 goggle module (eng 2023 / 2025, retail v1300) | `ZV90` | `0x3` | — | 1 | **pass**, real zip |
| G3 boot-chain `scp` | `TSCP` | `0x40003` | `TBIE` | 1 | pass, **zeros** |
| G3 boot-chain `tos` / `normal` | `TKRN` | `0x40003` | `TBIE` | 2 / 21 | **fail** `NOT_SUPPORTED` |
| G3 modem `wa520/{cp,ap,dsp}`, `scp` | `TBLD`/`TSCP` | `0x3` | `TBIE` | 1 | pass, **zeros** |
| G3 modem 2-chunk variants (`cp.img` `BLLK`+`CP2`, `l1c.img`) | `TBLD` | `0x3` | `TBIE` | 2 | **fail** `NOT_SUPPORTED` |
| G2 pigeon `cp`/`share_info` (4 files, 2026-11-23) | `TKRN` | **`0x2`** | `TBIE` | 8 / 1 | **fail** `NOT_SUPPORTED` |
| **Goggles 2 main module v10.00.81.97** | **`E3T`** | **`0x40003`** | **`UFIE`** | 1 | **fail** (`BAD_STATE`) |

The TA accepts **single-chunk containers only** — every multi-chunk image tried (boot-chain
`tos`, `normal`, the two-chunk modem variants, and the G2's 8-chunk pigeon files) fails at
`fw_invoke_verify_update` with `0xFFFF000A` (`TEE_ERROR_NOT_SUPPORTED`, origin 4), regardless
of name or `-c`. The G2 pigeon containers fail with exactly the code the G2 itself returns,
so there is **no** G3-as-decryption-oracle capability difference.

Takeaway: the G2 — an older product — ships a **newer** goggle-module container generation
(`E3T` + `0x40003` + `UFIE`) than the G3, whose modules are `ZV90`/`0x3`/plaintext. A rooted
Goggles 3 cannot decrypt it. The TA's key table lives inside the IM\*H-wrapped `tos.img`
(`TKRN`, enc `TBIE`) and is not readable from userspace; `UFIE` appears nowhere in G3
userspace or the system/vendor images.

### Goggles 2 pigeon modem containers (2026-11-23 request)

A G2 researcher asked whether a G3 can decrypt the G2's `pigeon` modem images, on the theory
that `wa520` is the same modem on both products. Four factory containers were supplied and
tested, all `TKRN` / `auth_key=PRAK` / `enc_key=TBIE` / header v2:

| file | bytes | `auth_alg` | chunks |
|---|---|---|---|
| pigeon default `cp` | 6,001,024 | `0x00000002` | 8 (`RTOS` 0x3771bc + M0IM/X164/X450/X451/SHRI/PHYS/RFNV) |
| pigeon `wa520` `cp` | 6,088,288 | `0x00000002` | 8 (`RTOS` 0x3861dc) |
| `wm169_unit` `cp` | 6,105,184 | `0x00000002` | 8 (`RTOS` 0x377668) |
| pigeon `share_info` | 544 | `0x00000002` | 1 (`SHRI`) |

Result: **all four fail** (`-n cp` / `-n share_info`, with and without `-c <chunk>`, `-n
ap/dsp/l1c/scp`, `-s 8`) with `0xFFFF000A` at `fw_invoke_verify_update` — the same
`TEE_ERROR_NOT_SUPPORTED` the G2 returns for the same files. Note `auth_alg` is `0x2`, not
`0x40003`: this is an older container generation than the G3's boot images.

The request's premise — "the G3 decrypts a `wa520/cp.img`" — conflates the name. The G3's
`wa520/cp.img` is a 442,336-byte `TBLD` / single-`BLLK` DDR blob (load `0x70000000`), not the
G2's 6 MB `TKRN` eight-chunk image with RTOS at `0x10020000` and DSPs at `0x12804000` /
`0x12a04000` / `0x12c04000`. And that G3 pass writes zeros (see §1 output notes), so no G3
plaintext has ever been produced for a modem class. Conclusion: the G2 `cp.img` is decrypted
by whatever loads it on the G2 (boot chain / modem loader), not by the AP trusted application
on either product.

**Repeated in a full normal boot** (`ro.bootmode=normal`, `dji_glasses`/`media_server`/`wlm`/
`sdrs_agent` running), same build/slot/files: identical. All four G2 containers still fail
(`0xffff000a`; `share_info` returns a raw negative code that varied `-4` / `-14` between boots),
and the zero-fill outputs are **byte-identical** across boot modes — `wa520/cp.img` sha256
`07cb8155…`, `dsp` `ded7839a…`, boot `scp` 81,344 B all-zero. So boot mode is not a factor.

**Positive control in the same normal boot:** a genuine `ZV90` module (232,263,936 B, payload
digest valid, `-n 2805 -c 2805`) → verify pass, 232,263,298 B output, **99.6 % non-zero**,
`PK\x03\x04`, valid zip with 15 entries. The tool does emit plaintext for classes the TA
accepts; zeros are specific to modem/boot-chain classes.

**Payload-digest check matters:** all four G2 files and the G3's own images pass the header
`payload_digest` (SHA-256 of the payload), so they are intact and their rejection is genuine.
An earlier `0xfffffff3` on a 282 MB module was a **bad input** — that file was cut from a USB
bulk capture and fails its own payload digest. Verify the digest before blaming the TA.

**Engineering slot tested too.** Booted slot 1 (`00.08.14.05` / `3062`, Nov 2023) in normal
mode: same `dji_fw_verify` binary (`sha256 913b32cd…`), different TA (`libfw_util.so`,
log line numbers `:589` vs `:613`) and a 3-entry `/vendor` (`wa140`/`wa233`/`wa520`).
Results identical — all four pigeon files fail `0xffff000a`, every modem/boot-class pass is
**all-zero** (434,656 / 283,972 / 357,824 / 57,552 / 96,560 B), `l1c` fails, and the genuine
`ZV90` module produces the **same** 232,263,298-byte zip (`sha256 58527cf3…`). The engineering
top-level `cp.img` is single-chunk and passes; the retail one is two-chunk and fails —
consistent with the single-chunk rule, not with a TA capability difference.

Booting the engineering slot **switched the modem personality** to `wa520` (its
`multi_type_default`): `pigeon_current_type` went `za530_lite` → `wa520`, the active
`cp_nvram.bin` was replaced with `nvram_wa520`'s (sha256 `054d35ac…`), and the previous files
were saved as `*_bak.bin`. Retail `29020` on return does **not** switch back (both values are
in its 9-entry list, and `pair_auto_switch=0`), so plan a restore after any engineering-slot
boot (see `MODEM_LOAD_CHAIN.md`).

---

## 3. The `2CA3:0040` boot-time USB gadget is G2-only

A Goggles 2 briefly enumerates a second device at power-on: `2CA3:0040`, USB 1.1 full-speed,
`bcdDevice 0xffff`, no strings, one self-powered config (60 mA), single `FF/FF/00`
interface, bulk `0x81`/`0x01` MPS 64, answers `GET_DESCRIPTOR`, never `GET_STATUS`, gone
after ~4.7 s.

On the Goggles 3 it never appears:

- warm `adb reboot`: PnP polled every ~100 ms — devices gone 14.5 s, nothing in the gap;
- cold power-on (USB-C only): 34 s dead window, sampled throughout — nothing;
- the bootloader log (Unisoc LK) contains **no USB/gadget init at all**
  (mmc → ddr → rpmb → DTB → kernel), and charger boots print
  `charger bootmode, power off devices/IO`.

Android's gadget on the G3 is `2ca3:0020` (`0021` for the UVC modes), configured by
`/vendor/etc/init/init.e3t.usb.rc`. There is no `0x0040` in any G3 config.

To reproduce the capture on Windows, poll PnP during a cold boot:

```powershell
while ($true) {
  Get-CimInstance Win32_PnPEntity -Filter "DeviceID LIKE 'USB\\VID_2CA3%'" |
    Select-Object DeviceID, Name, Status
  Start-Sleep -Milliseconds 100
}
```

---

## 4. DUSS host ids map to processes (and the command pipe is iface 4)

DUSS slices the device into 16-bit host ids; each is an abstract unix socket
`@/duss/mb/<addr>`. Resolve them live:

```bash
adb shell 'cat /proc/net/unix | grep -i duss'      # addr -> socket inode
adb shell 'for p in /proc/[0-9]*; do pid=${p#/proc/}; \
  ls -l $p/fd 2>/dev/null | grep -oE "socket:\[(22676|12997)\]" | \
  while read s; do echo "$pid $(cat $p/comm) $s"; done; done'
```

Retail 29020, observed map:

| host | process | | host | process |
|---|---|---|---|---|
| `0x1b00` | `dji_network` | | `0x1c04` | `dji_sec` |
| `0x1b01` | `dji_sw_uav` | | `0x1c07` | `dji_media_server` |
| `0x1c00` | `dji_glasses` | | `0x1d02` | `dji_blackbox` |
| `0x1c01` | `dji_sys` (router) | | `0x1f00` | `dji_sys` |
| `0x0e04` | `dji_sdrs_agent` | | `0x0e07` | `dji_wlm` |
| `0x1704` | `dji_config_store` | | | |

### Sending a read-only DUML probe

Vendor interfaces on the G3 are **3–7** (bulk pairs `0x03/0x84` … `0x07/0x88`, class
`ff/43/01`, MPS 512); there is **no iface 1 / EP `0x01`/`0x81`** (that layout is G2-era).
`goggles_tool` can claim iface 4:

```python
from goggles_tool.usb.transport import UsbTransport
from goggles_tool.protocol import duss

t = UsbTransport(timeout_ms=1500)
t.open(interface=4)
t.write(duss.pack_duml(bytes([0x2A, 0x1B, 0x11, 0x27, 0x40, 0x00, 0x01])))  # 00/01 -> 0x1b
# reply: 552904c91b2a1127c0000100302e30302e31332e32322c2d3032343036303732313032353800003bef
t.close()
```

Reply payload is `\x00 "<version>,<stamp>" \x00\x00`; on retail 29020 that is
`0.00.13.22,-0240607210258`. On a Goggles 2 the same frame answers `0.00.09.29`.

**Gotcha that costs a false negative:** iface 4 is only a command pipe while `dji_sys` and
`dji_network` are running. A charger-mode boot does not start them, nothing reads the
FunctionFS endpoints, and bulk writes **time out** on every vendor interface. In that state
you can start them by hand:

```bash
adb shell 'setprop dji.sys_service 1; setprop dji.network_service 1'
adb shell 'start dji_sys; start dji_network'
# ... probe ...
adb shell 'stop dji_network; stop dji_sys'
```

---

## 5. What the `07`-class command does (engpc mode)

The DUML `cmd_set 0x07` family is not a direct "start adbd". `dji_network` implements
**engpc mode**: a one-byte payload selects `1 = start`, `0 = stop`, and the start path runs:

```
setenforce 0
setprop sys.usb.config none
setprop sys.usb.config rndis,mass_storage,bulk,acm
setprop sys.usb.config acm,adb          <- ADB comes up here
busybox killall -9 hciattach
rmmod sprdbt_tty
insmod /system/lib/modules/sprdbt_tty.ko
dji_engpc &
sync
```

It touches `sys.usb.config` (three transitions), SELinux enforcing (not persisted), the BT tty
stack, and forks `dji_engpc` (Spreadtrum ENGPC bridge over `/vendor/etc/engpc/{chnl,dev}`,
`AT+SPENGPC*`). It does **not** write `dji_config_store` and does not call `dji_sys`.

Build bracketing: `dji_network` retail 29020 = `0.00.13.22` (2024-06-07); engineering build
= `0.00.12.99` (2023-10-31). Both contain the identical handler. A Goggles 2 on
`0.00.09.29` (2022-05-24) silently drops `07/xx`, which matches.

Caveat: the command-id → handler mapping is **behavioural**, not proven from the binary — the
dispatch table is built at runtime in `.bss` (handler pointers arrive via
`R_AARCH64_RELATIVE`), and there is no literal `cmp #0x65` anywhere.

**Do not send `07/xx` on a unit you care about.** It mutates `sys.usb.config`, SELinux and the
BT stack. Only `00/01` was sent in this research.

---

## 6. Boot modes on the G3: normal vs charger only

- The bootloader (Unisoc LK) knows exactly two modes and picks one from charger registers
  (`hw: 0x40 … normal` vs `hw: 0x4/0x0 … Charger`). It passes `boot_mode:0|1` to the M7
  and always prints `mp_state:241`. No `cali` / `factorytest` / `autotest` / `dload`.
- `mp_state=factory` in `/proc/cmdline` is a static token (present on charger boots too).
- Userspace reads one switch: `/sys/devices/platform/soc/soc:bootmode/bootmode` (0/1).
  `product_config.sh` gates kernel modules and services on it — in charger mode only
  `dji.config_store`, `dji.blackbox_service_v2` and `dji.system_service` start
  (`"charger bootmode, do not start service"`).
- `dji_network` is a `disabled` service in `/init.rc`, started by
  `on property:dji.network_service=1`, which `product_config.sh` sets only in bootmode 0 —
  so the `0x1b00` path is structurally dead in charger mode.
- There is **no** `engpc` service in `/init.rc`, `/system/etc/init` or `/vendor/etc/init`;
  `dji_engpc` is only forked by the `dji_network` handler.
- "Factory"/"upgrade" scenes live in a binder `SysModeManagerService`
  (`libsysmode_util.so`); `sysmode_scene_set.sh` handles the `upgrade` scene and skips
  `*factory*` scenes in charger mode.

---

## 7. Practical takeaways

1. Before blaming a file, run the stock control (`wa520/cp.img`, or a genuine G3 module).
2. Parse the IM\*H header first: `type` + `auth_alg` + `enc_key` decide whether this TA can
   open it. `E3T` + `UFIE` is out of scope for a Goggles 3.
3. Goggle modules need `-c 2805`; modem images must **not** get `-c`.
4. `verify pass` with a zero-filled output is a known modem-path quirk; a real goggle module
   decrypts to a valid zip.
5. On the G3 there is no bootloader USB window — any factory-mode selection seen on older
   hardware is gone.
6. Charger mode is a cut-down system: no `dji_network`, no command pipe, no UI stack.
   Do USB protocol work on a normal boot, or start `dji_sys` + `dji_network` explicitly.
