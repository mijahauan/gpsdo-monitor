"""UBX reader for LBE-Mini (HID interrupt-IN).

Placeholder — see `bvernoux/lbe-142x/src/model_mini.c` for the
frame-reassembly logic and the messages of interest: NAV-PVT (UTC +
fix), NAV-SAT (per-SV CNR), NAV-CLOCK (clock stats), MON-VER (firmware
strings). All UBX messages sync on 0xB5 0x62 with a Fletcher-8
checksum, so frame boundaries can be recovered after packet loss.
"""
from __future__ import annotations

# Intentionally empty stub.
