"""Firmware-advisory table tests."""
from gpsdo_monitor.advisories import lookup_protver


def test_protver_18_is_current():
    a = lookup_protver("18.00")
    assert a.status == "current"
    assert a.protver == "18.00"
    assert a.notes and "NAV-SAT" in a.notes


def test_protver_13_is_outdated():
    a = lookup_protver("13.01")
    assert a.status == "outdated"
    assert a.protver == "13.01"


def test_protver_22_is_current_newer_constellation():
    a = lookup_protver("22.00")
    assert a.status == "current"
    assert "M9/M10/F9" in (a.notes or "")


def test_protver_missing_yields_unknown():
    a = lookup_protver(None)
    assert a.status == "unknown"
    assert a.protver is None


def test_protver_unmatched_is_unknown_but_keeps_value():
    a = lookup_protver("99.99")
    assert a.status == "unknown"
    assert a.protver == "99.99"
