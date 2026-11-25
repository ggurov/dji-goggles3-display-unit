<#
.SYNOPSIS
  Optional post-flash fix-ups for a Goggles 3 unit whose IMU/motion module is
  ABSENT. Skip both on a unit that has a working IMU.

  1) OOBE unblock  - inserts novice_guidance=1 into /data/us.db so the setup
     wizard can move past the "passthrough goggles" screen.
  2) HMS suppression - removes 0x1B200003 from /system/etc/hms_errorcode_list.txt
     so the "goggles sensor system error" capsule stops showing. Engineering
     units only: the script refuses when ro.boot.verity is 1, because a dm-verity
     protected /system does not boot after an edit.

  Default is DRY-RUN. Pass -Execute to apply. Each step backs up the original.
  The two helper scripts live next to this file (override with -Tools).
#>
[CmdletBinding()]
param(
  [string]$Adb        = "C:\Users\ggurov\Downloads\platform-tools-latest-windows\platform-tools\adb.exe",
  [string]$Tools,
  [string]$WorkRoot,
  [string]$HmsCode    = "0x1B200003",
  [switch]$DoOobe,
  [switch]$DoHms,
  [switch]$Execute
)
$ErrorActionPreference = "Stop"
if (-not $Tools)    { $Tools    = $PSScriptRoot }                          # $PSScriptRoot is empty inside param()
if (-not $WorkRoot) { $WorkRoot = Join-Path $PSScriptRoot "_runtime" }    # scratch + backups, git-ignored
if (-not $DoOobe -and -not $DoHms) { $DoOobe = $true; $DoHms = $true }
$ts = Get-Date -Format "yyyyMMddHHmmss"
$work = Join-Path $WorkRoot $ts
New-Item -ItemType Directory -Force -Path $work | Out-Null

function Sh([string]$cmd) { & $Adb shell $cmd }
if ((Sh "id") -notmatch "uid=0") { throw "Not root on device." }

if ($DoOobe) {
  Write-Host "== OOBE unblock (novice_guidance) ==" -ForegroundColor Cyan
  & $Adb pull /data/us.db "$work\us.db" | Out-Null
  Copy-Item "$work\us.db" "$work\us.db.orig"
  python "$Tools\add_novice_guidance.py" "$work\us.db"
  if ($Execute) {
    Sh "cp /data/us.db /data/us.db.bak_$ts" | Out-Null
    & $Adb push "$work\us.db" /data/us.db | Out-Null
    Sh "chown system:system /data/us.db; chmod 660 /data/us.db" | Out-Null
    Write-Host "  applied (backup: /data/us.db.bak_$ts)" -ForegroundColor Green
  } else { Write-Host "  DRY-RUN (edited copy at $work\us.db)" -ForegroundColor Yellow }
}

if ($DoHms) {
  Write-Host "== HMS capsule suppression ($HmsCode) ==" -ForegroundColor Cyan
  $verity = (Sh "getprop ro.boot.verity").Trim()
  if ($verity -eq "1") {
    throw "ro.boot.verity=1: /system is dm-verity protected on this unit and does not boot after an edit. The HMS fix-up is for engineering units (verity=0) only."
  }
  $f = "/system/etc/hms_errorcode_list.txt"
  & $Adb pull $f "$work\hms.orig" | Out-Null
  python "$Tools\remove_hms_entry.py" "$work\hms.orig" "$work\hms.patched" $HmsCode
  if ($Execute) {
    Sh "cp $f /data/hms_errorcode_list.txt.bak_$ts" | Out-Null
    Sh "mount -o rw,remount /system" | Out-Null
    & $Adb push "$work\hms.patched" $f | Out-Null
    Sh "chown root:root $f; chmod 644 $f; restorecon $f 2>/dev/null" | Out-Null
    Sh "mount -o ro,remount /system" | Out-Null
    $cnt = (Sh "grep -c -i 1b200003 $f").Trim()
    Write-Host "  applied; remaining matches=$cnt (backup: /data/hms_errorcode_list.txt.bak_$ts)" -ForegroundColor Green
  } else { Write-Host "  DRY-RUN (patched copy at $work\hms.patched)" -ForegroundColor Yellow }
}

if ($Execute) { Write-Host "`nReboot to apply: adb reboot" -ForegroundColor Yellow }
else { Write-Host "`nDRY-RUN only. Re-run with -Execute to apply." -ForegroundColor Yellow }
