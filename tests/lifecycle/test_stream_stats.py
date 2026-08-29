"""Cached Dispatcharr stream stats: parsing, refresh, and clearing.

The DB stores managed_channel_streams.stream_stats as a JSON string.
- ManagedChannelStream.from_row decodes it to a dict, tolerates malformed JSON
  (→ None), and passes a dict through unchanged.
- refresh_stream_stats pulls stats for a managed channel's active streams from
  Dispatcharr (via get_stream_stats_by_ids) and writes them to the
  stream_stats / stream_stats_updated_at columns; streams Dispatcharr hasn't
  probed yet (stream_stats=None) are left unchanged.
- clear_stream_stats drops the cached stats when a group's match cache is
  cleared, so they get freshly pulled on the next run — like everything else
  the cache clear resets.
- get_active_dispatcharr_stream_ids / refresh_stream_stats_bulk are the
  ordering pass's route to the same data (#576, #616): one chunked fetch for
  every stream on a live channel, written to every row that holds it, instead
  of one HTTP round trip per channel.
"""

import json

import pytest

import teamarr.database.channels.streams as streams_mod
from teamarr.database.channels.streams import (
    clear_stream_stats,
    get_active_dispatcharr_stream_ids,
    refresh_stream_stats,
    refresh_stream_stats_bulk,
)
from teamarr.database.channels.types import ManagedChannelStream


def _insert_channel(db_conn) -> int:
    cur = db_conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name) "
        "VALUES ('e1', 'espn', 'tvg-1', 'NHL | CAR / VGK')"
    )
    return cur.lastrowid


def _insert_stream(
    db_conn, channel_id, stream_id, source_group_id=None, *, with_stats=False, removed=False
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


# ---------------------------------------------------------------------------
# ManagedChannelStream.from_row stream_stats JSON handling
# ---------------------------------------------------------------------------


def _row(stream_stats):
    return {
        "id": 1,
        "managed_channel_id": 1,
        "dispatcharr_stream_id": 100,
        "stream_stats": stream_stats,
    }


def test_valid_json_string_decoded_to_dict():
    s = ManagedChannelStream.from_row(_row('{"resolution": "1920x1080"}'))
    assert s.stream_stats == {"resolution": "1920x1080"}


def test_invalid_json_string_becomes_none():
    s = ManagedChannelStream.from_row(_row("{not valid json"))
    assert s.stream_stats is None


def test_dict_passthrough():
    s = ManagedChannelStream.from_row(_row({"source_fps": 60}))
    assert s.stream_stats == {"source_fps": 60}


def test_missing_stats_is_none():
    row = {"id": 1, "managed_channel_id": 1, "dispatcharr_stream_id": 100}
    assert ManagedChannelStream.from_row(row).stream_stats is None
    assert ManagedChannelStream.from_row(_row(None)).stream_stats is None


# ---------------------------------------------------------------------------
# refresh_stream_stats — caching Dispatcharr stream_stats locally
# ---------------------------------------------------------------------------


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
        monkeypatch.setattr(streams_mod, "get_dispatcharr_client", lambda: client)
        return client

    install(None)
    return install, holder


def test_no_active_streams_returns_zero_without_client(db_conn, patch_client):
    install, _ = patch_client
    stub = _StubClient([{"id": 1, "stream_stats": {"x": 1}, "stream_stats_updated_at": "t"}])
    install(stub)
    cid = _insert_channel(db_conn)  # channel with no streams
    db_conn.commit()

    assert refresh_stream_stats(db_conn, cid) == 0
    assert stub.calls == []  # short-circuits before touching the client


def test_client_none_returns_zero(db_conn, patch_client):
    install, _ = patch_client
    install(None)
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100)
    db_conn.commit()

    assert refresh_stream_stats(db_conn, cid) == 0


def test_empty_stats_list_returns_zero(db_conn, patch_client):
    install, _ = patch_client
    install(_StubClient([]))
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100)
    db_conn.commit()

    assert refresh_stream_stats(db_conn, cid) == 0
    assert _stats_row(db_conn, 100)["stream_stats"] is None


def test_happy_path_persists_stats_as_json(db_conn, patch_client):
    install, _ = patch_client
    install(_StubClient([
        {
            "id": 100,
            "stream_stats": {"resolution": "1920x1080"},
            "stream_stats_updated_at": "2026-06-16T00:00:00Z",
        },
    ]))
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100)
    db_conn.commit()

    assert refresh_stream_stats(db_conn, cid) == 1
    row = _stats_row(db_conn, 100)
    assert json.loads(row["stream_stats"]) == {"resolution": "1920x1080"}
    assert row["stream_stats_updated_at"] == "2026-06-16T00:00:00Z"


def test_unprobed_stream_is_skipped(db_conn, patch_client):
    install, _ = patch_client
    install(_StubClient([
        {"id": 100, "stream_stats": None, "stream_stats_updated_at": None},
        {"id": 101, "stream_stats": {"source_fps": 60}, "stream_stats_updated_at": "t"},
    ]))
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100)
    _insert_stream(db_conn, cid, 101)
    db_conn.commit()

    assert refresh_stream_stats(db_conn, cid) == 1
    assert _stats_row(db_conn, 100)["stream_stats"] is None
    assert json.loads(_stats_row(db_conn, 101)["stream_stats"]) == {"source_fps": 60}


def test_removed_streams_not_selected(db_conn, patch_client):
    install, _ = patch_client
    stub = _StubClient([{"id": 100, "stream_stats": {"x": 1}, "stream_stats_updated_at": "t"}])
    install(stub)
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, removed=True)
    db_conn.commit()

    # No active streams → returns 0 and the client is never queried.
    assert refresh_stream_stats(db_conn, cid) == 0
    assert stub.calls == []


# ---------------------------------------------------------------------------
# clear_stream_stats — dropping cached stats on match-cache clear
# ---------------------------------------------------------------------------


def test_clear_for_group_nulls_stats_and_returns_count(db_conn):
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, source_group_id=1, with_stats=True)
    _insert_stream(db_conn, cid, 101, source_group_id=1, with_stats=True)
    db_conn.commit()

    cleared = clear_stream_stats(db_conn, 1)

    assert cleared == 2
    for sid in (100, 101):
        row = _stats_row(db_conn, sid)
        assert row["stream_stats"] is None
        assert row["stream_stats_updated_at"] is None


def test_clear_for_group_leaves_other_groups_untouched(db_conn):
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, source_group_id=1, with_stats=True)
    _insert_stream(db_conn, cid, 200, source_group_id=2, with_stats=True)
    db_conn.commit()

    cleared = clear_stream_stats(db_conn, 1)

    assert cleared == 1
    assert _stats_row(db_conn, 200)["stream_stats"] is not None


def test_clear_for_group_skips_removed_streams(db_conn):
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, source_group_id=1, with_stats=True, removed=True)
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
    _insert_stream(db_conn, cid, 100, source_group_id=1, with_stats=True)
    _insert_stream(db_conn, cid, 200, source_group_id=2, with_stats=True)
    _insert_stream(db_conn, cid, 300, source_group_id=3, with_stats=True, removed=True)
    db_conn.commit()

    cleared = clear_stream_stats(db_conn)

    assert cleared == 2
    assert _stats_row(db_conn, 100)["stream_stats"] is None
    assert _stats_row(db_conn, 200)["stream_stats"] is None
    # Removed stream untouched.
    assert _stats_row(db_conn, 300)["stream_stats"] is not None


# ---------------------------------------------------------------------------
# get_active_dispatcharr_stream_ids — the population an ordering pass scores
# ---------------------------------------------------------------------------


def _insert_deleted_channel(db_conn) -> int:
    cur = db_conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name, deleted_at) "
        "VALUES ('e2', 'espn', 'tvg-2', 'Gone', '2026-08-01 00:00:00')"
    )
    return cur.lastrowid


def test_active_ids_excludes_removed_streams(db_conn):
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100)
    _insert_stream(db_conn, cid, 101, removed=True)
    db_conn.commit()

    assert get_active_dispatcharr_stream_ids(db_conn) == [100]


def test_active_ids_excludes_soft_deleted_channels(db_conn):
    live = _insert_channel(db_conn)
    dead = _insert_deleted_channel(db_conn)
    _insert_stream(db_conn, live, 100)
    _insert_stream(db_conn, dead, 200)
    db_conn.commit()

    assert get_active_dispatcharr_stream_ids(db_conn) == [100]


def test_active_ids_dedupes_a_stream_on_several_channels(db_conn):
    first = _insert_channel(db_conn)
    second = _insert_channel(db_conn)
    _insert_stream(db_conn, first, 100)
    _insert_stream(db_conn, second, 100)
    db_conn.commit()

    # One fetch, not one per channel — the reason the bulk path exists.
    assert get_active_dispatcharr_stream_ids(db_conn) == [100]


# ---------------------------------------------------------------------------
# refresh_stream_stats_bulk — one fetch for the whole ordering population
# ---------------------------------------------------------------------------


def test_bulk_empty_ids_returns_zero_without_client(db_conn, patch_client):
    install, _ = patch_client
    stub = _StubClient([{"id": 1, "stream_stats": {"x": 1}, "stream_stats_updated_at": "t"}])
    install(stub)

    assert refresh_stream_stats_bulk(db_conn, []) == 0
    assert stub.calls == []


def test_bulk_client_none_returns_zero(db_conn, patch_client):
    install, _ = patch_client
    install(None)
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100)
    db_conn.commit()

    assert refresh_stream_stats_bulk(db_conn, [100]) == 0


def test_bulk_writes_one_stream_onto_every_channel_holding_it(db_conn, patch_client):
    install, _ = patch_client
    install(_StubClient([
        {"id": 100, "stream_stats": {"alive": False}, "stream_stats_updated_at": "t"},
    ]))
    first = _insert_channel(db_conn)
    second = _insert_channel(db_conn)
    _insert_stream(db_conn, first, 100)
    _insert_stream(db_conn, second, 100)
    db_conn.commit()

    # Counted once — the return is distinct streams, matching the per-channel
    # contract — but both rows carry the verdict.
    assert refresh_stream_stats_bulk(db_conn, [100]) == 1
    rows = db_conn.execute(
        "SELECT stream_stats FROM managed_channel_streams WHERE dispatcharr_stream_id = 100"
    ).fetchall()
    assert len(rows) == 2
    assert all(json.loads(r["stream_stats"]) == {"alive": False} for r in rows)


def test_bulk_dedupes_and_sorts_requested_ids(db_conn, patch_client):
    install, _ = patch_client
    stub = _StubClient([])
    install(stub)

    refresh_stream_stats_bulk(db_conn, [101, 100, 101, 100])

    assert stub.calls == [[100, 101]]


def test_bulk_chunks_at_the_endpoint_page_size(db_conn, patch_client, monkeypatch):
    install, _ = patch_client
    stub = _StubClient([])
    install(stub)
    # The real cap is 1000; shrink it so the boundary is testable.
    monkeypatch.setattr(streams_mod, "STATS_BATCH_SIZE", 2)

    refresh_stream_stats_bulk(db_conn, [1, 2, 3, 4, 5])

    assert stub.calls == [[1, 2], [3, 4], [5]]


def test_bulk_leaves_unprobed_streams_alone(db_conn, patch_client):
    install, _ = patch_client
    install(_StubClient([
        {"id": 100, "stream_stats": None, "stream_stats_updated_at": None},
        {"id": 101, "stream_stats": {"alive": True}, "stream_stats_updated_at": "t"},
    ]))
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100)
    _insert_stream(db_conn, cid, 101)
    db_conn.commit()

    # Absent stats and stats reading zero are different claims; only one is true.
    assert refresh_stream_stats_bulk(db_conn, [100, 101]) == 1
    assert _stats_row(db_conn, 100)["stream_stats"] is None


def test_bulk_skips_removed_rows(db_conn, patch_client):
    install, _ = patch_client
    install(_StubClient([
        {"id": 100, "stream_stats": {"alive": True}, "stream_stats_updated_at": "t"},
    ]))
    cid = _insert_channel(db_conn)
    _insert_stream(db_conn, cid, 100, removed=True)
    db_conn.commit()

    assert refresh_stream_stats_bulk(db_conn, [100]) == 0
    assert _stats_row(db_conn, 100)["stream_stats"] is None


def test_per_channel_refresh_still_scopes_its_fetch_to_that_channel(db_conn, patch_client):
    install, _ = patch_client
    stub = _StubClient([])
    install(stub)
    mine = _insert_channel(db_conn)
    theirs = _insert_channel(db_conn)
    _insert_stream(db_conn, mine, 100)
    _insert_stream(db_conn, theirs, 200)
    db_conn.commit()

    refresh_stream_stats(db_conn, mine)

    assert stub.calls == [[100]]
