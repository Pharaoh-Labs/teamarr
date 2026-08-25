"""A team_cache write must invalidate the shared identity index (#609).

The index is memoized per process behind a TTL so a run does not rebuild it per
event group. That TTL alone is not enough, because this index **vetoes**: a
stale league membership makes the fixture gate return
`FIXTURE_NOT_IN_LEAGUE`, which is a silently missing match — the failure class
epic goax exists to keep at zero.

Before the index was shared, every group rebuilt it live, so a cache refresh was
always visible to the very next generation. These pin that the refresh-then-
generate sequence still behaves that way.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teamarr.consumers.cache.refresh import CacheRefresher
from teamarr.consumers.matching.team_matcher import TeamMatcher
from teamarr.database.leagues import purge_league_cache_rows
from teamarr.database.team_cache import invalidate_team_identity_caches


def _index(db_factory):
    return TeamMatcher(
        service=MagicMock(), cache=MagicMock(), db_factory=db_factory
    )._get_identity_index()


def _team(name, league="nba", sport="basketball"):
    return {
        "team_name": name,
        "team_abbrev": name[:3].upper(),
        "team_short_name": name.split()[-1],
        "provider": "espn",
        "provider_team_id": name.lower().replace(" ", "-"),
        "league": league,
        "sport": sport,
        "logo_url": None,
    }


def test_a_per_league_refresh_invalidates_the_index(db_factory):
    """`_save_league_teams` — the per-league path."""
    before = _index(db_factory)
    assert before is not None

    CacheRefresher(db_factory=db_factory)._save_league_teams(
        "nba",
        "espn",
        "basketball",
        display_name="NBA",
        logo_url=None,
        teams=[_team("Boston Celtics"), _team("Miami Heat")],
    )

    after = _index(db_factory)
    assert after is not None
    assert after is not before, "the shared index survived a league refresh"
    assert "boston celtics" in {s for s in after._surfaces}


def test_a_full_refresh_invalidates_the_index(db_factory):
    """`_save_cache` — the full path."""
    before = _index(db_factory)
    assert before is not None

    CacheRefresher(db_factory=db_factory)._save_cache(
        teams=[_team("Boston Celtics")],
        leagues=[
            {
                "league_slug": "nba",
                "provider": "espn",
                "league_name": "NBA",
                "sport": "basketball",
                "logo_url": None,
            }
        ],
    )

    after = _index(db_factory)
    assert after is not before, "the shared index survived a full refresh"


def test_purging_a_league_invalidates_the_index(db_factory):
    """Deleting a custom league's cached rows is a team_cache write too."""
    CacheRefresher(db_factory=db_factory)._save_league_teams(
        "custom.1",
        "espn",
        "soccer",
        display_name="Custom",
        logo_url=None,
        teams=[_team("Some Club", league="custom.1", sport="soccer")],
    )
    before = _index(db_factory)
    assert before is not None
    assert "some club" in set(before._surfaces)

    with db_factory() as conn:
        purge_league_cache_rows(conn, "custom.1")

    after = _index(db_factory)
    assert after is not before
    assert "some club" not in set(after._surfaces), (
        "the fixture gate is still vetoing against purged rows"
    )


def test_invalidation_clears_the_enrichment_memo_too(db_factory):
    """Both caches read the same rows, so they are dropped together."""
    from teamarr.services import sports_data

    sports_data._TEAM_IDENTITY_MEMO[("espn", "1", "nba")] = (1e18, {"name": "stale"})
    invalidate_team_identity_caches()
    assert not sports_data._TEAM_IDENTITY_MEMO


def test_a_refresh_that_writes_nothing_still_leaves_a_usable_index(db_factory):
    """Invalidation must not leave the gate permanently disabled."""
    CacheRefresher(db_factory=db_factory)._save_league_teams(
        "nba", "espn", "basketball", display_name="NBA", logo_url=None, teams=[]
    )
    assert _index(db_factory) is not None


@pytest.mark.parametrize("path", ["per_league", "full"])
def test_the_index_is_still_shared_between_refreshes(db_factory, path):
    """Invalidation must not defeat the memoization it guards."""
    refresher = CacheRefresher(db_factory=db_factory)
    if path == "per_league":
        refresher._save_league_teams(
            "nba",
            "espn",
            "basketball",
            display_name="NBA",
            logo_url=None,
            teams=[_team("Boston Celtics")],
        )
    else:
        refresher._save_cache(teams=[_team("Boston Celtics")], leagues=[])

    assert _index(db_factory) is _index(db_factory), "no longer memoized"
