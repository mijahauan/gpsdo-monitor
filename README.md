# gpsdo-monitor

Health monitor, mDNS advertiser, and configurator for
[Leo Bodnar](http://www.leobodnar.com/) GPS-disciplined clock sources
(LBE-1420, LBE-1421, LBE-1423, LBE-Mini).

Built to plug into the [HamSCI](https://hamsci.org) / `sigmond` SDR
management suite and supply an **actively probed A-level** signal to
`hf-timestd`'s authority manager — closing the "GPSDO is hopefully still
disciplining the RX888 ADC" gap — but the daemon stands alone and emits a
simple file + mDNS contract any consumer can read.

## Status

Alpha / skeleton. Design sketch complete; protocol port from
[bvernoux/lbe-142x](https://github.com/bvernoux/lbe-142x) in progress.

## What it does

1. **Detect** Leo Bodnar USB HID devices on the host (VID `0x1DD2`,
   four known PIDs). Refuses to guess when more than one is attached
   and no serial has been declared.
2. **Probe** health at 10 s cadence — PLL lock, GPS fix, antenna
   status, satellites used, fix age, output frequencies, 1PPS
   present/absent, Mini-specific signal-loss count.
3. **Publish** per-device state to `/run/gpsdo/<serial>.json` (schema
   v1, atomic write), and advertise over mDNS as `_gpsdo._tcp` so
   remote consumers (splitter-fed topologies) can read health without
   SSH.
4. **Advise** — emits `a_level_hint` (`A1` / `A0`) and a human-readable
   reason; on the Mini, parses UBX-MON-VER to report u-blox module
   firmware and flag outdated PROTVER.
5. **Configure** — set output frequencies, PPS on/off, PLL/FLL mode,
   drive strength (Mini). Primary surface is `smd gpsdo config` in
   `sigmond`; `gpsdo-monitor config …` is the secondary standalone
   path for manual debugging.

## What it does *not* do

- It is **not** a metrology reference. The PPS stability numbers it
  publishes are OS-millisecond bound (via TIOCMIWAIT on the CDC DCD
  line) and serve as a liveness + gross-stability indicator only.
- It does not discipline the host system clock. That's chrony's job.
- It does not reverse-engineer undocumented opcodes — it stays within
  the feature-report layouts documented by lbe-142x.

## Topology combinations supported

| Case | Description | Configuration |
|------|-------------|---------------|
| A | 1 GPSDO → 1 RX888 → 1 host (default) | autodetect, no explicit config |
| B | N GPSDOs on one host, each governing one radiod | declare `[[device]]` entries with `serial` + `governs` |
| C | N GPSDOs on N hosts | run gpsdo-monitor on each host; consumers use mDNS |
| D | 1 GPSDO → splitter → N RX888s (on one or more hosts) | single instance, `governs = ["radiod:a", "radiod:b", …]` |
| E | No GPSDO (dev / degraded) | not installed; consumers fall back to config-declared A-level |

See [docs/TOPOLOGY.md](docs/TOPOLOGY.md) for concrete examples.

## Credit

The USB HID opcodes, feature-report layouts, model-PID mapping, NMEA
monitor, and UBX stream parsing in this project are ports of the
documentation and reference implementation in
[bvernoux/lbe-142x](https://github.com/bvernoux/lbe-142x) (MIT).
We stay wire-compatible with that tool and credit it as the canonical
protocol reference.

Earlier protocol work by Simon Unsworth
([simontheu/lbe-1420](https://github.com/simontheu/lbe-1420)) seeded
the lbe-142x project.

## License

MIT — see [LICENSE](LICENSE).
