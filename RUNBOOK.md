# Goggles 3 "display unit" -> retail firmware (keep root) — Reproduction Runbook

Goal: take a dev/"display unit" DJI Goggles 3 (E3T ZV902) and install the **latest
retail firmware** (currently **v01.00.1300**, build 29020, Mar 2026) **without losing
root/ADB**, by writing reconstructed retail images to the **inactive A/B slot**. The
bootloader (eMMC boot area) is never touched.

This kit is **reference-only**: it points at images/scripts in this workspace and gives
the exact steps + helper scripts to repeat the procedure on a second physical unit.

---

## Slot policy (read this first)

**Always keep the original shipped engineering OS on slot 1. Never flash slot 1.**

| Slot | Role | Contents (donor unit) |
|---|---|---|
| **Slot 1** | **Permanent dev fallback** — boot here before any upgrade work | Engineering build **9998** (Nov 2023, rooted, 3 air units) |
| **Slot 2** | **Retail target** — overwrite freely on each upgrade | Currently **v01.00.1300** / build **29020** |

Why this matters: the flash scripts target whichever slot is **inactive**. If you run
them while booted on slot 2 (retail), they will target slot 1 and **destroy the
engineering fallback**. The v1300 flash script refuses this unless you pass an explicit
override flag.

**Canonical upgrade workflow:**

```
1. Boot slot 1 (engineering)     set_active_slot.ps1 -Slot 1 -Execute -Reboot
2. Dry-run flash to slot 2       flash_retail_v01_00_1300_to_inactive_slot.ps1
3. Execute flash to slot 2       flash_retail_v01_00_1300_to_inactive_slot.ps1 -Execute
4. Reboot into retail (optional) adb reboot   (or flip back to slot 1 first; see §4)
5. Post-flash fix-ups if needed  post_flash_fixups.ps1 -DoHms -Execute  (IMU-missing only)
```

To return to dev firmware at any time:

```powershell
.\repro_kit\set_active_slot.ps1 -Slot 1 -Execute -Reboot
```

---

## 0. Preconditions (verify on the NEW unit first)

- [ ] ADB online and **root**: `adb shell id` shows `uid=0`. Locked retail units STOP here.
- [ ] **E3T / ZV902**: `adb shell getprop ro.product.device` -> `e3t_zv902`.
- [ ] A/B slots present: `adb shell ls /dev/block/by-name/ | grep -E 'system(_2)?'`.
- [ ] `unrd` exists: `adb shell which unrd`.
- [ ] **Identify which slot holds engineering** (usually slot 1, incr **9998**):
      mount each slot read-only or check `unrd` + `getprop ro.build.version.incremental`
      while booted on each slot. **Label it "do not flash".**
- [ ] Free space on `/blackbox` for staging the 654 MB system image:
      `adb shell df -h /blackbox` — clear old logs if needed.
- [ ] **Per-unit safety snapshot** before any write (see §6).

> Safety: nothing is irreversible until you flip the active slot AND reboot. All writes
> go to the **inactive** slot only; the booted slot's partitions are never touched.

---

## 1. Have the payload ready

### v01.00.1300 (current — Avata 360 / 9 air units)

Prebuilt images: `E:\dji_g3\fw_patch\images_1300\`

Source OTA: decrypt from DJI Assistant `firm_cache`:
`1ed19cd27422aeccc8f73ce81f66498d.cache` (282 MB, `v10.00.59.40`, 2026-03-25).
Decrypted copy: `fw_patch/retail_ota_1300/ota.zip`.

```powershell
# On-device decrypt (if rebuilding from firm_cache):
adb push "<firm_cache>\1ed19cd27422aeccc8f73ce81f66498d.cache" /data/e3t_1300.fw.sig
adb shell "dji_fw_verify -n 2805 -c 2805 -o /blackbox/ota_1300.zip /data/e3t_1300.fw.sig"
adb pull /blackbox/ota_1300.zip fw_patch/retail_ota_1300/ota.zip

# Rebuild images:
pip install brotli
python fw_patch/build_images.py fw_patch/retail_ota_1300/ota.zip fw_patch/images_1300
```

See `MANIFEST.md` for SHA1 table and `unrd` descriptors.

### v01.00.1000 (older — 8 air units, superseded)

Images: `fw_patch/images/`. Script: `flash_retail_to_inactive_slot.ps1`.
Same procedure; use only if you specifically need the older retail build.

---

## 2. Boot engineering OS before flashing (mandatory)

```powershell
powershell -ExecutionPolicy Bypass -File E:\dji_g3\repro_kit\set_active_slot.ps1 -Slot 1 -Execute -Reboot
```

Wait for ADB, then confirm:

```powershell
adb shell getprop ro.boot.slot_suffix          # 1
adb shell getprop ro.build.version.incremental # 9998 (engineering)
adb shell id                                   # uid=0
```

**Do not proceed to §3 until slot_suffix=1.**

---

## 3. Flash retail to slot 2 (dry-run, then execute)

```powershell
# dry-run — must show: active=1, INACTIVE slot=2, writing to *_2 partitions
powershell -ExecutionPolicy Bypass -File E:\dji_g3\repro_kit\flash_retail_v01_00_1300_to_inactive_slot.ps1

# execute — writes + verifies readback + sets descriptors + flips active to slot 2
powershell -ExecutionPolicy Bypass -File E:\dji_g3\repro_kit\flash_retail_v01_00_1300_to_inactive_slot.ps1 -Execute
```

Override paths if needed: `-Adb <path>` `-ImagesDir <path>`.

What it does:
1. Confirms root + slot; **refuses to target slot 1** without `-IAcceptOverwriteSlot1`.
2. Writes `scp_2/tos_2/normal_2/vendor_2/system_2`, verifying each readback SHA1.
3. Sets slot_2 `system_new_*` / `system_zero_*` descriptors (v1300 values).
4. Flips `status_active`: slot_1=0, slot_2=1. Both stay bootable.

If readback mismatches, the script aborts **before** any slot switch.

---

## 4. Reboot — choose default boot slot

After §3, slot 2 is marked active. You are still running engineering firmware in RAM
until reboot.

**Boot into retail v1300 now:**

```powershell
adb reboot
```

**Or keep engineering as default boot** (retail staged but not active):

```powershell
powershell -ExecutionPolicy Bypass -File E:\dji_g3\repro_kit\set_active_slot.ps1 -Slot 1 -Execute
adb reboot
```

Switch to retail later: `set_active_slot.ps1 -Slot 2 -Execute -Reboot`.

### Verify after booting slot 2 (v1300)

```powershell
adb shell getprop ro.boot.slot_suffix          # 2
adb shell getprop ro.build.version.incremental # 29020
adb shell getprop ro.dji.build.version         # 10.00.59.40
adb shell id                                   # uid=0 -> root survived
adb shell "grep drone_name /system/etc/dji.json"   # 9 entries incl. wa530 (Avata 360)
```

If retail fails to boot: revert without reflashing — boot slot 1 if still possible, or:

```powershell
adb shell "unrd -s slot_1.status_active 1; unrd -s slot_2.status_active 0"
adb reboot
```

---

## 5. (Optional) IMU-missing fix-ups

Skip on a unit with a working IMU. On the donor (IMU module physically absent):

- OOBE stuck on "passthrough goggles" -> `post_flash_fixups.ps1 -DoOobe -Execute`
- HMS capsule `HSM0x1b200003` -> `post_flash_fixups.ps1 -DoHms -Execute`

Re-apply HMS suppression after **every** retail slot re-flash (lives in `/system`, not
`/data`). User confirmed capsule gone + **Avata 360** visible in bind list on v1300.

```powershell
powershell -ExecutionPolicy Bypass -File E:\dji_g3\repro_kit\post_flash_fixups.ps1 -DoHms -Execute
adb reboot
```

---

## 6. Per-unit safety snapshot (before §3 on a new unit)

```powershell
$ts = Get-Date -Format yyyyMMddHHmmss
adb shell "unrd" > "newunit_unrd_$ts.txt"
adb pull /dev/block/by-name/env "newunit_env_$ts.bin"
adb shell "getprop" > "newunit_getprop_$ts.txt"
```

Optional: full eMMC image (`dump_full_emmc.ps1`) before the first slot switch.

---

## 7. Done — what you should have (donor unit, 2026-06-16)

- **Slot 1**: engineering 9998, permanent fallback, never overwritten.
- **Slot 2**: retail **v01.00.1300** (29020), root + ADB intact.
- **9 air units** in `dji.json`: wa520/wa233/wa140 + wm1695/wa521/za530_lite/
  za530_pro/wa020/**wa530** (Avata 360 — confirmed in UI bind list).
- IMU capsule suppressed on slot 2; OOBE bypass in `/data` (if applicable).

---

## Notes / caveats

- `unrd` descriptors are bound to a specific `system_2.img` SHA1. Each retail OTA
  needs its own flash script (or updated descriptor block). The v1300 script guards
  against `4015aa68…`; the v1000 script guards against `cdd4395f…`.
- `bootarea.img` is never flashed (hard-brick risk). Donor booted retail fine without it.
- On-screen firmware version (`00.04.02.02` / module `00.08.12.17`) may stay stale —
  `/data/upgrade/device_info.json` is not refreshed by manual dd. Air-unit binding still
  works from retail `dji.json` + Sparrow2 blobs.
- Future retail upgrades: repeat §2–§5. Always boot engineering (slot 1) first.
