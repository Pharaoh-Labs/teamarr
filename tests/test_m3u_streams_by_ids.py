"""``M3UManager.get_streams_by_ids`` (#647): chunked ``?ids=`` lookups.

The channel-source builder needs details for a few hundred specific streams;
walking the whole catalog (119 pages on a real install) for that was the
single most expensive fetch of a generation.
"""

from types import SimpleNamespace

from teamarr.dispatcharr.managers.m3u import M3UManager


class _Client:
    def __init__(self, fail_urls=()):
        self.urls: list[str] = []
        self.fail_urls = set(fail_urls)

    def get(self, url):
        self.urls.append(url)
        if url in self.fail_urls:
            return SimpleNamespace(status_code=500, json=lambda: None)
        ids = [int(i) for i in url.split("ids=")[1].split(",")]
        return SimpleNamespace(
            status_code=200,
            json=lambda: [{"id": i, "name": f"s{i}", "url": "u", "is_stale": False} for i in ids],
        )


def test_chunks_dedupes_and_parses():
    client = _Client()
    streams = M3UManager(client).get_streams_by_ids([5, 3, 3, 1, 4, 2], chunk_size=2)
    assert [s.id for s in streams] == [1, 2, 3, 4, 5]
    assert streams[0].name == "s1"
    assert len(client.urls) == 3
    assert client.urls[0] == "/api/channels/streams/?ids=1,2"


def test_empty_input_makes_no_request():
    client = _Client()
    assert M3UManager(client).get_streams_by_ids([]) == []
    assert client.urls == []


def test_failed_chunk_is_skipped_not_fatal():
    client = _Client(fail_urls={"/api/channels/streams/?ids=1,2"})
    streams = M3UManager(client).get_streams_by_ids([1, 2, 3], chunk_size=2)
    assert [s.id for s in streams] == [3]


def test_known_stream_ids_answers_the_catalog_membership():
    client = _Client()
    known = M3UManager(client).known_stream_ids([3, 1, 2], chunk_size=2)
    assert known == {1, 2, 3}


def test_known_stream_ids_is_none_when_any_chunk_fails():
    """A partial answer is not evidence of absence (#1097)."""
    client = _Client(fail_urls={"/api/channels/streams/?ids=1,2"})
    assert M3UManager(client).known_stream_ids([1, 2, 3], chunk_size=2) is None


def test_known_stream_ids_empty_input_makes_no_request():
    client = _Client()
    assert M3UManager(client).known_stream_ids([]) == set()
    assert client.urls == []
