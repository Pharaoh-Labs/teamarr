"""Tests for clearing cached stream stats when a group's match cache is cleared.

When a user clears an event group's stream match cache, the cached Dispatcharr
stream stats (managed_channel_streams.stream_stats) should be dropped too so they
get freshly pulled on the next run — like everything else the cache clear resets.
"""

import json

from teamarr.database.channels.streams import clear_stream_stats


def _insert_channel(db_conn) -> int:
    cur = db_conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name) "
        "VALUES ('e1', 'espn', 'tvg-1', 'NHL | CAR / VGK')"
    )
    return cur.lastrowid


def _insert_stream(
    db_conn, channel_id, stream_id, source_group_id, *, with_stats=True, removed=False
):
    stats = json.dumps({"resolution": "1920x1080"}) if with_stats else None
    updated_at = "2026-06-16 00:00:00" if with_stats else None
    removed_at = "2026-06-16 01:00:00" if removed else None
    db_conn.execute(
        """INSERT INTO managed_channel_streams
           (managed_channel_id, dispatcharr_stream_id, source_group_id,
            stream_stats, stream_stats_updated_at, removed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (channel_id, stream_id, source_group_id, stats, updated_at, removed_at),
    )


def _stats_row(db_conn, stream_id):
    return db_conn.execute(
        "SELECT stream_stats, stream_stats_updated_at FROM managed_channel_streams "
        "WHERE dispatcharr_stream_id = ?",
        (stream_id,),
    ).fetchone()


def test_clear_for_group_nulls_stats_and_returns_count(db_conn):
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, source_group_id=1)
    _insert_stream(db_conn, cid, 101, source_group_id=1)
    db_conn.commit()

    cleared = clear_stream_stats(db_conn, 1)

    assert cleared == 2
    for sid in (100, 101):
        row = _stats_row(db_conn, sid)
        assert row["stream_stats"] is None
        assert row["stream_stats_updated_at"] is None


def test_clear_for_group_leaves_other_groups_untouched(db_conn):
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, source_group_id=1)
    _insert_stream(db_conn, cid, 200, source_group_id=2)
    db_conn.commit()

    cleared = clear_stream_stats(db_conn, 1)

    assert cleared == 1
    assert _stats_row(db_conn, 200)["stream_stats"] is not None


def test_clear_for_group_skips_removed_streams(db_conn):
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, source_group_id=1, removed=True)
    db_conn.commit()

    cleared = clear_stream_stats(db_conn, 1)

    assert cleared == 0
    # Removed-row stats are left as-is (it's out of the active set anyway).
    assert _stats_row(db_conn, 100)["stream_stats"] is not None


def test_clear_for_group_ignores_already_null_stats(db_conn):
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, source_group_id=1, with_stats=False)
    db_conn.commit()

    # Only rows that actually had stats count, so the log reflects real work.
    assert clear_stream_stats(db_conn, 1) == 0


def test_clear_all_nulls_every_active_stream(db_conn):
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, source_group_id=1)
    _insert_stream(db_conn, cid, 200, source_group_id=2)
    _insert_stream(db_conn, cid, 300, source_group_id=3, removed=True)
    db_conn.commit()

    cleared = clear_stream_stats(db_conn)

    assert cleared == 2
    assert _stats_row(db_conn, 100)["stream_stats"] is None
    assert _stats_row(db_conn, 200)["stream_stats"] is None
    # Removed stream untouched.
    assert _stats_row(db_conn, 300)["stream_stats"] is not None
