"""Tests for the clear_group_match_data / clear_all_match_data orchestrators.

These pair the two halves of "redo this group from scratch": wiping the
stream_match_cache AND nulling cached stream stats. The orchestrators keep them
together so a caller can't clear one and forget the other.
"""

from teamarr.consumers.stream_match_cache import (
    clear_all_match_data,
    clear_group_match_data,
)


def _seed(conn, group_id: int, stream_id: int):
    """Insert one match-cache row and one stat-bearing stream for a group."""
    conn.execute(
        """INSERT INTO stream_match_cache
           (fingerprint, group_id, stream_id, stream_name, event_id, league)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (f"fp-{group_id}-{stream_id}", group_id, stream_id, "ESPN", "e1", "nhl"),
    )
    cur = conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name) "
        "VALUES ('e1', 'espn', 'tvg-1', 'NHL | CAR / VGK')"
    )
    conn.execute(
        """INSERT INTO managed_channel_streams
           (managed_channel_id, dispatcharr_stream_id, source_group_id,
            stream_stats, stream_stats_updated_at)
           VALUES (?, ?, ?, '{"resolution": "1920x1080"}', '2026-06-16 00:00:00')""",
        (cur.lastrowid, stream_id, group_id),
    )
    conn.commit()


def _counts(conn, group_id: int):
    cache = conn.execute(
        "SELECT COUNT(*) FROM stream_match_cache WHERE group_id = ?", (group_id,)
    ).fetchone()[0]
    stats = conn.execute(
        "SELECT COUNT(*) FROM managed_channel_streams "
        "WHERE source_group_id = ? AND stream_stats IS NOT NULL",
        (group_id,),
    ).fetchone()[0]
    return cache, stats


def test_clear_group_clears_both_tables(db_factory, db_conn):
    _seed(db_conn, group_id=1, stream_id=100)
    _seed(db_conn, group_id=2, stream_id=200)

    entries, stats = clear_group_match_data(db_factory, 1)

    assert (entries, stats) == (1, 1)
    assert _counts(db_conn, 1) == (0, 0)  # group 1 fully cleared
    assert _counts(db_conn, 2) == (1, 1)  # group 2 untouched


def test_clear_all_clears_every_group(db_factory, db_conn):
    _seed(db_conn, group_id=1, stream_id=100)
    _seed(db_conn, group_id=2, stream_id=200)

    entries, stats = clear_all_match_data(db_factory)

    assert entries == 2
    assert stats == 2
    assert _counts(db_conn, 1) == (0, 0)
    assert _counts(db_conn, 2) == (0, 0)
