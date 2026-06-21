<#
.SYNOPSIS
  Install persistent donor hygiene: /data/local/donor/rc.local + init hook.

  After product_config.sh starts boot-critical services each boot, the hook runs
  rc.local, waits 30 s, then stops camera3/upgrade/ftpd/amt/agent/arhome/gfsk_agent.
  See DONOR_HYGIENE.md. No product_config.sh patch.

  Default DRY-RUN. Pass -Execute to apply. Pass -Uninstall to remove.
#>
[CmdletBinding()]
param(
  [string]$Adb = "adb",
  [string]$Serial = "",
  [string]$KitDir = $PSScriptRoot,
  [switch]$Execute,
  [switch]$Uninstall,
  [switch]$Reboot
)
$ErrorActionPreference = "Stop"

function Sh([string]$cmd) {
  if ($Serial) { & $Adb -s $Serial shell $cmd }
  else { & $Adb shell $cmd }
}
function AdbPush([string]$local, [string]$remote) {
  if ($Serial) { & $Adb -s $Serial push $local $remote }
  else { & $Adb push $local $remote }
}

if ((Sh "id") -notmatch "uid=0") { throw "Not root on device." }

$rcLocal  = Join-Path $KitDir "donor_rc.local"
$bootHook = Join-Path $KitDir "donor_boot_hook.sh"
$initRc   = Join-Path $KitDir "dji_donor_hygiene.rc"

foreach ($f in @($rcLocal, $bootHook, $initRc)) {
  if (-not (Test-Path $f)) { throw "Missing kit file: $f" }
}

if ($Uninstall) {
  Write-Host "== Uninstall donor rc.local hook ==" -ForegroundColor Cyan
  if ($Execute) {
    Sh "rm -f /data/local/donor/rc.local; rmdir /data/local/donor 2>/dev/null"
    Sh "mount -o rw,remount /system"
    Sh "rm -f /system/bin/donor_boot_hook.sh /system/etc/init/dji_donor_hygiene.rc"
    Sh "restorecon /system/bin /system/etc/init 2>/dev/null"
    Sh "mount -o ro,remount /system"
    Write-Host "  removed rc.local + system hook" -ForegroundColor Green
  } else {
    Write-Host "  DRY-RUN: would remove /data/local/donor/rc.local and system hook files" -ForegroundColor Yellow
  }
  if ($Execute -and $Reboot) { Sh "reboot" }
  exit 0
}

Write-Host "== Install donor rc.local hook ==" -ForegroundColor Cyan
Write-Host "  rc.local  -> /data/local/donor/rc.local"
Write-Host "  boot hook -> /system/bin/donor_boot_hook.sh"
Write-Host "  init rc   -> /system/etc/init/dji_donor_hygiene.rc"

if (-not $Execute) {
  Write-Host "  DRY-RUN only. Re-run with -Execute to apply." -ForegroundColor Yellow
  exit 0
}

Sh "mkdir -p /data/local/donor"
AdbPush $rcLocal /data/local/donor/rc.local | Out-Null
Sh "sed -i 's/\r$//' /data/local/donor/rc.local"
Sh "chmod 755 /data/local/donor/rc.local; chown root:root /data/local/donor/rc.local"

Sh "mount -o rw,remount /system"
AdbPush $bootHook /system/bin/donor_boot_hook.sh | Out-Null
AdbPush $initRc /system/etc/init/dji_donor_hygiene.rc | Out-Null
Sh "sed -i 's/\r$//' /system/bin/donor_boot_hook.sh /system/etc/init/dji_donor_hygiene.rc"
Sh "chmod 755 /system/bin/donor_boot_hook.sh"
Sh "chown root:shell /system/bin/donor_boot_hook.sh"
Sh "chcon u:object_r:dji_services_exec:s0 /system/bin/donor_boot_hook.sh"
Sh "chmod 644 /system/etc/init/dji_donor_hygiene.rc"
Sh "chown root:root /system/etc/init/dji_donor_hygiene.rc"
Sh "restorecon /system/bin/donor_boot_hook.sh /system/etc/init/dji_donor_hygiene.rc 2>/dev/null"
Sh "mount -o ro,remount /system"

Sh "sh /data/local/donor/rc.local"
$cam  = (Sh "getprop init.svc.dji_camera3").Trim()
$ar   = (Sh "getprop init.svc.dji_arhome").Trim()
$gfsk = (Sh "getprop init.svc.dji_gfsk_agent").Trim()
Write-Host "  installed; camera3=$cam arhome=$ar gfsk_agent=$gfsk (hygiene fires in ~30 s)" -ForegroundColor Green
Write-Host "  To disable hook: delete /data/local/donor/rc.local (init stub stays harmless)"
Write-Host "  To fully remove: .\install_donor_rc_local.ps1 -Uninstall -Execute"

if ($Reboot) {
  Write-Host "`nRebooting to verify boot hook..." -ForegroundColor Yellow
  Sh "reboot"
}
