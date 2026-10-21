"""A team-only stream is gated by its exact identity (#1108).

match_team_only scores the one branded name against each event side with
token_set_ratio, which hands a subset a free 100: every token of "florida
panthers" is in "Florida International Panthers", and "rangers" is a subset of
"new york rangers". On a production install an NHL team feed was attached to
FIU football and Rangers FC channels in 86 and 120 consecutive runs, because
the fixture gate (#619) only ever read two-sided streams.

The gate here has the same shape: veto only, an exact full-name identity is the
only evidence, a league the index has no teams for is never judged, and a league
hint keeps its #627 hatch.
"""

import sqlite3
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.result import FailedReason
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

UTC_TZ = ZoneInfo("UTC")
TODAY = datetime.now(UTC).date()

CACHED_TEAMS = [
    ("Florida Panthers", "Panthers", "FLA", "nhl", "hockey"),
    ("Ottawa Senators", "Senators", "OTT", "nhl", "hockey"),
    ("New York Rangers", "Rangers", "NYR", "nhl", "hockey"),
    ("New Jersey Devils", "Devils", "NJ", "nhl", "hockey"),
    ("Florida International Panthers", "FIU", "FIU", "college-football", "football"),
    ("Middle Tennessee Blue Raiders", "Middle Tenn", "MTSU", "college-football", "football"),
    ("Rangers", "Rangers", "RAN", "sco.1", "soccer"),
    ("Dundee", "Dundee", "DUN", "sco.1", "soccer"),
]


@pytest.fixture
def db_factory():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE team_cache (
            team_name TEXT, team_short_name TEXT, team_abbrev TEXT,
            league TEXT, sport TEXT
        )
        """
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


def _team(name, short, abbr, league, sport) -> Team:
    return Team(
        id=f"t-{abbr.lower()}-{league}",
        provider="espn",
        name=name,
        short_name=short,
        abbreviation=abbr,
        league=league,
        sport=sport,
    )


def _event(home: Team, away: Team, eid: str) -> Event:
    return Event(
        id=eid,
        provider="espn",
        name=f"{away.name} at {home.name}",
        short_name=f"{away.short_name} at {home.short_name}",
        start_time=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(hour=23),
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league=home.league,
        sport=home.sport,
    )


PANTHERS = _team("Florida Panthers", "Panthers", "FLA", "nhl", "hockey")
SENATORS = _team("Ottawa Senators", "Senators", "OTT", "nhl", "hockey")
NY_RANGERS = _team("New York Rangers", "Rangers", "NYR", "nhl", "hockey")
DEVILS = _team("New Jersey Devils", "Devils", "NJ", "nhl", "hockey")
FIU = _team("Florida International Panthers", "FIU", "FIU", "college-football", "football")
MTSU = _team("Middle Tennessee Blue Raiders", "Middle Tenn", "MTSU", "college-football", "football")
RANGERS_FC = _team("Rangers", "Rangers", "RAN", "sco.1", "soccer")
DUNDEE = _team("Dundee", "Dundee", "DUN", "sco.1", "soccer")

PANTHERS_SENATORS = _event(SENATORS, PANTHERS, "nhl-1")
MTSU_FIU = _event(FIU, MTSU, "ncaaf-1")
RANGERS_DEVILS = _event(NY_RANGERS, DEVILS, "nhl-2")
RANGERS_DUNDEE = _event(DUNDEE, RANGERS_FC, "sco-1")


def _match(stream_name, prefetched, db_factory, *, include_leagues=None, leagues=None):
    matcher = make_team_matcher(db_factory=db_factory, include_leagues=include_leagues)
    classified = classify_stream(stream_name)
    return matcher.match_team_only(
        classified,
        enabled_leagues=leagues or list(prefetched),
        target_date=TODAY,
        group_id=1,
        stream_id=424242,
        generation=1,
        user_tz=UTC_TZ,
        prefetched_events=prefetched,
    )


def _matched_ids(outcomes):
    return sorted(o.event.id for o in outcomes if o.is_matched)


class TestExactIdentityVetoes:
    def test_florida_panthers_does_not_reach_fiu_football(self, db_factory):
        outcomes = _match(
            "Florida Panthers",
            {"nhl": [PANTHERS_SENATORS], "college-football": [MTSU_FIU]},
            db_factory,
        )
        assert _matched_ids(outcomes) == ["nhl-1"]

    def test_new_york_rangers_does_not_reach_rangers_fc(self, db_factory):
        outcomes = _match(
            "New York Rangers",
            {"nhl": [RANGERS_DEVILS], "sco.1": [RANGERS_DUNDEE]},
            db_factory,
        )
        assert _matched_ids(outcomes) == ["nhl-2"]

    def test_every_candidate_vetoed_reports_fixture_not_in_league(self, db_factory):
        outcomes = _match("Florida Panthers", {"college-football": [MTSU_FIU]}, db_factory)
        assert len(outcomes) == 1
        assert outcomes[0].failed_reason is FailedReason.FIXTURE_NOT_IN_LEAGUE
        assert "nhl" in (outcomes[0].detail or "")

    def test_unsubscribed_league_is_the_791_refinement(self, db_factory):
        outcomes = _match(
            "Florida Panthers",
            {"college-football": [MTSU_FIU]},
            db_factory,
            include_leagues={"college-football"},
        )
        assert outcomes[0].failed_reason is FailedReason.FIXTURE_LEAGUE_NOT_SUBSCRIBED


class TestGateDefers:
    def test_bare_short_name_still_fans_out(self, db_factory):
        """ "Panthers" is a short name, never an exact identity: no evidence,
        no veto — the pre-#1108 fan-out stands and the scorer decides."""
        outcomes = _match(
            "Panthers",
            {"nhl": [PANTHERS_SENATORS], "college-football": [MTSU_FIU]},
            db_factory,
        )
        assert _matched_ids(outcomes) == ["ncaaf-1", "nhl-1"]

    def test_full_name_that_is_also_a_short_name_keeps_both_leagues(self, db_factory):
        """ "Rangers" is Rangers FC's full name AND the NHL side's short name.
        The exact hit carries its partial readings (#619), so neither league
        is vetoed."""
        outcomes = _match(
            "Rangers",
            {"nhl": [RANGERS_DEVILS], "sco.1": [RANGERS_DUNDEE]},
            db_factory,
        )
        assert _matched_ids(outcomes) == ["nhl-2", "sco-1"]

    def test_unknown_league_is_never_vetoed(self, db_factory):
        """A league the cache has no teams for cannot be judged (#619)."""
        with db_factory() as conn:
            conn.execute("DELETE FROM team_cache WHERE league = 'college-football'")
            conn.commit()
        outcomes = _match(
            "Florida Panthers",
            {"nhl": [PANTHERS_SENATORS], "college-football": [MTSU_FIU]},
            db_factory,
        )
        assert _matched_ids(outcomes) == ["ncaaf-1", "nhl-1"]

    def test_no_identity_index_matches_as_before(self):
        outcomes = _match(
            "Florida Panthers",
            {"nhl": [PANTHERS_SENATORS], "college-football": [MTSU_FIU]},
            None,
        )
        assert _matched_ids(outcomes) == ["ncaaf-1", "nhl-1"]

    def test_league_hint_keeps_its_hatch(self, db_factory):
        """An explicit hint is stronger than the identity index (#627)."""
        outcomes = _match(
            "NCAAF | Florida Panthers",
            {"nhl": [PANTHERS_SENATORS], "college-football": [MTSU_FIU]},
            db_factory,
        )
        assert _matched_ids(outcomes) == ["ncaaf-1"]
