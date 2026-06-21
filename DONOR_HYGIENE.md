# Donor RAM hygiene + GFSK shutdown — findings and runbook

Applies to **IMU-less dev/display units** running retail slot 2 as an FPV-only rig.
Optional after the retail flash in this repo — not required for the upgrade itself.

---

## Problem we were solving

**Symptom:** Screen goes black for ~2–3 s mid-flight (sometimes enough to lose the
drone). Link/OSD often still shows strong bitrate right before the event — **not** an RF
drop.

**Root cause [CONFIRMED, Jun 2026]:** `dji_media_server` **SIGSEGV** in thread
`iondma_cb_0_0` (ION DMA callback inside `OmxBufferQueue` / `LastDurRemux`). Init
restarts the service (~3 s gap = visible blackout).

**Typical field timing:** crash ~**7–10 min** after power-on on long/stale boots; also
correlated with **GFSK control-radio stress** (underflow bursts + `stop spi` on porch
tests, sometimes followed within milliseconds by the iondma fault).

---

## What hygiene does (and does not do)

### Mechanism

| Piece | Path | Survives slot switch? |
|-------|------|------------------------|
| Policy script | `/data/local/donor/rc.local` | **Yes** (`/data` preserved) |
| Init wrapper | `/system/bin/donor_boot_hook.sh` | Reinstall after slot re-flash |
| Init trigger | `/system/etc/init/dji_donor_hygiene.rc` | Reinstall after slot re-flash |

**Boot sequence:**

1. `dji.camera_service=1` → init starts `donor_boot_hook` (oneshot).
2. Hook waits up to 30 s for `/data/local/donor/rc.local`, then runs it.
3. rc.local writes boot_id marker (runs once per boot), logs to kmsg, **sleeps 30 s**.
4. `disable_donor_services()` sets props to `0` and `stop`s each service.

**Why 30 s delay:** `camera3`, `upgrade`, `amt`, `agent`, and `arhome` must complete
~8 s UI init (`VstManager` / Embedded Wizard stack). Immediate stop → blank screen /
EW watchdog [CONFIRMED].

### Services stopped @ t≈35 s

| Service | Prop | Typical RSS saved |
|---------|------|-------------------|
| `dji_camera3` | `dji.camera_service=0` | ~56 MB |
| `dji_upgrade` | `dji.upgrade_service=0` | ~11 MB |
| `dji_ftpd` | `dji.ftpd_service=0` | ~3 MB |
| `dji_amt` | `dji.amt_service=0` | (bundle ~26 MB with agent) |
| `dji_agent` | `dji.agent_service=0` | |
| `dji_arhome` | `dji.arhome_service=0` | ~28 MB |
| **`dji_gfsk_agent`** | **`dji.gfsk_agent_service=0`** | **~8 MB** (added 2026-06-20) |

### Always keep running (FPV path)

`dji_glasses`, `dji_media_server`, `dji_sys`, `dji_wlm`, `dji_sdrs_agent`,
`dji_sw_uav`, `dji_blackbox`, DSP/audio as needed.

**Do not stop** `dji_media_server` — that *is* the liveview pipeline.

---

## GFSK shutdown — why we added it (2026-06-20)

Porch and field testing showed **GFSK control-radio stress** often present before
iondma crashes:

```
gfsk_data_io: read buffer underflow (×N, ~1/s when armed)
gfsk_dev_mgr_ta: stop spi
dma0chan3: deadlock may occurred, try abort   (~every 41.6 s when armed)
→ iondma_cb_0_0 SIGSEGV (sometimes; not every burst)
```

**Important nuance:** `stop dji_gfsk_agent` stops the **userspace daemon only**. Kernel
GFSK (`gfsk_data_io`, SPI bridge) can still log underflows when armed. After userspace
stop, **idle / disarmed** sessions showed **zero** chronic underflows and **zero**
`dma0chan3` deadlock lines in kmsg.

### Expected side effects (acceptable)

- `dji_glasses`: `GfskManager: failed to request gfsk state` (~1 Hz)
- `dji_sys`: `TIME_SYNC: sync time to GFSK error, result=-1002`

Liveview and SDR link (`dji_wlm`, `dji_sdrs_agent`) continue. Log noise is preferable
to mid-flight blackout.

### Temporarily re-enable GFSK

```powershell
adb shell "setprop dji.gfsk_agent_service 1; start dji_gfsk_agent"
```

Reboot returns to hygiene policy (rc.local runs again).

---

## What we ruled out

| Hypothesis | Result |
|------------|--------|
| RF / link loss | Ruled out — bitrate high at blackout |
| Blackbox % full alone | Bench at 96% did not repro |
| Hygiene (camera/arhome/…) alone | Long session still had 11+ media_server crashes with hygiene but GFSK running |
| Antenna swap | No change in chronic underflow rate |
| Fresh reboot | Helps — clears stale ION/DMA state; still recommended pre-flight |

**Leading model [INFERRED]:** async ION buffer use-after-free in `LastDurRemux`; GFSK
timing stress increases odds; **GFSK userspace stop + cold boot** may reduce trigger rate.

---

## Field validation — flight0579 (2026-06-21) [CONFIRMED]

First clean **field flight** after GFSK was added to hygiene:

| Item | Value |
|------|-------|
| Boot | cold boot **07:40:45** GMT |
| Session | **flight0579**, **~46 min** uptime at USB check |
| `dji_media_server` | pid **951** — **no restart** (crossed old 7–10 min window) |
| User report | **Video perfect** |
| kmsg | **0** iondma, **0** SIGSEGV, **0** dma0chan3 deadlock |
| GFSK underflows | **29** total, all **t=7–36 s** (boot window only) |
| Hygiene kmsg | `delayed disable … arhome **gfsk**` @ t≈35 s |
| New coredumps | None |

Prior idle soak with manual GFSK stop: **11+ h**, same media_server pid, **0** iondma.

**Verdict:** Strong positive signal; **not** proof that GFSK is the sole root cause —
continue post-flight checks on each session.

---

## Install / update / disable

From this repo directory (donor on USB, root ADB):

```powershell
# Install or push updated rc.local + /system hook
.\install_donor_rc_local.ps1 -Execute -Reboot

# Verify after boot
adb shell "grep 'donor rc.local' /blackbox/system/kmsg.log | tail -3"
adb shell "getprop init.svc.dji_gfsk_agent; getprop dji.gfsk_agent_service; pidof dji_gfsk_agent"
```

Expected: `init.svc.dji_gfsk_agent=stopped`, `dji.gfsk_agent_service=0`, empty pid.

**Re-flash slot 2:** `/data/local/donor/rc.local` persists; re-run installer for
`/system/bin/donor_boot_hook.sh` and `dji_donor_hygiene.rc`.

**Disable policy only:** `adb shell rm /data/local/donor/rc.local`

**Full remove:** `.\install_donor_rc_local.ps1 -Uninstall -Execute`

---

## Post-flight check (usual suspects)

Run after every field session:

```powershell
adb shell "cat /proc/uptime; cat /blackbox/flight_latest"
adb shell "ps -A -o PID,ELAPSED,NAME | grep -E 'media_server|glasses'"
adb shell "grep -ci iondma /blackbox/system/kmsg.log; grep -ci SIGSEGV /blackbox/system/kmsg.log"
adb shell "grep -ci 'dma0chan3.*deadlock' /blackbox/system/kmsg.log"
adb shell "ls -lt /blackbox/system/coredump/ | head -5"
adb shell "cat /blackbox/system/tombstones/index"
```

**Healthy flight:** same `dji_media_server` pid as boot, zero new iondma cores, no
blackout felt in flight.

**Failure:** new `flightNNNN.core.dji_media_server…iondma_cb_0_0…` tarball and/or pid
change with ~7–10 min elapsed.

**Operational habits:**

- Power-cycle goggles before each field day.
- Prune `/blackbox` when >90% (`adb shell df -h /blackbox`; delete old `flightNNNN/` dirs).

---

## Kit file index (this repository)

| File | Role |
|------|------|
| `donor_rc.local` | Policy → `/data/local/donor/rc.local` |
| `donor_boot_hook.sh` | Init oneshot wrapper → `/system/bin/` |
| `dji_donor_hygiene.rc` | Triggers on `dji.camera_service=1` |
| `install_donor_rc_local.ps1` | Host installer |
| `DONOR_HYGIENE.md` | This document |
| `RUNBOOK.md` | §5 optional fix-ups + link here |
