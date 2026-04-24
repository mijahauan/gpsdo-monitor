"""mDNS advertiser for per-device health.

Uses `zeroconf` (python-zeroconf) — pure Python, no subprocess, robust
against avahi restarts. One `ServiceInfo` per physically-present
device; TXT records carry schema v1 (see docs/SCHEMA-v1.md).

Consumers (e.g. hf-timestd's `GpsdoMdnsProbe`) subscribe with
`ServiceBrowser` on type `_gpsdo._tcp.local.` and filter by TXT
`serial=`.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass

from zeroconf import IPVersion, ServiceInfo, Zeroconf

from gpsdo_monitor import SCHEMA_VERSION
from gpsdo_monitor.schema import DeviceReport

SERVICE_TYPE = "_gpsdo._tcp.local."


def _sanitize_instance_name(serial: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in serial.lower())
    return safe or "unknown"


def _txt_from_report(r: DeviceReport, *, probe_age_sec: float) -> dict[bytes, bytes]:
    def b(v: object) -> bytes:
        return str(v).encode("utf-8")

    txt: dict[bytes, bytes] = {
        b"schema":    b(SCHEMA_VERSION),
        b"host":      b(r.host),
        b"model":     b(r.device.model),
        b"serial":    b(r.device.serial),
        b"governs":   b(",".join(r.governs)),
        b"a_level":   b(r.a_level_hint),
        b"fresh":     b(int(r.probe_interval_sec)),
        b"probe_age": b(int(probe_age_sec)),
    }
    if r.outputs.out1_hz is not None:
        txt[b"f1"] = b(r.outputs.out1_hz)
    if r.outputs.out2_hz is not None:
        txt[b"f2"] = b(r.outputs.out2_hz)
    if r.outputs.pps_enabled is not None:
        txt[b"pps"] = b("true" if r.outputs.pps_enabled else "false")
    return txt


@dataclass
class _Registration:
    info: ServiceInfo
    last_txt: dict[bytes, bytes]


class Advertiser:
    """Maintains `_gpsdo._tcp` advertisements for a set of devices.

    Call `publish(report)` after every probe tick; it re-registers only
    when the TXT payload changes. Call `withdraw(serial)` when a device
    disappears, and `close()` on shutdown."""

    def __init__(self, zc: Zeroconf | None = None) -> None:
        self._zc = zc or Zeroconf(ip_version=IPVersion.All)
        self._own = zc is None
        self._registered: dict[str, _Registration] = {}

    def _host_addresses(self) -> list[bytes]:
        # Best-effort: resolve our own hostname. The advertisement
        # port is 0, so A records are informational.
        try:
            ip = socket.gethostbyname(socket.gethostname())
            return [socket.inet_aton(ip)]
        except OSError:
            return [socket.inet_aton("127.0.0.1")]

    def publish(self, report: DeviceReport, *, probe_age_sec: float = 0.0) -> None:
        serial = report.device.serial
        instance = _sanitize_instance_name(serial)
        name = f"{instance}.{SERVICE_TYPE}"
        txt = _txt_from_report(report, probe_age_sec=probe_age_sec)

        existing = self._registered.get(serial)
        if existing is not None and existing.last_txt == txt:
            return  # no change — don't rebroadcast

        info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=name,
            addresses=self._host_addresses(),
            port=0,
            properties=txt,
            server=f"{socket.gethostname()}.local.",
        )

        if existing is None:
            self._zc.register_service(info)
        else:
            self._zc.update_service(info)
        self._registered[serial] = _Registration(info=info, last_txt=txt)

    def withdraw(self, serial: str) -> None:
        reg = self._registered.pop(serial, None)
        if reg is None:
            return
        self._zc.unregister_service(reg.info)

    def close(self) -> None:
        for reg in list(self._registered.values()):
            try:
                self._zc.unregister_service(reg.info)
            except Exception:
                pass
        self._registered.clear()
        if self._own:
            self._zc.close()
