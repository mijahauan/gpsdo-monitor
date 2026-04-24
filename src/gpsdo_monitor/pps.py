"""1PPS edge capture (LBE-1421 / LBE-1423 CDC DCD line).

Placeholder. Intended design:

  - Background thread running `termios.TIOCMIWAIT` (Linux) on the CDC
    file descriptor, blocking on DCD transitions.
  - For each edge, record `time.monotonic_ns()`.
  - Roll a 60-entry window (one edge per second nominal); expose
    `edges_in_window`, `period_ms_p50`, `period_ms_p95`.
  - OS-millisecond bounded — the jitter numbers are *liveness*
    indicators, not metrology. Documented as such in
    `schema.PpsStudy.note`.
"""
from __future__ import annotations

# Intentionally empty stub.
