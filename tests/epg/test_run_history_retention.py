"""Run-history retention and database compaction (#906).

Per-stream match/failure rows are one row per stream per run and dominate the
database (69% on a real install, ~35x redundant); the multiplier is the
generation interval. They now prune on their own short window
(run_detail_retention_days, default 7) while the run rows keep the longer one
(run_history_retention_days, default 30). SQLite never returns freed pages to
the filesystem, so a Compact (VACUUM) action ships alongside.
"""

from datetime import datetime, timedelta

import pytest

from teamarr.database.stats import cleanup_old_run_details, cleanup_old_runs


def _ts(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).isoformat(sep=" ")


def _insert_run(conn, days_ago: int) -> int:
    cur = conn.execute(
        "INSERT INTO processing_runs (created_at, run_type, started_at, status) "
        "VALUES (?, 'full_epg', ?, 'completed')",
        (_ts(days_ago), _ts(days_ago)),
    )
    return cur.lastrowid


def _group(conn) -> int:
    row = conn.execute("SELECT id FROM event_epg_groups LIMIT 1").fetchone()
    if row:
        return row["id"]
    from teamarr.database.groups import create_group

    return create_group(conn, name="G", leagues=["nfl"])


def _insert_details(conn, run_id: int, days_ago: int, n: int = 3) -> None:
    gid = _group(conn)
    for i in range(n):
        conn.execute(
            "INSERT INTO epg_matched_streams (created_at, run_id, group_id, stream_name, event_id)"
            " VALUES (?, ?, ?, ?, 'e1')",
            (_ts(days_ago), run_id, gid, f"m{i}"),
        )
        conn.execute(
            "INSERT INTO epg_failed_matches (created_at, run_id, group_id, stream_name, reason)"
            " VALUES (?, ?, ?, ?, 'no_event_found')",
            (_ts(days_ago), run_id, gid, f"f{i}"),
        )


def _counts(conn) -> tuple[int, int, int]:
    q = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
    return q("processing_runs"), q("epg_matched_streams"), q("epg_failed_matches")


def test_detail_cleanup_prunes_old_rows_and_keeps_runs(db_conn):
    old = _insert_run(db_conn, days_ago=10)
    new = _insert_run(db_conn, days_ago=1)
    _insert_details(db_conn, old, days_ago=10)
    _insert_details(db_conn, new, days_ago=1)
    assert _counts(db_conn) == (2, 6, 6)

    deleted = cleanup_old_run_details(db_conn, days=7)

    assert deleted == 6
    # Runs survive: the history table still shows the old run's counts.
    assert _counts(db_conn) == (2, 3, 3)


def test_run_cleanup_cascades_details(db_conn):
    old = _insert_run(db_conn, days_ago=40)
    _insert_details(db_conn, old, days_ago=40)

    assert cleanup_old_runs(db_conn, days=30) == 1
    assert _counts(db_conn) == (0, 0, 0)


def test_detail_cleanup_keys_on_the_run_not_the_row(db_conn):
    """The window is the run's age (indexed via run_id); a row's own
    created_at is never scanned — that scan was the unindexed full pass."""
    old = _insert_run(db_conn, days_ago=10)
    new = _insert_run(db_conn, days_ago=1)
    _insert_details(db_conn, old, days_ago=1)  # row stamp inside the window
    _insert_details(db_conn, new, days_ago=10)  # row stamp outside it

    assert cleanup_old_run_details(db_conn, days=7) == 6
    remaining = db_conn.execute("SELECT DISTINCT run_id FROM epg_failed_matches").fetchall()
    assert [r[0] for r in remaining] == [new]


@pytest.mark.parametrize("purge", ["details", "runs", "clear"])
def test_purges_commit_in_batches(db_conn, monkeypatch, purge):
    """One transaction over the whole backlog put every deleted row in the
    WAL before it could checkpoint; on a volume with less free space than
    that the purge died with the disk full (#906). Every path that removes
    detail rows must commit per batch — including the run delete, whose
    cascade would otherwise carry them all."""
    from teamarr.database import stats

    monkeypatch.setattr(stats, "_DETAIL_DELETE_BATCH", 4)
    run = _insert_run(db_conn, days_ago=40)
    _insert_details(db_conn, run, days_ago=40, n=10)
    db_conn.commit()

    largest = 0
    statements: list[str] = []
    db_conn.set_trace_callback(statements.append)
    before = db_conn.total_changes
    if purge == "details":
        assert stats.cleanup_old_run_details(db_conn, days=7) == 20
    elif purge == "runs":
        assert stats.cleanup_old_runs(db_conn, days=30) == 1
    else:
        assert stats.clear_all_runs(db_conn) == 1
    db_conn.set_trace_callback(None)

    # Walk the statement log: no span between COMMITs deletes more than a batch.
    pending = 0
    for sql in statements:
        if sql.startswith("DELETE FROM epg_"):
            pending += 1
            largest = max(largest, pending)
        elif sql.startswith("COMMIT"):
            pending = 0
    assert largest == 1, "two detail DELETEs shared a transaction"
    assert sum(s.startswith("DELETE FROM epg_") for s in statements) >= 6  # 10 rows / 4, x2
    assert db_conn.total_changes - before >= 20
    assert _counts(db_conn)[1:] == (0, 0)
    assert not db_conn.in_transaction


def test_settings_defaults_and_round_trip(db_conn):
    from teamarr.database.channels import get_reconciliation_settings
    from teamarr.database.settings import update_reconciliation_settings

    s = get_reconciliation_settings(db_conn)
    assert s["run_detail_retention_days"] == 7
    assert s["run_history_retention_days"] == 30

    update_reconciliation_settings(
        db_conn, run_detail_retention_days=2, run_history_retention_days=14
    )
    s = get_reconciliation_settings(db_conn)
    assert (s["run_detail_retention_days"], s["run_history_retention_days"]) == (2, 14)


def test_post_generation_cleanup_uses_settings(db_factory, db_conn):
    from teamarr.consumers.generation_pipeline.stats import run_cleanup_tasks
    from teamarr.database.settings import update_reconciliation_settings

    update_reconciliation_settings(
        db_conn, run_detail_retention_days=2, run_history_retention_days=5
    )
    r_old = _insert_run(db_conn, days_ago=6)  # beyond run window → run + details go
    r_mid = _insert_run(db_conn, days_ago=3)  # inside run window, beyond detail → details go
    r_new = _insert_run(db_conn, days_ago=1)  # keeps everything
    for r, d in ((r_old, 6), (r_mid, 3), (r_new, 1)):
        _insert_details(db_conn, r, days_ago=d)
    db_conn.commit()

    results = run_cleanup_tasks(db_factory, None, lambda *a, **k: None)

    assert results["runs"] == {"details_deleted": 12, "runs_deleted": 1}
    assert _counts(db_conn) == (2, 3, 3)


# --- Compaction ------------------------------------------------------------


def test_database_status_reports_size_and_rows(db_path, db_conn):
    from teamarr.database.maintenance import get_database_status

    run = _insert_run(db_conn, days_ago=0)
    _insert_details(db_conn, run, days_ago=0, n=2)
    db_conn.commit()

    status = get_database_status(db_path)

    assert status["file_bytes"] > 0
    assert status["run_count"] == 1
    assert status["detail_rows"] == {"epg_matched_streams": 2, "epg_failed_matches": 2}
    assert status["compaction"]["running"] is False


def test_compact_shrinks_file_after_prune(db_path, db_conn):
    from teamarr.database.maintenance import compact_database, get_database_status

    run = _insert_run(db_conn, days_ago=10)
    gid = _group(db_conn)
    for i in range(3000):
        db_conn.execute(
            "INSERT INTO epg_failed_matches (created_at, run_id, group_id, stream_name, reason,"
            " detail) VALUES (?, ?, ?, ?, 'no_event_found', ?)",
            (_ts(10), run, gid, f"stream {i}", "x" * 400),
        )
    db_conn.commit()
    db_conn.close()
    before = get_database_status(db_path)["file_bytes"]

    from teamarr.database.connection import get_db

    with get_db(db_path) as conn:
        assert cleanup_old_run_details(conn, days=7) == 3000
    # Freed pages, but the file has not shrunk yet.
    status = get_database_status(db_path)
    assert status["reclaimable_bytes"] > 0

    state = compact_database(db_path, wait=True)

    assert state["error"] is None
    assert state["running"] is False
    assert state["after_bytes"] < before
    assert get_database_status(db_path)["reclaimable_bytes"] == 0


def test_compact_refuses_when_volume_is_too_full(db_path, monkeypatch):
    """VACUUM needs the live size free; failing halfway holds generation out
    for nothing, so refuse up front and leave the lock alone (#906)."""
    from teamarr.consumers.generation import _generation_lock
    from teamarr.database import maintenance

    monkeypatch.setattr(maintenance, "_free_disk_bytes", lambda path: 1024)

    with pytest.raises(RuntimeError, match="Not enough free disk space"):
        maintenance.compact_database(db_path, wait=True)
    assert _generation_lock.acquire(blocking=False)
    _generation_lock.release()

    status = maintenance.get_database_status(db_path)
    assert status["free_disk_bytes"] == 1024
    assert 0 < status["live_bytes"] <= status["file_bytes"]


def test_compact_refuses_during_generation(db_path):
    from teamarr.consumers.generation import _generation_lock
    from teamarr.database.maintenance import compact_database

    assert _generation_lock.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError, match="Generation in progress"):
            compact_database(db_path, wait=True)
    finally:
        _generation_lock.release()


def test_compact_releases_generation_lock_on_failure(tmp_path):
    from teamarr.consumers.generation import _generation_lock
    from teamarr.database import maintenance

    bogus = tmp_path / "not-a-db.db"
    bogus.write_bytes(b"definitely not sqlite" * 100)

    state = maintenance.compact_database(bogus, wait=True)

    assert state["error"]
    assert state["running"] is False
    assert _generation_lock.acquire(blocking=False)
    _generation_lock.release()


# --- API -------------------------------------------------------------------


def test_api_status_and_compact(monkeypatch, db_path):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    client = TestClient(app)

    resp = client.get("/api/v1/stats/database")
    assert resp.status_code == 200
    assert set(resp.json()) >= {"file_bytes", "reclaimable_bytes", "detail_rows", "compaction"}

    from teamarr.consumers.generation import _generation_lock

    assert _generation_lock.acquire(blocking=False)
    try:
        resp = client.post("/api/v1/stats/database/compact")
        assert resp.status_code == 409
    finally:
        _generation_lock.release()


def test_api_retention_bounds(monkeypatch, db_path):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    client = TestClient(app)

    current = client.get("/api/v1/settings/reconciliation").json()
    assert current["run_detail_retention_days"] == 7
    resp = client.put(
        "/api/v1/settings/reconciliation", json={**current, "run_detail_retention_days": 0}
    )
    assert resp.status_code == 422
    resp = client.put(
        "/api/v1/settings/reconciliation",
        json={**current, "run_detail_retention_days": 3, "run_history_retention_days": 60},
    )
    assert resp.status_code == 200
    assert resp.json()["run_detail_retention_days"] == 3
    assert resp.json()["run_history_retention_days"] == 60
