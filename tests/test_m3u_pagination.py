"""Paginated stream fetching: parallel pages, all-or-nothing failure (#610).

The full stream list is 34 pages at this scale, and walking them one `next`
link at a time was the largest single item left in the groups phase. Pages 2..N
are independently addressable once page 1 reports `count`, so they go out at
once.

The load-bearing property is not the speed — it is that a partial list is never
returned. A caller cannot tell 33-of-34-pages apart from a genuinely smaller
group: it would silently lose matches and could delete channels for the streams
that went missing. `[]` is safe because callers already guard the empty case;
"most of the streams" is not.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from teamarr.dispatcharr.managers.m3u import M3UManager


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeClient:
    """Serves `total` streams as pages of `page_size`, with injectable failures."""

    def __init__(self, total: int, page_size: int = 1000, fail_pages=(), status=500):
        self.total = total
        self.page_size = page_size
        self.fail_pages = set(fail_pages)
        self.status = status
        self.requested: list[int] = []
        self.threads: set[str] = set()
        self._lock = threading.Lock()

    def get(self, url: str):
        page = int(url.split("page=")[1].split("&")[0])
        with self._lock:
            self.requested.append(page)
            self.threads.add(threading.current_thread().name)
        if page in self.fail_pages:
            return _FakeResponse(None, status_code=self.status)
        start = (page - 1) * self.page_size
        results = [
            {"id": i, "name": f"s{i}"}
            for i in range(start, min(start + self.page_size, self.total))
        ]
        has_next = start + self.page_size < self.total
        return _FakeResponse(
            {
                "count": self.total,
                "next": f"/api/channels/streams/?page={page + 1}" if has_next else None,
                "results": results,
            }
        )


def _manager(client) -> M3UManager:
    mgr = M3UManager.__new__(M3UManager)
    mgr._client = client
    mgr._group_cache = MagicMock()
    return mgr


def test_returns_every_stream_across_many_pages():
    client = _FakeClient(total=33143)
    streams = _manager(client).list_streams()

    assert len(streams) == 33143
    assert {s.id for s in streams} == set(range(33143))
    assert sorted(client.requested) == list(range(1, 35)), "expected 34 pages"


def test_pages_are_fetched_concurrently():
    client = _FakeClient(total=33143)
    _manager(client).list_streams()

    # Page 1 is serial (it reports `count`); the rest fan out.
    assert len(client.threads) > 1, "pages were fetched one at a time"


@pytest.mark.parametrize("bad_page", [2, 17, 34])
def test_one_failed_page_returns_nothing(bad_page):
    """The invariant. A partial list must never reach the caller."""
    client = _FakeClient(total=33143, fail_pages=[bad_page])
    streams = _manager(client).list_streams()

    assert streams == [], (
        f"page {bad_page} failed but {len(streams)} streams were returned — a "
        "partial list silently loses matches and can delete channels (#610)"
    )


def test_a_failed_first_page_returns_nothing():
    client = _FakeClient(total=33143, fail_pages=[1])
    assert _manager(client).list_streams() == []


def test_a_single_page_result_still_works():
    client = _FakeClient(total=42)
    streams = _manager(client).list_streams()
    assert len(streams) == 42
    assert client.requested == [1], "a single-page result must not fan out"


def test_limit_still_stops_early():
    """One API route passes limit= precisely to avoid fetching everything."""
    client = _FakeClient(total=33143, page_size=500)
    streams = _manager(client).list_streams(limit=500)

    assert len(streams) == 500
    assert len(client.requested) == 1, (
        f"limit=500 fetched {len(client.requested)} pages — early stop was lost"
    )


def test_growth_between_pages_is_picked_up():
    """If the set grows while we page through it, the tail is still followed."""

    class _Growing(_FakeClient):
        def get(self, url):
            page = int(url.split("page=")[1].split("&")[0])
            if page == 2:  # last page by the original count
                self.total += self.page_size
            return super().get(url)

    client = _Growing(total=2000, page_size=1000)
    streams = _manager(client).list_streams()
    assert len(streams) == 3000, "the page that appeared mid-fetch was dropped"
