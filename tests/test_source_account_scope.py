"""Account-bound M3U sources must not consume another account's streams (#1226)."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from teamarr.consumers.event_group_processor.stream_fetcher import StreamFetcher
from teamarr.database.groups import EventEPGGroup
from teamarr.dispatcharr.managers.m3u import M3UManager
from teamarr.dispatcharr.types import DispatcharrChannelGroup


class _StreamAPI:
    """Dispatcharr stream-list contract, with group/account filters and pagination."""

    def __init__(self, rows):
        self.rows = rows
        self.requests = []

    def get(self, url):
        query = parse_qs(urlsplit(url).query)
        self.requests.append(query)
        rows = self.rows
        if "channel_group_name" in query:
            rows = [r for r in rows if r["group_name"] == query["channel_group_name"][0]]
        if "m3u_account" in query:
            rows = [r for r in rows if r["m3u_account"] == int(query["m3u_account"][0])]
        page = int(query["page"][0])
        page_size = int(query["page_size"][0])
        start = (page - 1) * page_size
        next_url = None
        if start + page_size < len(rows):
            next_url = "/api/channels/streams/?" + urlencode(
                {**query, "page": [str(page + 1)]}, doseq=True
            )
        return httpx.Response(
            200,
            json={"count": len(rows), "next": next_url, "results": rows[start : start + page_size]},
        )


def _row(stream_id, account_id, group_id=303, group_name="Shared group"):
    return {
        "id": stream_id,
        # Distinct accounts can carry identically named streams (#264).
        "name": "Synthetic event stream",
        "m3u_account": account_id,
        "channel_group": group_id,
        "group_name": group_name,
    }


def _fetcher(rows):
    api = _StreamAPI(rows)
    manager = M3UManager(api)
    manager._groups_cache = [DispatcharrChannelGroup(id=303, name="Shared group")]
    fetcher = StreamFetcher.__new__(StreamFetcher)
    fetcher._dispatcharr_client = SimpleNamespace(m3u=manager)
    # 999 is a live account with no streams in the group; an id Dispatcharr no
    # longer lists is a different case (#628) and falls back to the whole group.
    fetcher._account_name_cache = {101: "Account A", 202: "Account B", 999: "Account C"}
    fetcher._group_name_cache = {303: "Shared group"}
    return fetcher, api


@pytest.mark.parametrize(
    ("account_id", "expected_ids"),
    [(101, [1001]), (202, [1002]), (999, []), (None, [1001, 1002])],
)
def test_source_reads_its_group_and_bound_account(account_id, expected_ids):
    fetcher, api = _fetcher([_row(1002, 202), _row(1001, 101), _row(1003, 101, 404, "Other group")])
    group = EventEPGGroup(id=1, name="Source", m3u_group_id=303, m3u_account_id=account_id)

    streams = fetcher._fetch_streams(group)

    assert [s["id"] for s in streams] == expected_ids
    if account_id is not None:
        assert all(s["m3u_account_id"] == account_id for s in streams)
        # Also catches an unfiltered retry when the bound account is empty.
        assert all(q.get("m3u_account") == [str(account_id)] for q in api.requests)
    else:
        assert all("m3u_account" not in q for q in api.requests)


def test_account_filter_survives_paginated_fetches():
    fetcher, api = _fetcher([_row(i, 101) for i in range(1001)] + [_row(9999, 202)])
    group = EventEPGGroup(id=1, name="Source", m3u_group_id=303, m3u_account_id=101)

    streams = fetcher._fetch_streams(group)

    assert [s["id"] for s in streams] == list(range(1001))
    assert {q["page"][0] for q in api.requests} == {"1", "2"}
    assert all(q.get("m3u_account") == ["101"] for q in api.requests)


def test_missing_group_never_reads_the_catalog():
    fetcher, api = _fetcher([_row(1001, 101)])
    group = EventEPGGroup(id=1, name="Source", m3u_account_id=101)

    assert fetcher._fetch_streams(group) == []
    assert api.requests == []


def test_channel_source_keeps_its_curated_pool():
    fetcher, api = _fetcher([_row(1001, 101)])
    group = EventEPGGroup(id=1, name="Channel source", is_channel_source=True)
    curated = [{"id": 1002, "m3u_account_id": 202}]
    fetcher._fetch_channel_source_streams = MagicMock(return_value=curated)

    assert fetcher._fetch_streams(group) == curated
    fetcher._fetch_channel_source_streams.assert_called_once_with(group)
    assert api.requests == []
