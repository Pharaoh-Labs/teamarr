"""Processing-run timestamps are stored as UTC and served with an offset (#444).

Generation History showed UTC wall times labeled with the local timezone:
started_at/completed_at were written as naive local ``datetime.now()`` and
serialized without an offset, so the browser guessed the timezone. Runs are
now stored SQLite-canonical UTC ("YYYY-MM-DD HH:MM:SS") — comparable against
``datetime('now')`` and ``CURRENT_TIMESTAMP`` — and serialized to the API as
aware ISO-8601 so the frontend converts to the configured display timezone.
"""

import time
from datetime import UTC, datetime, timedelta

import pytest

from teamarr.database.stats import (
    create_run,
    get_current_stats,
    get_match_stats_summary,
    get_recent_runs,
    get_run,
    save_run,
)
from teamarr.utilities.tz import parse_db_timestamp, to_db_utc


@pytest.fixture
def conn(db_conn):
    return db_conn


# ---------------------------------------------------------------------------
# tz helpers
# ---------------------------------------------------------------------------


def test_to_db_utc_is_sqlite_canonical():
    dt = datetime(2026, 7, 14, 15, 3, 22, 123456, tzinfo=UTC)
    assert to_db_utc(dt) == "2026-07-14 15:03:22"
    assert to_db_utc(None) is None


def test_to_db_utc_converts_offsets_to_utc():
    from zoneinfo import ZoneInfo

    dt = datetime(2026, 7, 14, 11, 3, 22, tzinfo=ZoneInfo("America/New_York"))
    assert to_db_utc(dt) == "2026-07-14 15:03:22"


def test_parse_db_timestamp_space_naive_is_utc():
    # SQLite CURRENT_TIMESTAMP / datetime('now') / to_db_utc format
    dt = parse_db_timestamp("2026-07-14 15:03:22")
    assert dt == datetime(2026, 7, 14, 15, 3, 22, tzinfo=UTC)


def test_parse_db_timestamp_aware_iso_normalizes_to_utc():
    dt = parse_db_timestamp("2026-07-14T11:03:22-04:00")
    assert dt == datetime(2026, 7, 14, 15, 3, 22, tzinfo=UTC)
    assert dt.tzinfo == UTC


def test_parse_db_timestamp_legacy_t_naive_is_local(monkeypatch):
    # Legacy Python isoformat() rows were server-local wall time
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        dt = parse_db_timestamp("2026-07-14T11:03:22")
        assert dt == datetime(2026, 7, 14, 15, 3, 22, tzinfo=UTC)
    finally:
        monkeypatch.undo()
        time.tzset()


def test_parse_db_timestamp_none():
    assert parse_db_timestamp(None) is None
    assert parse_db_timestamp("") is None


# ---------------------------------------------------------------------------
# processing_runs round-trip
# ---------------------------------------------------------------------------


def test_create_run_stores_sqlite_canonical_utc(conn):
    run = create_run(conn, run_type="full_epg")
    raw = conn.execute(
        "SELECT started_at FROM processing_runs WHERE id = ?", (run.id,)
    ).fetchone()["started_at"]
    assert "T" not in raw and "+" not in raw
    stored = datetime.fromisoformat(raw).replace(tzinfo=UTC)
    assert abs((stored - datetime.now(UTC)).total_seconds()) < 5


def test_in_progress_guard_sees_fresh_run(conn):
    # The generation.py dedup guard compares against datetime('now') (UTC).
    # With naive local storage this silently broke for any TZ behind UTC.
    create_run(conn, run_type="full_epg")
    hit = conn.execute(
        """
        SELECT COUNT(*) AS n FROM processing_runs
        WHERE run_type = 'full_epg' AND status = 'running'
          AND started_at > datetime('now', '-5 minutes')
        """
    ).fetchone()["n"]
    assert hit == 1


def test_run_serializes_with_utc_offset(conn):
    run = create_run(conn, run_type="full_epg")
    run.complete(status="completed")
    save_run(conn, run)

    fetched = get_run(conn, run.id)
    payload = fetched.to_dict()
    assert payload["started_at"].endswith("+00:00")
    assert payload["completed_at"].endswith("+00:00")
    assert fetched.duration_ms == run.duration_ms
    assert run.duration_ms is not None and run.duration_ms >= 0


def test_legacy_naive_rows_still_parse(conn):
    # Pre-fix rows: naive local isoformat with 'T' separator
    legacy = (datetime.now() - timedelta(hours=1)).isoformat()
    conn.execute(
        "INSERT INTO processing_runs (run_type, started_at, completed_at, status)"
        " VALUES ('full_epg', ?, ?, 'completed')",
        (legacy, legacy),
    )
    runs = get_recent_runs(conn, run_type="full_epg")
    assert len(runs) == 1
    assert runs[0].started_at.tzinfo is not None
    assert runs[0].to_dict()["started_at"].endswith("+00:00")


def test_summary_endpoints_emit_offset_iso(conn):
    run = create_run(conn, run_type="full_epg")
    run.complete(status="completed")
    save_run(conn, run)

    stats = get_current_stats(conn)
    assert stats["last_run"].endswith("+00:00")

    summary = get_match_stats_summary(conn, run.id)
    assert summary["started_at"].endswith("+00:00")
    assert summary["completed_at"].endswith("+00:00")
