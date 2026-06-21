param(
    [string]$NdkRoot = $env:ANDROID_NDK_HOME
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $NdkRoot) {
    throw "Set ANDROID_NDK_HOME or pass -NdkRoot (e.g. C:\Android\android-ndk-r27c)"
}
$ndkBuild = Join-Path $NdkRoot "ndk-build.cmd"
if (-not (Test-Path $ndkBuild)) {
    throw "ndk-build not found: $ndkBuild"
}

Push-Location $here
try {
    & $ndkBuild NDK_PROJECT_PATH=. APP_BUILD_SCRIPT=Android.mk NDK_APPLICATION_MK=Application.mk
    $bin = Join-Path $here "libs\arm64-v8a\logutil_decrypt"
    if (-not (Test-Path $bin)) {
        throw "build output missing: $bin"
    }
    Write-Host "OK -> $bin"
} finally {
    Pop-Location
}
