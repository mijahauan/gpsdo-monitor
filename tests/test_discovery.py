"""Discovery + disambiguation tests (HID enumeration mocked)."""
from unittest.mock import patch

from gpsdo_monitor.discovery import DeclaredDevice, match
from gpsdo_monitor.hid_xport import HidCandidate


def _cand(serial: str, pid: int = 0x2444, path: bytes = b"/dev/hidraw2") -> HidCandidate:
    return HidCandidate(path=path, vid=0x1DD2, pid=pid, serial=serial,
                        product="LBE-1421", manufacturer="Leo Bodnar Electronics")


def test_singleton_autodetect():
    with patch("gpsdo_monitor.discovery.enumerate_lbe", return_value=[_cand("ABC")]):
        r = match([])
    assert r.ok
    assert len(r.matched) == 1
    assert r.matched[0][1].serial == "ABC"


def test_zero_devices_is_error():
    with patch("gpsdo_monitor.discovery.enumerate_lbe", return_value=[]):
        r = match([])
    assert not r.ok


def test_refuses_to_guess_when_multiple_present_and_none_declared():
    devs = [_cand("ABC"), _cand("XYZ", pid=0x2443, path=b"/dev/hidraw3")]
    with patch("gpsdo_monitor.discovery.enumerate_lbe", return_value=devs):
        r = match([])
    assert not r.ok
    assert "cannot disambiguate" in r.errors[0]


def test_declared_matches_by_serial():
    devs = [_cand("ABC"), _cand("XYZ", pid=0x2443, path=b"/dev/hidraw3")]
    declared = [DeclaredDevice(serial="XYZ", governs=("radiod:aux",))]
    with patch("gpsdo_monitor.discovery.enumerate_lbe", return_value=devs):
        r = match(declared)
    assert r.ok
    assert len(r.matched) == 1
    assert r.matched[0][1].serial == "XYZ"
    assert r.matched[0][0].governs == ("radiod:aux",)
    # ABC is unclaimed; not an error but surfaced
    assert len(r.unclaimed_present) == 1


def test_serial_match_is_case_insensitive():
    devs = [_cand("abc")]
    declared = [DeclaredDevice(serial="ABC")]
    with patch("gpsdo_monitor.discovery.enumerate_lbe", return_value=devs):
        r = match(declared)
    assert r.ok
    assert len(r.matched) == 1


def test_unmatched_declared_entry_is_reported():
    devs = [_cand("ABC")]
    declared = [DeclaredDevice(serial="DOES-NOT-EXIST")]
    with patch("gpsdo_monitor.discovery.enumerate_lbe", return_value=devs):
        r = match(declared)
    assert len(r.matched) == 0
    assert len(r.unmatched_declared) == 1
