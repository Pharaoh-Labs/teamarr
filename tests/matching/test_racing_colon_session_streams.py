"""Racing streams shaped ``Series Session: Race name`` reach the racing matcher (#770).

Reported from production as ``team2_not_found``: the colon made
``IndyCar Practice 1: Mission Grand Prix of Monterey`` read as a matchup, and
the racing matcher was said never to be tried. It is tried: in a source
dominated by team sports the stream classifies TEAM_ONLY, fails there, and the
racing fallback (#349) re-reads it as a racing stream. These pin that route,
the session each stream lands on, and the two cases that must NOT bind.

What the report could not have matched is a provider limitation, pinned here
too: ESPN lists only the race for an IndyCar weekend, so a practice or
qualifying stream has no session to attach to and gets no channel.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.matcher import StreamMatcher
from teamarr.consumers.racing_segments import expand_racing_segments
from teamarr.core.types import Event, EventStatus, RacingSession, Team, Venue

SERIES = Team(
    id="irl", provider="espn", name="IndyCar", short_name="IndyCar",
    abbreviation="IC", league="indycar", sport="racing",
)


def _weekend(sessions):
    return Event(
        id="202609061784", provider="espn", name="Grand Prix of Monterey",
        short_name="Monterey", start_time=sessions[0].start_time,
        home_team=SERIES, away_team=SERIES, status=EventStatus(state="scheduled"),
        league="indycar", sport="racing",
        venue=Venue(name="WeatherTech Raceway Laguna Seca", city="Monterey", country="USA"),
        sessions=sessions,
    )


RACE = RacingSession("race", "Race", datetime(2026, 9, 6, 18, 30, tzinfo=UTC))
# A weekend as a provider with full session data would list it.
FULL = _weekend(
    [
        RacingSession("fp1", "Practice 1", datetime(2026, 9, 5, 17, 0, tzinfo=UTC)),
        RacingSession("qualifying", "Qualifying", datetime(2026, 9, 5, 21, 0, tzinfo=UTC)),
        RACE,
    ]
)
# The weekend as ESPN actually lists it (captured 2026-10-03): the race alone.
RACE_ONLY = _weekend([RACE])

F1_TEAM = Team(
    id="f1", provider="espn", name="F1", short_name="F1",
    abbreviation="F1", league="f1", sport="racing",
)
ITALIAN_GP = Event(
    id="402", provider="espn", name="Pirelli Italian Grand Prix", short_name="Italian GP",
    start_time=datetime(2026, 9, 4, 10, 30, tzinfo=UTC), home_team=F1_TEAM, away_team=F1_TEAM,
    status=EventStatus(state="scheduled"), league="f1", sport="racing",
    venue=Venue(name="Autodromo Nazionale Monza", city="Monza", country="Italy"),
    sessions=[
        RacingSession("fp1", "Practice 1", datetime(2026, 9, 4, 10, 30, tzinfo=UTC)),
        RacingSession("race", "Race", datetime(2026, 9, 6, 13, 0, tzinfo=UTC)),
    ],
)


class _Service:
    def __init__(self, by_league):
        self._by_league = by_league

    def get_provider_name(self, league):
        return "espn"

    def get_events(self, league, target_date, cache_only=False):
        return self._by_league.get(league, [])

    def get_team_schedule(self, *args, **kwargs):
        return []


def _matcher(db_factory, by_league, leagues):
    racing = {"indycar", "f1"}
    matcher = StreamMatcher(
        service=_Service(by_league), db_factory=db_factory, group_id=1,
        search_leagues=leagues, user_tz=ZoneInfo("UTC"), generation=1, days_ahead=3,
        team_streams_enabled=True,
    )
    matcher._league_event_types = {
        lg: "event" if lg in racing else "team_vs_team" for lg in leagues
    }
    matcher._league_sports = {lg: "racing" if lg in racing else "football" for lg in leagues}
    return matcher


def _channels(result, name):
    if not result.matched:
        return None
    segments = expand_racing_segments(
        [{"stream": {"id": 1, "name": name}, "event": result.event}], {"racing": 3.0}
    )
    return [s.get("segment") for s in segments]


MIXED = ["indycar", "nfl", "mlb"]  # team sports dominate: primary pass is not racing


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("IndyCar Practice 1: Mission Grand Prix of Monterey", ["fp1"]),
        ("IndyCar Qualifying: Mission Grand Prix of Monterey", ["qualifying"]),
        ("TSN+ 02: IndyCar Qualifying: Grand Prix of Monterey", ["qualifying"]),
    ],
)
def test_session_stream_in_a_mixed_source_lands_on_its_own_session(db_factory, name, expected):
    matcher = _matcher(db_factory, {"indycar": [FULL]}, MIXED)
    result = matcher._match_single(1, name, date(2026, 9, 5))[0]
    assert result.matched and result.event.id == FULL.id
    assert _channels(result, name) == expected


def test_same_stream_in_a_racing_only_source(db_factory):
    name = "IndyCar Practice 1: Mission Grand Prix of Monterey"
    matcher = _matcher(db_factory, {"indycar": [FULL]}, ["indycar"])
    result = matcher._match_single(1, name, date(2026, 9, 5))[0]
    assert result.matched and _channels(result, name) == ["fp1"]


def test_practice_stream_gets_no_channel_when_the_provider_lists_only_the_race(db_factory):
    """ESPN's IndyCar weekend: there is no practice session to attach to, and
    the practice stream must not ride on the race channel."""
    name = "IndyCar Practice 1: Mission Grand Prix of Monterey"
    matcher = _matcher(db_factory, {"indycar": [RACE_ONLY]}, MIXED)
    result = matcher._match_single(1, name, date(2026, 9, 6))[0]
    assert _channels(result, name) in (None, [])


def test_race_stream_still_lands_on_the_race_when_only_the_race_is_listed(db_factory):
    name = "IndyCar: Mission Grand Prix of Monterey"
    matcher = _matcher(db_factory, {"indycar": [RACE_ONLY]}, MIXED)
    result = matcher._match_single(1, name, date(2026, 9, 6))[0]
    assert result.matched and _channels(result, name) == ["race"]


@pytest.mark.parametrize(
    "name",
    [
        "IndyCar Practice 1: Mission Grand Prix of Monterey",  # series not subscribed
        "TSN+ 02: Formula 3 Sprint Race: Monza",  # support series, same venue and weekend
    ],
)
def test_other_series_never_bind_to_the_f1_weekend(db_factory, name):
    matcher = _matcher(db_factory, {"f1": [ITALIAN_GP]}, ["f1", "nfl", "mlb"])
    result = matcher._match_single(1, name, date(2026, 9, 5))[0]
    assert not result.matched
