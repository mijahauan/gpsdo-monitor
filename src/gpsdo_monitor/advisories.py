"""Firmware-advisory table lookup.

Data lives in `src/gpsdo_monitor/data/firmware_advisories.toml` and is
loaded on first use. Today this only covers the u-blox PROTVER string
reported by the LBE-Mini — the 1420/1421/1423 have no documented
firmware-readback opcode, so their firmware_advisory block stays
unknown / operator-declared.
"""
from __future__ import annotations

import re
import tomllib
from functools import lru_cache
from importlib.resources import files

from gpsdo_monitor.schema import FirmwareAdvisory


@lru_cache(maxsize=1)
def _load_table() -> dict:
    raw = files("gpsdo_monitor.data").joinpath(
        "firmware_advisories.toml"
    ).read_bytes()
    return tomllib.loads(raw.decode("utf-8"))


def lookup_protver(protver: str | None) -> FirmwareAdvisory:
    """Match a u-blox PROTVER string against the advisory table.

    Returns `FirmwareAdvisory(status="unknown")` when we have no
    PROTVER or no rule matches — the daemon treats that as neutral."""
    if not protver:
        return FirmwareAdvisory(status="unknown", protver=None)
    table = _load_table()
    for rule in table.get("ubx", {}).get("protver", []):
        pattern = rule.get("match")
        if not pattern:
            continue
        if re.match(pattern, protver):
            return FirmwareAdvisory(
                status=rule.get("status", "unknown"),
                protver=protver,
                notes=rule.get("notes"),
            )
    return FirmwareAdvisory(status="unknown", protver=protver)
