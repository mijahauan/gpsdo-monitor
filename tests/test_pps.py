"""Unit tests for PPS stats helpers. Hardware-path tests live outside."""
from gpsdo_monitor.pps import _summarise_edges, percentile


def test_percentile_empty_returns_none():
    assert percentile([], 0.5) is None


def test_percentile_midpoint():
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.50) == 3.0


def test_percentile_tail():
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.95) == 5.0


def test_percentile_clamps_high():
    assert percentile([10.0, 20.0], 1.5) == 20.0


def test_percentile_clamps_low():
    assert percentile([10.0, 20.0], -0.1) == 10.0


def test_summarise_no_edges():
    s = _summarise_edges([], None, window_sec=60)
    assert s.edges == 0
    assert s.period_ms_p50 is None
    assert s.period_ms_p95 is None
    assert s.last_edge_utc is None
    assert s.enabled is True
    assert s.window_sec == 60


def test_summarise_one_edge_no_intervals():
    # A single edge produces no inter-edge interval; percentiles stay None.
    s = _summarise_edges([100.0], 1_700_000_000.0, window_sec=60)
    assert s.edges == 1
    assert s.period_ms_p50 is None
    assert s.period_ms_p95 is None
    assert s.last_edge_utc is not None
    assert s.last_edge_utc.endswith("Z")


def test_summarise_nominal_1hz():
    edges = [100.0 + i for i in range(60)]
    s = _summarise_edges(edges, 1_700_000_000.0, window_sec=60)
    assert s.edges == 60
    assert s.period_ms_p50 == 1000.0
    assert s.period_ms_p95 == 1000.0


def test_summarise_jitter_shows_in_p95():
    # 10 nominal + 1 long interval (1200 ms). p95 of 11 intervals is
    # index int(0.95 * 11) = 10 → the last (longest) value.
    intervals_s = [1.0] * 10 + [1.2]
    t = 100.0
    edges = [t]
    for dt in intervals_s:
        t += dt
        edges.append(t)
    s = _summarise_edges(edges, 1_700_000_000.0, window_sec=60)
    assert s.edges == 12
    assert abs(s.period_ms_p50 - 1000.0) < 1e-6
    assert abs(s.period_ms_p95 - 1200.0) < 1e-6
