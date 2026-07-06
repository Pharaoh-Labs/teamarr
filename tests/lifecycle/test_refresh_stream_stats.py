"""Tests for refresh_stream_stats — caching Dispatcharr stream_stats locally.

refresh_stream_stats pulls stats for a managed channel's active streams from
Dispatcharr (via get_stream_stats_by_ids) and writes them to the
stream_stats / stream_stats_updated_at columns. Streams Dispatcharr hasn't
probed yet (stream_stats=None) are left unchanged.
"""

import json
from pathlib import Path

import pytest

import teamarr.dispatcharr.factory as factory
from teamarr.database.channels.streams import refresh_stream_stats
from teamarr.database.connection import get_connection, init_db


@pytest.fixture
def conn(tmp_path: Path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


class _StubClient:
    def __init__(self, stats_list):
        self._stats_list = stats_list
        self.calls = []

    def get_stream_stats_by_ids(self, stream_ids):
        self.calls.append(list(stream_ids))
        return self._stats_list


@pytest.fixture
def patch_client(monkeypatch):
    """Install a stub Dispatcharr client; return a setter for the stub/None."""
    holder = {}

    def install(client):
        holder["client"] = client
        monkeypatch.setattr(factory, "get_dispatcharr_client", lambda: client)
        return client

    install(None)
    return install, holder


def _insert_channel(conn) -> int:
    cur = conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name) "
        "VALUES ('e1', 'espn', 'tvg-1', 'NHL | CAR / VGK')"
    )
    return cur.lastrowid


def _insert_stream(conn, channel_id, stream_id, *, removed=False):
    conn.execute(
        """INSERT INTO managed_channel_streams
           (managed_channel_id, dispatcharr_stream_id, removed_at)
           VALUES (?, ?, ?)""",
        (channel_id, stream_id, "2026-06-16 01:00:00" if removed else None),
    )


def _stats_row(conn, stream_id):
    return conn.execute(
        "SELECT stream_stats, stream_stats_updated_at FROM managed_channel_streams "
        "WHERE dispatcharr_stream_id = ?",
        (stream_id,),
    ).fetchone()


def test_no_active_streams_returns_zero_without_client(conn, patch_client):
    install, _ = patch_client
    stub = _StubClient([{"id": 1, "stream_stats": {"x": 1}, "stream_stats_updated_at": "t"}])
    install(stub)
    cid = _insert_channel(conn)  # channel with no streams
    conn.commit()

    assert refresh_stream_stats(conn, cid) == 0
    assert stub.calls == []  # short-circuits before touching the client


def test_client_none_returns_zero(conn, patch_client):
    install, _ = patch_client
    install(None)
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100)
    conn.commit()

    assert refresh_stream_stats(conn, cid) == 0


def test_empty_stats_list_returns_zero(conn, patch_client):
    install, _ = patch_client
    install(_StubClient([]))
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100)
    conn.commit()

    assert refresh_stream_stats(conn, cid) == 0
    assert _stats_row(conn, 100)["stream_stats"] is None


def test_happy_path_persists_stats_as_json(conn, patch_client):
    install, _ = patch_client
    install(_StubClient([
        {
            "id": 100,
            "stream_stats": {"resolution": "1920x1080"},
            "stream_stats_updated_at": "2026-06-16T00:00:00Z",
        },
    ]))
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100)
    conn.commit()

    assert refresh_stream_stats(conn, cid) == 1
    row = _stats_row(conn, 100)
    assert json.loads(row["stream_stats"]) == {"resolution": "1920x1080"}
    assert row["stream_stats_updated_at"] == "2026-06-16T00:00:00Z"


def test_unprobed_stream_is_skipped(conn, patch_client):
    install, _ = patch_client
    install(_StubClient([
        {"id": 100, "stream_stats": None, "stream_stats_updated_at": None},
        {"id": 101, "stream_stats": {"source_fps": 60}, "stream_stats_updated_at": "t"},
    ]))
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100)
    _insert_stream(conn, cid, 101)
    conn.commit()

    assert refresh_stream_stats(conn, cid) == 1
    assert _stats_row(conn, 100)["stream_stats"] is None
    assert json.loads(_stats_row(conn, 101)["stream_stats"]) == {"source_fps": 60}


def test_removed_streams_not_selected(conn, patch_client):
    install, _ = patch_client
    stub = _StubClient([{"id": 100, "stream_stats": {"x": 1}, "stream_stats_updated_at": "t"}])
    install(stub)
    cid = _insert_channel(conn)
    _insert_stream(conn, cid, 100, removed=True)
    conn.commit()

    # No active streams → returns 0 and the client is never queried.
    assert refresh_stream_stats(conn, cid) == 0
    assert stub.calls == []
