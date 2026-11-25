# Root on a locked retail Goggles 3 (V5)

A stock, never-rooted retail DJI Goggles 3 on **v01.00.1300 / build 29020** can be given
**root ADB from a PC over USB** with one DUML frame. That is the method
[toolya](https://toolya.dev/app) ([grom-labs/toolya](https://github.com/grom-labs/toolya))
uses; the path was theirs first, and what follows is our own verification of it on one unit.
Nothing is written to flash: ADB, SELinux state and the USB layout all revert at the next
reboot.

From that shell, two more things work:

- **SELinux permissive** with a single kernel byte (`setenforce` is neverallowed).
- **RNDIS and ADB at the same time**, which is how the engineering "display units" boot anyway.

Everything here was done on **one** retail unit, a **V5** board (`androidboot.hw_version=04.04.01.00`).
Section 6 compares it with the V4 engineering donors the rest of this repository is about:
same firmware, different board and bootloader state.

> **Scope and risk.** This is an unauthorised modification of your own device. It very likely
> breaches DJI's terms of service (account suspension, lost warranty), is runtime-only, and
> every step below writes to live kernel or service state. Use it only on hardware you own.
> `/system` on a retail unit is dm-verity protected in mode 2: editing it and rebooting bricks
> the unit, with no known recovery.

---

## 1. What a stock retail unit looks like

Read from the running unit once ADB was up:

| | Stock retail (V5) |
|---|---|
| Build | `e3t_zv902-userdebug 9 PD1A.180720.031 29020 test-keys`, `ro.dji.build.version=10.00.59.40` |
| Kernel | `5.4.123-rt59-g9f5c230d0af7-ab29020`, image loaded at physical `0x80000` |
| Bootloader cmdline | `mp_state=production androidboot.secure_debug=0 androidboot.verity=1 androidboot.selinux=enforcing console=secS0` |
| Stock USB | `rndis,mass_storage,bulk,acm`: MI_00 RNDIS, MI_02 mass storage, MI_03–MI_07 `ff/43/01` vendor, no ADB |
| SELinux | enforcing |
| `/system` | dm-verity: `init: [libfs_mgr]Enabling dm-verity for system (mode 2)`, mounted through `dm-0` |
| `dji.json` | 9 `support_type` entries, the same table the donors have |

The firmware is `userdebug` with `ro.debuggable=1` and `adbd` running as uid 0, so once ADB is
exposed there is no further step to root. ADB is simply left out of the stock USB config, by
`/system/bin/setup_usb.sh` (section 5).

---

## 2. The ADB enable

### 2.1 The frame

```
550e04662a1b112740076401349d
```

`0x55 | len | ver/flags | crc8 | 2a 1b 11 27 40 07 64 01 | crc16(LE)` = host `0x2a` to `0x1b`
(`dji_network`), sequence `0x2711`, ack `0x40`, **cmd_set `0x07`, cmd_id `0x64`, payload `01`**,
sent on vendor interface 4 (bulk OUT `0x04`, IN `0x85`, VID `2CA3` PID `0020`).

It is the same `07`-class "engpc mode" start that [FIRMWARE_CONTAINERS_AND_DUML.md](FIRMWARE_CONTAINERS_AND_DUML.md) §5
describes from the binary: the handler runs `setprop sys.usb.config none`, then
`rndis,mass_storage,bulk,acm`, then `acm,adb`, and forks `dji_engpc`. The command id is still an
empirical result, not a disassembly result: the dispatch table is built at runtime. toolya sends
`0x64` first and falls back to scanning `0x60–0x6F`; on 29020 `0x64` is enough.

Before the frame, replay DJI Assistant's init handshake on the same pipe: four frames
(`2a→1f 00/01`, `2a→5c 00/51`, `2a→9c 00/32` twice), then 24 acks to `0xbc`
(`00/4f`, 1000-byte flow). The device answers a fragmented XML that ends in `</dji>` and
reports `id="zv902"`, `formal="01.00.1300"`. The handshake is not strictly required for
read-only probes, but it is how both Assistant and toolya confirm the pipe is alive.

### 2.2 What happens

- The gadget is torn down **0.1 s** after the frame and comes back as `acm,adb`: MI_00 a USB
  serial port, MI_02 the ADB interface (`ff/42/01`).
- Windows binds the ADB interface to inbox `winusb.inf` on its own, and `adb devices` shows the
  unit as `device` with no RSA prompt (`ro.adb.secure` is empty).
- The shell is `uid=0`, `u:r:su:s0`. `dji_engpc` is left running.

### 2.3 The host side (Windows)

- **DJI Assistant 2 binds MI_03–MI_07 to its libusb-win32 driver.** Only the composite parent
  registers `GUID_DEVINTERFACE_USB_DEVICE`, and Chrome's WebUSB cannot open the device, so
  toolya in a browser stops before the handshake. toolya's instruction is right: rebind
  **MI_04** to **WinUSB** with [Zadig](https://zadig.akeo.ie).
- The rebind costs DJI Assistant its bulk path on MI_04 until the package is removed
  (`pnputil /delete-driver <oemNN.inf> /uninstall`). Zadig also adds a per-device libwdi
  certificate to the trusted publisher and root stores.
- **The libusb route does not need WinUSB.** `retail_root/enable_adb.py` talks to MI_04 on DJI's
  own libusb-win32 driver (libusb0) or on WinUSB (libusb-1.0), whichever is installed.
- Once ADB is up, libusb-1.0 **cannot open the unit at all while the adb server is running**: it
  opens every WinUSB interface of the composite and the ADB interface answers
  `ERROR_ACCESS_DENIED`. Stop the server (`adb kill-server`) if you need the DUML pipe again.

### 2.4 The pipe can be dead

| Event | DUML pipe afterwards |
|---|---|
| Boot with the cable attached | answers |
| Device-side USB reconfig (`sys.usb.config none → …`, section 5) | answers |
| Reboot | answers |
| **Host-side driver swap** that re-enumerates the unit while it runs | **silent until a reboot** |

Silent means: bulk OUT is still accepted at once, every vendor IN endpoint stays idle, and not
even the read-only `00/01 → 0x1b` gets an answer. toolya shows it as `iface 4: no </dji>`.
It was observed after the Zadig rebind, and once more from the first enumeration of a session
until a reboot. A plain cable re-plug was not isolated (the one re-plug of the session came with
a reboot). The cause inside `dji_network` is unknown.

Practical rule: after changing a host driver, reboot the goggles before using toolya or the
script.

### 2.5 The script

```
pip install pyusb libusb-package            # same dependencies as goggles_tool
python retail_root/enable_adb.py            # handshake only: prints the firmware (read-only)
python retail_root/enable_adb.py --enable   # + 07/64, waits for adb, prints uid and build
python retail_root/enable_adb.py --enable --wait 900    # poll until DUML answers
```

It runs the handshake, sends the enable only after `</dji>` came back, refuses to act when more
than one goggles is on USB (they share VID:PID and serial; `--bus/--address` selects) or when
`adb devices` already shows one, and needs no browser. `adb` is taken from `--adb`, `$ADB` or
PATH. `--scan` adds toolya's `0x60–0x6F` fallback, which sends unknown `07`-class commands; it
was never needed on 29020.

---

## 3. SELinux permissive

`setenforce 0` is refused for the shell (neverallow), but `/dev/mem` is open to the uid-0 shell
**even while enforcing**. Reads succeed across System RAM (checked at `0x10000000` and
`0x30000000`); only ranges that `/proc/iomem` lists as reserved fail with `Bad address`, which
is why a sequential `dd` stops just past the kernel. Writes were made only inside the kernel
image. `selinux_state.enforcing` is one byte there:

| Kernel | `selinux_state` (physical) | `enforcing` at |
|---|---|---|
| `5.4.123-rt59-g9f5c230d0af7-ab29020` | `0x17b6648` | `+1` |

```
adb shell /sbin/busybox devmem 0x17b6648 32      # 0x01000100 = enforcing, 0x01000000 = permissive
adb shell /sbin/busybox devmem 0x17b6649 8 0x00  # permissive
adb shell /sbin/busybox devmem 0x17b6649 8 0x01  # back to enforcing
```

Check with `getenforce` and `cat /sys/fs/selinux/enforce`. The same address is toolya's first
constant (it also tries `0x17e6888`, which reads 0 on this build). Before the write the 32 bytes
at `selinux_state` are `00 01 00 01 01 01 01 00`, eight zero bytes, then two pointers to
`selinux_avc` and `selinux_ss`.

Two things this does **not** change:

- **init keeps enforcing on its own side.** init's userspace AVC reads the mode once at boot, so
  `setprop sys.usb.config …` from the shell is still refused with
  `(init) selinux: avc: denied { set } for property=sys.usb.config … permissive=0`.
- **The store skips what the kernel does on a real switch** (AVC reset, netlink and status-page
  notification). Permissive takes effect at once; previously denied reads worked right after.

It reverts on reboot.

---

## 4. Kernel symbols without vmlinux

The address in section 3 is kernel-build specific, and there is nothing to take it from:

- `/proc/kallsyms` is empty on this kernel, even permissive as root (`kptr_restrict=0`).
- `/proc/config.gz` does not exist.
- `normal.img` in the OTA is an encrypted IM\*H container (uniform byte statistics, no Image
  header), so the kernel cannot simply be extracted from the update.

The kernel's own kallsyms tables are in memory, and `/dev/mem` reaches them:

```
adb exec-out "dd if=/dev/mem bs=4096 skip=128 count=7728 2>/dev/null" > kdump.bin
python retail_root/kallsyms_from_dump.py kdump.bin --write syms.txt --grep selinux_state
python retail_root/disasm_fn.py kdump.bin sel_read_enforce --kallsyms syms.txt   # pip install capstone
```

```
relative_base=0xffffffc010080000 num_syms=86569 kallsyms_offsets@dump+0xb0fc80 names@dump+0xb64538
0xffffffc0117b6648 phys 0x017b6648 Bselinux_state
```

How the address was pinned before writing to it:

1. `kallsyms_from_dump.py` rebuilt the table: 86,569 symbols. The tables are
   `offsets[] | relative_base | num_syms | names | markers[] | token_table[] | token_index[]`,
   and **every one of them is 8-aligned**. A 4-aligned start of `offsets[]` pairs each name
   with its neighbour's address, which still yields a plausible-looking table. Check a symbol
   with a known value first: `kimage_voffset` must hold `0xffffffc010000000`.
2. The object itself matches `struct selinux_state`: `+16` points at `selinux_avc`
   (`0x17ad628`), `+24` at `selinux_ss` (`0x17bb2d0`).
3. `sel_read_enforce` (behind `/sys/fs/selinux/enforce`) reads the flag as
   `ldrb w3, [x3, #1]` on `fsi->state`.

Delete the memory dump afterwards; it is a snapshot of live kernel memory.

---

## 5. USB: RNDIS and ADB together

`acm,adb` drops RNDIS and mass storage. The configuration that has both is the donors' stock one:
`rndis,mass_storage,bulk,acm,adb`.

### 5.1 Why the stock unit does not have it

`/system/bin/setup_usb.sh` (service `setup_usb`, started by `init_usb2` from `/init.rc`) decides
once per boot:

| Condition | USB config |
|---|---|
| `mp_state=production` **and** `secure_debug=0` | `none` → `rndis,mass_storage,bulk,acm` (no ADB; also clears `/blackbox/system/adb/*`) |
| anything else | `none` → `rndis,mass_storage,bulk,acm,adb` (`acm,adb` if `/data/wifi_factory` exists) |

So the same retail firmware gives a display unit ADB and a retail unit none. The triggers live
in `/system/etc/init/init.e3t.usb.rc`: the `rndis,mass_storage,bulk,acm,adb` trigger links
f1 rndis, f2 mass_storage, f3–f7 the five FunctionFS bulk instances, f8 adb into
`/sys/kernel/config/usb_gadget/g1/configs/c.1`, then binds `f9100000.usb`. The `none` trigger
unbinds, **runs `stop adbd`**, and removes f1–f8.

### 5.2 What it takes from a shell

- **`setprop sys.usb.config` must run as init**: `runcon u:r:init:s0 /system/bin/setprop …`.
  The kernel is permissive at this point, init's userspace check is not (section 3).
- **The `none` step is required.** Setting the target while the gadget is still bound changes
  nothing on the wire (the new links collide with f1/f2, the UDC write is refused) but still
  sets `sys.usb.state`, so the props then disagree with the real layout.
- **The second step must not come from the adb shell.** `stop adbd` makes init kill adbd's whole
  cpuacct cgroup (`/acct/uid_0/pid_<adbd>`), helper processes included. A helper that is in its
  own session and moved to the cgroup root survives:

```
adb shell "setsid sh -c 'echo \$\$ > /acct/cgroup.procs; sleep 3; runcon u:r:init:s0 /system/bin/setprop sys.usb.config rndis,mass_storage,bulk,acm,adb' >/dev/null 2>&1 & sleep 0.5; runcon u:r:init:s0 /system/bin/setprop sys.usb.config none"
```

The shell dies at `none`; about 4 s later ADB is back on MI_08 with RNDIS on MI_00 and mass
storage on MI_02, and SELinux stays permissive.

Without the `/acct/cgroup.procs` move the helper dies and **USB stays off** until the goggles
are rebooted. That happened once here; after the reboot the sequence was: enable ADB (2.5),
write the permissive byte (3), retry.

### 5.3 On the host afterwards

| Interface | Driver |
|---|---|
| MI_00 RNDIS | `usbrndis6` |
| MI_02 mass storage | `USBSTOR` |
| MI_03, MI_05, MI_06, MI_07 | DJI Assistant's libusb-win32 |
| MI_04 | still WinUSB (the Zadig rebind survives re-enumerations) |
| MI_08 ADB | `winusb.inf` |

- The gadget's RNDIS MACs are random on every bind, so Windows presents a **new** network
  adapter each time and `192.168.60.1/24` has to be set on it again (the goggles are
  `192.168.60.2`, no DHCP).
- TCP 21 (`dji_ftpd`) and 1415 (`irisdbgd`) are reachable from the host in this state; see
  [NETWORK_ATTACK_SURFACE.md](NETWORK_ATTACK_SURFACE.md).

---

## 6. The V5 retail next to the V4 engineering donors

The retail unit and the engineering "display units" running the same retail build 29020 on
slot 2 share the partition table (24 partitions, same sizes) and the firmware images. What
differs is the board, the bootloader's state, and what was done to the donors.

| | Locked retail | Engineering donors on retail 29020 |
|---|---|---|
| Board | V5: `androidboot.hw_version=04.04.01.00`, DT model `DJI E3T ZV902 V5 platform` | V4: `04.03.01.06`, DT `… V4 platform` |
| Bootloader cmdline | `mp_state=production`, `secure_debug=0`, `verity=1`, `selinux=enforcing`, `console=secS0`, `ps_thres=4000,150` | `mp_state=factory`, `secure_debug=1`, `verity=0`, `selinux=permissive`, `console=ttyS0`, `ps_thres=4095,1113` |
| Active slot 2 | build 29020, installed from DJI's signed v10.00.59.40 package | build 29020, flashed by hand ([RUNBOOK.md](RUNBOOK.md)) |
| Slot 2 images | `system_2`, `normal_2`, `tos_2`, `scp_2` sha1-identical to the OTA images in [MANIFEST.md](MANIFEST.md) | the same files |
| `vendor_2` | differs from the OTA image only in the five top-level `modem_firmware/sparrow2/*.img`, which are copies of the active modem personality | the same mechanism; a donor on `wa520` has the `wa520` copies there |
| Slot 1 | an older retail build (21787, July 2025) with 7 `support_type` entries | the engineering OS (build 9998 / 3062), the always-bootable root fallback |
| `/system` at boot | dm-verity, mode 2 | raw partition on their engineering slots (their bootloader passes `verity=0`); the mount on their retail slot was not re-checked |
| Stock USB | no ADB | ADB on MI_08 |
| SELinux at boot | enforcing | permissive |
| `dji.json` | 9 entries | 9 entries |

Consequences:

- The donors are engineering boards. Anything that depends on the secure path (TA behaviour,
  `dji_fw_verify`, modem key handling, see [MODEM_LOAD_CHAIN.md](MODEM_LOAD_CHAIN.md)) has to be
  re-checked on a production unit before it is assumed to hold there.
- A donor-style edit of `/system` (the HMS list fix in `post_flash_fixups.ps1`) would brick a
  retail unit: verity mode 2 has no recovery on this hardware.
- Slot 1 of a retail unit is not a fallback in the donor sense. It gives no root, no ADB and no
  non-production boot path, so the flash scripts in this repository were not attempted on it.

---

## 7. What was not done

- toolya's own interface (its Enable button completing, its shell, natartos, its dm-verity
  toggle) was not driven end to end; the packet was replayed from the script on the same
  interface.
- Nothing persistent: no file on `/system`, `/vendor` or `/data` was changed for this write-up.
- Whether a plain cable re-plug without a reboot keeps ADB in the section 5 configuration.
- One unit only. Other board revisions and firmware builds need the address in section 3 pinned
  again, as described in section 4.

---

## 8. Files

| File | Needs | Purpose |
|---|---|---|
| `retail_root/enable_adb.py` | pyusb, libusb-package, `goggles_tool` (checked out next to it or `pip install -e goggles_tool`) | handshake, `07/64` enable, optional scan, waits for adb |
| `retail_root/kallsyms_from_dump.py` | none | rebuild the symbol table from a `/dev/mem` dump of the kernel |
| `retail_root/disasm_fn.py` | capstone | disassemble one kernel function out of that dump |
| `retail_root/img_tree_hashes.py` | [pyext4](https://pypi.org/project/ext4/) | sha1 of every file in an ext4 image, to diff it against a live partition |
