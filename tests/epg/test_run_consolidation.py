"""One generation, one processing_runs row (#645).

Per-group ``event_group`` sub-runs are gone: groups report into the parent
``full_epg`` run (counters roll up, per-group breakdown in
``extra_metrics.groups``) and per-stream match details are keyed on the full
run's id. These tests lock the readers, the retention pruning, the processor
contract, and the v90 migration that re-keys pre-existing data.
"""

import contextlib
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from teamarr.consumers.event_group_processor import EventGroupProcessor
from teamarr.consumers.event_group_processor.results import (
    BatchProcessingResult,
    ProcessingResult,
)
from teamarr.consumers.matching.matcher import BatchMatchResult
from teamarr.database.groups import create_group, get_group
from teamarr.database.migrations.versioned import _migrate_v90_consolidate_group_subruns
from teamarr.database.stats import (
    cleanup_old_runs,
    create_run,
    get_failed_matches,
    get_match_stats_summary,
    get_matched_streams,
)
from teamarr.services.stream_filter import FilterResult

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "teamarr" / "database" / "schema.sql"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def _factory(conn):
    @contextlib.contextmanager
    def factory():
        yield conn
        conn.commit()

    return factory


def _insert_run(conn, *, run_type, started, completed=None, cached=0, days_ago=0):
    created = (datetime.now() - timedelta(days=days_ago)).isoformat(sep=" ")
    cur = conn.execute(
        """
        INSERT INTO processing_runs
            (created_at, run_type, started_at, completed_at, status, streams_cached)
        VALUES (?, ?, ?, ?, 'completed', ?)
        """,
        (created, run_type, started, completed, cached),
    )
    return cur.lastrowid


def _group(conn, name="G") -> int:
    """Detail rows carry a group_id FK, so tests need a real group."""
    gid = create_group(conn, name=name, leagues=["eng.1"])
    conn.commit()
    return gid


def _insert_matched(conn, run_id, group_id, name="s"):
    conn.execute(
        """
        INSERT INTO epg_matched_streams
            (run_id, group_id, group_name, stream_name, event_id)
        VALUES (?, ?, 'G', ?, 'e1')
        """,
        (run_id, group_id, name),
    )


def _insert_failed(conn, run_id, group_id, name="f"):
    conn.execute(
        """
        INSERT INTO epg_failed_matches (run_id, group_id, group_name, stream_name, reason)
        VALUES (?, ?, 'G', ?, 'unmatched')
        """,
        (run_id, group_id, name),
    )


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


def test_latest_run_is_latest_full_epg_row(db_conn):
    """With run_id omitted the readers resolve to the newest full_epg run —
    previously ``ORDER BY created_at`` landed on the last group sub-run."""
    gid = _group(db_conn)
    first = create_run(db_conn, run_type="full_epg")
    second = create_run(db_conn, run_type="full_epg")
    _insert_matched(db_conn, first.id, gid, name="old")
    _insert_matched(db_conn, second.id, gid, name="new")
    _insert_failed(db_conn, second.id, gid)

    assert [s["stream_name"] for s in get_matched_streams(db_conn)] == ["new"]
    assert len(get_failed_matches(db_conn)) == 1
    assert get_match_stats_summary(db_conn)["run_id"] == second.id


def test_summary_breakdowns_populate_for_full_run(db_conn):
    """Details are keyed on the full run, so by_group/by_league are no longer
    empty for the run the Generate endpoint reports on."""
    g1, g2 = _group(db_conn, "A"), _group(db_conn, "B")
    run = create_run(db_conn, run_type="full_epg")
    _insert_matched(db_conn, run.id, g1, name="a")
    _insert_matched(db_conn, run.id, g2, name="b")
    _insert_failed(db_conn, run.id, g2)

    summary = get_match_stats_summary(db_conn, run.id)
    assert [g["group_id"] for g in summary["matched"]["by_group"]] == [g1, g2]
    assert summary["failed"]["by_reason"] == {"unmatched": 1}


def test_readers_with_no_runs(db_conn):
    assert get_matched_streams(db_conn) == []
    assert get_failed_matches(db_conn) == []
    assert get_match_stats_summary(db_conn)["run_id"] is None


def test_cleanup_prunes_detail_rows_with_their_run(db_conn):
    """Detail rows leave with their run (FK ON DELETE CASCADE) — the key
    now being the full run, pruning a generation drops all of its details."""
    gid = _group(db_conn)
    old = _insert_run(db_conn, run_type="full_epg", started="2020-01-01 00:00:00", days_ago=60)
    fresh = _insert_run(db_conn, run_type="full_epg", started="2020-01-02 00:00:00", days_ago=1)
    _insert_matched(db_conn, old, gid)
    _insert_failed(db_conn, old, gid)
    _insert_matched(db_conn, fresh, gid)

    assert cleanup_old_runs(db_conn, days=30) == 1

    remaining = db_conn.execute("SELECT run_id FROM epg_matched_streams").fetchall()
    assert [r["run_id"] for r in remaining] == [fresh]
    assert db_conn.execute("SELECT COUNT(*) c FROM epg_failed_matches").fetchone()["c"] == 0


# ---------------------------------------------------------------------------
# Processor contract
# ---------------------------------------------------------------------------


def _seeded_group():
    conn = _db()
    cur = conn.execute("INSERT INTO templates (name, template_type) VALUES ('T', 'event')")
    conn.execute("INSERT INTO subscription_templates (template_id) VALUES (?)", (cur.lastrowid,))
    gid = create_group(conn, name="EPL", leagues=["eng.1"])
    conn.commit()
    return conn, get_group(conn, gid)


def _processor_with_zero_matches(conn, monkeypatch):
    proc = EventGroupProcessor(db_factory=_factory(conn), service=MagicMock())
    streams = [{"id": 11, "name": "Arsenal vs Spurs"}]
    monkeypatch.setattr(proc, "_fetch_streams", lambda g: list(streams))
    monkeypatch.setattr(
        proc,
        "_filter_streams",
        lambda s, g: (list(streams), FilterResult(total_input=1, passed_count=1)),
    )
    monkeypatch.setattr(proc, "_match_streams", lambda *a, **k: BatchMatchResult())
    return proc


def test_group_creates_no_run_row_and_reports_timings(monkeypatch):
    conn, group = _seeded_group()
    proc = _processor_with_zero_matches(conn, monkeypatch)
    parent = create_run(conn, run_type="full_epg")

    result = proc._process_group_internal(conn, group, date.today(), run_id=parent.id)

    rows = conn.execute("SELECT run_type FROM processing_runs").fetchall()
    assert [r["run_type"] for r in rows] == ["full_epg"]
    assert set(result.phase_timings) >= {"fetch", "match"}
    assert result.to_run_summary()["id"] == group.id


def test_details_keyed_on_parent_run_or_skipped(monkeypatch):
    conn, group = _seeded_group()
    proc = _processor_with_zero_matches(conn, monkeypatch)
    captured: list[int] = []
    monkeypatch.setattr(
        proc, "_save_match_details", lambda **kw: captured.append(kw["run_id"])
    )

    proc._process_group_internal(conn, group, date.today(), run_id=None)
    assert captured == []

    proc._process_group_internal(conn, group, date.today(), run_id=42)
    assert captured == [42]


def test_batch_rollups_and_group_summaries():
    a = ProcessingResult(group_id=1, group_name="A", streams_cached=3, channels_existing=2)
    b = ProcessingResult(group_id=2, group_name="B", streams_cached=4, channel_errors=1)
    b.errors.append("boom")
    batch = BatchProcessingResult(results=[a, b])

    assert batch.total_streams_cached == 7
    assert batch.total_channels_updated == 2
    assert batch.total_channel_errors == 1
    summaries = batch.group_summaries()
    assert [s["name"] for s in summaries] == ["A", "B"]
    assert summaries[0]["error"] is None
    assert summaries[1]["error"] == "boom"


# ---------------------------------------------------------------------------
# v90 migration
# ---------------------------------------------------------------------------


def test_v90_rekeys_details_folds_cache_hits_and_drops_subruns(db_conn):
    parent = _insert_run(
        db_conn, run_type="full_epg",
        started="2026-08-04 20:00:00", completed="2026-08-04 20:01:00", cached=0,
    )
    child1 = _insert_run(db_conn, run_type="event_group", started="2026-08-04 20:00:03", cached=30)
    child2 = _insert_run(db_conn, run_type="event_group", started="2026-08-04 20:00:34", cached=2)
    # A sub-run with no surviving parent (parent already pruned)
    orphan = _insert_run(db_conn, run_type="event_group", started="2026-07-01 10:00:00", cached=5)
    g1, g2 = _group(db_conn, "A"), _group(db_conn, "B")
    _insert_matched(db_conn, child1, g1, name="m1")
    _insert_failed(db_conn, child2, g2)
    _insert_matched(db_conn, orphan, g1, name="gone")

    _migrate_v90_consolidate_group_subruns(db_conn)

    runs = db_conn.execute("SELECT id, run_type, streams_cached FROM processing_runs").fetchall()
    assert [(r["id"], r["run_type"], r["streams_cached"]) for r in runs] == [
        (parent, "full_epg", 32)
    ]

    matched = get_matched_streams(db_conn, run_id=parent)
    assert [m["stream_name"] for m in matched] == ["m1"]
    assert [f["group_id"] for f in get_failed_matches(db_conn, run_id=parent)] == [g2]
    assert db_conn.execute("SELECT COUNT(*) c FROM epg_matched_streams").fetchone()["c"] == 1

    lifetime = db_conn.execute("SELECT streams_cached FROM lifetime_stats WHERE id = 1").fetchone()
    assert lifetime["streams_cached"] == 5


def test_v90_is_a_noop_on_a_clean_db(db_conn):
    run = create_run(db_conn, run_type="full_epg")
    _insert_matched(db_conn, run.id, _group(db_conn))
    _migrate_v90_consolidate_group_subruns(db_conn)
    assert len(get_matched_streams(db_conn, run_id=run.id)) == 1
