# Reproduction Kit — Manifest (reference-only)

This kit does not duplicate large payloads. It lists what is required to repeat the
procedure and where each piece lives. **Slot policy:** slot 1 = permanent engineering
fallback (never flash); slot 2 = retail target (overwrite on each upgrade). Always boot
slot 1 before running a flash script — see `RUNBOOK.md` §2.

## Kit contents (in this folder)

| File | Purpose |
|---|---|
| `RUNBOOK.md` | Step-by-step procedure; **slot-1-first upgrade workflow**. |
| `set_active_slot.ps1` | Flip active A/B slot via `unrd` (dry-run default). |
| `flash_retail_v01_00_1300_to_inactive_slot.ps1` | Flash **v01.00.1300** to inactive slot. Refuses to target slot 1. |
| `flash_retail_to_inactive_slot.ps1` | Flash **v01.00.1000** to inactive slot (older; superseded). |
| `post_flash_fixups.ps1` | Optional IMU-missing fix-ups (OOBE + HMS). |
| `MANIFEST.md` | This file. |

## Required payload — v01.00.1300 (current)

Images: `E:\dji_g3\fw_patch\images_1300\`

| Image | Size (bytes) | SHA1 | Flashed to |
|---|---|---|---|
| `system_2.img` | 654311424 | `4015aa6874003ffc6a8666e5453a09e3d975a90d` | inactive `system_2` |
| `vendor_2.img` | 150990848 | `6d4eda67309e927254116bd668d676d9c26a14b0` | inactive `vendor_2` |
| `normal.img` | 30196960 | `6fe92625268871a1d78d08eb5d74c3f8d40c97b6` | inactive `normal_2` |
| `tos.img` | 516480 | `b44dfd69d9da42e2ae3f4a59cf0caffaa4cb021b` | inactive `tos_2` |
| `scp.img` | 81952 | `c75a4d74258d390a26b32e64441a2febcb464f7a` | inactive `scp_2` |
| `bootarea.img` | 1173344 | `003bc239ea53e7c7196e723930faca9215e35847` | NOT flashed |
| `compatibility.zip` | 5723 | `22475d09808956f40fb3feb8be185cb4e9ebb209` | provenance |
| `otacert` | 1383 | `e3b6393ade899a2068669b8f88d8a2d9517444c1` | provenance |

Source: DJI Assistant `firm_cache\1ed19cd27422aeccc8f73ce81f66498d.cache` (282,358,176 B;
`zv902_2805_v10.00.59.40_20260325`). Decrypted OTA:
`fw_patch/retail_ota_1300/ota.zip` (post-build-incremental **29020**, Mar 25 2026).

### v01.00.1300 unrd descriptors (in flash script)

```
system_new_ranges  = 14,0,46,50,176,2530,32770,32808,65537,69632,98306,98344,145571,158486,159744
system_new_sha1    = 451e018ea5762e088cb5946e6f15f3ff7578cda9
system_zero_ranges = 18,46,50,176,688,2018,2530,32770,32808,65537,66049,69120,69632,98306,98344,145571,146083,157974,158486
system_zero_sha1   = 14eb8e7b65f491989dcb29f33ca15d2feebfca34
```

## Required payload — v01.00.1000 (older, superseded)

Images: `E:\dji_g3\fw_patch\images\` — see prior table in git history / `flash_retail_to_inactive_slot.ps1`.
Source cache: `firm_cache\ebffe7e5183ada4a89d84ae019ee9d42.cache` (271 MB, build 24626).
Local OTA: `post_factory_reset_20260614_112519/retail_ota/ota.zip`.

## Helper scripts

`E:\dji_g3\post_reset_tools\`: `add_novice_guidance.py`, `remove_hms_entry.py`
`E:\dji_g3\fw_patch\`: `build_images.py`, `verify_imgs.py`, `decrypt_e3t_ota.sh`

## Rebuilding images

```powershell
pip install brotli
python E:\dji_g3\fw_patch\build_images.py <path-to-ota.zip> E:\dji_g3\fw_patch\images_1300
```

Extract `range_sha1_save` from the OTA's `META-INF/com/google/android/updater-script` and
update the matching flash script (SHA1 provenance guard will block stale descriptors).

## DJI Assistant firm_cache version manifest (Goggles 3)

Plaintext JSON at `firm_cache\95714dcbe1a9f75ee8dde5f84fbe27eb.cache`:

| product_version | released | note |
|---|---|---|
| 01.00.0900 | 2025-07-25 | lock screen settings |
| 01.00.1000 | 2025-10-29 | Neo 2 support |
| **01.00.1300** | **2026-03-26** | **Avata 360 support** |

## NOT needed on a new unit

`full_emmc_backup/`, partition dumps, `binding_research/`, per-unit `us.db*`, loose
root-level `.bat`/`.ps1` collectors. See `RUNBOOK.md` §6 for per-unit snapshots instead.

## Environment assumptions

- ADB: `C:\Users\ggurov\Downloads\platform-tools-latest-windows\platform-tools\adb.exe`
- Python 3 + `brotli` (image rebuild only)
- Workspace: `E:\dji_g3` (override via script params)
