<#
.SYNOPSIS
  Flash retail Goggles 3 firmware v01.00.1300 (build 29020, 2026-03-23) to the
  INACTIVE A/B slot and switch to it, keeping root.

.DESCRIPTION
  Identical mechanism to flash_retail_to_inactive_slot.ps1 (which targets v1000),
  but with v01.00.1300 descriptor values and a provenance guard against
  fw_patch/images_1300/system_2.img. Auto-targets the inactive slot; whichever
  slot you're currently booted on stays untouched as the fallback.

  IMPORTANT for "preserve dev firmware as fallback":
    1. boot the device on slot 1 (engineering) FIRST  (use set_active_slot.ps1 -Slot 1).
    2. then run this script -- it will target slot 2 (currently retail v1000 -> overwritten with v1300).
    3. on success, this script flips active to slot 2; reboot into v1300.
  If you skip step 1 and run from slot 2 (current retail v1000), the script will
  target slot 1 and OVERWRITE the engineering build. Don't do that.

  Default mode is a DRY-RUN plan. Pass -Execute to actually write.

.NOTES
  - Requires rooted ADB (uid=0), images in -ImagesDir (default fw_patch/images_1300).
  - Source: retail OTA decrypted from DJI Assistant firm_cache hash
    1ed19cd27422aeccc8f73ce81f66498d.cache (282,358,176 B).
  - bootarea.img is intentionally NOT flashed (hard-brick risk).
#>
[CmdletBinding()]
param(
  [string]$Adb       = "C:\Users\ggurov\Downloads\platform-tools-latest-windows\platform-tools\adb.exe",
  [string]$ImagesDir = "E:\dji_g3\fw_patch\images_1300",
  [string]$Stage     = "/blackbox/stage.img",
  [switch]$Execute,
  [switch]$IAcceptOverwriteSlot1   # Required to target slot 1 (kills the eng fallback).
)

$ErrorActionPreference = "Stop"

# system_2.img build this descriptor set was captured for (provenance guard).
# Value derived from sdat2img reconstruction of v01.00.1300 ota.zip's system.new.dat.br.
$ExpectedSystemSha1 = "4015aa6874003ffc6a8666e5453a09e3d975a90d"

# unrd system integrity descriptors for v01.00.1300 (from the OTA's updater-script
# range_sha1_save calls). Note: system_zero_sha1 happens to match v1000's because
# the zero-block COUNT is identical even though the ranges shifted.
$Desc = @{
  "system_new_ranges"  = "14,0,46,50,176,2530,32770,32808,65537,69632,98306,98344,145571,158486,159744"
  "system_new_sha1"    = "451e018ea5762e088cb5946e6f15f3ff7578cda9"
  "system_zero_ranges" = "18,46,50,176,688,2018,2530,32770,32808,65537,66049,69120,69632,98306,98344,145571,146083,157974,158486"
  "system_zero_sha1"   = "14eb8e7b65f491989dcb29f33ca15d2feebfca34"
}

# Logical partition base -> image file. Suffix ("" for slot 1, "_2" for slot 2)
# is appended at runtime for the INACTIVE slot.
$Parts = @(
  @{ Base = "scp";    Img = "scp.img"    },
  @{ Base = "tos";    Img = "tos.img"    },
  @{ Base = "normal"; Img = "normal.img" },
  @{ Base = "vendor"; Img = "vendor_2.img" },
  @{ Base = "system"; Img = "system_2.img" }
)

function Sh([string]$cmd) { & $Adb shell $cmd }

function HostSha1([string]$path) { (Get-FileHash $path -Algorithm SHA1).Hash.ToLower() }

Write-Host "== Preflight ==" -ForegroundColor Cyan
$state = (& $Adb get-state) 2>&1
if ($state -notmatch "device") { throw "adb not in 'device' state: $state" }
$id = (Sh "id").Trim()
if ($id -notmatch "uid=0") { throw "Not root on device: $id" }
Write-Host "  root OK: $id"

$activeSuffixRaw = (Sh "getprop ro.boot.slot_suffix").Trim()
if ($activeSuffixRaw -notmatch '^[12]$') { throw "Unexpected slot_suffix: '$activeSuffixRaw'" }
$activeSlot   = [int]$activeSuffixRaw
$inactiveSlot = if ($activeSlot -eq 1) { 2 } else { 1 }
# slot 1 uses base partition names; slot 2 uses the _2 suffix.
$inactivePartSuffix = if ($inactiveSlot -eq 2) { "_2" } else { "" }
Write-Host "  active slot   = $activeSlot"
Write-Host "  INACTIVE slot = $inactiveSlot  (target; partition suffix '$inactivePartSuffix')"

# Safety: targeting slot 1 wipes the engineering fallback. Require explicit consent.
if ($inactiveSlot -eq 1 -and -not $IAcceptOverwriteSlot1) {
  throw @"
Refusing to target slot 1 (engineering fallback) without -IAcceptOverwriteSlot1.

You are currently booted on slot $activeSlot. Inactive slot 1 typically holds the
rooted engineering build that we want to keep as the always-bootable fallback.

To write v1300 to slot 2 instead (the standard "preserve dev firmware" path):
  1) .\set_active_slot.ps1 -Slot 1 -Reboot -Execute    # boot dev firmware
  2) wait for reboot, ensure ADB is back
  3) .\flash_retail_v01_00_1300_to_inactive_slot.ps1 -Execute    # writes slot 2

Only re-run with -IAcceptOverwriteSlot1 if you really want to overwrite the
engineering build on slot 1.
"@
}

# Provenance guard: descriptor values only match this exact system image.
$sysImg = Join-Path $ImagesDir "system_2.img"
$sysSha = HostSha1 $sysImg
if ($sysSha -ne $ExpectedSystemSha1) {
  throw "system_2.img SHA1 $sysSha != expected $ExpectedSystemSha1. The unrd descriptors in this script are bound to that build; rebuild descriptors before flashing."
}
Write-Host "  system_2.img provenance OK ($sysSha)"

Write-Host ""
Write-Host "== Plan ==" -ForegroundColor Cyan
foreach ($p in $Parts) {
  $dev = "/dev/block/by-name/$($p.Base)$inactivePartSuffix"
  $img = Join-Path $ImagesDir $p.Img
  $sz  = (Get-Item $img).Length
  Write-Host ("  {0,-12} <- {1,-13} ({2,12} B) sha1={3}" -f $dev, $p.Img, $sz, (HostSha1 $img))
}
Write-Host "  then: unrd slot_$inactiveSlot.system_* descriptors; slot_$activeSlot.status_active=0; slot_$inactiveSlot.status_active=1"

if (-not $Execute) {
  Write-Host ""
  Write-Host "DRY-RUN only. Re-run with -Execute to write. No changes made." -ForegroundColor Yellow
  return
}

Write-Host ""
Write-Host "== Verify inactive partitions exist ==" -ForegroundColor Cyan
foreach ($p in $Parts) {
  $dev = "/dev/block/by-name/$($p.Base)$inactivePartSuffix"
  $ls = (Sh "ls -l $dev").Trim()
  if ($ls -match "No such") { throw "Missing target partition: $dev" }
  Write-Host "  $ls"
}

Write-Host ""
Write-Host "== Writing images to INACTIVE slot ==" -ForegroundColor Cyan
foreach ($p in $Parts) {
  $dev = "/dev/block/by-name/$($p.Base)$inactivePartSuffix"
  $img = Join-Path $ImagesDir $p.Img
  $sz  = (Get-Item $img).Length
  $hostSha = HostSha1 $img
  Write-Host "  -> $($p.Img) ($sz B) to $dev"
  Sh "rm -f $Stage" | Out-Null
  & $Adb push $img $Stage | Out-Null
  Sh "cat $Stage > $dev; sync" | Out-Null
  $back = (Sh "head -c $sz $dev | sha1sum").Trim().Split(" ")[0]
  Sh "rm -f $Stage" | Out-Null
  if ($back -ne $hostSha) {
    throw "READBACK MISMATCH on ${dev}: device=$back host=$hostSha. ABORTING before any slot switch (active slot still boots)."
  }
  Write-Host "     verified sha1=$back" -ForegroundColor Green
}

Write-Host ""
Write-Host "== Writing inactive-slot system descriptors ==" -ForegroundColor Cyan
foreach ($k in $Desc.Keys) {
  $key = "slot_$inactiveSlot.$k"
  Sh "unrd -s $key $($Desc[$k])" | Out-Null
  $got = (Sh "unrd -g $key 2>/dev/null").Trim()
  Write-Host "  $key = [$got]"
}

Write-Host ""
Write-Host "== Flipping active slot ($activeSlot -> $inactiveSlot) ==" -ForegroundColor Cyan
Sh "unrd -s slot_$activeSlot.status_active 0"   | Out-Null
Sh "unrd -s slot_$inactiveSlot.status_active 1" | Out-Null
Sh "unrd -s boot.mode none"     | Out-Null
Sh "unrd -s force_ota no"       | Out-Null
Sh "unrd -s crash_counter 0"    | Out-Null
Sh "unrd -s wipe_counter 0"     | Out-Null
foreach ($s in @($activeSlot,$inactiveSlot)) {
  foreach ($f in @("status_active","status_bootable","status_successful")) {
    Write-Host ("  slot_{0}.{1} = [{2}]" -f $s,$f,(Sh "unrd -g slot_$s.$f 2>/dev/null").Trim())
  }
}

Write-Host ""
Write-Host "Flash complete. Both slots kept bootable; slot $inactiveSlot is now active." -ForegroundColor Green
Write-Host "Reboot to boot retail:  adb reboot" -ForegroundColor Yellow
Write-Host "If it fails to boot, revert:  adb shell unrd -s slot_$activeSlot.status_active 1; adb shell unrd -s slot_$inactiveSlot.status_active 0" -ForegroundColor Yellow
