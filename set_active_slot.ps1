<#
.SYNOPSIS
  Set the active A/B slot on the Goggles 3 via unrd, with safety checks.
  Both slots are kept bootable; this only flips the active flag + boot.mode.

.DESCRIPTION
  Used to toggle which slot the bootloader picks at the next reboot.
  Common uses on this project:
    - Boot the engineering fallback (slot 1) before reflashing slot 2:
        .\set_active_slot.ps1 -Slot 1 -Reboot
    - Switch back to retail after a flash:
        .\set_active_slot.ps1 -Slot 2 -Reboot

  Safety:
    - Refuses if the target slot is not marked bootable.
    - Refuses if uid != 0.
    - Default is dry-run (prints intended unrd writes); pass -Execute to apply.
    - Pass -Reboot to immediately 'adb reboot' after the flip.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidateSet(1,2)][int]$Slot,
  [string]$Adb = "C:\Users\ggurov\Downloads\platform-tools-latest-windows\platform-tools\adb.exe",
  [switch]$Execute,
  [switch]$Reboot
)
$ErrorActionPreference = "Stop"
function Sh([string]$cmd) { & $Adb shell $cmd }

if ((& $Adb get-state 2>&1) -notmatch "device") { throw "adb not in 'device' state." }
if ((Sh "id") -notmatch "uid=0") { throw "Not root on device." }

$other = if ($Slot -eq 1) { 2 } else { 1 }
$cur   = (Sh "getprop ro.boot.slot_suffix").Trim()

Write-Host "== Current state ==" -ForegroundColor Cyan
foreach ($s in 1,2) {
  foreach ($f in 'status_active','status_bootable','status_successful') {
    $v = (Sh "unrd -g slot_$s.$f 2>/dev/null").Trim()
    Write-Host ("  slot_{0}.{1} = [{2}]" -f $s,$f,$v)
  }
}
Write-Host "  ro.boot.slot_suffix (currently booted) = $cur"
Write-Host ""

if ($cur -eq "$Slot" -and (Sh "unrd -g slot_$Slot.status_active 2>/dev/null").Trim() -eq "1") {
  Write-Host "Already booted on slot $Slot and slot_$Slot.status_active=1. Nothing to do." -ForegroundColor Yellow
  return
}

$bootable = (Sh "unrd -g slot_$Slot.status_bootable 2>/dev/null").Trim()
if ($bootable -ne "1") {
  throw "Refusing to switch: slot_$Slot.status_bootable=[$bootable] (must be 1)."
}

Write-Host "== Plan ==" -ForegroundColor Cyan
Write-Host "  unrd -s slot_$other.status_active 0"
Write-Host "  unrd -s slot_$Slot.status_active 1"
Write-Host "  unrd -s boot.mode none"
Write-Host "  unrd -s force_ota no"
Write-Host "  unrd -s crash_counter 0"
Write-Host "  unrd -s wipe_counter 0"
if ($Reboot) { Write-Host "  adb reboot" }

if (-not $Execute) {
  Write-Host ""
  Write-Host "DRY-RUN only. Re-run with -Execute to apply." -ForegroundColor Yellow
  return
}

Write-Host ""
Write-Host "== Applying ==" -ForegroundColor Cyan
Sh "unrd -s slot_$other.status_active 0" | Out-Null
Sh "unrd -s slot_$Slot.status_active 1"  | Out-Null
Sh "unrd -s boot.mode none"  | Out-Null
Sh "unrd -s force_ota no"    | Out-Null
Sh "unrd -s crash_counter 0" | Out-Null
Sh "unrd -s wipe_counter 0"  | Out-Null

Write-Host "== After ==" -ForegroundColor Cyan
foreach ($s in 1,2) {
  foreach ($f in 'status_active','status_bootable','status_successful') {
    $v = (Sh "unrd -g slot_$s.$f 2>/dev/null").Trim()
    Write-Host ("  slot_{0}.{1} = [{2}]" -f $s,$f,$v)
  }
}
Write-Host ""
if ($Reboot) {
  Write-Host "Rebooting into slot $Slot..." -ForegroundColor Green
  & $Adb reboot
} else {
  Write-Host "Reboot when ready: adb reboot" -ForegroundColor Yellow
  Write-Host "To revert without rebooting: .\set_active_slot.ps1 -Slot $other -Execute" -ForegroundColor Yellow
}
