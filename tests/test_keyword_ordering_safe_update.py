"""Keyword-ordering number swap honors the closed-loop update contract (#522).

`KeywordOrderingEnforcer` swaps two Dispatcharr channel numbers, then records
the swap locally. It must not persist the swap unless Dispatcharr confirmed
BOTH updates — the same contract lifecycle's `_safe_update_channel` documents.

Persisting a rejected swap is worse than a no-op: the DB then agrees with
itself, so reconciliation sees no drift and the real mismatch in Dispatcharr
is never re-detected.
"""

from unittest.mock import MagicMock

import pytest

from teamarr.consumers.enforcement.ordering import KeywordOrderingEnforcer
from teamarr.database.connection import get_db, init_db
from teamarr.dispatcharr.types import OperationResult


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    with get_db() as conn:
        # High sentinel id: throwaway test groups use 999990+ so they can't
        # collide with a real group and orphan Dispatcharr channels.
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) "
            "VALUES (999991, 'test-ordering', '[\"nfl\"]')"
        )
        # A main channel numbered ABOVE its keyword sibling — needs a swap.
        conn.execute(
            """INSERT INTO managed_channels
               (id, event_id, event_provider, tvg_id, event_epg_group_id,
                channel_name, channel_number, dispatcharr_channel_id,
                exception_keyword)
               VALUES (1, 'evt-1', 'espn', 'tvg-main', 999991,
                       'Main', 200, 1001, NULL)"""
        )
        conn.execute(
            """INSERT INTO managed_channels
               (id, event_id, event_provider, tvg_id, event_epg_group_id,
                channel_name, channel_number, dispatcharr_channel_id,
                exception_keyword)
               VALUES (2, 'evt-1', 'espn', 'tvg-es', 999991,
                       'Main (ES)', 100, 1002, 'spanish')"""
        )
        conn.commit()
    yield


def _numbers() -> tuple[int, int]:
    with get_db() as conn:
        # channel_number is stored TEXT (hence the CAST in the pair query).
        rows = {
            r["id"]: int(r["channel_number"])
            for r in conn.execute(
                "SELECT id, channel_number FROM managed_channels ORDER BY id"
            )
        }
    return rows[1], rows[2]


def _enforcer(main_result: bool, keyword_result: bool) -> KeywordOrderingEnforcer:
    manager = MagicMock()
    manager.update_channel.side_effect = [
        OperationResult(success=main_result),
        OperationResult(success=keyword_result),
    ]
    return KeywordOrderingEnforcer(db_factory=get_db, channel_manager=manager)


def test_swap_persists_when_dispatcharr_confirms_both(db):
    result = _enforcer(True, True).enforce()

    assert result.reordered_count == 1
    assert not result.errors
    assert _numbers() == (100, 200), "main should take the lower number"


def test_swap_not_persisted_when_first_update_fails(db):
    before = _numbers()
    result = _enforcer(False, True).enforce()

    assert _numbers() == before, "DB must stay unchanged so drift is re-detected"
    assert result.reordered_count == 0
    assert result.errors


def test_swap_not_persisted_when_second_update_fails(db):
    """The dangerous half-swap: Dispatcharr took the first write, rejected the
    second. The DB must still not record a completed swap."""
    before = _numbers()
    result = _enforcer(True, False).enforce()

    assert _numbers() == before
    assert result.reordered_count == 0
    assert result.errors


def test_no_history_row_written_for_a_rejected_swap(db):
    _enforcer(True, False).enforce()

    with get_db() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM managed_channel_history "
            "WHERE change_type = 'number_swapped'"
        ).fetchone()
    assert rows["n"] == 0, "a rejected swap must not leave a 'number_swapped' audit row"
