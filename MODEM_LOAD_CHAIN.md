# Sparrow2 modem load chain, key location, and what the AP can do to it

Companion to `FIRMWARE_CONTAINERS_AND_DUML.md`. Everything here was measured on a rooted
Goggles 3 (retail **v01.00.1300 / 29020**, slot 2) and on the engineering build on slot 1
(`00.08.14.05` / `3062`, Nov 2023). No modem flash, no OTP, no slot change.

The internal modem is a separate USB device ("C5") that enumerates on the AP's internal bus.
It boots from the AP on every power-up: the AP uploads its bootloader and re-flashes twelve
partitions before the radio comes up. Nothing on the AP decrypts those images.

---

## 1. State machine

| state | USB id | notes |
|---|---|---|
| boot ROM | `2ca3:0040` | Unisoc BROM-style downloader: class `ff/ff/00`, bulk `0x01`/`0x81`, 64-byte MPS, full speed, `bcdDevice 0xffff`, no strings |
| bootloader | `18d1:d00d` | Unisoc LK: `kernel:lk`, `version:0.5`, `product:eagle-fpga`, `serialno:0x123456` |
| product | `2ca3:1020` | "C5", SuperSpeed, 11 vendor interfaces (`ff/43/01`); the AP claims 4/7/8/9 through `usbfs` |

The reset is a single GPIO (`gpio0`, active low; `reset_pin {group 0, port 0, index 0}` in
`dji.json`). `dji_sdrs_agent` holds and releases it as `hold P1/S1 reset pin` /
`release P1/S1 reset pin`.

```sh
stop dji_sdrs_agent
echo 0 > /sys/class/gpio/gpio0/value; sleep 1; echo 1 > /sys/class/gpio/gpio0/value
/system/bin/brload /vendor/modem_firmware/sparrow2/bootarea.img   # ROM -> LK
/system/bin/fastboot -B 1 getvar all                               # output goes to dmesg
start dji_sdrs_agent                                               # recovery
```

`fastboot` writes its protocol text to `dmesg` (tag `(fastboot)`), not stdout. Recovery from any
state is `start dji_sdrs_agent` (or a reboot), because the AP re-runs this chain at every boot.

## 2. Two files called `bootarea.img`

| file | size | what it is |
|---|---|---|
| `/vendor/modem_firmware/sparrow2/bootarea.img` | 131,072 | the **modem LK** that `brload` uploads and that is flashed as `modem-pub_key`: wrapper + IM\*H `bootloader` (`TBLD`, `auth_alg 0x40003`, `TBIE`), chunks `BLLK` 0x15430 → `0x61100000` and `BLFA` 0x80 → `0x57000` |
| `bootarea.img` from the OTA image | 1,173,344 | an AP/OTA boot-area package: 1024-byte header + three IM\*H containers — `bootloader`, `boardinfo` (`BINF`), `M7firmware` (`M7FW` → `0xf2600000`, which matches the LK log `M7firmware image addr is 0xf2600000`) |

Both are `PRAK`/`TBIE` and encrypted at rest.

## 3. Where the key is

Every modem image is `TBIE`. The AP's Trusted Application verifies them but writes an
**all-zero** output buffer for every modem/boot-chain class (see `FIRMWARE_CONTAINERS_AND_DUML.md`
§1), so the AP never sees plaintext and is not a decryption oracle.

The modem's own console (`/dev/ttyS1`, mirrored to `/blackbox/flight*/sdrs/SDRUART-*.log`) shows
its side of the load:

```
platform: SPARROW2 / target: SPARROW2_ZV902 / buildid: P3P2H_LOCAL
Boot from usb[0], BootMode is usb[2]
SE_SECURE_LCS
verify secure image ... / Begin verify image:cp / Verify success.
no key slot for id=0x45494254
```

`0x45494254` is a four-character key name stored little-endian — `TBIE` — the same name as the
IM\*H `enc_key`. A key-slot miss is logged, yet `Verify success` still prints: signature
verification and symmetric decryption are separate steps, and the key-slot table lives in the
modem, not on the AP. The uploaded bootloader must be decrypted by the modem ROM/OTP before any
AP-supplied material is in play.

The PRAK verification key is different: it is *provisioned by flash* (`modem-pub_key`, and the
factory `cmpu_ver`/`cmpu_kdr` partitions). The symmetric key is not.

## 4. The bootloader is verified

Host-patched copies of the 131,072-byte `/vendor` image were pushed with verified SHA-256 values
and loaded after a GPIO reset. `brload` returns 0 in every case, so its exit code proves nothing;
the signal is whether LK enumerates.

| image | change | result |
|---|---|---|
| stock | — | LK `18d1:d00d` appears |
| signature | one byte at `0x500` (start of the PRAK signature) zeroed | rc 0, **no LK**; device leaves USB |
| header | `IM*H` magic at `0x400` zeroed | rc 0, **no LK** |
| payload | first payload byte at `0x580` zeroed | rc 0, **no LK** |

So the ROM parses the IM\*H wrapper and rejects signature or payload corruption before it jumps.
A custom bootloader cannot be loaded, and a custom bootloader was the only route to the modem's
key slots.

Caution for anyone repeating this: on-device `dd … conv=notrunc` silently does nothing on this
platform. Patch on the host and verify the SHA-256 on the device before loading.

## 5. What the bootloader exposes

Fastboot surface of `18d1:d00d`:

- `flash`/`download` by partition name;
- `getvar version|serialno|product|kernel`; `getvar all` returns `version:0.5`,
  `serialno:0x123456`, `kernel:lk`, `product:eagle-fpga`;
- **no readback**: `oem help`, `oem device-info`, `oem dump` → `unknown command`; `get_staged`
  fails; partition-type/size variables are empty.

The modem is write-only from the AP.

## 6. Factory tooling still present

`/system/bin` ships the production scripts (their payload directory `/tmp/encrypt/` is absent on
retail units):

| script | sequence |
|---|---|
| `get_upload_sparrow2_0.sh` | reset → `brload` → `flash cmpu_ver pro_prak_rsa3k.pub.mon` → `flash cmpu_kdr` (same key) → `fastboot get_staged upload.bin` |
| `pro_sparrow2_0.sh` | reset → `brload` → `flash cmpu_pro bootarea.img` → reboot |
| `burn_otp_sparrow2_0.sh` | `flash cmpu_otp otp.sec` → reboot (**one-time**) |
| `modem_ddr_load.sh` | pigeon/G2 flow: poll for `0040`/`d00d`, `brload pigeon/bootarea.img`, then flash `modem-pub_key`, `modem-share_info`, `modem-rta7_nvram`, `modem-rf_nvram`, `modem-amt`, `modem-package` (= `cp.img`), `modem-normal` |

`dji.json` carries the same manifest (`bootctrl`): `btrom_pid 0040`, `btloader_pid d00d`, the
`reset_pin`, `sys_power_pin`, `fem_power_pin`, and the twelve `gpt`→file pairs flashed at boot.

Do not run `cmpu_otp` (one-time) and treat `cmpu_pro`/`cmpu_kdr`/`cmpu_ver` as trust-state writes.

## 7. Personality switching is a file copy

The agent remounts `/vendor` read-write, copies `<personality>/{cp,ap,dsp,l1c,scp}.img` over the
top-level `/vendor/modem_firmware/sparrow2/*.img`, and the next boot's fastboot flash loads them.
Confirmed by hash: with `za530_lite` active the top-level sizes matched that folder; after a
switch to `wa520` the top-level `cp.img` is byte-identical to `wa520/cp.img`. `/vendor` therefore
diverges from the OTA image after any personality change.

Booting the **engineering** slot changes the personality to its default (`wa520`), because the
engineering build ships only `wa140`/`wa233`/`wa520`. Retail does not switch back on its own
(both values are in its list and `pair_auto_switch=0`), so plan the restore.

## 8. Runtime bulk channels ("BULKMT")

The agent owns four `duss_hal_attach_linux_bulk` devices on the product firmware:

| channel | iface | ep in/out | default | what it carries |
|---|---|---|---|---|
| `/bulk/s2` | 4 | 0x85 / 0x05 | on | live link traffic, logged to `/blackbox/flight*/sdrs/S2Whole-*.log` |
| `/bulk/s2_sdrdump` | 6 | 0x87 / 0x07 | **off** | modem SDR/RAM dump → `dump_store` |
| `/bulk/s2_da` | 7 | 0x88 / 0x08 | on | modem DA log → DLS; optional socket 8902 (off) |
| `/bulk/s2_remotefile` | 8 | 0x89 / 0x09 | on | remote-file channel, protocol not reversed |

The `S2Whole` logs are framed as `f6 64 <u16 total_len>` + payload, small binary records
(10–86 bytes; a 2 MB sample held 29,481 records with no ASCII payloads) and rotate at roughly
100 MB per ten minutes. That is link control/telemetry, not file data.

The only plaintext-relevant path is `dump_v1`. Its parser is described in `dji.json` — magic
`` `~!@#$^&Dump Data: ``, then `Name: <file>`, terminator `^@@^Dump end` — and it writes
`AP_crash.bin`, `CP_crash.bin`, `L1C_crash.bin`, `DSP_crash.bin`. Those are modem-core RAM
images, which would contain loaded (decrypted) firmware. `/system/etc/dji_bb_dls.json` is a
DLS/blackbox variant of the config with this path and the 8902 socket enabled.

Enabling it in `dji.json` (seven `status` leaves) works — interface 6 becomes `usbfs`-bound and
the socket listens — but **nothing arrives at idle**: zero bytes on the socket and no dump files
over a 15-second window. The modem emits dumps only on an event; no AP-side request command is
known. The experiment was reverted and the config hash checked.

## 9. Summary

| operation | possible |
|---|---|
| reset the modem into ROM / LK | yes |
| read modem memory or partitions | no (LK has no readback) |
| flash named partitions | yes (the AP does twelve at every boot) |
| replace the PRAK key / change lifecycle / burn OTP | factory paths exist; trust-state, OTP one-time |
| load a custom bootloader | no — the ROM verifies |
| modify NVRAM (calibration/personality) | yes, by design |
| obtain modem plaintext | no known AP-side path; only an event-triggered dump could, and it is not requestable with known tooling |

## 10. Safety

Everything above was read-only on the modem except the reset/`brload` cycles, which the AP
performs at every boot anyway. The one configuration experiment was reverted with a hash check.
Never touch `bootarea`/`env`/`gpt` partitions, never run `amt_test_cmd`, and never burn OTP.
