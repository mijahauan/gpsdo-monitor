"""Unit tests for the NMEA parser and state accumulator."""
import time

from gpsdo_monitor.nmea import NmeaState, checksum_ok, feed


def _with_cs(body: str) -> str:
    """Wrap a raw NMEA body (no leading '$', no '*CS') with valid '*CS'."""
    ck = 0
    for ch in body.encode("ascii"):
        ck ^= ch
    return f"${body}*{ck:02X}"


# Real sentences captured live from an LBE-1421 on bee1 (2026-04-24).
RMC_VALID = "$GNRMC,024825.40,A,3855.12213,N,09207.65474,W,0.001,,240426,,,D*73"
GGA_FIX   = "$GNGGA,024825.40,3855.12213,N,09207.65474,W,2,10,0.48,265.6,M,-30.7,M,,0000*7D"
GSA_3D    = "$GNGSA,A,3,10,32,23,28,02,24,25,12,31,01,,,0.91,0.48,0.77*10"

# Synthetic sentences — valid checksums computed at test time so the
# parser sees the same shape it would from a u-blox with degraded state.
RMC_VOID  = _with_cs("GNRMC,024826.00,V,,,,,,,240426,,,N")
GGA_NOFIX = _with_cs("GNGGA,024826.00,,,,,0,00,99.99,,,,,,")
GSA_2D    = _with_cs("GNGSA,A,2,03,06,11,17,22,,,,,,,,2.05,1.20,1.67")
GSA_NOFIX = _with_cs("GNGSA,A,1,,,,,,,,,,,,,99.99,99.99,99.99")


def _verify_fixtures_valid():
    for s in (RMC_VALID, RMC_VOID, GGA_FIX, GGA_NOFIX, GSA_3D, GSA_2D, GSA_NOFIX):
        assert checksum_ok(s), f"fixture bad checksum: {s}"


_verify_fixtures_valid()


def test_checksum_rejects_mutation():
    bad = GGA_FIX[:-2] + "00"
    assert not checksum_ok(bad)


def test_checksum_rejects_no_dollar():
    assert not checksum_ok("GPGGA,blah*00")


def test_feed_gsa_sets_3d_fix():
    st = NmeaState()
    feed(st, GSA_3D)
    assert st.gps_fix == "3D"


def test_feed_gsa_sets_2d_fix():
    st = NmeaState()
    feed(st, GSA_2D)
    assert st.gps_fix == "2D"


def test_feed_gsa_sets_no_fix():
    st = NmeaState()
    feed(st, GSA_NOFIX)
    assert st.gps_fix == "no_fix"


def test_feed_gga_sets_sats_used():
    st = NmeaState()
    feed(st, GGA_FIX)
    assert st.sats_used == 10


def test_feed_gga_nofix_reports_zero_sats():
    st = NmeaState()
    feed(st, GGA_NOFIX)
    # Zero is a valid NMEA signal ("0 sats used in fix"); report it so
    # downstream can distinguish "never parsed a GGA" from "GPS has no sats".
    assert st.sats_used == 0


def test_feed_rmc_valid_sets_fix_age_zero():
    st = NmeaState()
    now = 1_700_000_000.0
    feed(st, RMC_VALID, now=now)
    assert st.fix_age_sec(now=now) == 0.0
    assert st.fix_age_sec(now=now + 5.0) == 5.0


def test_feed_rmc_void_does_not_stamp_fix_age():
    st = NmeaState()
    feed(st, RMC_VOID, now=1_700_000_000.0)
    assert st.fix_age_sec(now=1_700_000_005.0) is None


def test_feed_bad_checksum_is_counted_not_applied():
    st = NmeaState()
    mutated = GGA_FIX[:-1] + "X"
    feed(st, mutated)
    assert st.bad_checksum_count == 1
    assert st.sats_used is None


def test_feed_ignores_unknown_sentence():
    st = NmeaState()
    feed(st, _with_cs("GPGSV,1,1,01,10,45,180,40"))
    assert st.gps_fix is None
    assert st.sats_used is None


def test_fix_age_tracks_wall_clock():
    st = NmeaState()
    t0 = time.time()
    feed(st, RMC_VALID, now=t0)
    age = st.fix_age_sec(now=t0 + 3.14)
    assert age is not None
    assert abs(age - 3.14) < 1e-6
