"""LBE-Mini protocol driver (placeholder — to be ported from upstream).

The Mini is meaningfully different from the 1420-family:
  - No HID Report ID; every Feature command is a raw 60-byte payload.
  - GPS telemetry arrives as UBX on a HID interrupt-IN endpoint
    (classes: NAV-PVT, NAV-SAT, NAV-CLOCK, MON-VER).
  - No antenna-OK indicator, no OUT2, no 1PPS output, no PLL/FLL toggle.
  - OUT1 drive strength is discrete (8/16/24/32 mA).

See `bvernoux/lbe-142x/src/model_mini.c` for the wire layout and the
reverse-engineering notes at `docs/reverse/LBE-Mini-config-v1.10.md`.
"""
from __future__ import annotations

from gpsdo_monitor.models.base import Capabilities, GpsdoModel, RawStatus


class LbeMini(GpsdoModel):
    name = "lbe-mini"
    pid = 0x2211
    capabilities = Capabilities(
        has_out2=False,
        has_pps=False,
        has_pll_fll_toggle=False,
        has_antenna_flag=False,
        has_drive_ma=True,
        has_ubx_hid=True,
        has_ubx_mon_ver=True,
        max_freq_hz=810_000_000,
    )

    def get_status(self) -> RawStatus:  # pragma: no cover — TODO
        raise NotImplementedError(
            "LBE-Mini status parser not yet ported; see "
            "bvernoux/lbe-142x src/model_mini.c"
        )

    def read_gps_firmware(self) -> str | None:  # pragma: no cover — TODO
        # UBX-MON-VER poll: class 0x0A, id 0x04, no payload. Response
        # payload is [swVersion(30), hwVersion(10), extensions…].
        # Returns "SW=<sw> HW=<hw> PROTVER=<n>" once implemented.
        raise NotImplementedError(
            "UBX-MON-VER poll not yet ported; see upstream model_mini.c"
        )
