"""The team cache refresh clears only the failures naming a team it added or renamed (#1184).

#757 made ``invalidate_team_identity_caches`` wipe the whole negative match
cache, and both refresh save paths call it after rewriting ``team_cache`` by
delete-then-insert — so the wipe fired on every container start and once a
day whether or not a single team changed. On a real install the first run
after a deploy showed ``streams_cached`` at ~500 against a 2,200–4,400 steady
state, and the next two or three runs re-scored every never-matching stream.

#1153 already scoped the schedule-taught clear by stream-name surface. These
pin the same rule on the refresh path: a refresh that rewrites identical rows
clears nothing; one that adds or renames a team clears only the failures whose
stream name carries one of that team's surfaces. The user-driven paths (alias
edit, league reset) keep the full clear, because there is no diff to scope by.

The refresher holds its own connection across the save (#938), so these use
the real ``get_db`` factory, whose connections close on exit.
"""

from __future__ import annotations

from teamarr.consumers.cache.refresh import CacheRefresher
from teamarr.consumers.matching.result import FailedReason
from teamarr.consumers.stream_match_cache import FAILED_MATCH_EVENT_ID, StreamMatchCache
from teamarr.database.leagues import purge_league_cache_rows

NBA_LEAGUE = {
    "league_slug": "nba",
    "provider": "espn",
    "league_name": "NBA",
    "sport": "basketball",
    "logo_url": None,
}


def _team(name, short_name=None, abbrev=None, league="nba", sport="basketball"):
    return {
        "team_name": name,
        "team_abbrev": abbrev or name[:3].upper(),
        "team_short_name": short_name or name.split()[-1],
        "provider": "espn",
        "provider_team_id": name.lower().replace(" ", "-"),
        "league": league,
        "sport": sport,
        "logo_url": None,
    }


def _refresh_league(db_factory, teams):
    return CacheRefresher(db_factory=db_factory)._save_league_teams(
        "nba", "espn", "basketball", display_name="NBA", logo_url=None, teams=teams
    )


def _refresh_all(db_factory, teams):
    CacheRefresher(db_factory=db_factory)._save_cache(teams=teams, leagues=[NBA_LEAGUE])


def _seed_failures(db_factory):
    """Three failures: one names the Heat, one the Celtics, one nobody."""
    c = StreamMatchCache(db_factory)
    for stream_id, name in (
        (1, "NBA | Heat vs Knicks"),
        (2, "NBA | Celtics at Bulls"),
        (3, "Rays at Tigers"),
    ):
        c.set_failed(
            group_id=1,
            stream_id=stream_id,
            stream_name=name,
            generation=5,
            reason=FailedReason.NO_EVENT_FOUND.value,
        )


def _failed_names(db_factory) -> set[str]:
    with db_factory() as conn:
        rows = conn.execute(
            "SELECT stream_name FROM stream_match_cache WHERE event_id = ?",
            (FAILED_MATCH_EVENT_ID,),
        ).fetchall()
    return {r["stream_name"] for r in rows}


ALL = {"NBA | Heat vs Knicks", "NBA | Celtics at Bulls", "Rays at Tigers"}


class TestPerLeagueRefresh:
    def test_identical_rows_clear_nothing(self, db_factory):
        _refresh_league(db_factory, [_team("Boston Celtics"), _team("Miami Heat")])
        _seed_failures(db_factory)

        _refresh_league(db_factory, [_team("Boston Celtics"), _team("Miami Heat")])

        assert _failed_names(db_factory) == ALL, "an unchanged refresh wiped the cache"

    def test_an_added_team_clears_only_the_failures_naming_it(self, db_factory):
        _refresh_league(db_factory, [_team("Boston Celtics")])
        _seed_failures(db_factory)

        _refresh_league(db_factory, [_team("Boston Celtics"), _team("Miami Heat")])

        assert _failed_names(db_factory) == {"NBA | Celtics at Bulls", "Rays at Tigers"}

    def test_a_renamed_team_counts_as_added(self, db_factory):
        _refresh_league(db_factory, [_team("Boston Celtics"), _team("Miami Heaters")])
        _seed_failures(db_factory)

        _refresh_league(db_factory, [_team("Boston Celtics"), _team("Miami Heat")])

        assert _failed_names(db_factory) == {"NBA | Celtics at Bulls", "Rays at Tigers"}

    def test_a_removed_team_clears_nothing(self, db_factory):
        """A team that is gone cannot make a failing stream match."""
        _refresh_league(db_factory, [_team("Boston Celtics"), _team("Miami Heat")])
        _seed_failures(db_factory)

        _refresh_league(db_factory, [_team("Boston Celtics")])

        assert _failed_names(db_factory) == ALL

    def test_successes_and_pins_survive_an_added_team(self, db_factory):
        _refresh_league(db_factory, [_team("Boston Celtics")])
        c = StreamMatchCache(db_factory)
        event = {"id": "e1", "name": "Heat at Knicks"}
        c.set(
            group_id=1,
            stream_id=10,
            stream_name="NBA | Heat at Knicks",
            event_id="e1",
            league="nba",
            cached_data=event,
            generation=5,
        )
        c.set_user_correction(
            group_id=1,
            stream_id=11,
            stream_name="NBA | Heat pinned",
            event_id="e9",
            league="nba",
            cached_data=event,
        )

        _refresh_league(db_factory, [_team("Boston Celtics"), _team("Miami Heat")])

        assert c.get(1, 10, "NBA | Heat at Knicks") is not None
        assert c.is_user_corrected(1, 11, "NBA | Heat pinned") is True


class TestFullRefresh:
    def test_identical_rows_clear_nothing(self, db_factory):
        _refresh_all(db_factory, [_team("Boston Celtics"), _team("Miami Heat")])
        _seed_failures(db_factory)

        _refresh_all(db_factory, [_team("Boston Celtics"), _team("Miami Heat")])

        assert _failed_names(db_factory) == ALL, "an unchanged full refresh wiped the cache"

    def test_an_added_team_clears_only_the_failures_naming_it(self, db_factory):
        _refresh_all(db_factory, [_team("Boston Celtics")])
        _seed_failures(db_factory)

        _refresh_all(db_factory, [_team("Boston Celtics"), _team("Miami Heat")])

        assert _failed_names(db_factory) == {"NBA | Celtics at Bulls", "Rays at Tigers"}

    def test_the_first_refresh_of_an_empty_cache_clears_by_name(self, db_factory):
        """An empty cache means every team is new — but the clear is still by surface."""
        _seed_failures(db_factory)

        _refresh_all(db_factory, [_team("Miami Heat")])

        assert _failed_names(db_factory) == {"NBA | Celtics at Bulls", "Rays at Tigers"}


class TestUserDrivenPathsKeepTheFullClear:
    def test_league_reset_asks_for_the_full_clear(self, db_factory, monkeypatch):
        """A reset has no before/after diff to scope by, so it keeps #757's full clear.

        Pinned on the call rather than the rows: the purge runs inside the
        caller's open write transaction, and a second connection cannot clear
        rows while that lock is held (pre-existing, not changed here).
        """
        import teamarr.consumers.cache.refresh as refresh_mod
        import teamarr.database.team_cache as team_cache_mod

        calls: list[dict] = []

        def record(**kwargs):
            calls.append(kwargs)

        # The refresher binds the name at import; the league reset imports it
        # function-locally from team_cache. Patch both so each call is seen.
        monkeypatch.setattr(refresh_mod, "invalidate_team_identity_caches", record)
        monkeypatch.setattr(team_cache_mod, "invalidate_team_identity_caches", record)
        _refresh_league(db_factory, [_team("Boston Celtics")])
        assert calls == [{"clear_failed": False}], "the refresh must scope its clear"
        calls.clear()

        with db_factory() as conn:
            purge_league_cache_rows(conn, "nba")

        assert calls == [{}], "the league reset must keep the full clear"
