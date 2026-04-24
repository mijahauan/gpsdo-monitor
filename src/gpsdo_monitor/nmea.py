"""NMEA reader for LBE-1421 / LBE-1423 (and any other 1DD2 device that
streams NMEA on a CDC-ACM interface).

Scope intentionally narrow: we only want the three fields Health needs —
`gps_fix` ("no_fix" / "2D" / "3D"), `sats_used` (int), and `fix_age_sec`
(wall-clock seconds since the last RMC-valid sentence). Per-satellite
constellation views (GSV → sv-info) belong in a live monitor UI, not
here.

Port discovery matches the tty to its owning USB device by the same
serial string hidapi reports — this is what keeps the N:M topology
(multiple GPSDOs on one host) honest. Probe-the-port trick from
upstream is kept as a last-resort fallback.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from gpsdo_monitor.hid_xport import VID_LBE


@dataclass
class NmeaState:
    """Accumulator updated one sentence at a time by `feed()`."""

    gps_fix: str | None = None          # "no_fix" | "2D" | "3D"
    sats_used: int | None = None
    last_rmc_valid_wall: float | None = None   # time.time() of latest RMC with status 'A'
    bad_checksum_count: int = 0

    def fix_age_sec(self, *, now: float | None = None) -> float | None:
        """Wall-clock seconds since the last RMC we treated as valid.

        None if we've never seen one. A high value is not necessarily a
        downgrade trigger on its own — the classifier in `health.py`
        combines it with the other predicates."""
        if self.last_rmc_valid_wall is None:
            return None
        t = now if now is not None else time.time()
        return max(0.0, t - self.last_rmc_valid_wall)


def checksum_ok(line: str) -> bool:
    """Validate a NMEA sentence's `*HH` checksum.

    Matches upstream `nmea_checksum_ok()` semantics: the checksum is the
    XOR of all bytes between `$` and `*`. Lines without `*` are rejected
    here; the caller can decide whether to accept a checksum-less line
    (we don't — CDC bridges rarely drop `*CS` on this device)."""
    if not line or line[0] != "$":
        return False
    star = line.find("*")
    if star < 0 or star + 3 > len(line):
        return False
    body = line[1:star]
    ck = 0
    for ch in body.encode("ascii", errors="replace"):
        ck ^= ch
    try:
        expected = int(line[star + 1 : star + 3], 16)
    except ValueError:
        return False
    return expected == ck


def _strip_fields(line: str) -> list[str] | None:
    """Return the comma-separated fields of a NMEA body, or None if the
    sentence is malformed."""
    if not line or line[0] != "$":
        return None
    star = line.find("*")
    body = line[1:star] if star >= 0 else line[1:]
    return body.split(",")


def feed(state: NmeaState, line: str, *, now: float | None = None) -> None:
    """Update `state` from one NMEA sentence.

    Tolerant of missing trailing `*CS` only if the line was already
    vetted upstream; here we require a valid checksum to count the
    sentence. Unknown sentence types are ignored."""
    if not line.startswith("$"):
        return
    if "*" in line:
        if not checksum_ok(line):
            state.bad_checksum_count += 1
            return
    fields = _strip_fields(line)
    if not fields or len(fields[0]) < 5:
        return
    t = now if now is not None else time.time()
    sentence = fields[0][2:]   # strip talker (GP, GN, GL, ...)

    if sentence == "RMC":
        # $xxRMC,utc,status,lat,N/S,lon,E/W,sog,cog,date,magvar,...
        # status 'A' = active/valid, 'V' = void.
        if len(fields) > 2 and fields[2] == "A":
            state.last_rmc_valid_wall = t
    elif sentence == "GGA":
        # $xxGGA,utc,lat,N/S,lon,E/W,quality,numSV,hdop,...
        # quality: 0=invalid, 1=GPS, 2=DGPS, 4=RTK fix, 5=RTK float, 6=dead-reckoning, ...
        if len(fields) > 7:
            try:
                n = int(fields[7])
            except ValueError:
                n = None
            if n is not None:
                state.sats_used = n
    elif sentence == "GSA":
        # $xxGSA,mode1,mode2,prn1..prn12,pdop,hdop,vdop
        # mode2: 1=no fix, 2=2D, 3=3D.
        if len(fields) > 2:
            state.gps_fix = {"1": "no_fix", "2": "2D", "3": "3D"}.get(fields[2], state.gps_fix)


# --- Port discovery ----------------------------------------------------


def _read_sysfs(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def find_ttys_by_usb_serial(
    target_serial: str, *, vid: int = VID_LBE
) -> list[Path]:
    """Return `/dev/ttyACM*` nodes whose owning USB device matches
    `vid:<any pid>` and reports `target_serial`.

    Uses sysfs rather than probing — cheaper, and unambiguous in the
    N-GPSDOs-on-one-host case."""
    want_vid = f"{vid:04x}"
    out: list[Path] = []
    sys_tty = Path("/sys/class/tty")
    if not sys_tty.is_dir():
        return out
    for tty in sorted(sys_tty.glob("ttyACM*")):
        # /sys/class/tty/ttyACMx/device is the USB interface; its parent
        # is the USB device with idVendor, idProduct, serial.
        dev_link = tty / "device"
        try:
            usb_dev = dev_link.resolve().parent
        except OSError:
            continue
        serial = _read_sysfs(usb_dev / "serial")
        vidstr = _read_sysfs(usb_dev / "idVendor")
        if vidstr is None or serial is None:
            continue
        if vidstr.lower() == want_vid and serial == target_serial:
            out.append(Path("/dev") / tty.name)
    return out


def sample(
    tty_path: Path,
    *,
    duration_sec: float = 1.5,
    baudrate: int = 9600,
) -> NmeaState:
    """One-shot NMEA sampler — open the port, read lines for up to
    `duration_sec`, return accumulated state.

    Intended for the `gpsdo-monitor status` command and the daemon's
    10 s probe tick. The daemon's long-running PPS edge thread
    (pps.py) keeps the port open continuously; this function is the
    cheap one-shot path for callers that don't need edge capture."""
    import serial  # pyserial; imported lazily so unit tests don't need it

    state = NmeaState()
    deadline = time.monotonic() + duration_sec
    with serial.Serial(
        str(tty_path), baudrate=baudrate, timeout=0.2,
        rtscts=False, dsrdtr=False,
    ) as s:
        while time.monotonic() < deadline:
            raw = s.readline()
            if not raw:
                continue
            try:
                line = raw.decode("ascii", errors="replace").strip()
            except UnicodeDecodeError:
                continue
            if line.startswith("$"):
                feed(state, line)
    return state
