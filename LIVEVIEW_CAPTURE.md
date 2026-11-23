# Live video: capturing frames, the UVC gadget, and how CosmoViewer does it

Companion to `FIRMWARE_CONTAINERS_AND_DUML.md` and `MODEM_LOAD_CHAIN.md`. Measured on a rooted
Goggles 3 (retail **v01.00.1300 / 29020**, slot 2) with an O4-series air unit linked, so the
decoder and display pipeline were live. Nothing here needs a service stop or a reboot.

---

## 1. Capturing the live picture (works)

The display driver exposes a test-command node that can dump the scan-out planes:

```sh
cat /proc/display/plane
# VOP 0: plane 4 - video: 1440x1080 yuv420sp-8, frame idx climbing   <- decoded live video
#        plane 5 - gfx0 : 1920x1080 argb8888                          <- UI overlay

echo dumpframe,help > /proc/display/testcmd     # -> optional params: vop, plane, num, path, dir
echo dumpframe,vop=0,plane=4,num=3,path=/mnt/cap/seq.bin > /proc/display/testcmd
# dmesg: "dump 3 frames"  -> seq.bin, seq.bin.1, seq.bin.2
```

- `path=` must be a **file**; a directory yields `create dump file … failed` and `dump 0 frames`.
- Frames are **NV12 1440×1152** (`2,488,320 B`; 1080 visible rows, 72 rows padding). Plane 5
  dumps as 1920×1080 ARGB. Convert with BT.601.
- Capture is non-disruptive; the live view keeps running.

| step | measured |
|---|---|
| dump 30 frames → tmpfs | 0.54 s (~55 fps capability) |
| `adb pull` 30 frames (74.6 MB) | 2.75 s = 25.9 MB/s |
| sustained dump → pull → delete loop | 30 frames in 3.69 s = **8.1 fps end-to-end** |
| dump to `/blackbox` (eMMC) | ~7.5 fps |

The USB/ADB link is the limit, not capture. Use tmpfs (`/mnt` 225 MB, `/dev` 219 MB) for the frame
ring; `/blackbox` is shared with the agent's rotating logs.

## 2. The UVC webcam mode enumerates but sends nothing

The USB gadget defines `uvc.usb0` (MJPEG 1920×1080). `sys.usb.config=uvc` or `uvc,adb` re-binds the
gadget as PID `0x0021`, and a host sees a standard UVC camera. The frames, however, come from
`dji_media_server`'s UVC-only work mode, and on this build that mode is never selected:

- `WorkModeManager` instantiates one work mode per *supported* entry in `dji_media_service.json`;
  UVC is mode **7**, gated on `"uvc_only": {"supportable": …}` (shipped `false`).
- The active mode changes by **message**, not by USB state — the media server never reads
  `sys.usb.config`. `handleMessageByWorkMode` accepts message **type 0, id 8** = work-mode switch
  (payload = mode, 0…0xb); id 9 = query; 0x45/0x46 = mute.
- Selecting 7 leads to `UvcManager::start()`, which needs a prepared pipeline and an OMX graph in
  IDLE, then emits `{"live_action":"enter_uvc"}`.

Setting the config flag alone, even with the gadget switched, yields an enumerated camera with no
frames. The trigger message is what a host has to send.

## 3. How CosmoViewer / Cosmostreamer gets the video

Their Windows package unpacks to a .NET viewer plus per-device native helpers. The Goggles 3 helper
does **not** use UVC: it brings up the goggles' **USB networking** (RNDIS) and speaks a proprietary
UDP protocol.

- The helper configures the host's RNDIS adapter to the goggles' subnet through WMI
  (`MSFT_NetAdapter`), self-elevating when needed.
- It then talks **UDP to `192.168.60.2:9003`** — the goggles do bind that port.
- Protocol: packets carry a **20-byte header**; the type byte is at **+6** (1 = telemetry,
  2 = video) and the payload starts at **+0x14**. Video is expected as **raw H.264 Annex-B** — the
  helper scans for `00 00 00 01` and forwards complete frames to the viewer, whose GStreamer
  pipelines read UDP ports 3000/3002/5000.
- Startup is a fixed-length probe, then a periodic 34-byte ack echoing fields from the reply; status
  is reported as `camera_model=DJI Goggles 3, video_active=…`.

**Measured against a live unit:** the helper reaches `Camera connection found` / `Init UDP done`,
telemetry flows back, and a packet capture of the helper shows only control and telemetry frames —
**no video frames**, on this build/state. So their path is not a shortcut past the work-mode gate:
the transport works, the goggles simply do not stream until the video work mode is selected.

## 4. Dead ends

- **Reading the decoded frames from dma-buf**: reopening `/proc/<pid>/fd/<n>` fails (dma-buf fds do
  not support reopen) and `pidfd_getfd` needs a newer kernel than this device runs.
- **`test_disp` autotest**: gated by a unit-test that fails on missing 3DLUT files; the case runner
  exits before executing anything.
- **`dji_cst`**: camera-suite tooling for the camera pipeline, not the received liveview.

## 5. Notes

- Frame capture touches only the display driver's test node; no service stop, no slot change.
- The UVC experiment was reverted (`dji_media_service.json` restored, gadget back to
  `rndis,mass_storage,bulk,acm,adb` / PID `0020`, media server restarted).
- Third-party application analysis is behavioural (protocol fields, message ids, pipeline shape);
  no vendor binaries are redistributed here.
