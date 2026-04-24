# Schema v1 — runtime contracts

Two contracts ship at schema version `v1`:

1. **`/run/gpsdo/<serial>.json`** — one file per physically present
   device, written atomically on every probe tick.
2. **mDNS `_gpsdo._tcp`** — one advertisement per device, TXT records
   carrying a compact summary of the JSON above.

Both are designed to be additive-only within `v1`: consumers must
ignore unknown fields, and new fields will not change semantics of
existing ones.

## `/run/gpsdo/<serial>.json`

```jsonc
{
  "schema": "v1",
  "written_utc": "2026-04-24T00:01:12.345Z",
  "probe_interval_sec": 10,
  "host": "bee1.local",

  "device": {
    "model": "lbe-1421",                 // lbe-1420 | lbe-1421 | lbe-1423 | lbe-mini
    "pid":   "0x2444",
    "serial":"LBE1421-ABC123",
    "hid_path": "/dev/hidraw2",
    "firmware": null,                    // string if readable, else null
    "firmware_source": "unavailable",    // "ubx-mon-ver" | "unavailable" | "manual"
    "raw_trailing_hex": "00 00 …"        // optional, 1420/1421/1423 only; debug aid
  },

  "governs": ["radiod:main"],            // operator-declared; source of truth

  "health": {
    "pll_locked":     true,
    "fll_mode":       false,             // null if not applicable
    "gps_fix":        "3D",              // "no_fix" | "2D" | "3D" | null
    "sats_used":      9,
    "fix_age_sec":    0.4,
    "antenna_ok":     true,              // null on Mini (no indicator)
    "signal_loss_count": null,           // int on Mini, null elsewhere
    "outputs_enabled": true
  },

  "outputs": {
    "out1_hz":    122880000,
    "out1_power": "normal",              // "normal" | "low"
    "out2_hz":    10000000,              // null if variant has no OUT2
    "out2_power": "normal",              // null if variant has no OUT2
    "pps_enabled": true,                 // null if variant has no PPS
    "drive_ma":    null                  // 8|16|24|32 on Mini, null elsewhere
  },

  "pps_study": {
    "enabled":        true,              // false if disabled in config or unsupported
    "window_sec":     60,
    "edges":          60,
    "period_ms_p50":  1000.00,
    "period_ms_p95":  1000.18,
    "last_edge_utc":  "2026-04-24T00:01:11.998Z",
    "note":           "OS-millisecond bound; not a metrology reference"
  },

  "firmware_advisory": {                 // Mini only today; null elsewhere
    "status":  "current",                // "current" | "outdated" | "unknown"
    "protver": "18.00",
    "notes":   "u-blox M8, PROTVER 18.00 — NAV-SAT supported"
  },

  "a_level_hint":   "A1",                // "A1" | "A0"
  "a_level_reason": "pll_locked && gps_fix=3D && antenna_ok && pps_present && fresh"
}
```

Additionally an aggregate file `/run/gpsdo/index.json` lists all
presently-probed devices with `{serial, model, governs, a_level_hint,
written_utc}` entries for fast TUI consumption.

## A-level mapping

```
A1  iff  pll_locked
   &&   gps_fix in {"2D","3D"}
   &&   (antenna_ok is None or antenna_ok is True)
   &&   (pps_enabled is None or pps_present_in_window)
   &&   fix_age_sec < 30
   &&   probe_age_sec < 2 * probe_interval_sec
A0  otherwise, with `a_level_reason` naming the first failing predicate
```

The probe is a **hint**; `hf-timestd`'s authority manager is the
arbiter and may override on cross-check against T-level witnesses.

## mDNS `_gpsdo._tcp`

One service advertisement per device. Instance name = the serial
(lowercased, HID-safe). Port = 0 (we serve no TCP; this is metadata
only). TXT keys:

```
schema=v1
host=bee1.local
model=lbe-1421
serial=LBE1421-ABC123
governs=radiod:main,radiod:aux       # comma-separated
f1=122880000
f2=10000000                           # absent if variant has no OUT2
pps=true                              # absent if not applicable
a_level=A1
fresh=8                               # seconds since last successful probe
probe_age=3                           # seconds since last JSON write
```

Consumers MUST gate on `schema=v1`. Advertisements are re-published on
any TXT-field change and heartbeat every 60 s; they are withdrawn
immediately when the device disappears from `hid.enumerate()` or when
the daemon shuts down.
