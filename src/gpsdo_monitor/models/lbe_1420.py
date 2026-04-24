"""LBE-1420 protocol driver (placeholder — to be ported from upstream).

Shares the "opcode-as-Report-ID" convention with the 1421, but the
status feature report and the `set_frequency` offset differ. Fill in
from `bvernoux/lbe-142x/src/model_1420.c` before first hardware test.
"""
from __future__ import annotations

from gpsdo_monitor.models.base import Capabilities, GpsdoModel, RawStatus


class Lbe1420(GpsdoModel):
    name = "lbe-1420"
    pid = 0x2443
    capabilities = Capabilities(
        has_out2=False,
        has_pps=False,
        has_pll_fll_toggle=True,
        has_antenna_flag=True,
        has_temp_frequency=True,
        has_nmea_cdc=False,
        max_freq_hz=1_600_000_000,
    )

    def get_status(self) -> RawStatus:  # pragma: no cover — TODO
        raise NotImplementedError(
            "LBE-1420 status parser not yet ported; see "
            "bvernoux/lbe-142x src/model_1420.c"
        )
