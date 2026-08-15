"""Explicit stale cache reads are reserved for provider recovery paths."""

from teamarr.utilities.cache import TTLCache


def test_expired_entry_is_not_a_normal_hit_but_is_available_for_recovery():
    cache = TTLCache()
    cache.set("schedule", {"events": ["old"]}, ttl_seconds=-1)

    assert cache.get("schedule") is None
    assert cache.get_stale("schedule") == {"events": ["old"]}
