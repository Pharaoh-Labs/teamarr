"""Per-group matcher setup is built once per run, not once per group (#609).

A `TeamMatcher` is constructed per event group. On a real install that is 343
groups, and two of the things it built cost ~17ms (`CountryNameResolver`) and
~47ms (`TeamIdentityIndex`) each — roughly 22s of a 200s groups phase spent
rebuilding objects that do not vary by group.

Only *read-only* state is shared. The `TeamMatcher` itself is still per-group,
so its mutable memos (`_alias_resolve_cache`, `_candidates_memo`) keep their
per-group lifetime and none of the cross-group-leak hazards apply.
"""

from __future__ import annotations

import threading

import pytest

from teamarr.consumers.matching.country_resolver import (
    CountryNameResolver,
    get_country_resolver,
)
from teamarr.consumers.matching.team_matcher import (
    TeamMatcher,
    reset_identity_index_cache,
)


def _seed_teams(db_factory, rows):
    with db_factory() as conn:
        for name, short, abbrev, league, sport in rows:
            conn.execute(
                "INSERT INTO team_cache (team_name, team_short_name, team_abbrev, "
                "league, sport, provider, provider_team_id) "
                "VALUES (?,?,?,?,?,'espn',?)",
                (name, short, abbrev, league, sport, name),
            )


def _matcher(db_factory) -> TeamMatcher:
    from unittest.mock import MagicMock

    return TeamMatcher(service=MagicMock(), cache=MagicMock(), db_factory=db_factory)


# --- country resolver -------------------------------------------------------


def test_country_resolver_is_shared():
    assert get_country_resolver() is get_country_resolver()


def test_matchers_share_one_country_resolver(db_factory):
    a, b = _matcher(db_factory), _matcher(db_factory)
    assert a._country_resolver is b._country_resolver


def test_country_resolver_is_read_only_after_build():
    """Why sharing it is safe: nothing mutates it after construction."""
    resolver = get_country_resolver()
    before = dict(resolver._map)
    for name in ("brasil", "marruecos", "escocia", "not-a-country-at-all"):
        resolver.resolve(name)
    assert resolver._map == before, "resolve() mutated shared state"


def test_a_fresh_resolver_still_works_standalone():
    """The class must remain usable directly — tests and tools construct it."""
    assert CountryNameResolver().resolve("brasil") == get_country_resolver().resolve(
        "brasil"
    )


# --- identity index ---------------------------------------------------------


def test_identity_index_is_built_once_across_matchers(db_factory):
    _seed_teams(db_factory, [("Boston Celtics", "Celtics", "BOS", "nba", "basketball")])

    first = _matcher(db_factory)._get_identity_index()
    second = _matcher(db_factory)._get_identity_index()

    assert first is not None
    assert first is second, "the index was rebuilt for the second matcher"


def test_resetting_rebuilds_the_index(db_factory):
    """Staleness bound: a reseeded team_cache must become visible."""
    _seed_teams(db_factory, [("Boston Celtics", "Celtics", "BOS", "nba", "basketball")])
    first = _matcher(db_factory)._get_identity_index()
    assert first is not None

    _seed_teams(db_factory, [("Miami Heat", "Heat", "MIA", "nba", "basketball")])
    assert _matcher(db_factory)._get_identity_index() is first, "TTL not respected"

    reset_identity_index_cache()
    rebuilt = _matcher(db_factory)._get_identity_index()
    assert rebuilt is not None and rebuilt is not first
    assert len(rebuilt) > len(first), "the reseeded team is missing"


def _empty_team_cache(db_factory):
    """The schema seeds 22 rows, so an unseeded install has to be made."""
    with db_factory() as conn:
        conn.execute("DELETE FROM team_cache")


def test_an_empty_team_cache_yields_no_index(db_factory):
    """A fresh install matches before its first cache refresh. An empty index
    must not be shared and must not veto everything (epic goax)."""
    _empty_team_cache(db_factory)
    assert _matcher(db_factory)._get_identity_index() is None


def test_an_empty_result_is_not_cached_as_an_answer(db_factory):
    """...and once team_cache is seeded, the next lookup must see it.

    This is the reason the empty case returns early instead of caching None:
    a run that starts before the first cache refresh must not be stuck with
    'no index' for the whole TTL window.
    """
    _empty_team_cache(db_factory)
    assert _matcher(db_factory)._get_identity_index() is None

    _seed_teams(db_factory, [("Boston Celtics", "Celtics", "BOS", "nba", "basketball")])
    assert _matcher(db_factory)._get_identity_index() is not None


def test_index_build_is_single_flighted(db_factory):
    """Concurrent first-use must not build it once per thread."""
    _seed_teams(db_factory, [("Boston Celtics", "Celtics", "BOS", "nba", "basketball")])
    results = []
    barrier = threading.Barrier(4)

    def build():
        barrier.wait()
        results.append(_matcher(db_factory)._get_identity_index())

    threads = [threading.Thread(target=build) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({id(r) for r in results}) == 1, "the index was built more than once"


# --- the mutable state that is deliberately NOT shared ----------------------


def test_matchers_do_not_share_mutable_memos(db_factory):
    """The hazards in #609 are avoided by keeping TeamMatcher per-group."""
    a, b = _matcher(db_factory), _matcher(db_factory)
    assert a._alias_resolve_cache is not b._alias_resolve_cache
    assert a._candidates_memo is not b._candidates_memo


def test_the_resolve_memo_is_bounded(db_factory):
    """The index outlives a single group now, so its memo needs a cap."""
    from teamarr.consumers.matching.identity import _RESOLVE_CACHE_MAX, TeamIdentityIndex

    index = TeamIdentityIndex([("Boston Celtics", "Celtics", "BOS", "nba", "basketball")])
    for i in range(_RESOLVE_CACHE_MAX + 50):
        index.resolve(f"team number {i}")

    assert len(index._cache) <= _RESOLVE_CACHE_MAX
    # ...and it still answers correctly after a clear.
    assert index.resolve("Boston Celtics").identities


@pytest.mark.parametrize("name", ["Boston Celtics", "Celtics", "BOS"])
def test_resolution_is_unaffected_by_sharing(db_factory, name):
    _seed_teams(db_factory, [("Boston Celtics", "Celtics", "BOS", "nba", "basketball")])
    shared = _matcher(db_factory)._get_identity_index()
    assert shared is not None

    from teamarr.consumers.matching.identity import TeamIdentityIndex

    standalone = TeamIdentityIndex(
        [("Boston Celtics", "Celtics", "BOS", "nba", "basketball")]
    )
    assert {i.name for i in shared.resolve(name).identities} == {
        i.name for i in standalone.resolve(name).identities
    }
