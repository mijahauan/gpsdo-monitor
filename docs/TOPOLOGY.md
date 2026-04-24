# Topology combinations

`gpsdo-monitor` is the source of truth for the GPSDO↔radiod mapping.
The `governs` list on each device flows outward to:

- `/run/gpsdo/<serial>.json` (consumers on the same host)
- the mDNS TXT `governs=` record (consumers on any host on the LAN)
- `hf-timestd`'s `authority.json` via its `GpsdoProbe` (local) or
  `GpsdoMdnsProbe` (remote) — populates `a_level_detail.governs_radiod`

`sigmond`'s `harmonize.py` cross-checks: every radiod instance named
in `coordination.toml` must have exactly one governor in any reachable
`governs` list; zero governors warns (A0 implied); two or more is an
error.

## Case A — singleton (most common)

One host, one LBE device attached, one radiod. Zero config required.

```toml
# /etc/gpsdo-monitor/config.toml
[monitor]
# autodetect: the single attached device with no serial disambiguation
```

`hf-timestd`:

```toml
[timing.authority]
a_level_source = "local:auto"
```

## Case B — N GPSDOs on one host, N radiods

Two GPSDOs on the same machine, one per RX888.

```toml
# /etc/gpsdo-monitor/config.toml
[monitor]
probe_interval_sec = 10

[[monitor.device]]
serial  = "LBE1421-ABC123"
governs = ["radiod:main"]

[[monitor.device]]
serial  = "LBE1420-XYZ789"
governs = ["radiod:aux"]
```

Daemon refuses to start if two devices are present without disambiguating
entries (matches lbe-142x's `--pid` refusal semantics).

## Case C — N GPSDOs on N hosts

Each host runs its own gpsdo-monitor instance; hf-timestd on the
fusion host subscribes via mDNS:

```toml
[timing.authority]
a_level_source = "mdns:serial=LBE1421-ABC123"
```

## Case D — splitter: 1 GPSDO → N RX888s

GPSDO-host advertises a single device with a multi-entry `governs`
list:

```toml
# /etc/gpsdo-monitor/config.toml on the GPSDO host
[[monitor.device]]
serial  = "LBE1421-SHARED"
governs = ["radiod:main", "radiod:aux", "radiod:host2-main"]
```

Consumers on other hosts subscribe by serial (not by host):

```toml
# /etc/hf-timestd/timestd-config.toml on host2
[timing.authority]
a_level_source = "mdns:serial=LBE1421-SHARED"
```

This decouples consumers from GPSDO-host routing, so DHCP / hostname
changes (the 2026-04-18 ScreenPi4 incident class) don't silently
strand A-level probes.

## Case E — no GPSDO (dev / degraded)

Don't install gpsdo-monitor. hf-timestd falls back to its existing
config-declared A-level string, preserving current behavior.

## Failure modes and their effects

| Scenario | `/run/gpsdo/*.json` | mDNS | `a_level_hint` | Authority effect |
|----------|---------------------|------|----------------|------------------|
| PLL unlocks | still written, `pll_locked=false` | TXT `a_level=A0` refreshed | A0 | authority downgrades per §4.5 |
| Antenna fault (1421/1423) | `antenna_ok=false` | `a_level=A0` | A0 | downgrade |
| GPS loses fix | `gps_fix="no_fix"` | `a_level=A0` | A0 | downgrade |
| USB unplugged | file removed + atomic index update | advertisement **withdrawn** | n/a | authority loses probe → A0 |
| gpsdo-monitor daemon crashes | file stale (`probe_age_sec` grows) | advertisement expires after TTL | authority reads `probe_age_sec > 2 × interval` → A0 |
| PPS silent (1421/1423) | `pps_study.edges` drops to 0 | `a_level=A0` reason=`pps_silent` | A0 | downgrade |
| Mini signal-loss count increments | field updated | no a_level change unless PLL actually drops | A1 (informational) | — |

The design goal: any failure mode the operator cares about produces a
visible `A0` with a named reason within 2 × probe_interval_sec (≤ 20 s
default).
