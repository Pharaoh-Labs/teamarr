"""Enforcement must not run inside the group processor's write transaction (#607).

`process_all_groups` holds one connection open for the whole groups phase and
writes through it (`store_group_xmltv`, per group), committing only when its
`with` block exits. Every enforcer opens its *own* connection. Running them
inside that block therefore put two connections from a single thread on either
side of the SQLite write lock: the enforcer waited out the full 30s
`busy_timeout` and lost its write, every run, because the lock could not be
released until the block it was blocking exited.

These tests pin the mechanism and the fix. The pre-existing enforcement tests
could not see this at all — they run enforcement standalone, where no outer
connection exists.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.event_group_processor.processor import EventGroupProcessor
from teamarr.database.connection import get_connection, get_db


def _write(conn: sqlite3.Connection, key: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO settings (id, epg_output_path) VALUES (1, ?)", (key,)
    )


def test_a_second_connection_cannot_write_under_an_open_write_txn(db_path):
    """The mechanism, stated as a test: this is why enforcement failed.

    Not a test of our code — a test of the constraint our code has to respect,
    so the reasoning behind the ordering below is verifiable rather than
    asserted in a comment.
    """
    holder = get_connection(db_path)
    holder.execute("PRAGMA busy_timeout=200")  # keep the test fast
    _write(holder, "holder")  # takes the WAL write lock, uncommitted

    other = get_connection(db_path)
    other.execute("PRAGMA busy_timeout=200")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            _write(other, "other")
    finally:
        other.close()
        holder.rollback()
        holder.close()


def test_enforcement_runs_after_the_groups_connection_is_closed(db_path, db_factory):
    """The regression guard: an enforcer's own connection must be able to write.

    Before the fix this raised `database is locked` after a 30s stall, because
    `_run_enforcement` was called inside the `with self._db_factory() as conn:`
    block that had been writing since the first group.
    """
    processor = EventGroupProcessor(db_factory=db_factory, service=MagicMock())

    observed: dict[str, object] = {}

    def fake_enforcement(multi_league_ids, lifecycle_service=None):
        # Exactly what a real enforcer does: open a fresh connection and write.
        try:
            with get_db(db_path) as own:
                own.execute("PRAGMA busy_timeout=200")
                _write(own, "enforcement")
            observed["wrote"] = True
        except sqlite3.OperationalError as e:
            observed["wrote"] = False
            observed["error"] = str(e)
        return []

    processor._run_enforcement = fake_enforcement  # type: ignore[method-assign]
    processor.process_all_groups(date.today())

    assert observed.get("wrote") is True, (
        f"enforcement could not write: {observed.get('error')} — it is running "
        "inside the group processor's uncommitted write transaction again (#607)"
    )


def test_enforcement_sees_the_run_it_is_enforcing(db_path, db_factory):
    """The second half of the bug: it was also reading a pre-run snapshot.

    A second connection sees only committed state, so while the groups phase
    held its transaction open the enforcers were reading the database as it
    looked BEFORE this run — enforcing against channels that no longer matched
    reality. That was true even on the runs where the write did not deadlock.
    """
    processor = EventGroupProcessor(db_factory=db_factory, service=MagicMock())

    with get_db(db_path) as setup:
        _write(setup, "before-this-run")

    # Stand in for the groups phase's own write, on the processor's connection.
    original = processor._store_group_xmltv
    seen: dict[str, object] = {}

    def fake_enforcement(multi_league_ids, lifecycle_service=None):
        with get_db(db_path) as own:
            row = own.execute("SELECT epg_output_path FROM settings WHERE id=1").fetchone()
            seen["value"] = row[0] if row else None
        return []

    def marking_store(conn, group_id, content):
        _write(conn, "written-by-this-run")
        return original(conn, group_id, content)

    processor._store_group_xmltv = marking_store  # type: ignore[method-assign]
    processor._run_enforcement = fake_enforcement  # type: ignore[method-assign]

    with get_db(db_path) as conn:
        _write(conn, "written-by-this-run")

    processor.process_all_groups(date.today())

    assert seen.get("value") == "written-by-this-run", (
        f"enforcement read {seen.get('value')!r} — a snapshot from before the run (#607)"
    )


def test_run_enforcement_does_not_borrow_a_caller_connection(db_factory):
    """Its signature is the guard rail.

    `_run_enforcement` taking a live `conn` is what made it natural to call from
    inside the block. Keeping the connection out of the signature makes the
    correct call site the only convenient one.
    """
    import inspect

    params = inspect.signature(EventGroupProcessor._run_enforcement).parameters
    assert "conn" not in params, (
        "_run_enforcement must not accept a caller's connection — see #607"
    )
