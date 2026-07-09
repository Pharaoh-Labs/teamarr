"""Per-stream M3U account name resolution (#297, follow-up to #264).

Streams from Dispatcharr carry only ``m3u_account_id``; the display name must
be resolved per stream. Before #297 every stream in a group was labeled with
the group's single configured account name, so identically named streams from
multiple logins rendered as duplicate rows in Managed Channels and mis-fed
m3u-type stream-ordering rules.
"""

import sqlite3
from types import SimpleNamespace

import pytest

from teamarr.database.channels.streams import update_stream_account_name
from tests.fakes import make_bare_processor

# ======================================================== update_stream_account_name


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE managed_channel_streams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            managed_channel_id INTEGER,
            dispatcharr_stream_id INTEGER,
            m3u_account_id INTEGER,
            m3u_account_name TEXT,
            removed_at TEXT
        )"""
    )
    return c


def _add(conn, stream_id, account_id=None, account_name=None, removed_at=None):
    conn.execute(
        "INSERT INTO managed_channel_streams "
        "(managed_channel_id, dispatcharr_stream_id, m3u_account_id, m3u_account_name, removed_at) "
        "VALUES (1, ?, ?, ?, ?)",
        (stream_id, account_id, account_name, removed_at),
    )
    conn.commit()


def _row(conn, stream_id):
    return conn.execute(
        "SELECT m3u_account_id, m3u_account_name FROM managed_channel_streams "
        "WHERE dispatcharr_stream_id = ? AND removed_at IS NULL",
        (stream_id,),
    ).fetchone()


def test_heals_group_fallback_label(conn):
    # Row attached pre-#297: labeled with the group's account, not its own.
    _add(conn, 200, account_id=2, account_name="Provider Login 1")
    changed = update_stream_account_name(conn, 1, 200, "Provider Login 2", 2)
    assert changed is True
    row = _row(conn, 200)
    assert row["m3u_account_name"] == "Provider Login 2"
    assert row["m3u_account_id"] == 2


def test_noop_when_already_correct(conn):
    _add(conn, 200, account_id=2, account_name="Provider Login 2")
    assert update_stream_account_name(conn, 1, 200, "Provider Login 2", 2) is False


def test_updates_account_id_when_provided(conn):
    _add(conn, 200, account_id=1, account_name="Provider Login 2")
    changed = update_stream_account_name(conn, 1, 200, "Provider Login 2", 2)
    assert changed is True
    assert _row(conn, 200)["m3u_account_id"] == 2


def test_keeps_stored_id_when_none_given(conn):
    _add(conn, 200, account_id=2, account_name="Wrong Name")
    changed = update_stream_account_name(conn, 1, 200, "Right Name", None)
    assert changed is True
    row = _row(conn, 200)
    assert row["m3u_account_name"] == "Right Name"
    assert row["m3u_account_id"] == 2  # COALESCE keeps the stored id


def test_heals_from_null_name(conn):
    _add(conn, 200, account_id=2, account_name=None)
    changed = update_stream_account_name(conn, 1, 200, "Provider Login 2", 2)
    assert changed is True
    assert _row(conn, 200)["m3u_account_name"] == "Provider Login 2"


def test_ignores_removed_stream(conn):
    _add(conn, 200, account_id=2, account_name="Wrong", removed_at="2026-06-01 17:30:00")
    assert update_stream_account_name(conn, 1, 200, "Right", 2) is False


# ======================================================== fetcher stamps account names


def _fake_stream(sid, name, account_id):
    return SimpleNamespace(
        id=sid,
        name=name,
        tvg_id=None,
        tvg_name=None,
        channel_group="G",
        channel_group_id=7,
        m3u_account_id=account_id,
        is_stale=False,
    )


def _make_fetch_processor(streams, accounts, calls=None):
    def list_accounts(include_custom=False):
        if calls is not None:
            calls.append(include_custom)
        return accounts

    m3u = SimpleNamespace(
        list_streams=lambda group_id=None: streams,
        list_accounts=list_accounts,
    )
    return make_bare_processor(_dispatcharr_client=SimpleNamespace(m3u=m3u))


def test_fetch_streams_stamps_per_stream_account_name():
    # Two logins of the same provider: identical names, distinct accounts.
    streams = [
        _fake_stream(101, "MLB: Yankees vs Red Sox", 1),
        _fake_stream(202, "MLB: Yankees vs Red Sox", 2),
    ]
    accounts = [SimpleNamespace(id=1, name="Login 1"), SimpleNamespace(id=2, name="Login 2")]
    proc = _make_fetch_processor(streams, accounts)

    group = SimpleNamespace(is_channel_source=False, m3u_group_id=7)
    dicts = proc._fetch_streams(group)

    by_id = {d["id"]: d for d in dicts}
    assert by_id[101]["m3u_account_name"] == "Login 1"
    assert by_id[202]["m3u_account_name"] == "Login 2"


def test_fetch_streams_unknown_account_yields_none():
    streams = [_fake_stream(101, "S", 99)]  # id not in accounts list
    accounts = [SimpleNamespace(id=1, name="Login 1")]
    proc = _make_fetch_processor(streams, accounts)

    dicts = proc._fetch_streams(SimpleNamespace(is_channel_source=False, m3u_group_id=7))
    assert dicts[0]["m3u_account_name"] is None


def test_account_lookup_cached_per_processor():
    calls: list = []
    streams = [_fake_stream(101, "S", 1)]
    accounts = [SimpleNamespace(id=1, name="Login 1")]
    proc = _make_fetch_processor(streams, accounts, calls)

    group = SimpleNamespace(is_channel_source=False, m3u_group_id=7)
    proc._fetch_streams(group)
    proc._fetch_streams(group)
    assert len(calls) == 1  # one list_accounts call across both fetches
    # Custom accounts must be included — streams can belong to the custom account.
    assert calls == [True]


def test_account_lookup_failure_does_not_break_fetch():
    streams = [_fake_stream(101, "S", 1)]

    def boom(include_custom=False):
        raise RuntimeError("dispatcharr down")

    m3u = SimpleNamespace(list_streams=lambda group_id=None: streams, list_accounts=boom)
    proc = make_bare_processor(_dispatcharr_client=SimpleNamespace(m3u=m3u))

    dicts = proc._fetch_streams(SimpleNamespace(is_channel_source=False, m3u_group_id=7))
    assert len(dicts) == 1
    assert dicts[0]["m3u_account_name"] is None
