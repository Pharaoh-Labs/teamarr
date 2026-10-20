"""Regression tests for stale channel-group handling (bead teamarr-nr7).

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


# --- a value with no wildcard is a literal group name (#1095) ----------------


def _naming_resolver():
    r = _resolver({10}, loaded=True)
    created = []

    def get_or_create(name):
        created.append(name)
        return 77

    r._get_or_create_group = get_or_create
    return r, created


def test_a_plain_name_is_that_group():
    # "Favourite Teams" in a pinned block's group box used to be an unknown
    # mode: saved, then dropped at generation time for the static group.
    r, created = _naming_resolver()
    assert r.resolve_channel_group("Favourite Teams", None, "football", "nfl") == 77
    assert created == ["Favourite Teams"]


def test_a_plain_name_outranks_the_static_fallback():
    r, created = _naming_resolver()
    assert r.resolve_channel_group(" Favourite Teams ", 10, "football", "nfl") == 77
    assert created == ["Favourite Teams"]


def test_an_empty_mode_still_falls_back_to_the_static_group():
    r, created = _naming_resolver()
    assert r.resolve_channel_group("", 10, "football", "nfl") == 10
    assert created == []
