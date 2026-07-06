"""Tests for M3UManager.get_streams_by_ids and the no-group stream-fetch guard.

get_streams_by_ids fetches stream details via POST /api/channels/streams/by-ids/
in chunks of 1000 so the caller never pulls Dispatcharr's entire stream catalog.
EventGroupProcessor._fetch_streams must refuse (not list everything) when a
group has no m3u_group_id — the unbounded fallback could tip over Dispatcharr's
workers on large instances (35k+ streams).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.event_group_processor import EventGroupProcessor
from teamarr.dispatcharr.managers.m3u import M3UManager


@pytest.fixture
def manager():
    return M3UManager(MagicMock())


def _resp(status_code, payload=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload
    return r


def test_empty_ids_makes_no_requests(manager):
    assert manager.get_streams_by_ids([]) == []
    manager._client.post.assert_not_called()


def test_single_chunk_maps_streams(manager):
    payload = {
        "results": [
            {"id": 1, "name": "ESPN HD", "channel_group_id": 42, "m3u_account": 7},
            {"id": 2, "name": "FS1", "is_stale": True},
        ]
    }
    manager._client.post = MagicMock(return_value=_resp(200, payload))

    streams = manager.get_streams_by_ids([1, 2])

    assert [s.id for s in streams] == [1, 2]
    assert streams[0].channel_group_id == 42
    assert streams[0].m3u_account_id == 7
    assert streams[1].is_stale is True
    endpoint, body = manager._client.post.call_args[0]
    assert "streams/by-ids/" in endpoint
    assert body == {"ids": [1, 2]}


def test_ids_are_chunked_at_1000(manager):
    ids = list(range(2500))
    manager._client.post = MagicMock(return_value=_resp(200, {"results": []}))

    manager.get_streams_by_ids(ids)

    assert manager._client.post.call_count == 3
    chunks = [call.args[1]["ids"] for call in manager._client.post.call_args_list]
    assert [len(c) for c in chunks] == [1000, 1000, 500]
    assert [i for chunk in chunks for i in chunk] == ids


def test_api_failure_returns_empty(manager):
    manager._client.post = MagicMock(return_value=_resp(500))
    assert manager.get_streams_by_ids([1]) == []

    manager._client.post = MagicMock(return_value=None)
    assert manager.get_streams_by_ids([1]) == []


def test_double_encoded_names_are_fixed(manager):
    payload = {"results": [{"id": 1, "name": "EspaÃ±a TV"}]}
    manager._client.post = MagicMock(return_value=_resp(200, payload))

    streams = manager.get_streams_by_ids([1])

    assert streams[0].name == "España TV"


def test_fetch_streams_without_group_skips_instead_of_listing_all():
    proc = object.__new__(EventGroupProcessor)
    m3u = MagicMock()
    proc._dispatcharr_client = SimpleNamespace(m3u=m3u)

    group = SimpleNamespace(name="No Group", m3u_group_id=None, is_channel_source=False)

    assert proc._fetch_streams(group) == []
    m3u.list_streams.assert_not_called()
