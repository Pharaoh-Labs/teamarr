# ruff: noqa: E501  — captured provider stream names are the fixtures; wrapping them hides the shape
"""A NASCAR stream binds to the series it names (#1158).

Talladega, Sat 2026-10-24: the Cup Series (YellaWood 500, event 5631) and the
O'Reilly Auto Parts Series (The Progress Group 250, event 5664) both ran
sessions that day. "NASCAR" scoped a stream to all three national series, the
first league tried took it on session times alone, and

    US (ESPN+ 193): NASCAR O`Reilly Auto Parts Series: Sheldon Creed Cam … (2026-10-24 15:25:35) [1080p]

sat on the Cup qualifying channel (19:25Z is inside Cup qualifying + 90 min)
while

    CA (TSN+ 011): NASCAR Cup Series Qualifying: YellaWood 500 (2026-10-24 13:00:00) [1080p]

sat on the O'Reilly one. A local short-track race that only says "NASCAR"
bound to the O'Reilly race the same way.

The two events below are the cf.nascar.com schedule as fetched 2026-11-21
(names, track, session start times). The truck event is invented — the Truck
Series did not race that weekend — and deliberately shares the O'Reilly
qualifying hour so time cannot tell them apart.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import permutations
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import (
    NASCAR_SERIES_WORDS,
    classify_stream,
    detect_nascar_series,
)
from teamarr.consumers.matching.matcher import StreamMatcher
from teamarr.consumers.matching.racing_matcher import RacingMatcher
from teamarr.consumers.matching.result import FailedReason, MatchMethod
from teamarr.core.types import Event, EventStatus, RacingSession, Team, Venue

NY = ZoneInfo("America/New_York")
SATURDAY = date(2026, 10, 24)
TALLADEGA = "Talladega Superspeedway"


def _event(event_id: str, league: str, name: str, sessions, track: str = TALLADEGA) -> Event:
    team = Team(
        id=f"event_{event_id}",
        provider="nascar",
        name=name,
        short_name=name,
        abbreviation="NAS",
        league=league,
        sport="racing",
    )
    return Event(
        id=event_id,
        provider="nascar",
        name=name,
        short_name=name,
        start_time=sessions[0].start_time,
        home_team=team,
        away_team=team,
        status=EventStatus(state="scheduled"),
        league=league,
        sport="racing",
        venue=Venue(name=track),
        circuit_name=track,
        sessions=sessions,
    )


CUP = _event(
    "5631",
    "nascar-cup",
    "YellaWood 500",
    [
        RacingSession(
            "qualifying", "Qualifying (Impound)", datetime(2026, 10, 24, 17, 0, tzinfo=UTC)
        ),
        RacingSession("race", "Race", datetime(2026, 10, 25, 18, 0, tzinfo=UTC)),
    ],
)
OREILLY = _event(
    "5664",
    "nascar-xfinity",
    "The Progress Group 250",
    [
        RacingSession(
            "qualifying", "Qualifying (Impound)", datetime(2026, 10, 24, 15, 0, tzinfo=UTC)
        ),
        RacingSession("race", "Race", datetime(2026, 10, 24, 19, 30, tzinfo=UTC)),
    ],
)
TRUCK = _event(
    "9001",
    "nascar-truck",
    "Slim Jim 200",
    [
        RacingSession("qualifying", "Qualifying", datetime(2026, 10, 24, 15, 0, tzinfo=UTC)),
        RacingSession("race", "Race", datetime(2026, 10, 24, 23, 0, tzinfo=UTC)),
    ],
    track="Martinsville Speedway",
)
F1_TEAM = Team(
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
    home_team=F1_TEAM,
    away_team=F1_TEAM,
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

OREILLY_CAMS = [
    "US (ESPN+ 193): NASCAR O`Reilly Auto Parts Series: Sheldon Creed Cam  Battle Cam (Sheldon Creed Cam ) (2026-10-24 15:25:35) [1080p]",
    "US (ESPN+ 194): NASCAR O`Reilly Auto Parts Series: Justin Allgaier Cam  Battle Cam (Justin Allgaier Cam ) (2026-10-24 15:26:10) [1080p]",
    # A sibling 5 seconds past Cup qualifying's tolerance: it already landed right.
    "US (ESPN+ 195): NASCAR O`Reilly Auto Parts Series: Connor Zilisch Cam  Battle Cam (Connor Zilisch Cam ) (2026-10-24 15:30:05) [1080p]",
]
CUP_QUALIFYING = (
    "CA (TSN+ 011): NASCAR Cup Series Qualifying: YellaWood 500 (2026-10-24 13:00:00) [1080p]"
)
LANGLEY = "LIVE EVENT 16 - 6pm NASCAR Halloween Speedfest Langley"

SHARED_WEEKEND = {"nascar-cup": [CUP], "nascar-xfinity": [OREILLY]}
THREE_SERIES = {**SHARED_WEEKEND, "nascar-truck": [TRUCK]}


class _NoCache:
    def get(self, *a, **k):
        return None

    def touch(self, *a, **k):
        pass

    def set(self, *a, **k):
        pass

    def set_failed(self, *a, **k):
        pass

    def delete(self, *a, **k):
        pass


class _Service:
    def __init__(self, by_league):
        self._by_league = by_league

    def get_provider_name(self, league):
        return "nascar"

    def get_events(self, league, target_date, cache_only=False):
        return self._by_league.get(league, [])

    def get_team_schedule(self, *args, **kwargs):
        return []


def _classify(stream: str):
    return classify_stream(stream, "event", None, None, None, event_league_sport="racing")


def _router(by_league, leagues, target=SATURDAY, tz=NY, cache=None):
    """A StreamMatcher whose racing leagues are tried in the order given."""
    matcher = StreamMatcher(
        service=_Service(by_league),
        db_factory=None,
        group_id=1,
        search_leagues=list(leagues),
        user_tz=tz,
        generation=1,
        days_ahead=3,
    )
    matcher._league_event_types = dict.fromkeys(leagues, "event")
    matcher._league_sports = dict.fromkeys(leagues, "racing")
    if cache is not None:
        matcher._racing_matcher = RacingMatcher(matcher._service, cache)
    else:
        matcher._racing_matcher = RacingMatcher(matcher._service, _NoCache())
    return lambda stream: matcher._match_racing_event(_classify(stream), 1, target)


def _one_league(stream: str, league: str, events, target=SATURDAY):
    matcher = RacingMatcher(_Service({league: list(events)}), _NoCache())
    return matcher.match(_classify(stream), league, target, 1, 1, 1, NY)


class TestSeriesWords:
    @pytest.mark.parametrize(
        ("stream", "leagues"),
        [
            (OREILLY_CAMS[0], ("nascar-xfinity",)),
            ("NASCAR O'Reilly Auto Parts Series: Race", ("nascar-xfinity",)),
            ("NASCAR O’Reilly Auto Parts Series: Race", ("nascar-xfinity",)),
            ("NASCAR OReilly Series Qualifying", ("nascar-xfinity",)),
            ("NASCAR Xfinity Series: The Progress Group 250", ("nascar-xfinity",)),
            ("NASCAR ORAP | Talladega", ("nascar-xfinity",)),
            (CUP_QUALIFYING, ("nascar-cup",)),
            ("NASCAR Cup Qualifying @ 24 Oct 1:00 PM ET", ("nascar-cup",)),
            ("NASCAR Craftsman Truck Series: Slim Jim 200", ("nascar-truck",)),
            ("NASCAR Trucks Qualifying", ("nascar-truck",)),
            ("NASCAR Truck Series Race", ("nascar-truck",)),
            # The umbrella word alone names no series.
            (LANGLEY, ()),
            ("NASCAR Race Talladega", ()),
            # A sponsor word in front of a race distance is a race name, not a
            # series (2026 Cup schedule: "Xfinity 500", Martinsville).
            ("NASCAR Cup Series: Xfinity 500", ("nascar-cup",)),
            ("NASCAR: Xfinity 500 (2026-10-31 14:45:00)", ()),
            ("NASCAR O'Reilly Auto Parts 500", ()),
            ("NASCAR Craftsman 150", ()),
            ("NASCAR Craftsman Truck Series: Craftsman 150", ("nascar-truck",)),
            # A Cup broadcast that mentions the other series by name names both: no narrowing.
            ("NASCAR Cup Series after the Xfinity Series race", ("nascar-cup", "nascar-xfinity")),
        ],
    )
    def test_detect(self, stream, leagues):
        assert detect_nascar_series(stream) == leagues

    def test_words_cover_exactly_the_nascar_leagues_in_the_schema(self):
        import re

        schema = open("teamarr/database/schema.sql").read()
        codes = set(re.findall(r"\('(nascar-[a-z]+)',\s+'nascar'", schema))
        assert codes == set(NASCAR_SERIES_WORDS) == {"nascar-cup", "nascar-xfinity", "nascar-truck"}


class TestSharedWeekend:
    """Both series at Talladega; every order the leagues could be handed over in."""

    @pytest.mark.parametrize("order", list(permutations(SHARED_WEEKEND)))
    @pytest.mark.parametrize("stream", OREILLY_CAMS)
    def test_oreilly_cam_lands_on_the_oreilly_event(self, order, stream):
        outcome = _router(SHARED_WEEKEND, order)(stream)
        assert outcome.is_matched
        assert (outcome.event.id, outcome.detected_league) == ("5664", "nascar-xfinity")

    @pytest.mark.parametrize("order", list(permutations(SHARED_WEEKEND)))
    def test_cup_qualifying_lands_on_the_cup_event(self, order):
        outcome = _router(SHARED_WEEKEND, order)(CUP_QUALIFYING)
        assert outcome.is_matched
        assert (outcome.event.id, outcome.detected_league) == ("5631", "nascar-cup")
        assert not outcome.time_only  # "YellaWood 500" is a name match

    @pytest.mark.parametrize("order", list(permutations(SHARED_WEEKEND)))
    def test_local_race_that_only_says_nascar_binds_to_nothing(self, order):
        outcome = _router(SHARED_WEEKEND, order)(LANGLEY)
        assert not outcome.is_matched
        assert outcome.failed_reason == FailedReason.NO_RACING_MATCH

    def test_the_other_series_refuses_the_stream_when_asked_directly(self):
        # Not only the router: each league's own matcher holds the rule, so
        # no caller can reintroduce the cross-series bind.
        assert not _one_league(OREILLY_CAMS[0], "nascar-cup", [CUP]).is_matched
        assert not _one_league(CUP_QUALIFYING, "nascar-xfinity", [OREILLY]).is_matched
        assert not _one_league(LANGLEY, "nascar-xfinity", [OREILLY]).is_matched
        assert not _one_league(LANGLEY, "nascar-cup", [CUP]).is_matched

    @pytest.mark.parametrize("order", list(permutations(SHARED_WEEKEND)))
    def test_event_name_without_a_series_word_still_matches(self, order):
        route = _router(SHARED_WEEKEND, order)
        cup = route("NASCAR: YellaWood 500 (2026-10-25 14:00:00) [1080p]")
        assert cup.is_matched and cup.event.id == "5631" and not cup.time_only
        oreilly = route("NASCAR: The Progress Group 250 (2026-10-24 15:30:00) [1080p]")
        assert oreilly.is_matched and oreilly.event.id == "5664" and not oreilly.time_only


class TestSponsorNamedRace:
    """Martinsville 2026 as scheduled: the Cup race is the "Xfinity 500" and
    the O'Reilly race starts 75 minutes after this stream's time."""

    CUP_XFINITY_500 = _event(
        "5632",
        "nascar-cup",
        "Xfinity 500",
        [
            RacingSession("fp1", "Practice", datetime(2026, 10, 31, 17, 0, tzinfo=UTC)),
            RacingSession("qualifying", "Qualifying", datetime(2026, 10, 31, 18, 5, tzinfo=UTC)),
            RacingSession("race", "Race", datetime(2026, 11, 1, 19, 0, tzinfo=UTC)),
        ],
        track="Martinsville Speedway",
    )
    OREILLY_250 = _event(
        "5665",
        "nascar-xfinity",
        "National Debt Relief 250",
        [
            RacingSession("fp1", "Practice", datetime(2026, 10, 30, 19, 0, tzinfo=UTC)),
            RacingSession("qualifying", "Qualifying", datetime(2026, 10, 30, 20, 5, tzinfo=UTC)),
            RacingSession("race", "Race", datetime(2026, 10, 31, 20, 0, tzinfo=UTC)),
        ],
        track="Martinsville Speedway",
    )
    WEEKEND = {"nascar-cup": [CUP_XFINITY_500], "nascar-xfinity": [OREILLY_250]}

    @pytest.mark.parametrize("order", list(permutations(WEEKEND)))
    @pytest.mark.parametrize(
        "stream",
        [
            "NASCAR: Xfinity 500 (2026-10-31 14:45:00) [1080p]",
            "NASCAR Cup Series Qualifying: Xfinity 500 (2026-10-31 14:45:00) [1080p]",
        ],
    )
    def test_the_cup_race_named_for_the_sponsor_stays_on_cup(self, order, stream):
        outcome = _router(self.WEEKEND, order, target=date(2026, 10, 31))(stream)
        assert outcome.is_matched and outcome.event.id == "5632"


class TestThreeSeries:
    @pytest.mark.parametrize("order", list(permutations(THREE_SERIES)))
    @pytest.mark.parametrize(
        ("stream", "event_id"),
        [
            # 11:05 ET sits inside O'Reilly AND truck qualifying: time cannot choose.
            ("NASCAR Xfinity Series Qualifying (2026-10-24 11:05:00) [1080p]", "5664"),
            ("NASCAR Craftsman Truck Series Qualifying (2026-10-24 11:05:00) [1080p]", "9001"),
            ("NASCAR Trucks: Qualifying (2026-10-24 11:05:00)", "9001"),
            ("NASCAR Truck Series - Race (2026-10-24 19:00:00)", "9001"),
            (OREILLY_CAMS[0], "5664"),
            (CUP_QUALIFYING, "5631"),
        ],
    )
    def test_series_word_chooses_the_league(self, order, stream, event_id):
        outcome = _router(THREE_SERIES, order)(stream)
        assert outcome.is_matched and outcome.event.id == event_id

    def test_named_series_with_no_event_does_not_fall_to_another(self):
        # Truck stream, no truck event that weekend: nothing, not O'Reilly's
        # qualifying that shares its hour.
        outcome = _router(SHARED_WEEKEND, list(THREE_SERIES))(
            "NASCAR Craftsman Truck Series Qualifying (2026-10-24 11:05:00) [1080p]"
        )
        assert not outcome.is_matched
        assert outcome.failed_reason == FailedReason.NO_RACING_MATCH


class TestBareNascarWithOneEvent:
    """Rule 2 pinned: with one NASCAR event covering the day, the umbrella
    word binds through the event's own names and never through the clock."""

    ONLY_CUP = {"nascar-cup": [CUP]}
    SUNDAY = date(2026, 10, 25)

    def test_track_name_is_a_name_match(self):
        outcome = _router(self.ONLY_CUP, list(THREE_SERIES), target=self.SUNDAY)(
            "NASCAR Race Talladega (2026-10-25 14:00:00) [1080p]"
        )
        assert outcome.is_matched and outcome.event.id == "5631"
        assert not outcome.time_only

    def test_time_alone_is_not_enough(self):
        outcome = _router(self.ONLY_CUP, list(THREE_SERIES), target=self.SUNDAY)(
            "NASCAR Race (2026-10-25 14:00:00) [1080p]"
        )
        assert not outcome.is_matched
        assert outcome.failed_reason == FailedReason.NO_RACING_MATCH

    def test_series_word_and_time_is_enough(self):
        outcome = _router(self.ONLY_CUP, list(THREE_SERIES), target=self.SUNDAY)(
            "NASCAR Cup Series (2026-10-25 14:00:00) [1080p]"
        )
        assert outcome.is_matched and outcome.event.id == "5631"
        assert outcome.time_only


class TestStrongestEvidenceAcrossLeagues:
    def test_a_name_match_beats_an_earlier_time_only_match(self):
        # No NASCAR series word, a session word, and a time both events cover.
        # f1 sorts first and accepts on time; the IndyCar event is named.
        indy = _event(
            "77",
            "indycar",
            "Java House Monterey 200",
            [RacingSession("qualifying", "Qualifying", datetime(2026, 9, 12, 14, 0, tzinfo=UTC))],
            track="Laguna Seca",
        )
        by_league = {"f1": [SPANISH_GP], "indycar": [indy]}
        stream = "Qualifying: Java House Monterey 200 @ 12 Sep 10:00 AM ET"
        assert _one_league(stream, "f1", [SPANISH_GP], target=date(2026, 9, 12)).time_only
        for order in permutations(by_league):
            outcome = _router(by_league, order, target=date(2026, 9, 12))(stream)
            assert outcome.is_matched and outcome.event.id == "77"
            assert not outcome.time_only

    def test_two_time_only_matches_resolve_the_same_way_in_any_order(self):
        indy = _event(
            "77",
            "indycar",
            "Java House Monterey 200",
            [RacingSession("qualifying", "Qualifying", datetime(2026, 9, 12, 14, 0, tzinfo=UTC))],
            track="Laguna Seca",
        )
        by_league = {"f1": [SPANISH_GP], "indycar": [indy]}
        picks = set()
        for order in permutations(by_league):

            class _Recording(_NoCache):
                def __init__(self):
                    self.writes = []

                def set(self, **kwargs):
                    self.writes.append(kwargs["event_id"])

            cache = _Recording()
            outcome = _router(by_league, order, target=date(2026, 9, 12), cache=cache)(
                "Qualifying @ 12 Sep 10:00 AM ET"
            )
            assert outcome.is_matched and outcome.time_only
            # The cache holds the match that was returned, not the last one tried.
            assert cache.writes == [outcome.event.id]
            picks.add(outcome.event.id)
        assert len(picks) == 1


class TestCachedBindFromBeforeTheFix:
    class _Entry:
        user_corrected = False
        match_method = "direct"

        def __init__(self, event: Event, league: str, user_corrected: bool = False):
            from teamarr.consumers.stream_match_cache import event_to_cache_data

            self.cached_data = event_to_cache_data(event)
            self.league = league
            self.event_id = event.id
            self.user_corrected = user_corrected

    class _Cache(_NoCache):
        def __init__(self, entry):
            self.entry = entry
            self.deleted = False

        def get(self, *a, **k):
            return None if self.deleted else self.entry

        def delete(self, *a, **k):
            self.deleted = True

    def test_wrong_series_row_is_dropped_and_rematched(self):
        cache = self._Cache(self._Entry(CUP, "nascar-cup"))
        outcome = _router(SHARED_WEEKEND, list(SHARED_WEEKEND), cache=cache)(OREILLY_CAMS[0])
        assert cache.deleted
        assert outcome.is_matched and outcome.event.id == "5664"
        assert outcome.match_method != MatchMethod.CACHE

    def test_time_only_bare_nascar_row_is_dropped(self):
        cache = self._Cache(self._Entry(OREILLY, "nascar-xfinity"))
        outcome = _router(SHARED_WEEKEND, list(SHARED_WEEKEND), cache=cache)(LANGLEY)
        assert cache.deleted and not outcome.is_matched

    def test_right_series_row_replays(self):
        cache = self._Cache(self._Entry(OREILLY, "nascar-xfinity"))
        outcome = _router(SHARED_WEEKEND, list(SHARED_WEEKEND), cache=cache)(OREILLY_CAMS[0])
        assert not cache.deleted
        assert outcome.match_method == MatchMethod.CACHE and outcome.event.id == "5664"

    def test_a_users_own_pick_stands(self):
        cache = self._Cache(self._Entry(CUP, "nascar-cup", user_corrected=True))
        outcome = _router(SHARED_WEEKEND, list(SHARED_WEEKEND), cache=cache)(OREILLY_CAMS[0])
        assert not cache.deleted
        assert outcome.match_method == MatchMethod.CACHE and outcome.event.id == "5631"


class TestF1Unchanged:
    """The GP-less single-event path (#245) is not NASCAR's and does not move."""

    F1_SATURDAY = date(2026, 9, 12)

    @pytest.mark.parametrize(
        "stream",
        [
            "F1 TV 05: F1 LIVE @ 13 Sep 09:00 AM",
            "F1 TV 05: F1 LIVE @ 12 Sep 10:00 AM",
        ],
    )
    def test_bare_world_feed_still_binds_on_series_and_time(self, stream):
        direct = _one_league(stream, "f1", [SPANISH_GP], target=self.F1_SATURDAY)
        assert direct.is_matched and direct.event.id == "401" and direct.time_only
        for order in permutations(["f1", *THREE_SERIES]):
            routed = _router({"f1": [SPANISH_GP], **THREE_SERIES}, order, target=self.F1_SATURDAY)(
                stream
            )
            assert routed.is_matched and routed.event.id == "401"

    def test_world_feed_outside_every_session_still_fails(self):
        outcome = _one_league(
            "F1 TV 05: F1 LIVE @ 12 Sep 11:00 PM", "f1", [SPANISH_GP], target=self.F1_SATURDAY
        )
        assert not outcome.is_matched

    def test_driver_feed_still_binds(self):
        # "F1 TV 26" names the series and 09:00 on the 13th is the race; with
        # a roster the same stream binds as a race feed instead
        # (tests/matching/test_racing_session_binding.py, untouched).
        stream = "F1 TV 26: [4K] Ferrari: Charles Leclerc @ 13 Sep 09:00 AM"
        direct = _one_league(stream, "f1", [SPANISH_GP], target=self.F1_SATURDAY)
        assert direct.is_matched and direct.event.id == "401"
        for order in permutations(["f1", *THREE_SERIES]):
            routed = _router({"f1": [SPANISH_GP], **THREE_SERIES}, order, target=self.F1_SATURDAY)(
                stream
            )
            assert routed.is_matched and routed.event.id == "401"
