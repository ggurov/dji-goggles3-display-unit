# goggles-tool

Command-line utility to talk to **DJI Goggles 3** over the same USB bulk path as DJI
Assistant 2 — device discovery, log listing, log download, firmware upload research.

Built from USBPcap captures and static RE of DJI Assistant. Used by `log_export/` scripts
in this repository.

**Status:** research prototype (v0.2). Bulk log download works for retail units; large
multi-file bundles may need window ack tuning (see `log_export/BULK_PROTOCOL.md`).

## Install

```powershell
cd goggles_tool
pip install -e .
```

Requires **Python 3.10+**, `pyusb`, and `libusb-package`.

**Windows:** Goggles MI_03–MI_07 use **libusb-win32** (libusb0). The tool auto-loads DJI
Assistant's `bulk_amd64/libusb0.dll`. Use **64-bit Python**. Close DJI Assistant before
claiming bulk.

## Commands

```powershell
python -m goggles_tool devices
python -m goggles_tool info --dump-xml version.xml
python -m goggles_tool logs-list -o export_list.raw
python -m goggles_tool -v logs-download --path "/blackbox/system/df00.log" `
  --expected-size 12345 -o df00.logh
```

Engineering donor with ADB: `logs-list --via-adb --parse-json` for complete JSON.

## Architecture

```
goggles_tool/
  cli.py              argparse subcommands
  client.py           GogglesClient (handshake, version, logs, bundle download)
  protocol/
    duss.py           DUSS 0x55 frames, TRANS download, CRC16
    constants.py      VID/PID, endpoints, paths
    upgrade.py        upgrade FSM phase names
  usb/
    transport.py      pyusb bulk IN/OUT
```

## Safety

- Prefer **donor unit** for firmware experiments; slot 1 = engineering fallback.
- Retail bulk pulls are read-only.
- See repo root `RUNBOOK.md` for flash constraints.

## Related

- `../log_export/README.md` — retail pull + decrypt workflow
- `../log_export/BULK_PROTOCOL.md` — TRANS ack sequencing
- `../log_export/LOG_ENCRYPTION.md` — LOGH / liblog_util decrypt
