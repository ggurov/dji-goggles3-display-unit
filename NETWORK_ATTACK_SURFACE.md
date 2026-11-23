# Network attack surface of a Goggles 3

What listens on the goggles' USB network interface (`rndis0`, `192.168.60.2/24`), what each service
does, and what was actually verified on a **rooted retail v01.00.1300 / build 29020** unit with an
O4-series air unit linked. Work was done on owned hardware; only read-only probes or trivially
reversible actions were used, and no persistent device state was changed.

This is a research note, not a scanner. Findings are version-specific and were not reported to the
vendor as part of this work.

---

## 1. Inventory

```sh
ip -br addr      # lo + rndis0 only; no Wi-Fi interface on this platform
ss -lnutp        # root; maps every port to pid/name
```

| proto | port | process | role |
|---|---|---|---|
| TCP | 1415 | `irisdbgd` | display-controller debug daemon (I3C to the Iris6 at 0x26) |
| TCP | 8902 | `dji_sdrs_agent` | modem DA-log socket (`sdrs_log.channel.da_log_out`) |
| UDP | 9003 | `dji_sw_uav` | UAV-side media transport (same endpoint CosmoViewer uses) |
| UDP | 7400 | `dji_sys`, `dji_sec`, `dji_blackbox` | DDS discovery port (multicast group + wildcard) |
| UDP | 7412/13, 7414/15, 7416/17 | `dji_blackbox`, `dji_sec`, `dji_sys` | DDS discovery endpoints |

`adbd` listens on `127.0.0.1:5037` only. Every daemon above runs as **root** and is an init child, so
a crashed process is respawned automatically. The interface is USB-link-local: the threat model is a
compromised host PC (or any device the host forwards the link to), not the internet.

---

## 2. TCP 1415 — `irisdbgd`: unauthenticated I2C to the display controller

The daemon takes a **fixed 52-byte** message per connection:

| offset | field |
|---|---|
| 0 | magic `0x584F5652` |
| 4 | flags: 1 = read, 2 = write |
| 8 | register / value |
| 24 | data words |
| 40 | count |
| 44 | length (words) |
| 48 | size, must be 4 |

There is no authentication and no source check. Bench-verified over the USB network:

- `flags=1` performs I2C reads and returns the values in the same 52-byte reply.
- `flags=2` performs an I2C write (a read-back of the value just read was used to prove the path
  without changing state).
- a malformed message is logged as `bad magic value in message: 0 != 0x584f5652` and the connection
  is closed.

The read path loops `length` times writing 4-byte words into a 16-byte stack array without a bound.
`length=6` visibly overwrites the adjacent `count`/`length` fields in the reply; `length=24` writes
96 bytes into the frame (canary/return-address region). It does **not** crash: the loop lives in
`main`, whose locals are re-initialised every iteration and whose canary is only checked on return —
which never happens. The practical risk is therefore raw hardware I2C access (wrong power/PLL/panel
registers can damage the display) plus a denial of service: `count × length` sequential I2C
transactions block the single-client accept loop.

Mitigation: stop the daemon when not debugging (`setprop debug.irisdbgd 0`); it only exists for
display bring-up.

---

## 3. TCP 8902 — `dji_sdrs_agent`: modem DA log stream, no auth, one client

`dji.json` maps `sdrs_log.channel.da_log_out` to `{"channel":"socket","port":8902}`, fed by
`modem_da_log` over the `/bulk/s2_da` endpoint. The daemon accepts **one** client, sets a 2 MB send
buffer and never reads from the socket; log bytes are pushed as they arrive.

Verified: a second connection closes the first (`recv` returns EOF) — log hijack/DoS. The stream was
idle on the bench (0 bytes in 20 s); when the modem is logging, this is a plaintext tap on the DA log
(useful for modem research, and an information-disclosure surface otherwise).

---

## 4. UDP 9003 — `dji_sw_uav`: media transport with a single-slot session

The `sw_pro` transport (in `libduml_frwk.so`) binds `0.0.0.0:9003`:

- 20-byte header: `u16` length | `0x8000`, `u16` **session id** at +2, type at +6, XOR checksum of
  bytes 0..6 at +7.
- The length field must equal the datagram length; the checksum and magic bits are checked.
- A session is keyed on the source address and held in a **single slot**. The first valid type-0
  packet of at least 0x2b bytes owns the stream; later clients get `ip or session invalid` until it
  times out (~8 s after the owner stops).

Verified: client A gets telemetry, client B gets nothing while A holds the session, B succeeds after
A times out. The telemetry includes the device serial, so this is unauthenticated information
disclosure plus a trivial squat/DoS of the video/telemetry channel.

The parser tolerated 1,148 crafted datagrams (valid checksums, every type and length from 0x0b to
0x5c0) without a crash. Note the negotiated session id: packets without it are dropped early and
exercise nothing.

---

## 5. UDP 7400/7412–7417 — DDS: loopback-only discovery, but a network crash

The 74xx family is **eProsima Fast DDS** (`libduml_fastrtps.so`, DJI fork). Ports follow the DDS
default layout: 7400 for discovery, `7400 + 2·participant` for the per-participant endpoints
(participants 6/7/8 here).

### Discovery is not reachable

With the air unit streaming (DDS linked), the device-side picture is:

- participants announce SPDP (244-byte RTPS 2.2 packets, vendor `0x010f`, property
  `PARTICIPANT_TYPE=SIMPLE`) from `127.0.0.1` ephemeral ports to `127.0.0.1:7412/7414/7416` every
  few seconds — visible only on `lo`;
- their unicast discovery sockets are bound to `127.0.0.1`;
- `ip maddr` on `rndis0` shows only `224.0.0.1` — the `239.255.0.1` group is **not joined** on the
  USB interface.

A standard CycloneDDS participant on `192.168.60.1` announced SPDP to the multicast group and got no
response. A **cloned** DJI SPDP (real `PARTICIPANT_TYPE=SIMPLE` property, new GUID prefix, locators
rewritten to the host) sent to 7400 and 7412–7417 also drew no reply. The DDS plane is loopback-only
by configuration; it cannot be joined from the network.

### Any byte to 7400 crashes a root service

While the DDS plane is linked, a single UDP datagram to `192.168.60.2:7400` crashes the receiving
process's `DDSListen7400` thread. One byte is enough; content does not matter.

| trigger | result |
|---|---|
| 1 byte, or one SPDP, to 7400 | `dji_sys` SIGSEGV, process respawned |
| 50 × 1-byte burst | `dji_sec` SIGSEGV + `dji_sys` SIGSEGV + `dji_sec` SIGABRT |

Tombstones:

```
signal 11 (SIGSEGV)
Abort message: "Can't get mb_channel, the rmlsync channel attr is not enabled"
#00  UDPChannelResource::perform_listen_operation(Locator_t)+264   libduml_fastrtps.so
signal 6 (SIGABRT): abort+116 <- __fortify_fatal(...)              same abort message
```

Mechanism: `CreateInputChannelResource` allocates a 0x98-byte `UDPChannelResource`, whose constructor
stores a receiver pointer at `+0x38` and starts the listen thread; the listen loop reads a datagram,
then calls a virtual method through `[[this+0x38]]+0x10`. In the crash, `[this+0x38]` points at a
**device-generated JSON event string** (`{"event_id":"fw_0801_temperature…`), so the "vtable" is the
fixed text `{"event` and the call faults. The channel object itself is intact — this looks like a
type-confusion/repurposed slot in the fork's modem-bridge path. A second fault shape occurs when the
chain lands on a heap pointer and the indirect call executes into the heap (`SEGV_ACCERR`).

A pointer-shaped payload (`0x4141…` + filler) lands exactly in the channel's pre-allocated receive
buffer (`[this+8]`), not in the object; there is no packet-driven allocation or free of the channel
before the call, and the first datagram crashes, so there is no heap-grooming window. Even a
redirected pointer into another event string would hit fixed JSON text, and there is no address leak.
**This is a DoS, not a controllable call.**

Impact: unauthenticated remote crash loop of `dji_sys`/`dji_sec` (root). init respawns them; the
live view kept running in our tests, but `dji_sys` is the system state machine, so a sustained flood
is disruptive. The same probes with the air unit **off** did not crash — the bad path is gated on the
linked DDS state.

---

## 6. Non-vector found along the way

`dji_blackbox` also runs a 196-byte UDP "log file info" command interface (cmd 1 = add file, cmd 2 =
delete, bounded filename, `..` and system directories rejected), but it binds `127.0.0.1:10778` —
not reachable from the USB network.

---

## 7. Practical guidance

- Treat the goggles' USB network as a hostile link: host-firewall `1415`, `8902`, `9003` and
  `7400–7417` to the tools that need them.
- Avoid port scans or UDP probes against `7400` while the air unit is streaming — a single packet
  restarts root services.
- `irisdbgd` is a debug daemon; stop it when not doing display bring-up.
- The DDS plane is loopback-only; do not expect to join it from the host.

## 8. What was not done

No I2C writes that changed state, no fuzzing beyond the bounded 9003/1415 sets, no forged DDS
data-plane traffic (impossible without discovery), no persistent firmware/config changes. The
`7400` crash was reproduced repeatedly, then stopped; services were confirmed back up afterwards.
