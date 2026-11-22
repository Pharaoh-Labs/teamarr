"""The Sources page arrangement is cosmetic (#1109).

``sort_order`` used to be the processing order, and so — through attach
time — the stream tie-break inside a priority band. That made the drag list
a second place to say "this source's feed first" beside Stream Ordering.
Now the run reads sources by id and the tie-break is source id, then attach
time, in both the SQL readers and the in-memory sort.
"""

from datetime import datetime

from teamarr.database.channels.crud import mark_all_channels_deleted, mark_channel_deleted
from teamarr.database.channels.streams import (
    get_all_channel_streams,
    get_all_ordered_stream_ids,
    get_channel_streams,
    get_ordered_stream_ids,
)
from teamarr.database.channels.types import ManagedChannelStream
from teamarr.database.groups import get_all_groups
from teamarr.services.stream_ordering import StreamOrderingService


def _group(conn, name, sort_order):
    conn.execute(
        "INSERT INTO event_epg_groups"
        " (name, leagues, m3u_group_id, m3u_group_name, sort_order, enabled)"
        " VALUES (?, '[]', ?, ?, ?, 1)",
        (name, 1000 + sort_order, name, sort_order),
    )


def test_processing_order_ignores_the_arrangement(db_conn):
    _group(db_conn, "created first, dragged last", 9)
    _group(db_conn, "created second, dragged first", 1)
    db_conn.commit()

    shown = [g.name for g in get_all_groups(db_conn)]
    processed = [g.name for g in get_all_groups(db_conn, processing_order=True)]

    assert shown == ["created second, dragged first", "created first, dragged last"]
    assert processed == ["created first, dragged last", "created second, dragged first"]


def _attach(conn, channel_id, stream_id, source_group_id, added_at, priority=5):
    conn.execute(
        """INSERT INTO managed_channel_streams
           (managed_channel_id, dispatcharr_stream_id, stream_name, priority,
            source_group_id, added_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (channel_id, stream_id, f"stream {stream_id}", priority, source_group_id, added_at),
    )


def test_sql_tie_break_is_source_id_then_attach_time(db_conn):
    db_conn.execute(
        "INSERT INTO managed_channels (id, event_id, event_provider, tvg_id, channel_name)"
        " VALUES (1, 'e1', 'espn', 'tvg1', 'Test Channel')"
    )
    # Same band. Attached in the order 3, 2, 1 by time; source ids 7, 7, 3;
    # one hand-attached stream (no source) added before all of them.
    _attach(db_conn, 1, 901, None, "2026-01-01 00:00:00")
    _attach(db_conn, 1, 903, 7, "2026-01-01 00:00:01")
    _attach(db_conn, 1, 902, 7, "2026-01-01 00:00:02")
    _attach(db_conn, 1, 904, 3, "2026-01-01 00:00:03")
    _attach(db_conn, 1, 905, 3, "2026-01-01 00:00:04", priority=1)
    db_conn.commit()

    expected = [905, 904, 903, 902, 901]
    assert get_ordered_stream_ids(db_conn, 1) == expected
    assert get_all_ordered_stream_ids(db_conn)[1] == expected
    assert [s.dispatcharr_stream_id for s in get_channel_streams(db_conn, 1)] == expected


def _stream(stream_id, source_group_id, added_at, priority=5):
    return ManagedChannelStream(
        id=stream_id,
        managed_channel_id=1,
        dispatcharr_stream_id=stream_id,
        stream_name=f"stream {stream_id}",
        priority=priority,
        source_group_id=source_group_id,
        added_at=datetime(2026, 1, 1, 0, 0, added_at),
    )


def test_in_memory_sort_agrees_with_sql():
    streams = [
        _stream(901, None, 0),
        _stream(903, 7, 1),
        _stream(902, 7, 2),
        _stream(904, 3, 3),
        _stream(905, 3, 4, priority=1),
    ]
    ordered = StreamOrderingService([]).sort_streams(streams)
    assert [s.dispatcharr_stream_id for s in ordered] == [905, 904, 903, 902, 901]


def test_soft_deleted_channels_excluded_from_bulk_stream_reads_and_cleaned_up(db_conn):
    """Soft-deleted channels do not leak zombie streams into bulk scans (#1263)."""
    db_conn.execute(
        "INSERT INTO managed_channels (id, event_id, event_provider, tvg_id, channel_name)"
        " VALUES (1, 'e1', 'espn', 'tvg1', 'Active Channel'),"
        "        (2, 'e2', 'espn', 'tvg2', 'Deleted Channel'),"
        "        (3, 'e3', 'espn', 'tvg3', 'Legacy Zombie Channel')"
    )
    _attach(db_conn, 1, 101, 1, "2026-01-01 00:00:00")
    _attach(db_conn, 2, 202, 1, "2026-01-01 00:00:00")
    _attach(db_conn, 3, 303, 1, "2026-01-01 00:00:00")
    # Simulate a legacy soft-deleted channel whose stream row was left removed_at IS NULL.
    db_conn.execute("UPDATE managed_channels SET deleted_at = datetime('now') WHERE id = 3")
    # Delete channel 2 through mark_channel_deleted — should also soft-remove its streams.
    assert mark_channel_deleted(db_conn, 2, reason="expired")
    db_conn.commit()

    ch2_stream = db_conn.execute(
        "SELECT removed_at, remove_reason FROM managed_channel_streams WHERE managed_channel_id = 2"
    ).fetchone()
    assert ch2_stream["removed_at"] is not None
    assert ch2_stream["remove_reason"] == "expired"

    # Both bulk readers return only channel 1 (excluding legacy zombie channel 3 too).
    assert set(get_all_channel_streams(db_conn)) == {1}
    assert get_all_ordered_stream_ids(db_conn) == {1: [101]}

    # Reset marks remaining active channels deleted and soft-removes their streams.
    mark_all_channels_deleted(db_conn)
    assert get_all_channel_streams(db_conn) == {}
    assert get_all_ordered_stream_ids(db_conn) == {}
    ch1_stream = db_conn.execute(
        "SELECT removed_at, remove_reason FROM managed_channel_streams WHERE managed_channel_id = 1"
    ).fetchone()
    assert ch1_stream["removed_at"] is not None
    assert ch1_stream["remove_reason"] == "channel_deleted"

    # Verify idx_mch_changed_at index exists on managed_channel_history (#1263).
    indexes = {
        row["name"]
        for row in db_conn.execute("PRAGMA index_list('managed_channel_history')").fetchall()
    }
    assert "idx_mch_changed_at" in indexes
