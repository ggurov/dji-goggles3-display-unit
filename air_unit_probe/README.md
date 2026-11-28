# Host-side tools for `AIR_UNIT_USB_PROBES.md`

Python 3, `pyusb` plus DJI Assistant 2's own `libusb0.dll` (the same dependency as
`assistant_update/usbdesc.py`); `v1frames.py` and the `goggles_tool` package come from this repo.
Run them with the unit on USB and **DJI Assistant closed** — Assistant claims interface 4
exclusively.

| Script | Purpose |
|---|---|
| `o3_fileio.py` | the file service at DUML host `1d00`: `dir` (phase 06), `read` (phase 08, MD5-checked against the end frame), `raw` (any command, for probes) |
| `pull_crash.py` | walks `/blackbox/system/{tombstones,coredump,crash_log,event_track}` and `/blackbox/info`, pulls every file, parses the clear part of each LOGH header, writes `_index.json` |
| `export_timing.py` | latency and reply of ping / get_version / one unknown command / the export prepare (`00/ea`) — the quick way to tell whether the exporter is up |

All three only ever send read requests (phases 06 and 08), the export flow's own prepare, the
file-service ping and `get_version`, and they acknowledge what the unit sends. They never write to
the unit's storage.

```
python air_unit_probe/o3_fileio.py dir /blackbox/info
python air_unit_probe/o3_fileio.py read /blackbox/info/export_list.json
python air_unit_probe/pull_crash.py --out crash_pull
python air_unit_probe/export_timing.py --rounds 3
```

What comes back is LOGH-wrapped for everything except `export_list.json` and `list.json`; see
`AIR_UNIT_USB_PROBES.md` §5–§6 for the wrapper and what the sizes still tell you. The crashes the
blind sweeps leave behind are described in §7 — check for them after any sweep.
