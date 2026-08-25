"""TTLCache eviction behaviour and its cost profile.

The eviction path is on every insert of a new key, and a warm sports cache
holds tens of thousands of entries — so its asymptotics are a correctness-
adjacent property, not a micro-detail. These pin both the semantics (never
exceed max_size, evict least-recently-used, drop expired) and the fact that a
cache with room to spare does no scanning at all.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from teamarr.utilities.cache import TTLCache


def test_never_exceeds_max_size():
    cache = TTLCache(default_ttl_seconds=3600, max_size=100)
    for i in range(500):
        cache.set(f"k{i}", i)
        assert cache.size <= 100


def test_evicts_least_recently_used_first():
    cache = TTLCache(default_ttl_seconds=3600, max_size=10)
    for i in range(10):
        cache.set(f"k{i}", i)

    # Touch the first half so the second half becomes the LRU tail.
    for i in range(5):
        cache.get(f"k{i}")

    for i in range(10, 15):
        cache.set(f"k{i}", i)

    assert [cache.get(f"k{i}") for i in range(5)] == [0, 1, 2, 3, 4]
    assert all(cache.get(f"k{i}") == i for i in range(10, 15))


def test_expired_entries_are_reclaimed_before_live_ones():
    cache = TTLCache(default_ttl_seconds=3600, max_size=10)
    for i in range(8):
        cache.set(f"dead{i}", i, ttl_seconds=1)
    for i in range(2):
        cache.set(f"live{i}", i)

    # Expire the short-TTL half without waiting.
    past = datetime.now() - timedelta(seconds=1)
    for i in range(8):
        cache._cache[f"dead{i}"].expires_at = past

    cache.set("new", "x")

    assert cache.get("new") == "x"
    assert cache.get("live0") == 0
    assert cache.get("live1") == 1
    assert all(cache.get(f"dead{i}") is None for i in range(8))


def test_insert_into_a_roomy_cache_does_not_scan():
    """A cache under its limit must not pay for the eviction sweep.

    Regression guard: the sweep used to run unconditionally, making every
    new-key insert O(n) — roughly 1ms per `set` at 45k entries, paid thousands
    of times per generation run for a cache nowhere near full. Timed rather
    than mocked because the defect was purely asymptotic.
    """
    cache = TTLCache(default_ttl_seconds=3600, max_size=200_000)

    def fill(start: int, count: int) -> float:
        t0 = time.perf_counter()
        for i in range(start, start + count):
            cache.set(f"k{i}", i)
        return time.perf_counter() - t0

    fill(0, 2_000)
    small = fill(2_000, 2_000)
    fill(4_000, 40_000)
    large = fill(44_000, 2_000)

    # With a per-insert scan this ratio tracks cache size (>10x here). Allow
    # generous headroom for a noisy CI box; the defect was orders of magnitude.
    assert large < small * 5, (
        f"insert cost grew with cache size: {small:.4f}s at 2k vs {large:.4f}s at 44k"
    )
