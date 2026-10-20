"""Cricket national teams reach their own matches (#944, bead 7cmb.5).

A cricket format league has no team list, so the identity index knows
"Australia" only as a rugby or soccer side until the schedule teaches it
(#912). A stream naming the format ("1st Test", "3rd ODI", "2nd T20I") must
reach the cricket match even when the same two countries play rugby that day,
and the fixture gate must never veto the cricket league for its own fixture.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching import team_matcher as team_matcher_module
from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.team_matcher import MatchContext, reset_identity_index_cache
from teamarr.core import Event, EventStatus, RacingSession, Team
from tests.fakes import make_team_matcher

TODAY = date(2026, 10, 11)
TEST = "cricket-test"
T20I = "cricket-t20i"
RUGBY = "rugby-world-cup"


def _team(name, short, abbr, league, sport, team_id=None) -> Team:
    return Team(
        id=team_id or f"{abbr.lower()}-{league}",
        provider="espn",
        name=name,
        short_name=short,
        abbreviation=abbr,
        league=league,
        sport=sport,
    )


def _event(home: Team, away: Team, eid: str, hour=7, sessions=()) -> Event:
    start = datetime(TODAY.year, TODAY.month, TODAY.day, hour, 30, tzinfo=UTC)
    return Event(
        id=eid,
        provider="espn",
        name=f"{away.name} v {home.name}",
        short_name=f"{away.abbreviation} v {home.abbreviation}",
        start_time=start,
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league=home.league,
        sport=home.sport,
        sessions=list(sessions),
    )


SA_CRICKET = _team("South Africa", "South Africa", "SA", TEST, "cricket", "3")
AUS_CRICKET = _team("Australia", "Australia", "AUS", TEST, "cricket", "2")
TEST_MATCH = _event(
    SA_CRICKET,
    AUS_CRICKET,
    "1525659",
    sessions=[
        RacingSession(
            code=f"day{i}", name=f"Day {i}", start_time=datetime(2026, 10, 8 + i, 7, 30, tzinfo=UTC)
        )
        for i in range(1, 6)
    ],
)
IND = _team("India", "India", "IND", T20I, "cricket", "6")
WI = _team("West Indies", "West Indies", "WI", T20I, "cricket", "4")
T20_MATCH = _event(IND, WI, "1529232", hour=13)

SA_RUGBY = _team("South Africa Springboks", "South Africa", "RSA", RUGBY, "rugby")
AUS_RUGBY = _team("Australia Wallabies", "Australia", "AUS", RUGBY, "rugby")
RUGBY_MATCH = _event(SA_RUGBY, AUS_RUGBY, "rugby-1", hour=9)

# The cache knows the rugby sides (ESPN lists rugby teams); it knows no cricket side.
CACHED_TEAMS = [
    ("South Africa Springboks", "South Africa", "RSA", RUGBY, "rugby"),
    ("Australia Wallabies", "Australia", "AUS", RUGBY, "rugby"),
    ("Australia", "Australia", "AUS", "aus.1", "soccer"),
    ("India", "India", "IND", "ind.1", "soccer"),
]


@pytest.fixture(autouse=True)
def _fresh_shared_index():
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


@pytest.mark.parametrize(
    "name",
    [
        "Australia v South Africa 1st Test",
        "SA vs AUS - 1st Test Day 3",
        "Australia vs South Africa Test match",
    ],
)
def test_a_format_word_takes_the_stream_to_the_cricket_match_not_the_rugby(db_factory, name):
    assert classify_stream(name).sport_hint == "Cricket"
    matcher = make_team_matcher(db_factory=db_factory)
    outcome = matcher._match_against_multi_league_events(
        _ctx(name), [(RUGBY, RUGBY_MATCH), (TEST, TEST_MATCH)]
    )
    assert outcome.is_matched, outcome.failed_reason
    assert outcome.event.id == "1525659"


def test_the_identity_index_learns_the_cricket_sides_from_the_schedule(db_factory):
    """Before the schedule teaches it, the cache says Australia and South Africa
    meet only in rugby; a cricket Test must not be vetoed for its own fixture."""
    matcher = make_team_matcher(db_factory=db_factory)
    outcome = matcher._match_against_events(
        _ctx("Australia v South Africa 1st Test"), [TEST_MATCH], TEST
    )
    assert outcome.is_matched and outcome.event.id == "1525659"


def test_an_odi_or_t20i_word_is_a_cricket_hint_and_a_bare_test_is_not():
    assert classify_stream("India v West Indies 3rd T20I").sport_hint == "Cricket"
    assert classify_stream("Canada vs Nepal ODI").sport_hint == "Cricket"
    assert classify_stream("Pakistan v England 2nd ODI").sport_hint == "Cricket"
    assert classify_stream("TEST CHANNEL 1").sport_hint != "Cricket"
    assert classify_stream("Lakers vs Celtics test").sport_hint != "Cricket"


def test_a_day_three_date_on_a_test_stream_is_on_time(db_factory):
    """The trusted-date gate measures distance to the nearest session day (#944)."""
    matcher = make_team_matcher(db_factory=db_factory)
    outcome = matcher._match_against_events(
        _ctx("Australia v South Africa 1st Test @ Oct 11 07:30"), [TEST_MATCH], TEST
    )
    assert outcome.is_matched, outcome.failed_reason


def test_without_a_format_word_the_rugby_game_can_win_the_same_day(db_factory):
    """Known exposure (#912): no sport word and both sports play the same day."""
    matcher = make_team_matcher(db_factory=db_factory)
    outcome = matcher._match_against_multi_league_events(
        _ctx("Australia v South Africa"), [(RUGBY, RUGBY_MATCH), (TEST, TEST_MATCH)]
    )
    assert outcome.is_matched  # it matches something; which one the ranking decides


# ---------------------------------------------------------------------------
# EPG path (#1098): the anchor gate measures to the nearest session day.
# ---------------------------------------------------------------------------


def _anchored(stream_name: str, anchor_dt: datetime) -> MatchContext:
    ctx = _ctx(stream_name)
    ctx.anchor_dt = anchor_dt
    ctx.target_date = anchor_dt.date()
    return ctx


@pytest.mark.parametrize("day", [2, 3, 5])
def test_a_later_day_programme_clears_the_anchor_gate(db_factory, day):
    """A day-N programme at that day's start is within tolerance of its session."""
    matcher = make_team_matcher(db_factory=db_factory)
    anchor = datetime(2026, 10, 8 + day, 7, 30, tzinfo=UTC)
    outcome = matcher._match_against_events(
        _anchored(f"Live 2nd Test Day {day}: SA v AUS", anchor), [TEST_MATCH], TEST
    )
    assert outcome.is_matched, outcome.failed_reason


def test_a_programme_a_day_after_the_last_session_is_still_gated(db_factory):
    """Nearest-session measuring widens to the sessions, not to the whole week."""
    matcher = make_team_matcher(db_factory=db_factory)
    anchor = datetime(2026, 10, 14, 7, 30, tzinfo=UTC)  # day 6 of a five-day Test
    outcome = matcher._match_against_events(
        _anchored("Live 2nd Test Day 6: SA v AUS", anchor), [TEST_MATCH], TEST
    )
    assert not outcome.is_matched


def test_an_event_without_sessions_still_measures_to_its_start(db_factory):
    matcher = make_team_matcher(db_factory=db_factory)
    anchor = datetime(TODAY.year, TODAY.month, TODAY.day, 13, 30, tzinfo=UTC) + timedelta(days=1)
    outcome = matcher._match_against_events(
        _anchored("India v West Indies 2nd T20I", anchor), [T20_MATCH], T20I
    )
    assert not outcome.is_matched
