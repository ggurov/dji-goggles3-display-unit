# Host-side tools for `AIR_UNIT_FIRMWARE_UPDATE.md`

Python 3, standard library only except where noted. Run with native Windows paths.

| Script | Purpose |
|---|---|
| `v1frames.py` | shared pieces: V1 frame layout and CRCs, the streaming parser, the tshark reader |
| `v1dump.py` | every V1 frame of a small capture (device discovery, a page being opened) as one listing |
| `v1stream.py` | streaming decoder for firmware-transfer captures (hundreds of MB): control frames, file parts, part acks |
| `reconstruct.py` | rebuilds the files the PC sent from a capture and checks them against the MD5 in each end frame |
| `compare_runs.py` | diffs two decoded captures: control frames normalised, progress pushes, transfer statistics |
| `usbdesc.py` | read-only USB descriptor dump of attached DJI devices (needs `goggles_tool` and DJI Assistant's `libusb0.dll`) |
| `assistant_ws_crypto.py` | keys and message crypto of the UI ↔ engine WebSocket, derived from the local installation (needs `pycryptodome` or `cryptography`) |

`tshark` (Wireshark) is needed for the capture tools; it is found on `PATH`, through `$TSHARK`
or `--tshark`, else at the default Windows install location.

```
USBPcapCMD -d \\.\USBPcapN --inject-descriptors --snaplen 65535 --capture-from-all-devices -o session.pcapng
tshark -r session.pcapng -Y "usb.idVendor == 0x2ca3" -T fields -e usb.device_address     # the unit's address
python v1dump.py       session.pcapng --addr 62 --max-hex 400 --out frames.txt --summary summary.txt
python v1stream.py     session.pcapng --addr 62 --tag before --outdir out
python v1stream.py     session.pcapng --addr 64 --tag after  --outdir out                # address after the reboot
python reconstruct.py  session.pcapng --addr 62 --outdir files
python compare_runs.py out/before out/after other/before other/after
```

A decoded output directory, the rebuilt files and the decrypted UI log contain device
identifiers or DJI firmware: keep them out of any repository.
