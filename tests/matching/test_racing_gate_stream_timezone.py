# ruff: noqa: E501  — captured provider stream names are the fixtures; wrapping them hides the shape
"""The racing weekend gate reads a stream's date in the stream's timezone (#1276).

2026 Las Vegas Grand Prix, a New York user. The sessions in UTC and New York:

    FP1         11-20 00:30 UTC   11-19 19:30 ET
    FP2         11-20 04:00 UTC   11-19 23:00 ET
    FP3         11-21 00:30 UTC   11-20 19:30 ET
    Qualifying  11-21 04:00 UTC   11-20 23:00 ET
    Race        11-22 04:00 UTC   11-21 23:00 ET

so in New York the weekend is Nov 19, 20 and 21, and a UK/UTC-dated stream of
the race ("Sun 22 Nov 02:50 UTC") named a day no session falls on. The gate
compared the digits as written with session dates in the user timezone; it
now places the written date and time in the stream's zone first — the zone
code in the name, else the source's Stream Timezone — which is what session
binding already did. Stream names are from a production install's sources
for that weekend.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers import racing_segments
from teamarr.consumers.matching import normalizer
from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.matcher import StreamMatcher
from teamarr.consumers.matching.racing_matcher import RacingMatcher, _gate_date
from teamarr.consumers.matching.result import MatchMethod
from teamarr.consumers.racing_segments import expand_racing_segments
from teamarr.consumers.stream_match_cache import StreamCacheEntry, event_to_cache_data
from teamarr.core.types import Event, EventStatus, RacingSession, Team, Venue

NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
SATURDAY = date(2026, 11, 21)  # the run day; every dated name carries its own


def _grand_prix(event_id: str, name: str, short: str, country: str, sessions: dict) -> Event:
    team = Team(
        id=f"event_{event_id}",
        provider="espn",
        name=name,
        short_name=short,
        abbreviation="GP",
        league="f1",
        sport="racing",
    )
    racing_sessions = [RacingSession(code, code, start) for code, start in sessions.items()]
    return Event(
        id=event_id,
        provider="espn",
        name=name,
        short_name=short,
        start_time=racing_sessions[0].start_time,
        home_team=team,
        away_team=team,
        status=EventStatus(state="scheduled"),
        league="f1",
        sport="racing",
        venue=Venue(name=short, city=short, country=country),
        circuit_name=f"{short} Circuit",
        sessions=racing_sessions,
    )


LAS_VEGAS = _grand_prix(
    "600057449",
    "Heineken Las Vegas Grand Prix",
    "Las Vegas GP",
    "United States",
    {
        "fp1": datetime(2026, 11, 20, 0, 30, tzinfo=UTC),
        "fp2": datetime(2026, 11, 20, 4, 0, tzinfo=UTC),
        "fp3": datetime(2026, 11, 21, 0, 30, tzinfo=UTC),
        "qualifying": datetime(2026, 11, 21, 4, 0, tzinfo=UTC),
        "race": datetime(2026, 11, 22, 4, 0, tzinfo=UTC),
    },
)
QATAR = _grand_prix(
    "600057450",
    "Qatar Airways Qatar Grand Prix",
    "Qatar GP",
    "Qatar",
    {
        "fp1": datetime(2026, 11, 27, 13, 30, tzinfo=UTC),
        "fp2": datetime(2026, 11, 27, 17, 0, tzinfo=UTC),
        "fp3": datetime(2026, 11, 28, 14, 30, tzinfo=UTC),
        "qualifying": datetime(2026, 11, 28, 18, 0, tzinfo=UTC),
        "race": datetime(2026, 11, 29, 16, 0, tzinfo=UTC),
    },
)

RACE_UTC = "LIVE: LAS VEGAS: RACE: Sun 22 Nov 02:50 UTC (UK)"
RACE_EST = "LIVE: LAS VEGAS: RACE: Sat 21 Nov 21:50 EST (US)"
RACE_LONDON = "Sky Sports + 31: F1 Driver Cams Max Verstappen: Onboard @ 22 Nov 02:30 AM London"
FP1_LONDON = "Sky Sports + 31: F1 Driver Cams Max Verstappen: Onboard @ 19 Nov 11:00 PM London"
FP3_LONDON = "Sky Sports + 31: F1 Driver Cams Max Verstappen: Onboard @ 20 Nov 11:00 PM London"
FP2_ET = "Apple TV F1 01: AppleTV 03 | Formula 1: Las Vegas: Practice 2 - Main Broadcast (English) (UHD) @ 19 Nov 11:35 PM ET"


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


class _DictCache(_NoCache):
    """The match cache's get/set/delete contract, in memory."""

    def __init__(self):
        self.rows: dict[tuple, StreamCacheEntry] = {}

    def plant(self, stream: str, event: Event) -> None:
        self.rows[(1, 1, stream)] = StreamCacheEntry(
            event_id=event.id,
            league="f1",
            cached_data=event_to_cache_data(event),
            match_method="direct",
        )

    def get(self, group_id, stream_id, stream_name):
        return self.rows.get((group_id, stream_id, stream_name))

    def set(self, group_id, stream_id, stream_name, event_id, league, cached_data, **k):
        self.rows[(group_id, stream_id, stream_name)] = StreamCacheEntry(
            event_id=event_id,
            league=league,
            cached_data=cached_data,
            match_method=k.get("match_method"),
        )

    def delete(self, group_id, stream_id, stream_name):
        self.rows.pop((group_id, stream_id, stream_name), None)


class _Service:
    def __init__(self, events):
        self._events = list(events)

    def get_provider_name(self, league):
        return "espn"

    def get_events(self, league, target_date, cache_only=False):
        return self._events

    def get_team_schedule(self, *args, **kwargs):
        return []


@pytest.fixture(autouse=True)
def _new_york_user_in_2026(monkeypatch):
    """Pin the two things the fixtures do not carry: the user timezone session
    binding falls back to, and the year a year-less date ("22 Nov") is in."""
    monkeypatch.setattr(racing_segments, "get_user_timezone", lambda: NY)
    monkeypatch.setattr(normalizer, "_infer_year_for_date", lambda m, d: date(2026, m, d))


def _classify(stream: str):
    return classify_stream(stream, "event", None, None, None, event_league_sport="racing")


def _match(stream, source_tz=None, user_tz=NY, events=(LAS_VEGAS, QATAR), cache=None):
    """The real route: StreamMatcher holds the source timezone and hands the
    racing matcher the stream's known zone."""
    matcher = StreamMatcher(
        service=_Service(events),
        db_factory=None,
        group_id=1,
        search_leagues=["f1"],
        user_tz=user_tz,
        generation=1,
        days_ahead=3,
        stream_timezone=source_tz,
    )
    matcher._league_event_types = {"f1": "event"}
    matcher._league_sports = {"f1": "racing"}
    matcher._racing_matcher = RacingMatcher(matcher._service, cache or _NoCache())
    return matcher._match_racing_event(_classify(stream), 1, SATURDAY)


def _sessions(stream, outcome, source_tz=None) -> list[str]:
    """Session channels the matched stream lands on, from the written date,
    time and zone the processor carries on the match — never a converted one."""
    norm = _classify(stream).normalized
    match = {
        "stream": {"name": stream},
        "event": outcome.event,
        "stream_date": norm.extracted_date.isoformat() if norm.extracted_date else None,
        "stream_time": norm.extracted_time.strftime("%H:%M:%S") if norm.extracted_time else None,
        "stream_tz": norm.extracted_tz,
    }
    return [m["segment"] for m in expand_racing_segments([match], None, source_tz)]


def _verdict(stream, source_tz=None, **kwargs):
    outcome = _match(stream, source_tz, **kwargs)
    if not outcome.is_matched:
        return None
    return outcome.event.id, _sessions(stream, outcome, source_tz)


class TestTheIssueStreams:
    def test_utc_dated_race_stream_matches_and_binds_the_race(self):
        # 22 Nov 02:50 UTC is 21 Nov 21:50 in New York — race night.
        assert _verdict(RACE_UTC) == ("600057449", ["race"])

    def test_est_dated_race_stream_matches_as_before(self):
        assert _verdict(RACE_EST) == ("600057449", ["race"])

    def test_london_word_is_not_a_zone(self):
        # "London" is not in the abbreviation list and no source timezone is
        # set: the zone is unknown and the stream is read as it always was.
        assert _classify(RACE_LONDON).normalized.extracted_tz is None
        assert _verdict(RACE_LONDON) is None

    def test_source_timezone_places_the_london_stream(self):
        assert _verdict(RACE_LONDON, "Europe/London") == ("600057449", ["race"])


class TestPracticeNights:
    """Two sessions share each New York evening; the zone picks the right one."""

    def test_first_night_binds_fp1_not_fp2(self):
        # 19 Nov 23:00 London = 18:00 ET, 90 minutes before FP1.
        assert _verdict(FP1_LONDON, "Europe/London") == ("600057449", ["fp1"])

    def test_second_night_binds_fp3_not_qualifying(self):
        assert _verdict(FP3_LONDON, "Europe/London") == ("600057449", ["fp3"])


class TestWhichZone:
    def test_name_zone_wins_over_the_source_timezone(self):
        # Read in Los Angeles, 22 Nov 02:50 is 05:50 on the 22nd in New York —
        # no session that day. The name says UTC, so it is race night.
        assert _verdict(RACE_UTC, "America/Los_Angeles") == ("600057449", ["race"])

    def test_invalid_source_timezone_is_unknown(self):
        assert _verdict(RACE_LONDON, "Mars/Olympus_Mons") is None
        assert _verdict(RACE_EST, "Mars/Olympus_Mons") == ("600057449", ["race"])

    def test_stream_zone_west_of_the_user(self):
        # A London user: FP2 is 04:00 on the 20th there, and the weekend's days
        # are Nov 20, 21 and 22. The ET-dated stream says the 19th.
        outcome = _match(FP2_ET, user_tz=LONDON)
        assert outcome.is_matched and outcome.event.id == "600057449"
        assert _sessions(FP2_ET, outcome) == ["fp2"]

    def test_the_other_weekend_is_not_reached(self):
        # The converted date selects among covering events like any date did.
        outcome = _match(RACE_UTC)
        assert outcome.event.id == "600057449"


class TestDateWithoutTime:
    """A bare date is a whole day in the stream's zone, which straddles two of
    the user's: it cannot be shifted, so it is compared as written (rule 3)."""

    @pytest.mark.parametrize("source_tz", [None, "Europe/London", "Australia/Sydney"])
    def test_bare_date_with_a_source_timezone_is_read_as_written(self, source_tz):
        assert _verdict("F1: Las Vegas Grand Prix Race 22 Nov", source_tz) is None
        assert _verdict("F1: Las Vegas Grand Prix Race 21 Nov", source_tz) == (
            "600057449",
            ["qualifying", "race"],
        )

    def test_bare_date_with_a_zone_code_is_read_as_written(self):
        stream = "F1: Las Vegas Grand Prix Race 22 Nov UTC"
        norm = _classify(stream).normalized
        assert (norm.extracted_date, norm.extracted_time, norm.extracted_tz) == (
            date(2026, 11, 22),
            None,
            "UTC",
        )
        assert _verdict(stream) is None

    def test_gate_date_needs_date_time_and_zone(self):
        timed = _classify(RACE_UTC).normalized
        bare = _classify("F1: Las Vegas Grand Prix Race 22 Nov UTC").normalized
        undated = _classify("Formula 1: Las Vegas Grand Prix").normalized
        assert _gate_date(timed, UTC, NY) == date(2026, 11, 21)
        assert _gate_date(timed, None, NY) == date(2026, 11, 22)
        assert _gate_date(bare, UTC, NY) == date(2026, 11, 22)
        assert _gate_date(undated, UTC, NY) is None


# Captured from origin/dev (09320215) before the change, same events, New York
# user, no source timezone: (stream, matched event, session channels).
UNKNOWN_ZONE_BASELINE = [
    (RACE_LONDON, None, None),
    (FP1_LONDON, "600057449", ["fp2"]),
    (FP3_LONDON, "600057449", ["qualifying"]),
    ("F1 TV 26: [4K] Ferrari: Charles Leclerc @ 21 Nov 11:00 PM", "600057449", ["race"]),
    ("F1 TV 05: F1 LIVE @ 20 Nov 07:30 PM", "600057449", ["fp3"]),
    ("F1 TV 05: F1 LIVE @ 22 Nov 04:00 AM", None, None),
    (
        "CA (TSN+ 011): Formula 1: Las Vegas Grand Prix Qualifying (2026-11-20 22:55:00) [1080p]",
        "600057449",
        ["qualifying"],
    ),
    ("Formula 1: Las Vegas Grand Prix", "600057449", ["qualifying", "race"]),
    ("Formula 1: Las Vegas Grand Prix - Race", "600057449", ["qualifying", "race"]),
    ("F1: Las Vegas Grand Prix Race 22 Nov", None, None),
    ("F1: Las Vegas Grand Prix Race (2026-11-22)", None, None),
    ("F1: Las Vegas Grand Prix Race 21 Nov", "600057449", ["qualifying", "race"]),
    ("Formula 1 Las Vegas Grand Prix - Sun 22 Nov", None, None),
    ("F1 Las Vegas Grand Prix 11/22", None, None),
]


class TestUnknownZoneIsUnchanged:
    @pytest.mark.parametrize(("stream", "event_id", "sessions"), UNKNOWN_ZONE_BASELINE)
    def test_same_verdict_as_before(self, stream, event_id, sessions):
        verdict = _verdict(stream, events=(LAS_VEGAS,))
        assert verdict == (None if event_id is None else (event_id, sessions))


class TestTimedEvidenceReadsTheWrittenInstant:
    """A GP-less world feed binds on series word + a time inside a session
    (#245). The instant is the WRITTEN date and time in the stream's zone —
    not the already-converted gate date read a second time."""

    BARE_FEED = "F1 TV 05: F1 LIVE @ 22 Nov 04:00 AM"

    def test_source_timezone_places_the_instant(self):
        # 22 Nov 04:00 London is the race start. Shifting the converted gate
        # date (21 Nov) again would put it a day early and miss every session.
        assert _verdict(self.BARE_FEED, "Europe/London", events=(LAS_VEGAS,)) == (
            "600057449",
            ["race"],
        )

    def test_name_zone_places_the_instant(self):
        stream = "F1 TV 05: F1 LIVE @ 22 Nov 04:00 AM UTC"
        assert _classify(stream).normalized.extracted_tz == "UTC"
        assert _verdict(stream, events=(LAS_VEGAS,)) == ("600057449", ["race"])

    def test_a_time_far_from_every_session_in_the_stream_zone_does_not_bind(self):
        # 20 Nov 19:30 is FP3 for a New York clock; on a London clock it is
        # five hours before it, so the time is no evidence.
        stream = "F1 TV 05: F1 LIVE @ 20 Nov 07:30 PM"
        assert _verdict(stream, events=(LAS_VEGAS,)) == ("600057449", ["fp3"])
        assert _verdict(stream, "Europe/London", events=(LAS_VEGAS,)) is None


class TestCacheGate:
    def test_row_cached_under_the_converted_date_is_served(self):
        cache = _DictCache()
        first = _match(RACE_LONDON, "Europe/London", cache=cache)
        assert first.is_matched and first.match_method != MatchMethod.CACHE
        assert [e.event_id for e in cache.rows.values()] == ["600057449"]

        second = _match(RACE_LONDON, "Europe/London", cache=cache)
        assert second.match_method == MatchMethod.CACHE
        assert second.event.id == "600057449"
        assert _sessions(RACE_LONDON, second, "Europe/London") == ["race"]

    def test_utc_stream_is_served_from_cache(self):
        cache = _DictCache()
        _match(RACE_UTC, cache=cache)
        assert _match(RACE_UTC, cache=cache).match_method == MatchMethod.CACHE

    def test_cached_row_for_another_event_is_not_served(self):
        cache = _DictCache()
        cache.plant(RACE_LONDON, QATAR)
        outcome = _match(RACE_LONDON, "Europe/London", cache=cache)
        assert outcome.is_matched and outcome.match_method != MatchMethod.CACHE
        assert outcome.event.id == "600057449"

    def test_cached_row_is_not_served_when_the_zone_is_unknown(self):
        # Without a zone the written date (22 Nov) names no New York session
        # day, exactly as before: the row is not replayed and nothing matches.
        cache = _DictCache()
        cache.plant(RACE_LONDON, LAS_VEGAS)
        assert not _match(RACE_LONDON, cache=cache).is_matched

    def test_row_cached_before_the_source_timezone_was_set_still_serves(self):
        cache = _DictCache()
        assert _verdict(FP1_LONDON, cache=cache) == ("600057449", ["fp2"])
        outcome = _match(FP1_LONDON, "Europe/London", cache=cache)
        assert outcome.match_method == MatchMethod.CACHE
        assert _sessions(FP1_LONDON, outcome, "Europe/London") == ["fp1"]


class TestDirectCallers:
    """RacingMatcher.match without the threaded zone still reads the name's."""

    def test_name_zone_without_a_threaded_zone(self):
        matcher = RacingMatcher(_Service([LAS_VEGAS]), _NoCache())
        outcome = matcher.match(_classify(RACE_UTC), "f1", SATURDAY, 1, 1, 1, NY)
        assert outcome.is_matched and outcome.event.id == "600057449"
