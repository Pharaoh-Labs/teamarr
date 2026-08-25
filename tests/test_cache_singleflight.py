"""Single-flight dedup: concurrent identical fetches collapse to one request.

Parallel stream matching fans out across threads that frequently want the same
``(league, date)`` scoreboard. Without single-flight, every thread that races
past the cache miss issues its own upstream fetch. SportsDataService.get_events
now serializes the miss path per cache key so only the first thread fetches.
"""

import threading
import time
from datetime import date, timedelta

from teamarr.services import sports_data
from teamarr.services.sports_data import SportsDataService
from teamarr.utilities.cache import PersistentTTLCache


class _SlowProvider:
    """Provider whose fetch is slow enough that concurrent callers pile up."""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    @property
    def name(self):
        return "espn"

    def supports_league(self, league):
        return True

    def get_events(self, league, target_date):
        with self._lock:
            self.calls += 1
        time.sleep(0.1)  # simulate a network round-trip
        return []  # empty slate is enough; we count fetches, not contents


def _service(monkeypatch):
    # Hermetic cache: stub SQLite load/flush so the shared cache starts empty
    # and never touches the real service_cache DB.
    monkeypatch.setattr(PersistentTTLCache, "_load_from_sqlite", lambda self: None)
    monkeypatch.setattr(PersistentTTLCache, "flush", lambda self: 0)
    monkeypatch.setattr(sports_data, "_shared_cache", None)
    provider = _SlowProvider()
    return provider, SportsDataService(providers=[provider])


def _hammer(service, league, target, n):
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()  # release all threads at once to maximize the race
        service.get_events(league, target)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_concurrent_same_key_fetches_once(monkeypatch):
    provider, service = _service(monkeypatch)
    target = date.today() + timedelta(days=3)

    _hammer(service, "nba", target, n=20)

    # 20 threads, one cache key -> one upstream fetch per provider-day bucket
    # (D-1, D, D+1 since #601), and crucially NOT one per thread.
    assert provider.calls == 3


def test_distinct_keys_not_serialized_away(monkeypatch):
    """Guard: single-flight must not drop fetches for different keys."""
    provider, service = _service(monkeypatch)
    d1 = date.today() + timedelta(days=3)
    d2 = date.today() + timedelta(days=4)

    _hammer(service, "nba", d1, n=10)
    _hammer(service, "nba", d2, n=10)

    # {d1-1, d1, d1+1} then only d2+1 is new — consecutive days share buckets.
    assert provider.calls == 4


def test_shared_buckets_are_singleflighted_across_target_dates(monkeypatch):
    """Adjacent target dates overlap on buckets; the overlap must fetch once.

    The outer lock is per user-day, so two threads on *different* target dates
    hold different locks while sharing two of their three provider-day buckets
    (#601). Only the raw layer's own lock keeps that from double-fetching.
    """
    provider, service = _service(monkeypatch)
    d1 = date.today() + timedelta(days=3)
    d2 = d1 + timedelta(days=1)

    barrier = threading.Barrier(2)

    def worker(target):
        def run():
            barrier.wait()
            service.get_events("nba", target)

        return run

    threads = [threading.Thread(target=worker(d)) for d in (d1, d2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Union of {d1-1, d1, d1+1} and {d2-1, d2, d2+1} is 4 distinct buckets.
    # Without the raw lock the two shared buckets fetch twice -> 6.
    assert provider.calls == 4
