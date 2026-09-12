# ruff: noqa: E501  — captured stream names are the fixtures
"""The racing single-event path needs series or session evidence, not "grand prix" alone (#804).

Prod, 2026-09-12: two cycling "Grand Prix Cycliste de Québec" streams sat on
the Spanish Grand Prix session channels. With one F1 event covering the date
the cycling name scored 52.6 (shared "grand prix") and the generic racing
evidence accepted the same two words.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.racing_matcher import RacingMatcher, _single_event_evidence
from teamarr.consumers.matching.result import ResultCategory
from teamarr.core.types import Event, EventStatus, RacingSession, Team, Venue

TEAM = Team(
    id="event_401",
    provider="espn",
    name="Tag Heuer Spanish Grand Prix",
    short_name="Spanish GP",
    abbreviation="SGP",
    league="f1",
    sport="racing",
)
SPANISH_GP = Event(
    id="401",
    provider="espn",
    name="Tag Heuer Spanish Grand Prix",
    short_name="Spanish GP",
    start_time=datetime(2026, 9, 11, 11, 30, tzinfo=UTC),
    home_team=TEAM,
    away_team=TEAM,
    status=EventStatus(state="scheduled"),
    league="f1",
    sport="racing",
    venue=Venue(name="Madring", city="Madrid", country="Spain"),
    circuit_name="Madring",
    sessions=[
        RacingSession("fp3", "Practice 3", datetime(2026, 9, 12, 10, 30, tzinfo=UTC)),
        RacingSession("qualifying", "Qualifying", datetime(2026, 9, 12, 14, 0, tzinfo=UTC)),
        RacingSession("race", "Race", datetime(2026, 9, 13, 13, 0, tzinfo=UTC)),
    ],
)


class _NoCache:
    def get(self, *a, **k):
        return None

    def touch(self, *a, **k):
        pass

    def set(self, *a, **k):
        pass

    def set_failed(self, *a, **k):
        pass


class _Service:
    def get_provider_name(self, league):
        return "espn"

    def get_events(self, league, target_date, cache_only=False):
        return [SPANISH_GP]


def _match(stream: str):
    classified = classify_stream(stream, "event", None, None, None, event_league_sport="racing")
    return RacingMatcher(_Service(), _NoCache()).match(
        classified, "f1", date(2026, 9, 12), 1, 1, 1, ZoneInfo("America/New_York")
    )


class TestEvidence:
    def test_grand_prix_alone_is_not_evidence(self):
        assert _single_event_evidence("Grand Prix Cycliste de Québec") is False

    def test_series_or_session_is(self):
        assert _single_event_evidence("Sky Sports F1 coverage") is True
        assert _single_event_evidence("NASCAR Cup Series at Bristol") is True
        assert _single_event_evidence("Grand Prix Weekend - Qualifying") is True


class TestCyclingStreamsStayOff:
    def test_the_prod_streams_no_longer_bind(self):
        for stream in (
            "MAX USA 01: Men | Quebec City (206km): Grand Prix Cycliste de Quebec @ 11 Sep 09:50 AM ET",
            "Flo Sports 31: flobikes: 2026 Grand Prix Cycliste de Québec (Grand Prix Cycliste de Québec) @ 12 Sep 12:00 PM ET",
        ):
            assert _match(stream).category is not ResultCategory.MATCHED, stream

    def test_real_f1_shapes_still_bind(self):
        for stream in (
            "TSN+ 02: Formula 1 Pit Lane - Spanish Grand Prix Practice #3 @ 12 Sep 06:20 AM ET",  # name score 100
            "F1: Grand Prix Weekend Coverage @ 12 Sep 08:00 AM ET",  # weak score, series word
            "Spanish Grand Prix Qualifying @ 12 Sep 10:00 AM ET",  # name score, session word
        ):
            assert _match(stream).category is ResultCategory.MATCHED, stream
