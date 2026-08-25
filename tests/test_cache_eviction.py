"""TTLCache eviction behaviour and its cost profile.

The eviction path is on every insert of a new key, and a warm sports cache
holds tens of thousands of entries — so its asymptotics are a correctness-
adjacent property, not a micro-detail. These pin both the semantics (never
exceed max_size, evict least-recently-used, drop expired) and the fact that a
cache with room to spare does no scanning at all.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from unittest import mock

from teamarr.utilities.cache import (
    _EXPIRY_SWEEP_INTERVAL_RATIO,
    PersistentTTLCache,
    TTLCache,
)


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


def _expire(cache: TTLCache, *keys: str) -> None:
    """Backdate entries so they are expired without waiting."""
    past = datetime.now() - timedelta(seconds=1)
    for key in keys:
        cache._cache[key].expires_at = past


def _sweep_interval(max_size: int) -> int:
    return max(int(max_size * _EXPIRY_SWEEP_INTERVAL_RATIO), 1)


def test_the_expiry_sweep_reclaims_dead_entries_before_evicting_live_ones():
    """On a sweep tick, expired entries are what gets reclaimed.

    Note the qualifier: the sweep is *periodic*, not per-insert (see
    `_evict_if_needed` — finding expired entries is O(n) and this runs on every
    insert into a full cache). This pins the behaviour on the tick; the test
    below pins what happens between ticks. `max_size=10` puts the interval at
    1, so the very first at-capacity insert sweeps.
    """
    cache = TTLCache(default_ttl_seconds=3600, max_size=10)
    assert _sweep_interval(10) == 1, "this test relies on sweeping every insert"

    for i in range(8):
        cache.set(f"dead{i}", i, ttl_seconds=1)
    for i in range(2):
        cache.set(f"live{i}", i)
    _expire(cache, *[f"dead{i}" for i in range(8)])

    cache.set("new", "x")

    assert cache.get("new") == "x"
    assert cache.get("live0") == 0
    assert cache.get("live1") == 1
    assert all(cache.get(f"dead{i}") is None for i in range(8))


def test_between_sweeps_eviction_is_plain_lru():
    """Between sweep ticks, expired entries are NOT preferentially reclaimed.

    This is the honest statement of the trade: the sweep costs O(n), so at
    production size (50k entries, sweeping every 2500th at-capacity insert)
    most evictions are pure LRU and an expired-but-recently-used entry can
    outlive a live-but-old one. It costs nothing — both are re-fetchable, and
    `get()` drops expired entries lazily on read either way.
    """
    max_size = 200
    interval = _sweep_interval(max_size)
    assert interval > 1, "this test needs a cache big enough to defer sweeps"

    cache = TTLCache(default_ttl_seconds=3600, max_size=max_size)
    for i in range(max_size):
        cache.set(f"k{i}", i)

    # Expire a recently-used entry and touch it so it sits at the MRU end.
    _expire(cache, "k5")
    cache._cache.move_to_end("k5")

    # One at-capacity insert: below the sweep interval, so pure LRU.
    cache.set("new", "x")

    assert cache.get("k0") is None, "the LRU entry should have been evicted"
    # The expired entry survived eviction — it is simply still in the map.
    assert "k5" in cache._cache
    # ...and a read still refuses to serve it.
    assert cache.get("k5") is None


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


def test_background_maintenance_reaps_expired_entries():
    """Nothing else calls `cleanup_expired`, so the flush timer must.

    `_evict_if_needed` deliberately does nothing while the cache has room, so
    without this an under-capacity cache would hold expired entries until it
    filled. The old per-insert sweep reaped them incidentally — at the cost of
    making every insert O(n).
    """
    cache = PersistentTTLCache.__new__(PersistentTTLCache)
    cache._memory_cache = TTLCache(default_ttl_seconds=3600, max_size=1000)
    cache._default_ttl = timedelta(seconds=3600)
    cache._flush_interval = 3600
    cache._dirty_keys = set()
    cache._deleted_keys = set()
    cache._dirty_lock = threading.Lock()
    cache._keylocks = {}
    cache._keylocks_guard = threading.Lock()
    cache._flush_timer = None
    cache._shutdown = False

    for i in range(10):
        cache.set(f"dead{i}", i)
    cache.set("live", "x")
    _expire(cache._memory_cache, *[f"dead{i}" for i in range(10)])

    assert cache.size == 11, "precondition: nothing reaped them yet"

    with mock.patch.object(cache, "_schedule_flush"):
        cache._background_flush()

    assert cache.size == 1
    assert cache.get("live") == "x"


def test_background_maintenance_still_flushes_when_the_reap_fails():
    """Reap and flush are isolated so one cannot skip the other."""
    cache = PersistentTTLCache.__new__(PersistentTTLCache)
    cache._memory_cache = TTLCache(default_ttl_seconds=3600, max_size=1000)
    cache._flush_interval = 3600
    cache._dirty_lock = threading.Lock()
    cache._shutdown = False

    with (
        mock.patch.object(cache, "cleanup_expired", side_effect=RuntimeError("boom")),
        mock.patch.object(cache, "flush") as flush,
        mock.patch.object(cache, "_schedule_flush") as reschedule,
    ):
        cache._background_flush()

    assert flush.called, "a failing reap must not skip the flush"
    assert reschedule.called, "the timer chain must survive either failure"
