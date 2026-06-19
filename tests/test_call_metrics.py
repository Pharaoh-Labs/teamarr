"""Tests for the run-scoped provider-call counter (kbbk.1)."""

import threading

import pytest

from teamarr.utilities import call_metrics


@pytest.fixture(autouse=True)
def _clean_counter():
    """Each test starts and ends with an empty counter."""
    call_metrics.reset()
    yield
    call_metrics.reset()


def test_record_and_snapshot():
    call_metrics.record_call("espn", "basketball/nba/summary")
    call_metrics.record_call("espn", "basketball/nba/summary")
    call_metrics.record_call("espn", "football/nfl/scoreboard")
    snap = call_metrics.snapshot()
    assert snap["espn:summary"] == 2
    assert snap["espn:scoreboard"] == 1
    assert call_metrics.total() == 3


def test_endpoint_label_reduces_url_to_last_segment():
    # URL with query string -> last path segment, query stripped
    call_metrics.record_call("espn", "https://x/sports/baseball/mlb/summary?event=1")
    call_metrics.record_call("mlbstats", "schedule")  # bare label passes through
    snap = call_metrics.snapshot()
    assert "espn:summary" in snap
    assert "mlbstats:schedule" in snap


def test_trailing_numeric_id_collapses_to_resource():
    # Resource URLs ending in an id must NOT explode into one label per id —
    # they collapse to the resource type so cardinality stays bounded.
    call_metrics.record_call("espn", "https://x/sports/basketball/nba/teams/8")
    call_metrics.record_call("espn", "https://x/sports/basketball/nba/teams/130")
    call_metrics.record_call("espn", "https://x/core/event/401/competitions/12")
    snap = call_metrics.snapshot()
    assert snap["espn:teams"] == 2
    assert snap["espn:competitions"] == 1
    assert not any(k.split(":")[1].isdigit() for k in snap)


def test_snapshot_is_ordered_high_to_low():
    for _ in range(5):
        call_metrics.record_call("espn", "summary")
    call_metrics.record_call("tsdb", "eventsday.php")
    keys = list(call_metrics.snapshot())
    assert keys[0] == "espn:summary"  # most frequent first


def test_reset_clears_counts():
    call_metrics.record_call("espn", "summary")
    call_metrics.reset()
    assert call_metrics.snapshot() == {}
    assert call_metrics.total() == 0


def test_thread_safe_increments():
    """Concurrent increments (parallel matching) don't lose counts."""

    def worker():
        for _ in range(1000):
            call_metrics.record_call("espn", "summary")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert call_metrics.total() == 8000
    assert call_metrics.snapshot()["espn:summary"] == 8000
