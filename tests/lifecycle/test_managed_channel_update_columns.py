"""Regression tests for managed_channels update column safety (bead teamarrv2-91l).

The stream-drift path in _sync_channel_settings used to write
db_updates["dispatcharr_stream_id"] and pass it to update_managed_channel(),
which UPDATEs the managed_channels table. But dispatcharr_stream_id only exists
on managed_channel_streams — so it raised "no such column: dispatcharr_stream_id"
on every drift fix and aborted the per-channel settings sync. These tests pin the
schema split and confirm the legitimate update fields work.
"""

import sqlite3

import pytest

from teamarr.database.channels.crud import update_managed_channel


def _columns(db_conn, table: str) -> set[str]:
    return {row["name"] for row in db_conn.execute(f"PRAGMA table_info({table})")}


def test_stream_id_column_lives_only_on_streams_table(db_conn):
    # The schema split: per-stream id is on managed_channel_streams, never on
    # managed_channels. Code must add stream membership via add_stream_to_channel,
    # not by updating a column on the channel row.
    assert "dispatcharr_stream_id" not in _columns(db_conn, "managed_channels")
    assert "dispatcharr_stream_id" in _columns(db_conn, "managed_channel_streams")


def _insert_channel(db_conn) -> int:
    cur = db_conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name) "
        "VALUES ('e1', 'espn', 'tvg-1', 'NHL | CAR / VGK')"
    )
    db_conn.commit()
    return cur.lastrowid


def test_update_with_real_sync_fields_succeeds(db_conn):
    # The fields the drift/settings-sync path legitimately writes.
    cid = _insert_channel(db_conn)
    ok = update_managed_channel(
        db_conn,
        cid,
        {
            "channel_name": "NHL | CAR @ VGK",
            "tvg_id": "tvg-2",
            "scheduled_delete_at": "2026-06-07 02:00:00",
        },
    )
    assert ok is True
    row = db_conn.execute(
        "SELECT channel_name, tvg_id, scheduled_delete_at FROM managed_channels WHERE id = ?",
        (cid,),
    ).fetchone()
    assert row["channel_name"] == "NHL | CAR @ VGK"
    assert row["tvg_id"] == "tvg-2"
    assert row["scheduled_delete_at"] == "2026-06-07 02:00:00"


def test_update_with_stream_id_column_raises(db_conn):
    # Guards the regression: routing a per-stream id through the channel update
    # must fail loudly (it's not a managed_channels column), so nobody reintroduces
    # the V1-parity leftover that caused bead 91l.
    cid = _insert_channel(db_conn)
    with pytest.raises(sqlite3.OperationalError, match="dispatcharr_stream_id"):
        update_managed_channel(db_conn, cid, {"dispatcharr_stream_id": 123})
