"""Tests for DispatcharrClient.get_stream_stats_by_ids.

Fetches stream_stats for a batch of streams via POST
/api/channels/streams/by-ids/, returning only id / stream_stats /
stream_stats_updated_at. Non-existent ids are silently omitted by Dispatcharr.
"""

from unittest.mock import MagicMock

import pytest

from teamarr.dispatcharr.client import DispatcharrClient


@pytest.fixture
def client():
    # __init__ does not authenticate, so a bare client is safe to construct.
    return DispatcharrClient("http://dispatcharr.local", "user", "pass")


def _resp(status_code, payload=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload
    return r


def test_empty_ids_short_circuits(client):
    client.post = MagicMock()
    assert client.get_stream_stats_by_ids([]) == []
    client.post.assert_not_called()


def test_none_response_returns_empty(client):
    client.post = MagicMock(return_value=None)
    assert client.get_stream_stats_by_ids([1, 2]) == []


def test_non_200_returns_empty(client):
    client.post = MagicMock(return_value=_resp(500))
    assert client.get_stream_stats_by_ids([1]) == []


def test_results_wrapper_is_mapped(client):
    payload = {
        "results": [
            {
                "id": 1,
                "stream_stats": {"resolution": "1920x1080"},
                "stream_stats_updated_at": "t1",
                "extra": "drop",
            },
            {"id": 2, "stream_stats": None, "stream_stats_updated_at": None},
        ]
    }
    client.post = MagicMock(return_value=_resp(200, payload))

    result = client.get_stream_stats_by_ids([1, 2])

    assert result == [
        {"id": 1, "stream_stats": {"resolution": "1920x1080"}, "stream_stats_updated_at": "t1"},
        {"id": 2, "stream_stats": None, "stream_stats_updated_at": None},
    ]
    # endpoint + body sanity
    endpoint, body = client.post.call_args[0]
    assert "streams/by-ids/" in endpoint
    assert body == {"ids": [1, 2]}


def test_bare_list_payload_is_handled(client):
    payload = [{"id": 5, "stream_stats": {"source_fps": 60}, "stream_stats_updated_at": "t"}]
    client.post = MagicMock(return_value=_resp(200, payload))

    result = client.get_stream_stats_by_ids([5])
    assert result == [{"id": 5, "stream_stats": {"source_fps": 60}, "stream_stats_updated_at": "t"}]


def test_entries_without_id_are_skipped(client):
    payload = {
        "results": [
            {"stream_stats": {"x": 1}},
            {"id": 9, "stream_stats": {"y": 2}, "stream_stats_updated_at": "t"},
        ]
    }
    client.post = MagicMock(return_value=_resp(200, payload))

    result = client.get_stream_stats_by_ids([9])
    assert [r["id"] for r in result] == [9]
