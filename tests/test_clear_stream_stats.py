"""Tests for clearing cached stream stats when a group's match cache is cleared.

When a user clears an event group's stream match cache, the cached Dispatcharr
stream stats (managed_channel_streams.stream_stats) should be dropped too so they
get freshly pulled on the next run — like everything else the cache clear resets.
"""

import json
from pathlib import Path

import pytest

from teamarr.database.channels.streams import clear_stream_stats
from teamarr.database.connection import get_connection, init_db


@pytest.fixture
def conn(tmp_path: Path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


def _insert_channel(conn) -> int:
    cur = conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name) "
        "VALUES ('e1', 'espn', 'tvg-1', 'NHL | CAR / VGK')"
    )
    return cur.lastrowid


def _insert_stream(conn, channel_id, stream_id, source_group_id, *, with_stats=True, removed=False):
    stats = json.dumps({"resolution": "1920x1080"}) if with_stats else None
    updated_at = "2026-06-16 00:00:00" if with_stats else None
    removed_at = "2026-06-16 01:00:00" if removed else None
    conn.execute(
        """INSERT INTO managed_channel_streams
           (managed_channel_id, dispatcharr_stream_id, source_group_id,
            stream_stats, stream_stats_updated_at, removed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (channel_id, stream_id, source_group_id, stats, updated_at, removed_at),
    )


def _stats_row(conn, stream_id):
    return conn.execute(
        "SELECT stream_stats, stream_stats_updated_at FROM managed_channel_streams "
        "WHERE dispatcharr_stream_id = ?",
        (stream_id,),
    ).fetchone()


def test_clear_for_group_nulls_stats_and_returns_count(conn):
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100, source_group_id=1)
    _insert_stream(conn, cid, 101, source_group_id=1)
    conn.commit()

    cleared = clear_stream_stats(conn, 1)

    assert cleared == 2
    for sid in (100, 101):
        row = _stats_row(conn, sid)
        assert row["stream_stats"] is None
        assert row["stream_stats_updated_at"] is None


def test_clear_for_group_leaves_other_groups_untouched(conn):
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100, source_group_id=1)
    _insert_stream(conn, cid, 200, source_group_id=2)
    conn.commit()

    cleared = clear_stream_stats(conn, 1)

    assert cleared == 1
    assert _stats_row(conn, 200)["stream_stats"] is not None


def test_clear_for_group_skips_removed_streams(conn):
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100, source_group_id=1, removed=True)
    conn.commit()

    cleared = clear_stream_stats(conn, 1)

    assert cleared == 0
    # Removed-row stats are left as-is (it's out of the active set anyway).
    assert _stats_row(conn, 100)["stream_stats"] is not None


def test_clear_for_group_ignores_already_null_stats(conn):
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100, source_group_id=1, with_stats=False)
    conn.commit()

    # Only rows that actually had stats count, so the log reflects real work.
    assert clear_stream_stats(conn, 1) == 0


def test_clear_all_nulls_every_active_stream(conn):
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100, source_group_id=1)
    _insert_stream(conn, cid, 200, source_group_id=2)
    _insert_stream(conn, cid, 300, source_group_id=3, removed=True)
    conn.commit()

    cleared = clear_stream_stats(conn)

    assert cleared == 2
    assert _stats_row(conn, 100)["stream_stats"] is None
    assert _stats_row(conn, 200)["stream_stats"] is None
    # Removed stream untouched.
    assert _stats_row(conn, 300)["stream_stats"] is not None
