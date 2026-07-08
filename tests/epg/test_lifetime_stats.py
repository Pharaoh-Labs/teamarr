"""Lifetime stats accumulator (bead teamarrv2-3qyp).

processing_runs is pruned to a rolling window and can be cleared from the UI,
so the Dashboard's "All-Time Totals" must come from lifetime_stats: run sums
are folded into it BEFORE deletion, and get_current_stats reports both.
"""

from datetime import datetime, timedelta

import pytest

from teamarr.database.stats import cleanup_old_runs, clear_all_runs, get_current_stats


def _insert_run(
    conn,
    *,
    run_type: str = "full_epg",
    status: str = "completed",
    days_ago: int = 0,
    matched: int = 10,
    programmes: int = 100,
    channels_created: int = 5,
):
    created = (datetime.now() - timedelta(days=days_ago)).isoformat(sep=" ")
    conn.execute(
        """
        INSERT INTO processing_runs
            (created_at, run_type, started_at, status, streams_matched,
             programmes_total, channels_created, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1000)
        """,
        (created, run_type, created, status, matched, programmes, channels_created),
    )


@pytest.fixture
def conn(db_conn):
    return db_conn


def _totals(conn):
    stats = get_current_stats(conn)
    return stats["total_runs"], stats["totals"]


def test_cleanup_folds_pruned_runs_into_lifetime(conn):
    _insert_run(conn, days_ago=60, matched=10, programmes=100, channels_created=5)
    _insert_run(conn, days_ago=1, matched=20, programmes=200, channels_created=7)

    runs_before, totals_before = _totals(conn)
    assert runs_before == 2
    assert totals_before["streams_matched"] == 30

    deleted = cleanup_old_runs(conn, days=30)
    assert deleted == 1

    # Totals unchanged after pruning: the old run now lives in lifetime_stats
    runs_after, totals_after = _totals(conn)
    assert runs_after == 2
    assert totals_after["streams_matched"] == 30
    assert totals_after["programmes_generated"] == 300
    assert totals_after["channels_created"] == 12

    row = conn.execute("SELECT * FROM lifetime_stats WHERE id = 1").fetchone()
    assert row["runs"] == 1
    assert row["streams_matched"] == 10


def test_clear_all_runs_preserves_lifetime_totals(conn):
    _insert_run(conn, matched=15, programmes=150)
    _insert_run(conn, matched=25, programmes=250, status="failed")

    cleared = clear_all_runs(conn)
    assert cleared == 2

    stats = get_current_stats(conn)
    assert stats["total_runs"] == 2
    assert stats["successful_runs"] == 1
    assert stats["failed_runs"] == 1
    assert stats["totals"]["streams_matched"] == 40
    assert stats["totals"]["programmes_generated"] == 400
    # Run history itself is gone
    assert conn.execute("SELECT COUNT(*) c FROM processing_runs").fetchone()["c"] == 0


def test_scoped_runs_are_pruned_but_not_folded(conn):
    """Only full_epg runs count toward all-time totals (matches live filter)."""
    _insert_run(conn, run_type="event_group", days_ago=60, matched=999)
    _insert_run(conn, days_ago=60, matched=10)

    deleted = cleanup_old_runs(conn, days=30)
    assert deleted == 2

    row = conn.execute("SELECT * FROM lifetime_stats WHERE id = 1").fetchone()
    assert row["runs"] == 1
    assert row["streams_matched"] == 10


def test_fold_is_cumulative_across_cleanups(conn):
    _insert_run(conn, days_ago=60, matched=10)
    cleanup_old_runs(conn, days=30)
    _insert_run(conn, days_ago=45, matched=20)
    cleanup_old_runs(conn, days=30)

    row = conn.execute("SELECT * FROM lifetime_stats WHERE id = 1").fetchone()
    assert row["runs"] == 2
    assert row["streams_matched"] == 30

    _, totals = _totals(conn)
    assert totals["streams_matched"] == 30


def test_cleanup_with_nothing_to_prune_is_noop(conn):
    _insert_run(conn, days_ago=1, matched=10)
    assert cleanup_old_runs(conn, days=30) == 0

    row = conn.execute("SELECT * FROM lifetime_stats WHERE id = 1").fetchone()
    assert row["runs"] == 0
