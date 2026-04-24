"""Long-running probe daemon.

One iteration per probe tick:
  1. Discovery.match() against configured [[device]] entries.
  2. For each matched (DeclaredDevice, HidCandidate):
       open the right model, call get_status(), merge NMEA/UBX state,
       classify A-level, build schema.DeviceReport, atomic-write JSON.
  3. Refresh mDNS advertisements; withdraw any that vanished.
  4. Update /run/gpsdo/index.json.
  5. sd_notify WATCHDOG=1 and sleep probe_interval_sec.

This skeleton wires the lifecycle but leaves NMEA / UBX coroutines and
PPS edge-capture as stubs (see nmea.py / ubx.py / pps.py placeholders
to be filled in once the first hardware bring-up starts).
"""
from __future__ import annotations

import logging
import signal
import socket
import threading
import time
from dataclasses import asdict
from pathlib import Path

from gpsdo_monitor import SCHEMA_VERSION
from gpsdo_monitor.config import Config
from gpsdo_monitor.discovery import DiscoveryResult, match
from gpsdo_monitor.health import classify
from gpsdo_monitor.hid_xport import HidCandidate
from gpsdo_monitor.models import open_model
from gpsdo_monitor.publish import Advertiser
from gpsdo_monitor.schema import (
    Device,
    DeviceReport,
    IndexEntry,
    IndexFile,
    PpsStudy,
    atomic_write,
    new_report,
    utc_now_iso,
)

log = logging.getLogger("gpsdo_monitor.service")


class Service:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.stopping = threading.Event()
        self.advertiser: Advertiser | None = None
        self._last_written: dict[str, float] = {}   # serial → monotonic()

    # --- Lifecycle -----------------------------------------------------
    def start(self) -> None:
        self.cfg.run_dir.mkdir(parents=True, exist_ok=True)
        if self.cfg.mdns_enabled:
            self.advertiser = Advertiser()
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

    def stop(self) -> None:
        self.stopping.set()
        if self.advertiser is not None:
            self.advertiser.close()
            self.advertiser = None

    def _on_signal(self, *_a: object) -> None:
        log.info("signal received, shutting down")
        self.stopping.set()

    # --- Probe loop ----------------------------------------------------
    def run(self) -> int:
        self.start()
        try:
            while not self.stopping.is_set():
                started = time.monotonic()
                self._tick()
                elapsed = time.monotonic() - started
                self.stopping.wait(max(0.0, self.cfg.probe_interval_sec - elapsed))
        finally:
            self.stop()
        return 0

    def _tick(self) -> None:
        result = match(self.cfg.devices)
        for err in result.errors:
            log.error("discovery: %s", err)
        self._write_reports(result)
        self._write_index(result)
        self._reap_advertisements(result)

    # --- Per-device report --------------------------------------------
    def _write_reports(self, result: DiscoveryResult) -> None:
        host = socket.getfqdn() or socket.gethostname()
        for declared, candidate in result.matched:
            try:
                report = self._build_report(host, declared, candidate)
            except NotImplementedError as e:
                log.warning("skip %s: %s", candidate.serial or candidate.path, e)
                continue
            except Exception:
                log.exception("probe failed for %s", candidate.serial)
                continue
            self._publish_report(report)

    def _build_report(
        self,
        host: str,
        declared,
        candidate: HidCandidate,
    ) -> DeviceReport:
        with open_model(candidate) as model:
            raw = model.get_status()

        device = Device(
            model=candidate.model,
            pid=f"{candidate.pid:#06x}",
            serial=candidate.serial or "unknown",
            hid_path=candidate.path.decode(errors="replace"),
            firmware=raw.firmware,
            firmware_source=raw.firmware_source,
            raw_trailing_hex=raw.raw_trailing_hex,
        )

        pps_study = PpsStudy(
            enabled=self.cfg.pps_study_enabled
                    and bool(raw.outputs.pps_enabled),
            window_sec=60,
        )

        a_level, reason = classify(
            raw.health,
            pps_study,
            probe_age_sec=0.0,
            probe_interval_sec=self.cfg.probe_interval_sec,
            pps_expected=bool(raw.outputs.pps_enabled),
        )

        return new_report(
            host=host,
            probe_interval_sec=self.cfg.probe_interval_sec,
            device=device,
            governs=list(declared.governs),
            health=raw.health,
            outputs=raw.outputs,
            pps_study=pps_study,
            a_level_hint=a_level,
            a_level_reason=reason,
        )

    def _publish_report(self, report: DeviceReport) -> None:
        path = self.cfg.run_dir / f"{_sanitize(report.device.serial)}.json"
        atomic_write(str(path), report.to_json())
        self._last_written[report.device.serial] = time.monotonic()
        if self.advertiser is not None:
            self.advertiser.publish(report, probe_age_sec=0.0)

    # --- Index file ----------------------------------------------------
    def _write_index(self, result: DiscoveryResult) -> None:
        host = socket.getfqdn() or socket.gethostname()
        entries = []
        for declared, candidate in result.matched:
            entries.append(IndexEntry(
                serial=candidate.serial or "unknown",
                model=candidate.model,
                governs=list(declared.governs),
                a_level_hint="A1",  # refined once per-report path lands
                written_utc=utc_now_iso(),
            ))
        idx = IndexFile(
            schema=SCHEMA_VERSION,
            written_utc=utc_now_iso(),
            host=host,
            devices=entries,
        )
        atomic_write(str(self.cfg.run_dir / "index.json"), idx.to_json())

    # --- mDNS reaping --------------------------------------------------
    def _reap_advertisements(self, result: DiscoveryResult) -> None:
        if self.advertiser is None:
            return
        present_serials = {c.serial for _, c in result.matched}
        for serial in list(self._last_written.keys()):
            if serial not in present_serials:
                log.info("device %s vanished; withdrawing advertisement", serial)
                self.advertiser.withdraw(serial)
                self._last_written.pop(serial, None)


def _sanitize(serial: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in serial) or "unknown"
