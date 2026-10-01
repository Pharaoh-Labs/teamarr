"""The identity index learns who plays where from the schedule itself (#912).

`Massachusetts vs. #23 Vermont` — a men's college soccer game ESPN had on its
scoreboard — was vetoed as hockey. ESPN had renamed its NCAA soccer rows (568
of 688 gained a mascot in a month), so the soccer row became "Massachusetts
MInutewomen" (sic) with short name "UMass", and the bare school survived only
as the *hockey* row's short name. The gate read that as "these two meet in
hockey, never in soccer".

That is one case of a broader flaw: the gate treated team_cache — a provider's
per-league team LIST — as the truth about who plays where. Measured against a
same-day cache, 21 of 1,177 real ESPN events were vetoed from their own league,
and most were not naming problems at all: Vanderbilt volleyball, UT Rio Grande
Valley football and Delaware women's hockey had games and no row.

The fix is no alias table. An event is better evidence than the list: a team
with a game in a league plays in that league, under the names the event gives
it — including the provider's bare `location`, which is what streams write.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching import team_matcher as team_matcher_module
from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.identity import TeamIdentityIndex
from teamarr.consumers.matching.result import FailedReason
from teamarr.consumers.matching.team_matcher import MatchContext, reset_identity_index_cache
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()
CORPUS = Path(__file__).parent / "corpus" / "schedule_taught.json"

# (name, short_name, abbrev, league, sport) — the shape ESPN's lists had on
# 2026-09-30. Soccer carries the mascot and a nickname short name; only hockey
# still calls the school by its bare name.
CACHED_TEAMS = [
    ("Massachusetts Minutemen", "Massachusetts", "MASS", "mens-college-hockey", "hockey"),
    ("Vermont Catamounts", "Vermont", "UVM", "mens-college-hockey", "hockey"),
    ("Massachusetts MInutewomen", "UMass", "MASS", "usa.ncaa.m.1", "soccer"),
    ("Vermont Catamounts", "Vermont", "UVM", "usa.ncaa.m.1", "soccer"),
    # Vanderbilt plays volleyball; ESPN's volleyball list does not say so.
    ("LSU Tigers", "LSU", "LSU", "womens-college-volleyball", "volleyball"),
    ("LSU Tigers", "LSU", "LSU", "college-football", "football"),
    ("Vanderbilt Commodores", "Vanderbilt", "VAN", "college-football", "football"),
    # Cross-sport pair the gate exists to refuse.
    ("Tampa Bay Rays", "Rays", "TB", "mlb", "baseball"),
    ("Detroit Tigers", "Tigers", "DET", "mlb", "baseball"),
    ("Tampa Bay Lightning", "Lightning", "TB", "nhl", "hockey"),
    ("Detroit Red Wings", "Red Wings", "DET", "nhl", "hockey"),
]

SOCCER = "usa.ncaa.m.1"
HOCKEY = "mens-college-hockey"
VOLLEYBALL = "womens-college-volleyball"


def _team(name, short, abbr, league, sport, location=None, team_id=None) -> Team:
    return Team(
        id=team_id or f"t-{abbr.lower()}-{league}",
        provider="espn",
        name=name,
        short_name=short,
        abbreviation=abbr,
        league=league,
        sport=sport,
        location=location,
    )


def _event(home: Team, away: Team, eid: str) -> Event:
    return Event(
        id=eid,
        provider="espn",
        name=f"{away.name} at {home.name}",
        short_name=f"{away.abbreviation} @ {home.abbreviation}",
        start_time=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(hour=23),
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league=home.league,
        sport=home.sport,
    )


UMASS_SOCCER = _team(
    "Massachusetts MInutewomen", "UMass", "MASS", SOCCER, "soccer", "Massachusetts"
)
VERMONT_SOCCER = _team("Vermont Catamounts", "Vermont", "UVM", SOCCER, "soccer", "Vermont")
SOCCER_GAME = _event(VERMONT_SOCCER, UMASS_SOCCER, "401899183")

LSU_VB = _team("LSU Tigers", "LSU", "LSU", VOLLEYBALL, "volleyball", "LSU")
VANDY_VB = _team("Vanderbilt Commodores", "Vanderbilt", "VAN", VOLLEYBALL, "volleyball")
VOLLEYBALL_GAME = _event(VANDY_VB, LSU_VB, "vb-lsu-van")

RAYS = _team("Tampa Bay Rays", "Rays", "TB", "mlb", "baseball", "Tampa Bay")
TIGERS = _team("Detroit Tigers", "Tigers", "DET", "mlb", "baseball", "Detroit")
MLB_GAME = _event(TIGERS, RAYS, "401816657")


def _row(team: Team):
    return (team.name, team.short_name, team.abbreviation, team.location, team.league, team.sport)


def _rows(*events: Event):
    return {_row(team) for event in events for team in (event.home_team, event.away_team)}


@pytest.fixture(autouse=True)
def _fresh_shared_index():
    """The index and the taught-team ledger are process-wide; isolate each test."""
    reset_identity_index_cache()
    team_matcher_module._taught_teams.clear()
    yield
    reset_identity_index_cache()
    team_matcher_module._taught_teams.clear()


@pytest.fixture
def db_factory():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE team_cache (team_name TEXT, team_short_name TEXT, team_abbrev TEXT,"
        " league TEXT, sport TEXT)"
    )
    conn.execute("CREATE TABLE team_aliases (alias TEXT, team_name TEXT, league TEXT)")
    conn.executemany("INSERT INTO team_cache VALUES (?,?,?,?,?)", CACHED_TEAMS)
    conn.commit()

    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return conn

        def __exit__(self, *exc):
            return False

    return _Factory()


def _ctx(stream_name: str) -> MatchContext:
    classified = classify_stream(stream_name)
    return MatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=TODAY,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        classified=classified,
        team1=classified.team1,
        team2=classified.team2,
    )


class TestIndexLearnsFromEvents:
    def test_the_reported_stream_was_read_as_hockey_only(self):
        index = TeamIdentityIndex(CACHED_TEAMS)
        assert index.fixture_leagues("Massachusetts", "Vermont") == {HOCKEY}

    def test_location_gives_the_bare_school_its_soccer_reading(self):
        index = TeamIdentityIndex(CACHED_TEAMS)
        index.learn(_rows(SOCCER_GAME))
        assert index.fixture_leagues("Massachusetts", "Vermont") == {HOCKEY, SOCCER}

    def test_a_team_missing_from_its_leagues_list_is_learned(self):
        index = TeamIdentityIndex(CACHED_TEAMS)
        assert index.fixture_leagues("LSU", "Vanderbilt") == {"college-football"}

        index.learn(_rows(VOLLEYBALL_GAME))

        assert index.fixture_leagues("LSU", "Vanderbilt") == {"college-football", VOLLEYBALL}
        assert index.fixture_leagues("LSU Tigers", "Vanderbilt Commodores") == {
            "college-football",
            VOLLEYBALL,
        }

    def test_location_is_a_partial_reading_never_an_exact_one(self):
        """A bare school widens; it must not become grounds for a veto."""
        index = TeamIdentityIndex(CACHED_TEAMS)
        index.learn(_rows(SOCCER_GAME))
        assert index.resolve("Massachusetts").exact is False

    def test_the_resolve_memo_does_not_outlive_a_lesson(self):
        index = TeamIdentityIndex(CACHED_TEAMS)
        assert SOCCER not in index.resolve("Massachusetts").leagues  # now memoized

        index.learn(_rows(SOCCER_GAME))

        assert SOCCER in index.resolve("Massachusetts").leagues

    def test_teaching_the_same_schedule_again_changes_nothing(self):
        index = TeamIdentityIndex(CACHED_TEAMS)
        assert len(index.learn(_rows(SOCCER_GAME))) == 1  # Vermont's row already says it all
        assert index.learn(_rows(SOCCER_GAME)) == []
        # A fresh but equal tuple set, as the next run would build it.
        assert index.learn(set(_rows(SOCCER_GAME))) == []

    def test_a_team_the_cache_already_describes_is_not_news(self):
        index = TeamIdentityIndex(CACHED_TEAMS)
        assert index.learn({("Detroit Tigers", "Tigers", "DET", None, "mlb", "baseball")}) == []

    def test_learning_does_not_make_an_unseeded_league_known(self):
        """A league the cache never seeded holds only the teams its events
        happened to carry; judging streams against that is the #619 failure."""
        index = TeamIdentityIndex(CACHED_TEAMS)
        index.learn({("Chatham-Kent Barnstormers", "Barnstormers", "CK", None, "cbl", "baseball")})
        assert index.knows_league("cbl") is False

    def test_cross_sport_veto_survives_teaching_the_real_game(self):
        index = TeamIdentityIndex(CACHED_TEAMS)
        index.learn(_rows(MLB_GAME, SOCCER_GAME, VOLLEYBALL_GAME))
        leagues = index.fixture_leagues("Tampa Bay Lightning", "Detroit Red Wings")
        assert leagues == {"nhl"}

    def test_refinement_sees_a_taught_surface(self):
        """#799 strips junk around a known surface; a taught team is one."""
        index = TeamIdentityIndex(CACHED_TEAMS)
        utrgv = ("UT Rio Grande Valley Vaqueros", "UT Rio Grande", "RGV", None)
        index.learn({(*utrgv, "college-football", "football")})
        assert index.refine_side("ESPN+ 15: UT Rio Grande Valley", anchor="end") == (
            "UT Rio Grande Valley"
        )


class TestMatcherTeachesBeforeItGates:
    def test_the_reported_stream_reaches_its_soccer_game(self, db_factory):
        matcher = make_team_matcher(db_factory=db_factory)
        outcome = matcher._match_against_events(
            _ctx("ESPN+ 52: Massachusetts vs. #23 Vermont"), [SOCCER_GAME], SOCCER
        )
        assert outcome.is_matched
        assert outcome.event.id == "401899183"

    def test_both_entry_points_agree(self, db_factory):
        """Taught in the one candidate loop (#660), so no source type misses it."""
        single = make_team_matcher(db_factory=db_factory)._match_against_events(
            _ctx("LSU vs. Vanderbilt"), [VOLLEYBALL_GAME], VOLLEYBALL
        )
        reset_identity_index_cache()
        multi = make_team_matcher(db_factory=db_factory)._match_against_multi_league_events(
            _ctx("LSU vs. Vanderbilt"), [(VOLLEYBALL, VOLLEYBALL_GAME)]
        )
        assert single.is_matched and multi.is_matched
        assert single.event.id == multi.event.id == "vb-lsu-van"

    def test_cross_sport_stream_is_still_refused(self, db_factory):
        matcher = make_team_matcher(db_factory=db_factory)
        outcome = matcher._match_against_events(
            _ctx("ESPN+ 81 (D): Tampa Bay Lightning vs. Detroit Red Wings"), [MLB_GAME], "mlb"
        )
        assert not outcome.is_matched
        assert outcome.failed_reason is FailedReason.FIXTURE_NOT_IN_LEAGUE

    def test_placeholder_slots_are_not_taught(self, db_factory):
        """ESPN's undecided playoff slots: negative id, location "TBD"."""
        tbd = _team("TBD", "TBD", "TBD", "mlb", "baseball", "TBD", team_id="-1")
        slot = _team("Padres/Cubs", "Padres/Cubs", "Padres/Cubs", "mlb", "baseball", "TBD", "-2")
        matcher = make_team_matcher(db_factory=db_factory)

        matcher.learn_events([_event(tbd, slot, "playoff-1")])

        index = matcher._get_identity_index()
        assert not index.resolve("TBD")
        assert not index.resolve("Padres/Cubs")

    def test_a_shared_candidate_tuple_is_taught_once(self, db_factory):
        matcher = make_team_matcher(db_factory=db_factory)
        candidates = ((SOCCER, SOCCER_GAME),)
        matcher._teach_candidates(candidates)
        matcher.learn_events = MagicMock()

        matcher._teach_candidates(candidates)

        matcher.learn_events.assert_not_called()


class TestCachedVerdictsDoNotOutliveALesson:
    """A cached failure replays before the logic that would now pass it
    (#757), so the first time a team is taught, cached failures go — every
    reason, because refinement (#799) reads the index too and a taught surface
    turns NO_EVENT_FOUND into a match as readily as it lifts a veto."""

    def test_a_new_team_clears_cached_failures(self, db_factory):
        cache = MagicMock()
        matcher = make_team_matcher(cache=cache, db_factory=db_factory)

        matcher.learn_events([SOCCER_GAME])

        cache.clear_failed.assert_called_once_with()

    def test_reteaching_after_an_index_rebuild_clears_nothing(self, db_factory):
        """The index is rebuilt every TTL window and re-taught the same
        schedule; that must not empty the negative cache every run."""
        make_team_matcher(cache=MagicMock(), db_factory=db_factory).learn_events([SOCCER_GAME])
        reset_identity_index_cache()
        cache = MagicMock()

        make_team_matcher(cache=cache, db_factory=db_factory).learn_events([SOCCER_GAME])

        cache.clear_failed.assert_not_called()

    def test_a_schedule_the_cache_already_covers_clears_nothing(self, db_factory):
        cache = MagicMock()
        mlb_no_location = _event(
            _team("Detroit Tigers", "Tigers", "DET", "mlb", "baseball"),
            _team("Tampa Bay Rays", "Rays", "TB", "mlb", "baseball"),
            "mlb-1",
        )
        make_team_matcher(cache=cache, db_factory=db_factory).learn_events([mlb_no_location])
        cache.clear_failed.assert_not_called()


class TestProviderCarriesLocation:
    def test_espn_competitor_location_reaches_the_team(self):
        from teamarr.providers.espn.provider import ESPNProvider

        competitor = {
            "team": {
                "id": "5687",
                "location": "Massachusetts",
                "displayName": "Massachusetts MInutewomen",
                "shortDisplayName": "UMass",
                "abbreviation": "MASS",
            }
        }
        team = ESPNProvider._parse_team(MagicMock(name="provider"), competitor, SOCCER, "soccer")
        assert team.location == "Massachusetts"

    def test_location_survives_the_event_cache(self):
        from teamarr.database.provider_cache import dict_to_team, team_to_dict

        assert dict_to_team(team_to_dict(UMASS_SOCCER)).location == "Massachusetts"
        # Events cached before #912 have no such key.
        legacy = team_to_dict(UMASS_SOCCER)
        del legacy["location"]
        assert dict_to_team(legacy).location is None


# ---------------------------------------------------------------------------
# Real fixtures the gate vetoed from their own league (captured 2026-09-30)
# ---------------------------------------------------------------------------


def _corpus() -> dict:
    return json.loads(CORPUS.read_text())


def _case_id(case: dict) -> str:
    return f"{case['league']}: {case['side_a']} / {case['side_b']} ({case['form']})"


@pytest.fixture(scope="module")
def corpus() -> dict:
    return _corpus()


def test_corpus_is_present(corpus) -> None:
    assert len(corpus["cases"]) >= 50
    assert len(corpus["teams"]) >= 1000


@pytest.mark.parametrize("case", _corpus()["cases"], ids=_case_id)
def test_a_real_event_is_never_vetoed_from_its_own_league(corpus, case) -> None:
    """Each case is a real ESPN event whose own league the gate refused,
    against the team_cache rows that produced the refusal. Once the event has
    taught the index its two teams, the refusal must be gone."""
    index = TeamIdentityIndex([tuple(row) for row in corpus["teams"]])
    before = index.fixture_leagues(case["side_a"], case["side_b"])
    assert before is not None and case["league"] not in before, "capture no longer reproduces"

    index.learn({(*team, case["league"], case["sport"]) for team in map(tuple, case["teams"])})

    after = index.fixture_leagues(case["side_a"], case["side_b"])
    assert after is None or case["league"] in after
