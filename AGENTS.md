# DJI Goggles 3 ("Display Unit") Multi-Drone Compatibility — Agent Brief

This file is the entry point for an agentic coding agent continuing this research.
It summarizes what exists, what is known, what the next steps are, and the hard
safety constraints. Read this file and `AI_SEED.txt` before acting.

> Source of truth for raw findings: `AI_SEED.txt` (original seed) +
> `docs/findings.md` (live, kept up to date) + `docs/activity-log.md` (chronological).
> This file adds structure, file/path index, and a prioritized work plan.

---

## 0. Status banner (2026-06-21) — Phase 1+ complete; dual-slot retail + FPV hygiene

Phase 1 goal (expand air-unit support beyond `wa520/wa233/wa140`) achieved via **manual
retail A/B-slot flashes while keeping root**. Donor unit runs **v01.00.1300**
(build **29020**, Mar 2026) on **slot 2** with **9** air units incl. **Avata 360**
(`wa530`). **Slot 1** permanently holds the original engineering build **9998** as
the always-bootable dev fallback — never overwritten.

**FPV hygiene (2026-06-20+):** delayed shutdown of non-FPV services incl.
**`dji_gfsk_agent`** via `/data/local/donor/rc.local` — mitigates `dji_media_server`
iondma blackouts. **flight0579 (2026-06-21):** ~46 min field flight, video perfect.
See `DONOR_HYGIENE.md`.

**Canonical upgrade policy (shareable):** boot slot 1 (engineering) → flash inactive
slot 2 with latest retail → reboot into slot 2 when ready. Repeat for future OTAs.
See `RUNBOOK.md` §"Slot policy".

Current donor state:
- Slot 2 active: retail v01.00.1300, `ro.dji.build.version=10.00.59.40`, root+ADB.
- Slot 1 fallback: engineering 9998, bootable, untouched.
- IMU capsule suppressed on slot 2; user confirmed Avata 360 in bind list + no capsule.
- `/data` persisted across all slot switches (`novice_guidance=1` OOBE bypass).
- Hygiene: camera3/upgrade/ftpd/amt/agent/arhome/**gfsk_agent** stopped @ t≈35 s.

Kit in this repo: `RUNBOOK.md`, `DONOR_HYGIENE.md`, `set_active_slot.ps1`,
`flash_retail_v01_00_1300_to_inactive_slot.ps1`, `post_flash_fixups.ps1`,
`install_donor_rc_local.ps1`, `MANIFEST.md`, `log_export/` (retail bulk pull +
LOGH decrypt), `goggles_tool/` (USB bulk CLI).

**Log export (2026-06):** Retail bulk → LOGH ciphertext; donor bulk → plaintext
(`secure_debug=1`). Decrypt via NDK harness + `liblog_util.so` on donor. See
`log_export/LOG_ENCRYPTION.md`, `log_export/BULK_PROTOCOL.md`.

Phase 2 (open): add air units beyond retail via modem personality reverse; retail unit
(no ADB) passive analysis only.

---

## 1. Objective

Make a DJI Goggles 3 unit (physically labeled "display unit", internally an
engineering/dev build) pair with and display more drones / air units than its
current firmware exposes.

The compatibility gate is a **modem "personality" table** (Sparrow2/pigeon) plus
the link/pairing stack. The goal is to understand the exact code-driven switch
path well enough to safely extend the supported set, with a tested recovery path.

### Non-goals / hard constraints (do not violate)
- Do **not** write to live eMMC (`/dev/block/mmcblk0`) from the running OS.
- Do **not** manually edit `pigeon_current_type` or hand-copy modem firmware/NVRAM
  until the exact code switch path and a tested restore path are understood.
- Do **not** brute-force FTP or any credentials.
- Do **not** publish unredacted dumps/logs (they contain serials, keys, GNSS, certs).
- Prefer **read-only / passive** investigation first. No flashing without recovery.
- **A/B slot writes are allowed only against the INACTIVE slot**, with readback-SHA1
  verification before any slot switch (the active slot must remain bootable as
  fallback). Never write `bootarea` (eMMC boot area = bootloader) — that's the one
  hard-brick path.
- Never write to `env`, `gpt`, or `boot0`/`boot1` partitions. Slot state changes
  go through `unrd` (`/system/bin/unrd`), which is the supported key/value API
  over the env partition.

---

## 2. Two physical units under study

| Aspect | Dev / engineering unit (post-flash) | Retail unit |
|---|---|---|
| Marking / platform | TKGS3 / E3T ZV902 | same USB family |
| Currently boots | **slot 2 = RETAIL v01.00.1300 / build 29020** (Mar 2026) | retail (locked) |
| Fallback slot | slot 1 = engineering build **9998** (original rooted donor; **never flash**) | n/a |
| Build flags | still `userdebug`, `test-keys`, `ro.debuggable=1`, permissive — retail is also userdebug/test-keys (root + ADB survive the flash) | locked |
| ADB | root ADB over USB still available | **no ADB** (5555 refused), no fastboot |
| Air units exposed | **9** (wa520/wa233/wa140 + wm1695/wa521/za530_lite/za530_pro/wa020/**wa530** Avata 360) | retail set |
| IMU / motion module | physically **missing** -> OOBE blocks at "passthrough", HMS `0x1B200003` capsule (both currently suppressed) | present (assumed) |
| `/data` (userdata) | preserved across the slot switch; carries `novice_guidance=1` OOBE bypass | n/a |
| USB VID:PID | 2CA3:0020 | 2CA3:0020 |
| USB interfaces | rndis, mass_storage, bulk, acm, adb | rndis (MI_00), mass_storage (MI_02), vendor/libusb (MI_03–07); no adb |
| RNDIS IP | goggles `192.168.60.2`, host `192.168.60.1` | same; goggles gives no DHCP (host must set `192.168.60.1/24`) |
| FTP (port 21) | `dji_ftpd`, banner `220 Hello!` | open, banner `220 Hello!`, login required (anon denied) |

The dev unit is the **research donor** and is now the demonstration of the
keep-root retail flash. Slot 1 (engineering 9998) is preserved untouched as a
fallback. The retail unit remains a passive analysis target.

**Pre-flash dev state (historical, preserved in dumps):** engineering build 9998,
slot 1, `pigeon_current_type=wa520`, only 3 air units (wa520/wa233/wa140), full
eMMC backup at `full_emmc_backup/goggles3_emmc_20260614_061942/mmcblk0_full.img`
(7,818,182,656 bytes; SHA256 `95438C51…3BE5E7E6`).

---

## 3. Core mechanism (most important finding)

Compatibility lives in `/system/etc/dji.json` under `multi_type_compatibility`
(see `binding_research/etc/system_etc/dji.json:2405`).

```json
"multi_type_compatibility": {
  "status": 1,
  "switch_ap_mask": 0,
  "pair_auto_switch": 0,
  "firmware_path": {
    "multi_default":  "/vendor/modem_firmware/sparrow2/",
    "nvram_default":  "/cali/sdr/nvram/",
    "multi_firware":  "/vendor/modem_firmware/sparrow2/",
    "nvram_firmware": "/cali/sdr/nvram/"
  },
  "multi_type_list": {
    "multi_type_default": "wa520",
    "support_type": [
      {"drone_type": 94, "sdr_id": 34817, "drone_name": "wa520", "firmware_fold": "wa520", "nvram_fold": "nvram_wa520"},
      {"drone_type": 90, "sdr_id": 32769, "drone_name": "wa233", "firmware_fold": "wa233", "nvram_fold": "nvram_wa233"},
      {"drone_type": 93, "sdr_id": 34305, "drone_name": "wa140", "firmware_fold": "wa140", "nvram_fold": "nvram_wa140"}
    ]
  }
}
```

Mapping (**engineering 9998 / slot 1 — historical**):

| drone_name | drone_type | sdr_id (hex) | firmware_fold | nvram_fold |
|---|---|---|---|---|
| wa520 | 94 | 0x8801 | wa520 | nvram_wa520 |
| wa233 | 90 | 0x8001 | wa233 | nvram_wa233 |
| wa140 | 93 | 0x8601 | wa140 | nvram_wa140 |

Mapping (**retail v01.00.1300 / slot 2 — current live state**, 9 entries):

| drone_name | drone_type | sdr_id (dec / hex) | known model |
|---|---|---|---|
| wa520 | 94 | 34817 / 0x8801 | DJI Avata 2 |
| wa233 | 90 | 32769 / 0x8001 | DJI Air 3 |
| wa140 | 93 | 34305 / 0x8601 | DJI Mini 4 Pro |
| wm1695 | 80 | 10280 / 0x2828 | (WM line) |
| wa521 | 104 | 42497 / 0xa601 | O4 family |
| za530_lite | 113 | 48641 / 0xbe01 | |
| za530_pro | 114 | 48129 / 0xbc01 | |
| wa020 | 124 | 158 / 0x009e | O3-class |
| **wa530** | **127** | **159** / 0x009f | **DJI Avata 360** [CONFIRMED in UI bind list, 2026-06-16] |

(Historical: v01.00.1000 / build 24626 had 8 entries — same table minus `wa530`.)

Active NVRAM currently only contains `nvram_wa520`; switching to a different
`drone_name` requires `dji_sdrs_agent` to copy the matching firmware folder +
NVRAM into place — that switch path is **still un-reversed** (Phase 2).

### The switch is code-driven, not file-driven
`dji_sdrs_agent` strings indicate the personality switch is done by functions, not
manual edits:
`sa_update_multi_drone_type`, `sa_switch_multi_firmware`,
`sa_copy_fw_to_pigeon_default`, `sa_copy_nvram_to_cali_default`,
`sa_check_nvram_integrity`, `sa_reset_modem`,
`multi_current_drone_type`, `pigeon_current_type`, `pair_auto_switch`.

`pair_auto_switch = 0` ⇒ it likely does not auto-switch personality during pairing.

### Related dji.json facts
- NVRAM file set (vendor/original/backup) is enumerated around `dji.json:2397–2403`:
  `rf_nvram.bin`, `amt.bin`, `pwr.bin` (`need_check:false`), `share_info.bin`.
  `sa_check_nvram_integrity` likely validates these.
- A vendor **bulk** channel is defined (`dji.json:2430`):
  `/bulk/s2_da`, `vid 2CA3`, `pid 1020`, `interface 7`, `ep_in 88`, `ep_out 08`
  — candidate for how DJI Assistant talks to the modem/SDR.
- `product_type` is `e3t_zv902` / `ZV902`; `product_line_type: consumer`;
  `module_need_time_sync` references hosts `pigeon` (host 14), `wm169` (host 8),
  `remote_control` (host 13).

---

## 4. Component model (who does what)

```
dji_glasses     UI / product-mode selection, liveview
dji_sys         system-level product/device state machine
dji_sdrs_agent  *** SDR / Sparrow2 / pigeon personality switching ***  <- primary target
dji_wlm         wireless link manager: routing, link modes, RNDIS/bulk/liveview paths
dji_gfsk_agent  GFSK control-side pairing/control path
dji_sw_uav      UAV-side software type handling
dji_ftpd        FTP server over RNDIS (blackbox/export/upgrade staging)
dji_upgrade     platform upgrade modules (not necessarily aircraft compatibility)
```

Product/modem resolution chain:
```
UI product/mode selection
  -> internal product type -> drone_type -> sdr_id
  -> dji_sdrs_agent switch path
  -> Sparrow2/pigeon firmware folder + active NVRAM
  -> /cali/sdr/nvram/pigeon_current_type
```

---

## 5. Key files & paths

### On-device (dev unit), pulled into this workspace
- Binaries: `/system/bin/{dji_glasses,dji_sys,dji_sdrs_agent,dji_gfsk_agent,dji_wlm,dji_sw_uav,dji_upgrade,dji_ftpd}`
- Configs: `/system/etc/{dji.json,device_table.json,gfsk_agent_cfg.json,glass.json,upgrade.json,wlm_cfg.json}`
- USB init: `/vendor/etc/init/init.e3t.usb.rc`
- Modem fw: `/vendor/modem_firmware/sparrow2/{wa140,wa233,wa520,*.bin}`
- NVRAM: `/cali/sdr/nvram/{pigeon_current_type,nvram_wa520,rf_nvram.bin,amt.bin,pwr.bin,share_info.bin,...}`
- FTP config (to retrieve next): `/etc/ftp.conf`

### Workspace layout (`E:\dji_g3`)

**Active / canonical (read these first):**
```
AGENTS.md                           this file (entry point)
AI_SEED.txt                         original raw research notes
docs/                               LIVE knowledge base (kept current)
    README.md                       conventions
    findings.md                     consolidated [CONFIRMED]/[INFERRED]/[OPEN] facts
    activity-log.md                 chronological ledger of every action
    recovery_boot_architecture.md   A/B slots, no Android recovery, Unisoc download mode
    hms_error_1b200003.md           sensor-capsule analysis + suppression
    upgrade_investigation.md        DJI Assistant 2 stall analysis
    custom_display_research.md      test_disp / display planes (Milestone 1 done)

repro_kit/                          REPRODUCTION KIT for second physical unit
    RUNBOOK.md                      step-by-step; **slot-1-first upgrade policy**
    set_active_slot.ps1             flip active A/B slot via unrd
    flash_retail_v01_00_1300_to_inactive_slot.ps1   v01.00.1300 flasher (current)
    flash_retail_to_inactive_slot.ps1               v01.00.1000 flasher (older)
    post_flash_fixups.ps1           OOBE + HMS fix-ups (only if IMU absent)
    MANIFEST.md                     payload SHA1 table, descriptor values
```

**Reproduction payloads (referenced by repro_kit/, not copied):**
```
fw_patch/
    images/                         v01.00.1000 flashable images (superseded)
    images_1300/                    v01.00.1300 flashable images (current)
    retail_ota_1300/ota.zip         decrypted v1300 OTA source
    build_images.py                 brotli + sdat2img v4 -> system_2/vendor_2 from ota.zip
    verify_imgs.py                  SHA1 check against expected
    decrypt_e3t_ota.sh              dji_fw_verify-driven IM*H -> ota.zip on-device

post_reset_tools/
    add_novice_guidance.py          OOBE unblock helper
    remove_hms_entry.py             HMS list line remover
    extract_data_from_image.py      offline /data extraction from eMMC image
    extract_bins_from_image.py      offline /system bin extraction
    find_lib_with.py, search_hms.py, hms_keys_and_map.py, dump_sqlite.py, xref_dump.py
    COMPARISON_REPORT.md            pre/post factory-reset diff
```

**Reference dumps + analysis (do NOT carry to a new unit):**
```
full_emmc_backup/goggles3_emmc_20260614_061942/
    mmcblk0_full.img                full raw dump (7,818,182,656 bytes)
    SHA256SUMS.txt                  95438C51...3BE5E7E6
    metadata/                       getprop, partitions, mounts, by_name, dmesg, logcat

binding_research/                   pre-flash binaries + extracted strings
    bin/                            pulled DJI binaries (from engineering /system)
    etc/system_etc/dji.json         pre-flash multi_type_compatibility (3 entries)
    etc/{system_etc,vendor_etc}/    init.e3t.usb.rc, fstab.e3t, selinux, vintf, configs
    cali/, factory_data/            calibration / identity (sensitive)
    local_strings/, string_summary/, targeted_report/, json_focus/   string analysis

post_factory_reset_20260614_112519/ post-reset diagnostics + retail OTA source
    retail_ota/ota.zip              retail v01.00.1000 source (271 MB; rebuilt to fw_patch/images)
    fix_hms_list/                   slot-1 HMS fix backups
    fix_novice_guidance/            us.db before/after, postboot, verify
    image_prereset_data/            /data extracted from eMMC image (working pre-reset state)
    recovery_research/              env.bin + mmcblk0boot0/1.bin (read-only)
    slot_safety/                    env_p2.bin + gpt_p1.bin host backups (read-only)
    upgrade_test/                   on-device upgrade logs (failed-attempt forensics)
    sensor_error_hsm/, recheck_*/, listings/, pulls/

image_bins/                         offline-extracted binaries (dji_glasses, dji_sys, libapp_util.so,
                                    libeagle_md_up.so, libupgrade_upgrade.so, hms_cfg/*)

fw_analysis/                        firm_cache scanners (DJI Assistant cache fingerprinting)
ftp_research_dev/                   dji_ftpd strings + /etc/ftp.conf reference (FTP path closed)
ftp_research_existing/              empty placeholder
retail_usb_probe/                   USB / network / FTP probes against retail unit
display_test/                       test_disp config + raw 1920x1080 ARGB frame (Milestone 1)
hwids_extra/                        eMMC CID/CSD, USB descriptors, MACs
live_multitype_state/               pigeon_current_type + state grep (pre-flash)
log_export_From_dev/                ~500 MB of pulled blackbox logs
bind_test_o4/                       bind-test logcat (~186 MB)
powered_on_runtime/, powered_on_deeper/   runtime sysfs/USB snapshots
dump_20260614_000001/, partition_cat_dump/, partition_retry/   earlier read-only dumps
post_flash_us.db                    snapshot of /data/us.db post-retail-flash
```

**Loose root-level scripts (legacy, mostly superseded by repro_kit/):**
~30 `.bat` / `.ps1` files (acquisition, string analysis, FTP/USB probes). Useful as
historical record; AGENTS.md §9 flags duplicates and bugs. Do NOT use them as the
basis for repeating the work — start from `repro_kit/RUNBOOK.md` instead.

---

## 6. Script inventory

All ADB scripts hardcode
`C:\Users\ggurov\Downloads\platform-tools-latest-windows\platform-tools\adb.exe`
and `E:\dji_g3` as defaults (the new `repro_kit/` scripts accept overrides via
`-Adb` / `-ImagesDir`; the legacy ones do not).

### Canonical (use these)
- `repro_kit/set_active_slot.ps1` — flip active slot; **boot slot 1 before any flash**.
- `repro_kit/flash_retail_v01_00_1300_to_inactive_slot.ps1` — flash v01.00.1300 to
  inactive slot (refuses to overwrite slot 1 engineering fallback).
- `repro_kit/flash_retail_to_inactive_slot.ps1` — flash v01.00.1000 (older).
- `repro_kit/post_flash_fixups.ps1` — optional OOBE `novice_guidance` and HMS
  `0x1B200003` suppression for IMU-missing units.
- `fw_patch/build_images.py`, `fw_patch/verify_imgs.py` — rebuild and verify the
  retail images from a fresh `ota.zip`.
- `post_reset_tools/{add_novice_guidance.py,remove_hms_entry.py}` — primitives the
  fix-up script wraps.

### Legacy / one-shot (kept for provenance)

#### Acquisition (dev unit, ADB)
- `dump_g3_readonly.bat` — broad read-only collection: props, partitions, mounts,
  device-tree, sysfs, network, processes, logs; pulls `/factory_data /cali /system
  /vendor /blackbox/upgrade`; raw-dumps safe partitions; SHA256 everything.
- `dump_full_emmc.ps1` — streams full `/dev/block/mmcblk0` to image, verifies size,
  hashes, edge-hash sanity. (Produced the 7.8 GB backup.)
- `dump_partitions_cat.bat` / `dump_partitions_retry.bat` — per-partition `cat` dumps.
- `dump_powered_on_runtime.bat` / `dump_powered_on_runtime_more.bat` — runtime state,
  USB gadget, video/display nodes, input devices, dmesg radio hits.
- `dump_hwid_extra.bat` — eMMC CID/CSD, USB gadget descriptors, MACs, bus names.
- `pull_more_info.bat` — generates+runs `extract_local_strings.ps1` (string extraction).

#### Live modem/state queries (dev unit)
- `query_live_device.ps1` / `query_live_2.ps1` — dump current pigeon type, nvram dirs,
  sparrow2 fw dirs.
- `extract_multi_1.ps1` — extract `multi_type_compatibility` region from `dji.json`.
- `read_json1.ps1` — context windows for dji.json/wlm/gfsk/upgrade configs.

#### String analysis (local, offline)
- `local_strings.ps1` — ASCII+UTF16 string extraction over bin/etc/factory_data/cali.
- `summarize_strings.ps1` — parse index, categorize keyword hits, build `summary.md`.
- `smaller_strings_summary.ps1`, `more_relevant_strings.ps1` — targeted product/SDR
  mapping reports (see Code Smells: output is broken).

#### FTP research (CLOSED — see §7 facts)
- `dev_goggles_search_ftpd.ps1` — pull `dji_ftpd`, grep device for ftp/USER/PASS.
- `dev_goggles_search_ftpd_local.ps1` — extract `dji_ftpd` strings locally.
- `dev_search_ftpd_local_files.ps1` — grep existing dumps for ftp creds.
- `retail_probe_ftp.ps1` — scripted FTP command probe (no-login + anon) against retail.
- `sniff_dji_login.ps1` — pktmon capture of FTP (port 21) while DJI Assistant runs.

#### Retail network/USB probing
- `usb_enum_goggles.ps1` — capture USB/PnP at disconnected/charging/on/assistant states.
- `diff_usb.ps1` — diff those captures for VID/PID/ADB/RNDIS/etc.
- `retail_network.ps1` / `retail_network_new.ps1` — host adapter/IP/route/ARP snapshot.
- `retail_probe_network.ps1` / `retail_probe_network_60_2.ps1` /
  `probe_retail_network_new.ps1` / `probe_retail_netrwork_2.ps1` — TCP port scan of
  `192.168.60.2` (near-duplicates; `netrwork` is a typo).
- `mk_emmc_manifest.ps1` — write read-only researcher notes next to the eMMC backup.
- `sum.bat` — build a summary text from an ADB dump folder.

---

## 7. Confirmed facts (quick reference)

### Hardware / identity
```
Platform:           E3T ZV902, Unisoc/SPRD SoC, AArch64, 4x Cortex-A55 (ARMv8.2)
Display:            Pixelworks Iris6 (pxlw,iris6); custom DJI display HAL via /dev/dji_display
                    (no fbdev/DRM); planes 5/6 = ARGB GFX, plane 4 = video/NV12; 1920x1080
USB family:         VID 2CA3 PID 0020 (gadget serial 987654321ABCDEF on both units)
Vendor bulk:        /bulk/s2_da  VID 2CA3 PID 1020 iface 7 ep_in 88 ep_out 08
Dev eMMC backup:    7,818,182,656 bytes
   SHA256:          95438C513394E23BB2E26D0B9ACE4AA26C2CDC8C11582B754BFE49293BE5E7E6
```

### Boot / slot architecture (see `docs/recovery_boot_architecture.md`)
```
Slots:              system/system_2, vendor/vendor_2, normal/normal_2, tos/tos_2, scp/scp_2
                    (NO recovery / boot / misc partitions exist -> no Android recovery menu)
Slot suffix prop:   ro.boot.slot_suffix (1 or 2)
Slot key/value:     /system/bin/unrd  -> -g/-s/-d, env partition (libunrd.so)
Active-slot flip:   unrd -s slot_<old>.status_active 0; unrd -s slot_<new>.status_active 1
                    (both kept bootable; bootloader auto-falls back if new slot fails)
Verity / AVB:       androidboot.verity=0, "verity not enabled - ENG build"; fstab.e3t has
                    NO verify/avb on system or vendor; userdata force_format/formattable
                    (but the OTA does NOT wipe /data — confirmed across slot switch)
Bootarea:           the eMMC HW boot area (mmcblk0boot0/1) holds bootloader; FDL/SPRD
                    markers absent (encrypted, ~8 MB each). DO NOT FLASH.
Sub-OS recovery:    Unisoc BROM/FDL "download mode" (VID 0x1782 PID 0x4D00); gated by
                    DJI's signed FDL (which we don't have) + secure_debug=1. Practical
                    unbrick path is the active-slot fallback, not BROM.
```

### Firmware versions seen
```
Pre-flash dev:      engineering 9998 (slot 1; active before flash) + 10002 (slot 2; inactive)
                    Both userdebug/test-keys/PD1A.180720.031, Nov 2023, root-survives.
                    Same air-unit set as 9998 (Air3/Mini4Pro/Avata2 only).
Post-flash dev (current): RETAIL v01.00.1300 / build 29020 / Mar 2026 (slot 2; active)
                    -- userdebug/test-keys -> ADB+root SURVIVED both flashes.
                    9 air units in support_type (incl. wa530 / Avata 360).
Prior retail:       v01.00.1000 / build 24626 / Oct 2025 (was on slot 2; overwritten by 1300).
```

### Air-unit support_type
```
pair_auto_switch:   0  (no auto personality switch on pairing)
Pre-flash:          wa520, wa233, wa140 (3 entries; only nvram_wa520 active)
Post-flash:         wa520, wa233, wa140 + wm1695, wa521, za530_lite, za530_pro, wa020,
                    wa530 (9 total; v1300 adds Avata 360)
Phase-2 mapping:    user-confirmed: wa520=Avata2, wa233=Air3, wa140=Mini4Pro;
                    wm1695/wa521/za530_*/wa020 are O4/O4Pro/Neo/O3-class
                    (exact 1:1 mapping pending bind tests on retail unit)
```

### Manual flash recipe (executed; lives in repro_kit/)
```
1. Confirm root + ro.boot.slot_suffix; target the OTHER slot.
2. dd images to /dev/block/by-name/{scp,tos,normal,vendor,system}<inactive_suffix>
   (push to /blackbox/stage.img, cat > <dev>, sync, head -c <size> | sha1sum vs host).
3. unrd -s slot_<inactive>.system_new_ranges  14,0,46,...,159744
   unrd -s slot_<inactive>.system_new_sha1    529ee0f458e547cb78b4ff57aefabbe9aa2d0767
   unrd -s slot_<inactive>.system_zero_ranges 18,46,...,158486
   unrd -s slot_<inactive>.system_zero_sha1   14eb8e7b65f491989dcb29f33ca15d2feebfca34
4. unrd -s slot_<old>.status_active 0; unrd -s slot_<new>.status_active 1
   unrd -s boot.mode none; force_ota no; crash_counter 0; wipe_counter 0
5. adb reboot
   These descriptors are bound to system_2.img SHA1 cdd4395f...; rebuilt OTAs need new descriptors.
```

### Fix-ups for IMU-missing units (cosmetic, /data + /system writes)
```
OOBE block:         setup wizard stuck on "passthrough goggles" -> insert
                    novice_guidance=1 into /data/us.db (user_settings_kv table).
                    Survives reboots; /data is NOT wiped by OTA slot switch.
HMS capsule:        on-screen "goggles sensor system error (HSM0x1b200003)" ->
                    remove line "0x1B200003" from /system/etc/hms_errorcode_list.txt
                    (mount rw, push, restorecon, mount ro). Logcat shows
                    "cur hms 0x1b200003 in not supported in whitelist" = filtered.
                    REAPPLY after any slot re-flash (it's in /system, not /data).
```

### Failed/closed avenues
```
FTP authentication: dji_ftpd reads /etc/ftp.conf (user:pass per line); that file
                    is ABSENT in the stock image -> no default credentials, no
                    brute force. The retail control channel is the vendor BULK
                    interface (DUSS protocol over MI_03..MI_07), not FTP.
DJI Assistant 2     pre-built v01.00.1000 was downloaded but stalled in Assistant
upgrade path:       (device-version mismatch on dev build); manual flash bypassed
                    that. /cache (232 MB) is too small for the 271 MB E3T image
                    -> in-Assistant path can't decrypt-then-apply. Bind mounts are
                    disabled on this 5.4.123-rt kernel (mount -o bind returns
                    EINVAL).
Retail ADB:         5555 refused; no USB ADB; no fastboot; no VID_18D1.
SPRD download mode: BROM enumeration likely reachable, but real flashing requires
                    DJI's signed FDL1/FDL2 + secure_debug=1 -> blocked.
```

### Custom display (Milestone 1 done)
```
Method:             stop dji_arhome + dji_glasses; test_disp -t <case.cfg> -d <data>
                    -s <id> with raw 1920x1080x4 ARGB at /data/<...>_argb.bin;
                    restart UI services. User visually confirmed color bars.
                    Frame format = exactly 8,294,400 B (BGRA byte order).
```

Product terms seen in strings (`binding_research/targeted_report/deep_focus/unique_product_terms.txt`):
`pigeon_*`, `zv900*`, `zv902*`, and a long WM-series list (`wm169`, `wm170`, `WM233`,
`WM265E/M/T`, etc.) — candidate drone identifiers worth mapping to drone_type/sdr_id.

---

## 8. Prioritized next steps (for the coding agent)

Phase 1 (manual retail flash + keep root + 8 air units) is done. Original §8.2/3/6
items are also done (full eMMC image parsed; `/etc/ftp.conf` confirmed absent from
image; flash had a recovery-first plan and worked). The new priority list:

1. **Bind-test the new air units** (user has O4 Air Unit + O4 Pro on hand;
   O3 + Neo arriving). Confirm which `drone_name` (wm1695/wa521/za530_*/wa020)
   maps to which physical product. Capture logs from `dji_sdrs_agent`,
   `dji_gfsk_agent`, `dji_wlm` during pairing. Update §3 table as confirmed.

2. **Reverse `dji_sdrs_agent` switch path** (Phase 2 — adding units beyond retail).
   - Use the now-richer `binding_research/bin/dji_sdrs_agent` + retail
     `/system/bin/dji_sdrs_agent` (slot 2, post-flash). Diff symbols / strings.
   - Map `sa_switch_multi_firmware`, `sa_update_multi_drone_type`,
     `sa_copy_fw_to_pigeon_default`, `sa_copy_nvram_to_cali_default`,
     `sa_check_nvram_integrity`, `sa_reset_modem`.
   - Determine whether `support_type` is the authoritative list or whether there's
     an additional hardcoded allow-list / sdr_id check in the binary.
   - Identify the IPC/command that `dji_glasses` sends to trigger a switch.

3. **Vendor bulk control protocol** (the real DJI Assistant control channel).
   - Iface 7, `/bulk/s2_da`, ep_in 0x88 / ep_out 0x08. Likely DUSS framing
     (DUSS70 logs in upgrade flow). Static-analyze `dji_upgrade` + libusb in
     DJI Assistant.
   - This is the pivot for non-flash personality switches and for understanding
     what Assistant does to the retail unit (which has no ADB).

4. **Image-build hygiene for fresh OTAs.**
   - When DJI ships v01.00.1300 (or later), rebuild via `fw_patch/build_images.py`
     and **regenerate** the `unrd` system_new/zero descriptors from that OTA's
     `range_sha1_save` (see `repro_kit/MANIFEST.md`). The flash script's SHA1
     guard will block a stale-descriptor flash.

5. **Bake fix-ups into the image for IMU-missing donors.**
   - Patch `system_2.img` with `0x1B200003` removed from
     `etc/hms_errorcode_list.txt` so the suppression survives any future re-flash
     (currently a manual post-flash step).

6. **Retail unit (no ADB) — passive only.**
   - Wireshark/usbpcap on DJI Assistant ⇄ retail. Catalogue DUSS commands.
   - No write attempts on the retail unit. Treat as observation surface only.

7. **Phase 1.5 (optional): "PC FPV monitor" Milestone 2.**
   - Real-time H.264 feeder into the video plane (4) via `dji_mb_ctrl` simulator
     mode. Frames-per-second over RNDIS USB is the practical ceiling; profile
     before committing.

---

## 9. Code smells / data-quality issues in current artifacts

These will mislead an agent if trusted blindly:

1. **Broken report content (high impact).** `more_relevant_strings.ps1` (and the
   `smaller_strings_summary.ps1` family) emit the literal text `$line` instead of the
   matched line, because the markdown writer used a backtick-escaped `` `$line ``
   inside a double-quoted string. As a result
   `binding_research/targeted_report/targeted_report.md` and
   `deep_focus/important_pairing_product_mapping.md` contain only line numbers with
   `$line` placeholders — **no actual string content**. The `.csv` outputs
   (`targeted_hits.csv`, `all_product_term_lines.csv`) and
   `unique_product_terms.txt` are the trustworthy versions. Regenerate the MD with
   `"... $($row.Line)"`.

2. **Duplicated/near-duplicate scripts.** Four overlapping retail port-scanners
   (`retail_probe_network.ps1`, `retail_probe_network_60_2.ps1`,
   `probe_retail_network_new.ps1`, `probe_retail_netrwork_2.ps1`), two host-network
   snapshots (`retail_network.ps1`, `retail_network_new.ps1`), and three ftpd search
   scripts. One typo'd filename (`netrwork`). Consolidate into parameterized scripts.

3. **Hardcoded environment.** ADB path, `E:\dji_g3`, host interface `"Ethernet 4"`,
   and pktmon interface index `-i 4` are hardcoded everywhere. Brittle across machines
   and across re-enumeration of the RNDIS adapter. (`repro_kit/*.ps1` scripts at
   least accept overrides via `-Adb` / `-ImagesDir`.)

4. **Two divergent `Get-AsciiStrings` implementations.** `local_strings.ps1` uses a
   latin1 regex; the version generated by `pull_more_info.bat` uses a byte loop. They
   can produce different string sets for the same input. Pick one.

5. **Code-generating-code.** `pull_more_info.bat` writes a here-string into
   `extract_local_strings.ps1` then executes it. Hard to review/diff; prefer a
   committed `.ps1`.

6. **Expensive hashing loop.** `dump_g3_readonly.bat` runs `certutil -hashfile` over
   *every* pulled file including multi-GB trees — slow and largely redundant with the
   eMMC image hash.

7. **Auto-`notepad`/`pause` side effects.** Most scripts open notepad and pause,
   making them unsuitable for non-interactive / agent-driven execution. Add a
   `-NonInteractive` path.

8. **Provenance-bound flash descriptors (NEW).**
   `repro_kit/flash_retail_to_inactive_slot.ps1` hardcodes the `unrd`
   `system_new_*` / `system_zero_*` descriptors derived from this exact retail
   `system_2.img` (SHA1 `cdd4395f...`). The script's SHA1 guard will refuse to run
   if a different image is supplied — but a future contributor must regenerate the
   descriptors from that OTA's updater-script `range_sha1_save` values rather than
   "fix" the guard.

9. **Cosmetic suppressions are flash-local (NEW).**
   The HMS `0x1B200003` removal lives in `/system/etc/hms_errorcode_list.txt`, so
   any future re-flash of `system_<slot>` re-introduces the capsule. The OOBE
   `novice_guidance` fix lives in `/data/us.db` and survives slot switches but
   would not survive a true factory reset / userdata wipe. Bake the HMS edit into
   the host-side `fw_patch/images/system_2.img` build to make it durable.

10. **`/cache` is too small for the full E3T image (NEW).**
    `libeagle_md_up.so` hardcodes `/cache/ota.zip` as the decrypt target;
    `/cache` is 232 MB while the E3T package is ~271 MB, so the in-Assistant
    OTA path **cannot complete** on this device family. Bind mounts are
    disabled on the 5.4.123-rt kernel (`mount -o bind` returns EINVAL), so
    there's no in-place workaround — you must use the manual flash path.
    Don't waste cycles trying to "fix" the in-Assistant upgrade.

11. **Display-test prerequisites are unreviewed (NEW).**
    `repro_kit` does not include the FPV/Milestone-1 display work; if you
    revisit it, note that `test_disp` v1 (`-a`) crashes on a missing 3DLUT
    gtest case, and v2 (`-t cfg -d data -s id`) requires the UI services to be
    stopped (`stop dji_arhome; stop dji_glasses`) to free planes 5/6.

---

## 10. Operating rules for the agent

- Treat `full_emmc_backup/` as **read-only, sensitive**; never modify, never publish.
- Do all binary analysis against the **pulled copies** in `binding_research/bin/` and
  partitions extracted from the image — not against the live device.
- Before proposing any on-device write, produce: (a) the exact code path, (b) a
  snapshot/backup step, (c) a tested restore step. Surface these to the user for
  approval first.
- Keep new scripts parameterized (paths, interface) and non-interactive.
- When regenerating reports, fix the `$line` interpolation bug rather than copying it.
- Keep `docs/findings.md` and `docs/activity-log.md` current as you work; tag new
  facts `[CONFIRMED]` / `[INFERRED]` / `[OPEN]`. AGENTS.md should be updated only
  when phase boundaries change (e.g. Phase 2 milestones).
- For any A/B-slot write: dry-run the slot detection first, write only the
  inactive slot, verify readback SHA1 against the host image, abort on any
  mismatch BEFORE flipping the active slot.
- Do not touch `bootarea`, `env`, `gpt`, `boot0`, `boot1`. Slot state changes go
  through `unrd`.

---

## 11. Reproduction kit (repeating on a second physical unit)

**Slot policy:** slot 1 = permanent engineering fallback (never flash). Slot 2 =
retail target. Always `set_active_slot.ps1 -Slot 1 -Execute -Reboot` before flashing.

Kit lives in `repro_kit/` — read `RUNBOOK.md` first. Key scripts:
`set_active_slot.ps1`, `flash_retail_v01_00_1300_to_inactive_slot.ps1`,
`post_flash_fixups.ps1`, `MANIFEST.md`.

Payloads: `fw_patch/images_1300/` (current), `fw_patch/retail_ota_1300/ota.zip`.
Source IM*H: DJI Assistant `firm_cache\1ed19cd27422aeccc8f73ce81f66498d.cache`.

---

## 12. Boot / recovery / slot architecture (summary)

Full write-up in `docs/recovery_boot_architecture.md`. Key points:

- **No Android recovery menu exists**. There are no `recovery`, `boot`, or `misc`
  partitions. `adb reboot recovery` / `bootloader` / `fastboot` do nothing useful;
  the bootloader falls back to `normal` and reboots into the active slot. Buttons
  at power-on do not enter any rescue UI.
- **The only reflash path inside the OS** is the DJI A/B upgrade flow
  (`dji_upgrade` / DUSS70 / `dji_fw_verify` -> `/cache/ota.zip` ->
  `update_engine` writes inactive slot). This is what DJI Assistant uses; on the
  dev unit it fails because `/cache` < image size and bind mounts are blocked.
  The manual flash bypasses this entire pipeline.
- **The fallback below the OS** is Unisoc/SPRD BROM "download mode" (VID `0x1782`
  PID `0x4D00`, FDL1/FDL2 chain). DJI's signed FDL is not in our possession and
  `secure_debug=1` rejects mismatched/foreign FDLs, so the BROM is reachable but
  practically unusable for read/write. The active-slot fallback is the real safety
  net for this work.
- **Slot state lives in `env`** (33 MB partition), accessed via
  `/system/bin/unrd -g/-s/-d <key>` (a thin CLI over `libunrd.so`). Keys we
  touched: `slot_<n>.status_active|status_bootable|status_successful`,
  `slot_<n>.system_new_sha1|system_new_ranges|system_zero_sha1|system_zero_ranges`,
  `boot.mode`, `force_ota`, `crash_counter`, `wipe_counter`. Read-only enumeration
  is `unrd` with no args.

---

## 13. Open questions / Phase 2

- Is `support_type` in `dji.json` the **authoritative** allow-list, or does
  `dji_sdrs_agent` enforce a hardcoded set in addition? (Static analysis pending.)
- What does the live `pigeon_current_type` switch sequence look like over the
  vendor bulk control channel (`/bulk/s2_da`, iface 7)? Is `dji_sdrs_agent`
  reachable via DUSS commands from Assistant?
- Can we add a 9th entry to `support_type` (or substitute one of the 8) and have
  `dji_sdrs_agent` honor it without the matching firmware/NVRAM payload? If yes,
  what is the minimum payload to forge?
- For the retail unit (no ADB): can we observe a real Assistant pairing/upgrade
  session over the bulk interface enough to build a passive control inventory?
- IMU/motion module replacement feasibility: hardware-level question for a
  future donor unit; not addressable from software alone.

---

## 14. Glossary (terms an agent reading this for the first time will need)

- **E3T / ZV902 / TKGS3** — DJI's internal codenames for the Goggles 3 hardware
  family. `ro.product.device == e3t_zv902`.
- **Sparrow2 / pigeon** — DJI's RF modem subsystem and per-unit "personality"
  profile. `pigeon_current_type` records the active personality on disk
  (`/cali/sdr/nvram/pigeon_current_type`).
- **`drone_name` / `drone_type` / `sdr_id`** — the three identifiers used in
  `multi_type_compatibility.support_type`. `drone_name` is the firmware folder
  basename; `drone_type` and `sdr_id` are the numeric codes used over the link.
- **`unrd`** — DJI's slot/env key-value tool (`/system/bin/unrd`); only sanctioned
  way to manipulate `env`. CLI: `-g/-s/-d <key> [value]`.
- **DUSS / DUSS70** — DJI's USB-bulk transport/protocol family used by
  `dji_upgrade` and Assistant. Logs tag as `D/DUSS70`.
- **HMS** — Health Management System. On-device alarm pipeline; the on-screen
  capsule is gated by `/system/etc/hms_errorcode_list.txt` (whitelist),
  `hms_errorcode_remap.txt`, and `hms_errorcode_remap_level.txt`.
- **OOBE** — out-of-box experience (the first-run setup wizard); on this device
  it is gated by the `novice_guidance` row in `/data/us.db user_settings_kv`.
- **IM\*H** — DJI's signed-image container header (seen on `normal.img`,
  `tos.img`, `scp.img`, `bootarea.img`); these are dd'd as-is by the OTA
  updater-script and bootloader-verified.
- **A/B slot suffixes** — partitions ending in `_2` are the slot-2 copies
  (`system_2`, `vendor_2`, `normal_2`, `tos_2`, `scp_2`); base names without a
  suffix are slot 1. `ro.boot.slot_suffix == 1|2` reports the active one.

