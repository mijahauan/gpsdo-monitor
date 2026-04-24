"""Tests for the probe daemon — NmeaReader + Service end-to-end tick.

Hardware is replaced by fakes: fake hidapi `device` for HID feature
reads, fake `serial.Serial` for the NMEA line stream, and a
monkeypatched PpsTracker so no real tty is opened. The daemon still
runs its real code paths: DeviceWorker composition, classify(),
atomic_write of /run/gpsdo/<serial>.json, and the index file.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import pytest

from gpsdo_monitor.config import Config, DeclaredDevice
from gpsdo_monitor.hid_xport import HidCandidate
from gpsdo_monitor.nmea import NmeaReader
from gpsdo_monitor.schema import PpsStudy
from gpsdo_monitor.service import DeviceWorker, Service

# Live NMEA captures from bee1's 1421 — same fixtures used by test_nmea.
RMC_VALID = "$GNRMC,024825.40,A,3855.12213,N,09207.65474,W,0.001,,240426,,,D*73"
GGA_FIX   = "$GNGGA,024825.40,3855.12213,N,09207.65474,W,2,10,0.48,265.6,M,-30.7,M,,0000*7D"
GSA_3D    = "$GNGSA,A,3,10,32,23,28,02,24,25,12,31,01,,,0.91,0.48,0.77*10"


# --- Fakes ----------------------------------------------------------------


class _FakeSerial:
    """Stand-in for pyserial.Serial that hands out pre-queued lines.

    `readline` returns each line in turn (with the trailing \\r\\n
    pyserial would give us); once the queue is empty it returns b""
    to simulate a read timeout — same as the real driver does when no
    bytes arrive within the timeout window."""

    SerialException = OSError

    def __init__(self, lines: list[str]) -> None:
        self._lines = [ln.encode("ascii") + b"\r\n" for ln in lines]
        self.closed = False

    def readline(self) -> bytes:
        if self.closed:
            raise OSError("port closed")
        if not self._lines:
            return b""
        return self._lines.pop(0)

    def close(self) -> None:
        self.closed = True


def _install_fake_serial(monkeypatch, lines: list[str]) -> None:
    """Monkeypatch the lazy `import serial` inside nmea.NmeaReader."""
    import sys
    import types

    mod = types.ModuleType("serial")
    mod.Serial = lambda *a, **kw: _FakeSerial(lines)         # type: ignore[attr-defined]
    mod.SerialException = OSError                             # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "serial", mod)


class _FakeHid:
    """Enough of hid_xport.HidDevice for a fake device to build a
    status RawStatus via the real Lbe1421 driver."""

    def __init__(self, feature_reports: dict[int, bytes]) -> None:
        self._feature_reports = feature_reports
        self.writes: list[tuple[int, bytes]] = []

    def feature_get(self, report_id: int, length: int = 60) -> bytes:
        buf = self._feature_reports[report_id]
        assert len(buf) == length
        return buf

    def feature_set(self, report_id: int, payload: bytes) -> None:
        self.writes.append((report_id, bytes(payload)))

    def close(self) -> None:
        pass


def _locked_1421_status_buf() -> bytes:
    """60-byte HID status payload for a fully-locked 1421: PLL, GPS,
    antenna all set; OUT1=10 MHz, OUT2=27 MHz; PPS enabled."""
    from gpsdo_monitor.models.lbe_1421 import (
        ANT_OK_BIT, GPS_LOCK_BIT, OUT1_EN_BIT, OUT2_EN_BIT,
        PLL_LOCK_BIT, PPS_EN_BIT,
    )
    buf = bytearray(60)
    buf[0] = 0x4B
    buf[1] = (GPS_LOCK_BIT | PLL_LOCK_BIT | ANT_OK_BIT
              | OUT1_EN_BIT | OUT2_EN_BIT | PPS_EN_BIT)
    buf[6:10] = (10_000_000).to_bytes(4, "little")
    buf[14:18] = (27_000_000).to_bytes(4, "little")
    return bytes(buf)


def _fake_candidate(serial: str = "TEST1421") -> HidCandidate:
    return HidCandidate(
        path=b"/dev/null-fake",
        vid=0x1DD2,
        pid=0x2444,       # 1421
        serial=serial,
        product="LBE-1421 GPSDO Locked Clock Source",
        manufacturer="Leo Bodnar Electronics Ltd",
    )


# --- NmeaReader tests -----------------------------------------------------


def test_nmea_reader_continuously_updates_state(monkeypatch, tmp_path):
    """Lines pushed through the fake serial update the shared state;
    snapshot() returns the freshest view on every call."""
    _install_fake_serial(monkeypatch, [RMC_VALID, GGA_FIX, GSA_3D])
    rdr = NmeaReader(tmp_path / "fake-tty")
    rdr.start()
    try:
        # Let the worker consume all three lines plus the empty-queue
        # readline that signals EOF-for-now.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            snap = rdr.snapshot()
            if snap.gps_fix == "3D" and snap.sats_used == 10:
                break
            time.sleep(0.01)
        snap = rdr.snapshot()
        assert snap.gps_fix == "3D"
        assert snap.sats_used == 10
        assert snap.last_rmc_valid_wall is not None
    finally:
        rdr.stop(timeout_sec=1.0)


def test_nmea_reader_records_open_error_when_port_missing(monkeypatch, tmp_path):
    """A bad tty path should not crash the reader — snapshot stays
    empty and open_error records the reason."""
    import sys
    import types
    mod = types.ModuleType("serial")

    def _raising(*a, **kw):
        raise OSError("no such device")
    mod.Serial = _raising                                     # type: ignore[attr-defined]
    mod.SerialException = OSError                             # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "serial", mod)

    rdr = NmeaReader(tmp_path / "no-such-tty")
    rdr.start()
    try:
        deadline = time.monotonic() + 0.5
        while rdr.open_error is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert rdr.open_error is not None
        assert "no such device" in rdr.open_error
        # Snapshot is still safe to call.
        assert rdr.snapshot().gps_fix is None
    finally:
        rdr.stop(timeout_sec=1.0)


# --- Service end-to-end tick ---------------------------------------------


def _install_fake_hidapi(monkeypatch, status_buf: bytes) -> None:
    """Replace the `hid` module object already bound inside hid_xport so
    HidDevice uses our fake `hid.device()` / `open_path` / etc."""
    import types

    from gpsdo_monitor import hid_xport

    class _FakeDevice:
        def open_path(self, path: bytes) -> None:
            pass

        def get_feature_report(self, report_id: int, length: int):
            # hidapi returns a list of ints; return our fixture directly.
            return list(status_buf[:length])

        def send_feature_report(self, payload: bytes) -> int:
            return len(payload)

        def read(self, length: int, timeout_ms: int = 0):
            return []

        def close(self) -> None:
            pass

    fake = types.SimpleNamespace(
        device=_FakeDevice,
        enumerate=lambda *a, **kw: [],
    )
    monkeypatch.setattr(hid_xport, "hid", fake)


@pytest.fixture
def locked_1421_service(monkeypatch, tmp_path):
    """Service configured with one fake LBE-1421 that reads as nominal
    A1 via HID + NMEA. PPS tracker is stubbed so no tty is needed."""
    _install_fake_serial(monkeypatch, [RMC_VALID, GGA_FIX, GSA_3D])
    _install_fake_hidapi(monkeypatch, _locked_1421_status_buf())

    candidate = _fake_candidate("TEST1421")
    declared = DeclaredDevice(serial="TEST1421", governs=("radiod:main",))

    # Force discovery to return exactly our fake candidate pair.
    from gpsdo_monitor import service as svc
    from gpsdo_monitor.discovery import DiscoveryResult
    monkeypatch.setattr(
        svc, "match",
        lambda _devs: DiscoveryResult(
            matched=((declared, candidate),),
            unmatched_declared=(), unclaimed_present=(), errors=(),
        ),
    )

    # Point the tty discovery at a real path we control so NmeaReader
    # tries to open it — our fake serial module handles the actual open.
    monkeypatch.setattr(
        svc, "find_ttys_by_usb_serial",
        lambda serial: [tmp_path / "fake-tty"],
    )

    # PpsTracker: replace with a stub that records start/stop calls and
    # returns a canned snapshot. Using the real TIOCMIWAIT path would
    # require a real tty.
    class _FakePps:
        def __init__(self, *, window_sec: int = 60) -> None:
            self.window_sec = window_sec
            self.started = False
            self.stopped = False

        def start(self, tty_path) -> None:
            self.started = True

        def stop(self, *, timeout_sec: float = 2.0) -> None:
            self.stopped = True

        def snapshot(self) -> PpsStudy:
            # Emit a healthy nominal 60-edge window so classify() can
            # reach A1 with pps_expected=True.
            return PpsStudy(
                enabled=True, window_sec=60, edges=60,
                period_ms_p50=1000.0, period_ms_p95=1000.2,
            )

    monkeypatch.setattr(svc, "PpsTracker", _FakePps)

    # mDNS off — nothing stops unit tests faster than avahi confusion.
    cfg = Config(
        probe_interval_sec=1,
        run_dir=tmp_path / "run-gpsdo",
        pps_study_enabled=True,
        mdns_enabled=False,
        devices=[declared],
    )
    return Service(cfg)


def test_service_tick_writes_a1_report(locked_1421_service):
    svc = locked_1421_service
    svc.start()
    try:
        # Give the NMEA reader a moment to consume fixtures so the
        # snapshot has gps_fix="3D" when the tick fires.
        time.sleep(0.2)
        svc._tick()
    finally:
        svc.stop()

    run_dir = svc.cfg.run_dir
    json_path = run_dir / "TEST1421.json"
    idx_path = run_dir / "index.json"

    assert json_path.exists()
    doc = json.loads(json_path.read_text())
    assert doc["schema"] == "v1"
    assert doc["device"]["serial"] == "TEST1421"
    assert doc["device"]["model"] == "lbe-1421"
    assert doc["governs"] == ["radiod:main"]
    assert doc["health"]["pll_locked"] is True
    assert doc["outputs"]["out1_hz"] == 10_000_000
    assert doc["outputs"]["out2_hz"] == 27_000_000
    assert doc["a_level_hint"] == "A1"
    assert "pll_locked" in doc["a_level_reason"]
    assert doc["pps_study"]["edges"] == 60

    idx = json.loads(idx_path.read_text())
    assert idx["schema"] == "v1"
    assert len(idx["devices"]) == 1
    assert idx["devices"][0]["serial"] == "TEST1421"
    # Regression: index used to hardcode "A1"; verify it now tracks the
    # per-report value.
    assert idx["devices"][0]["a_level_hint"] == "A1"


def test_service_tick_reports_a0_when_pll_unlocked(locked_1421_service, monkeypatch):
    """Flip the HID bitmap to PLL-unlocked and verify the tick produces
    A0 with a reason string naming the failing predicate."""
    from gpsdo_monitor.models.lbe_1421 import (
        ANT_OK_BIT, GPS_LOCK_BIT, OUT1_EN_BIT, OUT2_EN_BIT, PPS_EN_BIT,
    )
    unlocked = bytearray(_locked_1421_status_buf())
    unlocked[1] = (GPS_LOCK_BIT | ANT_OK_BIT | OUT1_EN_BIT
                   | OUT2_EN_BIT | PPS_EN_BIT)   # no PLL_LOCK_BIT
    _install_fake_hidapi(monkeypatch, bytes(unlocked))

    svc = locked_1421_service
    svc.start()
    try:
        time.sleep(0.2)
        svc._tick()
    finally:
        svc.stop()

    doc = json.loads((svc.cfg.run_dir / "TEST1421.json").read_text())
    assert doc["a_level_hint"] == "A0"
    assert doc["a_level_reason"] == "pll_unlocked"


def test_service_worker_lifecycle_tracks_discovery(locked_1421_service, monkeypatch):
    """When a previously-seen device disappears, its worker stops and
    its /run/gpsdo entry persists (we deliberately don't delete stale
    files — operators shouldn't see a flap as "device gone forever")."""
    svc = locked_1421_service
    svc.start()
    try:
        time.sleep(0.1)
        svc._tick()
        assert "TEST1421" in svc._workers

        # Now simulate the device being unplugged.
        from gpsdo_monitor import service as svc_mod
        from gpsdo_monitor.discovery import DiscoveryResult
        monkeypatch.setattr(
            svc_mod, "match",
            lambda _devs: DiscoveryResult((), (), (), ()),
        )
        svc._tick()
        assert svc._workers == {}
    finally:
        svc.stop()
