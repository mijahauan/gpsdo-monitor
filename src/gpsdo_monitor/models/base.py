"""Model vtable, Python-side.

Mirrors lbe-142x's `struct lbe_model_ops` (see upstream
`include/lbe_model.h`). Unsupported methods raise `NotImplementedError`
— callers must branch on `capabilities` for user-facing features.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from gpsdo_monitor.hid_xport import HidDevice
from gpsdo_monitor.schema import Health, Outputs


@dataclass
class Capabilities:
    """What this variant supports. Lets the CLI and TUI hide options
    that would be no-ops on the attached model."""

    has_out2: bool = False
    has_pps: bool = False
    has_pll_fll_toggle: bool = False
    has_antenna_flag: bool = False
    has_drive_ma: bool = False
    has_temp_frequency: bool = False
    has_nmea_cdc: bool = False          # 1421/1423: NMEA + DCD 1PPS over CDC
    has_ubx_hid: bool = False           # Mini: UBX stream on interrupt-IN
    has_ubx_mon_ver: bool = False       # Mini only: u-blox firmware readback
    max_freq_hz: int = 0


@dataclass
class RawStatus:
    """Raw status after parsing the HID feature report.

    Model-specific fields are optional; the `health.Health` and
    `schema.Outputs` dataclasses produced by `normalize()` are the
    canonical view consumers see."""

    health: Health
    outputs: Outputs
    firmware: str | None = None
    firmware_source: str = "unavailable"
    raw_trailing_hex: str | None = None
    extras: dict[str, object] = field(default_factory=dict)


class GpsdoModel(ABC):
    """Base class for per-variant protocol drivers."""

    name: str = ""
    pid: int = 0
    capabilities: Capabilities = Capabilities()

    def __init__(self, hid: HidDevice) -> None:
        self.hid = hid

    # --- Mandatory -----------------------------------------------------
    @abstractmethod
    def get_status(self) -> RawStatus: ...

    # --- Optional (raise NotImplementedError by default) ---------------
    def set_frequency(self, output: int, hz: int, *, persist: bool = True) -> None:
        raise NotImplementedError

    def set_outputs_enable(self, enable: bool) -> None:
        raise NotImplementedError

    def set_power_level(self, output: int, low: bool) -> None:
        raise NotImplementedError

    def set_pll_mode(self, fll: bool) -> None:
        raise NotImplementedError

    def set_1pps(self, enable: bool) -> None:
        raise NotImplementedError

    def set_drive_ma(self, ma: int) -> None:
        raise NotImplementedError

    def blink(self) -> None:
        raise NotImplementedError

    def read_gps_firmware(self) -> str | None:
        """Read GPS-module firmware string where available.

        Mini: UBX-MON-VER poll; returns SW version (30B trimmed).
        Others: return None (no documented readback)."""
        return None

    def close(self) -> None:
        self.hid.close()

    def __enter__(self) -> "GpsdoModel":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
