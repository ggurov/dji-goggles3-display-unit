# DJI Goggles 3 "Display Unit" — Retail Firmware Upgrade Kit

Upgrade a **rooted engineering / "display unit"** DJI Goggles 3 to the **latest retail
firmware** while **keeping root and ADB**, and while **preserving the original
engineering OS** as a permanent fallback.

Tested successfully on hardware labeled **TKGS3 / E3T ZV902** (June 2026):

| Before | After |
|---|---|
| Engineering firmware, build **9998** | Retail **v01.00.1300**, build **29020** (Mar 2026) |
| 3 supported air units (Avata 2, Air 3, Mini 4 Pro) | **9** air units incl. O4 family, Neo, O3, **Avata 360** |
| Root + ADB | Root + ADB **still works** |

This repository contains the **PowerShell automation and documentation** used to perform
the upgrade. It does **not** include the large firmware image files (~840 MB) or DJI
copyrighted binaries — you obtain those yourself from DJI Assistant 2.

---

## What we learned (short version)

1. **Air-unit compatibility is firmware-driven.** Retail firmware carries a
   `multi_type_compatibility` table in `/system/etc/dji.json` plus Sparrow2 modem
   payloads under `/vendor/modem_firmware/sparrow2/`. Flashing retail firmware is what
   unlocks newer drones — not a simple config edit.

2. **Retail Goggles 3 firmware is also `userdebug` / `test-keys`.** Despite being
   "retail" product firmware, the build is not locked down the way a phone would be.
   **Root and USB debugging survive the flash.**

3. **DJI Assistant 2 cannot complete the OTA on these units.** The in-app upgrade path
   fails because `/cache` (232 MB) is too small for the ~271–282 MB firmware package,
   and bind mounts are disabled on the kernel. We bypass Assistant entirely by manually
   `dd`-ing reconstructed partition images to the **inactive A/B slot**.

4. **A/B slots are the safety net.** The device has two full firmware slots (`system` /
   `system_2`, etc.). We **never touch slot 1** (original engineering OS). All retail
   images go to slot 2. If retail fails to boot, flip back with one `unrd` command.

5. **Bootloader is not updated.** We deliberately do **not** flash `bootarea.img`
   (eMMC boot area). The engineering bootloader boots retail fine (same test-keys family).

6. **On-screen firmware version can lie.** After a manual flash, the goggles may still
   display the old engineering version string (`00.04.02.02`). That comes from a stale
   `/data/upgrade/device_info.json` cache. The **bind list and actual air-unit support
   reflect the real flashed firmware.**

7. **Mid-flight video blackout (display units, Jun 2026).** Some units hit ~2–3 s screen
   blackouts caused by `dji_media_server` crashing in an ION DMA thread — not RF loss.
   **Delayed hygiene** that stops non-FPV services (including **`dji_gfsk_agent`**) after
   boot, plus a **cold reboot before flying**, is a working mitigation. First validated
   field flight: **46 min, video perfect** (flight0579, 2026-06-21). See
   [`DONOR_HYGIENE.md`](DONOR_HYGIENE.md).

---

## What you need

### Hardware

- DJI Goggles 3 labeled as a **"display unit"** / engineering build (not a locked
  consumer retail unit).
- USB connection to a Windows PC.
- The unit must already have **root ADB** (`adb shell id` → `uid=0`). If yours is a
  locked retail pair, this procedure does not apply.

### Software (host PC)

- **Windows** with PowerShell 5+
- **Android platform-tools** (`adb`) on your PATH or passed via `-Adb`
- **DJI Assistant 2 (Consumer Drones Series)** — to download the signed firmware package
- **Python 3** + `pip install brotli` — only if you need to rebuild flash images from
  the decrypted OTA zip
- **Python 3.10+** + `pip install -e goggles_tool` — for retail bulk log export
  ([`log_export/README.md`](log_export/README.md)); requires DJI Assistant installed
  (libusb0 DLL) and optional Android NDK for decrypt harness

### Materials NOT in this repository

You must obtain and prepare these locally:

| Item | How to get it | Size |
|---|---|---|
| Signed firmware package (IM\*H) | DJI Assistant 2 → downloads to `firm_cache\` while checking for updates | ~282 MB for v01.00.1300 |
| Flashable partition images | Decrypt on-device, pull `ota.zip`, run `build_images.py` (see below) | ~840 MB total |
| Python fix-up scripts (optional) | `add_novice_guidance.py`, `remove_hms_entry.py` — needed only for IMU-missing units | tiny |

**v01.00.1300** firm_cache file (as of Jun 2026):

```
DJI Assistant 2\DJIEngine\DJIData\firm_cache\1ed19cd27422aeccc8f73ce81f66498d.cache
```

Internal name: `zv902_2805_v10.00.59.40_20260325.ar0.pro.fw.sig` (282,358,176 bytes).

---

## Repository contents

| File | Purpose |
|---|---|
| [`RUNBOOK.md`](RUNBOOK.md) | Detailed step-by-step procedure |
| [`MANIFEST.md`](MANIFEST.md) | Image SHA1 table, `unrd` descriptor values, rebuild instructions |
| [`DONOR_HYGIENE.md`](DONOR_HYGIENE.md) | RAM/GFSK shutdown + video blackout findings (optional, post-flash) |
| [`AGENTS.md`](AGENTS.md) | Full technical brief for developers / AI agents |
| `set_active_slot.ps1` | Switch which A/B slot boots (via `unrd`) |
| `flash_retail_v01_00_1300_to_inactive_slot.ps1` | Flash **v01.00.1300** to the inactive slot |
| `flash_retail_to_inactive_slot.ps1` | Flash **v01.00.1000** (older; superseded) |
| `post_flash_fixups.ps1` | Optional OOBE + sensor-error fixes for IMU-missing units |
| `install_donor_rc_local.ps1` | Install delayed RAM/GFSK hygiene hook |
| `donor_rc.local` | Hygiene policy (installed to `/data/local/donor/rc.local`) |
| `donor_boot_hook.sh` | Init wrapper for rc.local |
| `dji_donor_hygiene.rc` | Init trigger on `dji.camera_service=1` |
| [`log_export/`](log_export/) | **Retail bulk log pull + LOGH decrypt** (see below) |
| [`goggles_tool/`](goggles_tool/) | USB bulk CLI (`pip install -e goggles_tool`) |

---

## Log export & decrypt (retail unit, no ADB)

Pull blackbox logs from a **retail** Goggles 3 over USB bulk (same path as DJI Assistant),
decrypt **LOGH** ciphertext on a **rooted engineering donor** via `liblog_util.so`.

| Topic | Doc |
|-------|-----|
| Quick start | [`log_export/README.md`](log_export/README.md) |
| LOGH / encryption | [`log_export/LOG_ENCRYPTION.md`](log_export/LOG_ENCRYPTION.md) |
| Bulk USB protocol | [`log_export/BULK_PROTOCOL.md`](log_export/BULK_PROTOCOL.md) |

```powershell
pip install -e goggles_tool
python log_export\pull_log_index.py --list
python log_export\pull_log_index.py --flight 235 --no-decrypt
python log_export\batch_decrypt.py bulk log_export\output\pull_*\files
```

**Findings:** Logs are plaintext on eMMC; retail bulk export wraps them in **LOGH + AES**.
Engineering donors skip encryption (`secure_debug=1`). Decrypt uses an NDK harness
(`log_export/logutil_decrypt/`) calling `log_decrypt_fragment` on the donor — no
standalone decrypt binary exists on-device.

---

## Quick start

### Slot policy (read before you flash anything)

```
Slot 1  =  original engineering OS  →  NEVER flash this
Slot 2  =  retail target            →  overwrite on each upgrade
```

**Always boot slot 1 (engineering) before running a flash script.** The scripts write to
whichever slot is *inactive*. If you run them while booted on retail, they will target
slot 1 and destroy your engineering fallback. The v1300 script blocks this by default.

### 1. Verify preconditions

```powershell
adb shell id                              # must show uid=0
adb shell getprop ro.product.device       # e3t_zv902
adb shell getprop ro.build.version.incremental   # 9998 on engineering slot
adb shell which unrd                      # must exist
adb shell df -h /blackbox                 # need ~700 MB free
```

### 2. Prepare firmware images

Decrypt the signed package on the goggles (root required), pull the OTA zip, rebuild
images. You need a `build_images.py` script (see `MANIFEST.md` for the algorithm) or
pre-built images with the SHA1 values listed there.

```powershell
# Push signed package from DJI Assistant firm_cache
adb push "path\to\1ed19cd27422aeccc8f73ce81f66498d.cache" /data/e3t_1300.fw.sig

# Decrypt on-device (uses built-in dji_fw_verify)
adb shell "dji_fw_verify -n 2805 -c 2805 -o /blackbox/ota_1300.zip /data/e3t_1300.fw.sig"

# Pull and rebuild (on host)
adb pull /blackbox/ota_1300.zip .\retail_ota_1300\ota.zip
pip install brotli
python build_images.py .\retail_ota_1300\ota.zip .\images_1300
```

Place the resulting `images_1300\` folder somewhere on your PC (e.g. next to these
scripts).

### 3. Boot engineering firmware

```powershell
.\set_active_slot.ps1 -Slot 1 -Execute -Reboot
# wait for reboot; confirm: adb shell getprop ro.boot.slot_suffix  →  1
```

### 4. Flash retail to slot 2

```powershell
# Dry-run first (prints plan, writes nothing)
.\flash_retail_v01_00_1300_to_inactive_slot.ps1 -ImagesDir .\images_1300 -Adb adb

# Execute (writes all partitions, verifies readback SHA1, flips active slot)
.\flash_retail_v01_00_1300_to_inactive_slot.ps1 -ImagesDir .\images_1300 -Adb adb -Execute
```

### 5. Reboot into retail

```powershell
adb reboot
# verify:
adb shell getprop ro.boot.slot_suffix              # 2
adb shell getprop ro.build.version.incremental     # 29020
adb shell id                                       # uid=0  (root survived)
```

### 6. Optional fix-ups (IMU-missing units only)

Some display units ship without the internal IMU/motion module. Symptoms:

- OOBE stuck on "passthrough goggles" screen
- On-screen "goggles sensor system error (HSM0x1b200003)" capsule

Skip this section if your unit has a working IMU.

```powershell
.\post_flash_fixups.ps1 -DoHms -Execute -Tools .\tools -Adb adb
adb reboot
```

Requires `remove_hms_entry.py` and (for OOBE) `add_novice_guidance.py` in the
`-Tools` directory.

### 7. Optional FPV hygiene + GFSK shutdown (IMU-less display units)

If you use the goggles for **field FPV** and see occasional ~2–3 s video blackouts,
install the delayed hygiene hook. It stops non-essential services (including
`dji_gfsk_agent`) 30 s after boot to reduce `dji_media_server` crash risk. Liveview
keeps working; expect harmless `GfskManager` log noise.

```powershell
.\install_donor_rc_local.ps1 -Execute -Reboot
```

Full rationale, post-flight checks, and flight0579 validation:
[`DONOR_HYGIENE.md`](DONOR_HYGIENE.md).

### Revert to engineering firmware any time

```powershell
.\set_active_slot.ps1 -Slot 1 -Execute -Reboot
```

---

## Expected result

After a successful v01.00.1300 flash you should have:

- **9 bindable air units** in the goggles menu, including **Avata 360**
- **Root ADB** still available (`adb shell` as uid=0)
- **Slot 1** untouched — original engineering build 9998, one reboot away
- Firmware version on-screen may still show the old engineering string; trust the bind
  list and `getprop ro.build.version.incremental` (29020) instead

---

## Safety rules

| Do | Don't |
|---|---|
| Write only to the **inactive** slot | Flash `bootarea` (bootloader = hard-brick risk) |
| Boot engineering (slot 1) before upgrading | Run flash scripts while booted on retail |
| Dry-run every flash script first | Write to `env`, `gpt`, or `boot0`/`boot1` partitions |
| Verify readback SHA1 before slot switch | Use DJI Assistant's in-app upgrade (it will fail on /cache size) |
| Keep both slots bootable | Publish device serials, keys, or unredacted dumps |

If retail fails to boot after a slot switch, the engineering slot should still work:

```powershell
adb shell "unrd -s slot_1.status_active 1; unrd -s slot_2.status_active 0"
adb reboot
```

---

## Firmware versions reference

| Product version | Build | Released | Notable addition |
|---|---|---|---|
| (engineering) | 9998 | Nov 2023 | 3 air units; original display-unit OS |
| 01.00.1000 | 24626 | Oct 2025 | Neo 2; 8 air units |
| **01.00.1300** | **29020** | **Mar 2026** | **Avata 360; 9 air units** |

DJI Assistant stores a plaintext version manifest at:

```
firm_cache\95714dcbe1a9f75ee8dde5f84fbe27eb.cache
```

---

## Further reading

- **[RUNBOOK.md](RUNBOOK.md)** — complete procedure with per-unit safety snapshots
- **[MANIFEST.md](MANIFEST.md)** — SHA1 hashes, `unrd` slot descriptors, rebuild commands
- **[DONOR_HYGIENE.md](DONOR_HYGIENE.md)** — optional RAM/GFSK shutdown, video blackout
  mitigation, post-flight checklist
- **[log_export/README.md](log_export/README.md)** — retail bulk log pull + LOGH decrypt
- **[log_export/LOG_ENCRYPTION.md](log_export/LOG_ENCRYPTION.md)** — encryption pipeline
- **[AGENTS.md](AGENTS.md)** — deep technical reference (boot architecture, component
  model, open research questions)

---

## Disclaimer

This is independent research on hardware you own. It is not affiliated with or endorsed
by DJI. Firmware files are DJI copyrighted material — obtain them through DJI Assistant
for your own devices only. Flashing firmware carries brick risk; follow the slot policy
and keep your engineering fallback slot intact. You are responsible for your own hardware.
