"""NMEA + 1PPS reader for LBE-1421 / LBE-1423.

Placeholder — to be filled in once hardware bring-up begins. The
upstream `bvernoux/lbe-142x/src/nmea.c` handles RMC / GGA / GSA / GSV
and the CDC DCD-line 1PPS edge is captured via TIOCMIWAIT (Linux) or
GetCommModemStatus (Windows). For our daemon we only need:

  - port discovery (match first /dev/ttyACM* whose stream starts with "$G")
  - RMC/GGA/GSA parsing for gps_fix, sats_used, fix_age_sec
  - DCD edge capture for pps.py's rolling period window
"""
from __future__ import annotations

# Intentionally empty stub; see models/lbe_1421.py for the consumer.
