"""Tests for get_stream_match_details — cache-derived 'how it matched' detail.

Reads stream_match_cache to explain a stream's match (matched event, method,
user correction). Used by the Managed Channels method popover.
"""

import json
from pathlib import Path

import pytest

from teamarr.database.channels.streams import get_stream_match_details
from teamarr.database.connection import get_connection, init_db


@pytest.fixture
def conn(tmp_path: Path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


def _insert(conn, group_id, stream_id, *, event_id="e1", league="nhl",
            event_name="Hurricanes at Golden Knights", method="fuzzy",
            user_corrected=0, corrected_at=None, updated_at="2026-06-16 00:00:00",
            fingerprint=None):
    data = json.dumps({"name": event_name}) if event_name is not None else None
    conn.execute(
        """INSERT INTO stream_match_cache
           (fingerprint, group_id, stream_id, stream_name, event_id, league,
            cached_event_data, match_method, user_corrected, corrected_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fingerprint or f"fp-{group_id}-{stream_id}-{updated_at}", group_id, stream_id,
         "ESPN", event_id, league, data, method, user_corrected, corrected_at, updated_at),
    )
    conn.commit()


def test_returns_match_detail_for_pair(conn):
    _insert(conn, 1, 100, event_name="Hurricanes at Golden Knights", method="alias",
            user_corrected=1, corrected_at="2026-06-15 12:00:00")

    out = get_stream_match_details(conn, [(1, 100)])

    assert (1, 100) in out
    d = out[(1, 100)]
    assert d["event_name"] == "Hurricanes at Golden Knights"
    assert d["league"] == "nhl"
    assert d["match_method"] == "alias"
    assert d["user_corrected"] is True
    assert d["corrected_at"] == "2026-06-15 12:00:00"


def test_failed_match_is_excluded(conn):
    _insert(conn, 1, 100, event_id="__FAILED__", event_name=None, method="no_match")
    assert get_stream_match_details(conn, [(1, 100)]) == {}


def test_unrequested_pairs_excluded(conn):
    _insert(conn, 1, 100)
    _insert(conn, 2, 200)
    out = get_stream_match_details(conn, [(1, 100)])
    assert set(out.keys()) == {(1, 100)}


def test_most_recent_row_wins_per_pair(conn):
    _insert(conn, 1, 100, event_name="Old Event", method="fuzzy",
            updated_at="2026-06-10 00:00:00")
    _insert(conn, 1, 100, event_name="New Event", method="alias",
            updated_at="2026-06-16 00:00:00")

    d = get_stream_match_details(conn, [(1, 100)])[(1, 100)]
    assert d["event_name"] == "New Event"
    assert d["match_method"] == "alias"


def test_empty_pairs_returns_empty(conn):
    assert get_stream_match_details(conn, []) == {}
