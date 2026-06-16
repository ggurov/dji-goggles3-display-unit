<#
.SYNOPSIS
  Flash retail Goggles 3 firmware to the INACTIVE A/B slot and switch to it,
  keeping root. Reproduces the manual upgrade performed on the donor unit.

.DESCRIPTION
  Stages each reconstructed retail image to /blackbox, writes it to the inactive
  slot partition (via 'cat > /dev/block/by-name/<part><suffix>'), reads the block
  device back and compares SHA1 against the host image. Then writes the inactive
  slot's system integrity descriptors (unrd) and flips the active-slot flag.

  The bootloader (eMMC boot area) is NOT touched. The active slot stays bootable
  as a fallback until you switch and reboot.

  Default mode is a DRY-RUN plan. Pass -Execute to actually write.

.NOTES
  - Requires: rooted ADB (uid=0), the device online, images in -ImagesDir.
  - Slot is detected dynamically from ro.boot.slot_suffix; the script targets the
    OTHER slot, so it works whether the unit currently boots slot 1 or slot 2.
  - The unrd system descriptor values are bound to THIS system image build; only
    valid while -ImagesDir/system_2.img has SHA1 = $ExpectedSystemSha1 below.
  - bootarea.img is intentionally NOT flashed (hard-brick risk). Last resort only.
#>
[CmdletBinding()]
param(
  [string]$Adb       = "C:\Users\ggurov\Downloads\platform-tools-latest-windows\platform-tools\adb.exe",
  [string]$ImagesDir = "E:\dji_g3\fw_patch\images",
  [string]$Stage     = "/blackbox/stage.img",
  [switch]$Execute
)

$ErrorActionPreference = "Stop"

# system_2.img build this descriptor set was captured for (provenance guard).
$ExpectedSystemSha1 = "cdd4395fb4fddfec37ea8daabbbba8ebb7e8d8da"

# unrd system integrity descriptors for the retail system image (slot-independent).
$Desc = @{
  "system_new_ranges"  = "14,0,46,50,176,2530,32770,32808,65537,69632,98306,98344,142694,158486,159744"
  "system_new_sha1"    = "529ee0f458e547cb78b4ff57aefabbe9aa2d0767"
  "system_zero_ranges" = "18,46,50,176,688,2018,2530,32770,32808,65537,66049,69120,69632,98306,98344,142694,143206,157974,158486"
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
