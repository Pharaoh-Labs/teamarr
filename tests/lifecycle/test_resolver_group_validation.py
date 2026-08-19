"""Regression tests for stale channel-group handling (bead teamarrv2-nr7).

A configured static/per-league channel group that was deleted in Dispatcharr
must not fail every channel creation ("Invalid pk … object does not exist" → 0
channels). The resolver drops a stale group id to ungrouped (None) so channels
are still created, but only when it actually knows the current groups.
"""

from teamarr.consumers.lifecycle.dynamic_resolver import DynamicResolver


def _resolver(known_ids: set[int], loaded: bool) -> DynamicResolver:
    r = DynamicResolver()
    r._initialized = True  # skip Dispatcharr/DB load
    r._groups_loaded = loaded
    r._known_group_ids = set(known_ids)
    return r


def test_static_valid_group_passes_through():
    r = _resolver({10, 20}, loaded=True)
    assert r.resolve_channel_group("static", 10, None, None) == 10


def test_static_stale_group_falls_back_to_ungrouped():
    # 35292 was deleted in Dispatcharr → drop to None so creation still works.
    r = _resolver({10, 20}, loaded=True)
    assert r.resolve_channel_group("static", 35292, None, None) is None


def test_unknown_group_kept_when_fetch_failed():
    # If the group fetch failed (groups_loaded False), don't assume deletion —
    # keep the configured id rather than dropping grouping on a transient error.
    r = _resolver(set(), loaded=False)
    assert r.resolve_channel_group("static", 35292, None, None) == 35292


def test_none_static_group_stays_none():
    r = _resolver({10}, loaded=True)
    assert r.resolve_channel_group("static", None, None, None) is None
