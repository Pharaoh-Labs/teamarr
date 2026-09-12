# ruff: noqa: E501  — captured provider stream names are the fixtures; wrapping them hides the shape
"""Racing streams with no Grand Prix name, and sessions read from mid-name words or the timestamp (#245).

Captured 2026-09-12 from a 121,957-stream install. Three provider shapes carry
no event name at all:

    Apple TV F1 3: AppleTV 3 | Formula 1: Spain: Qualifying - Charles Leclerc (English) @ 12 Sep 10:00AM ET
    F1 TV 26: [4K] Ferrari: Charles Leclerc @ 13 Sep 09:00 AM
    F1 TV 05: F1 LIVE @ 13 Sep 09:00 AM

and the session word, when present, sits mid-name ("Practice #3", "Spain:
Qualifying - …") where the trailing-label scan never saw it. Before this the
first shape bound only through the venue country, the other two not at all,
and every driver-only name fanned out to every non-practice session.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.racing_matcher import RacingMatcher
from teamarr.consumers.matching.result import ResultCategory
from teamarr.consumers.racing_segments import (
    _session_category_from_stream_name,
    expand_racing_segments,
    strip_stream_metadata,
)
from teamarr.core.types import Event, EventStatus, RacingSession, Team, Venue
from teamarr.database.race_feeds import RosterEntry, upsert_roster

NY = ZoneInfo("America/New_York")
TEAM = Team(
    id="event_401",
    provider="espn",
    name="Tag Heuer Spanish Grand Prix",
    short_name="Spanish GP",
    abbreviation="SGP",
    league="f1",
    sport="racing",
)
SESSIONS = [
    RacingSession("fp1", "Practice 1", datetime(2026, 9, 11, 11, 30, tzinfo=UTC)),
    RacingSession("fp2", "Practice 2", datetime(2026, 9, 11, 15, 0, tzinfo=UTC)),
    RacingSession("fp3", "Practice 3", datetime(2026, 9, 12, 10, 30, tzinfo=UTC)),
    RacingSession("qualifying", "Qualifying", datetime(2026, 9, 12, 14, 0, tzinfo=UTC)),
    RacingSession("race", "Race", datetime(2026, 9, 13, 13, 0, tzinfo=UTC)),
]
SPANISH_GP = Event(
    id="401",
    provider="espn",
    name="Tag Heuer Spanish Grand Prix",
    short_name="Spanish GP",
    start_time=SESSIONS[0].start_time,
    home_team=TEAM,
    away_team=TEAM,
    status=EventStatus(state="scheduled"),
    league="f1",
    sport="racing",
    venue=Venue(name="Madring", city="Madrid", country="Spain"),
    circuit_name="Madring",
    sessions=SESSIONS,
)
ITALIAN_GP = Event(
    id="402",
    provider="espn",
    name="Pirelli Italian Grand Prix",
    short_name="Italian GP",
    start_time=datetime(2026, 9, 4, 10, 30, tzinfo=UTC),
    home_team=TEAM,
    away_team=TEAM,
    status=EventStatus(state="final"),
    league="f1",
    sport="racing",
    venue=Venue(name="Monza", city="Monza", country="Italy"),
    circuit_name="Monza",
    sessions=[RacingSession("race", "Race", datetime(2026, 9, 6, 13, 0, tzinfo=UTC))],
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
    def __init__(self, events):
        self._events = events

    def get_provider_name(self, league):
        return "espn"

    def get_events(self, league, target_date, cache_only=False):
        return self._events


@pytest.fixture
def feeds_db():
    schema = open("teamarr/database/schema.sql").read()
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS race_feeds \(.*?\n\);", schema, re.S).group(0)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(ddl)
    upsert_roster(conn, "f1", [RosterEntry("Charles Leclerc", "C. Leclerc", "LEC")])

    class Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return conn

        def __exit__(self, *exc):
            return False

    return Factory()


def _match(stream: str, events=(SPANISH_GP,), db_factory=None):
    classified = classify_stream(stream, "event", None, None, None, event_league_sport="racing")
    matcher = RacingMatcher(_Service(list(events)), _NoCache(), db_factory=db_factory)
    return matcher.match(classified, "f1", date(2026, 9, 12), 1, 1, 1, NY), classified


def _sessions_for(stream: str, classified, event=SPANISH_GP) -> list[str]:
    norm = classified.normalized
    match = {
        "stream": {"name": stream},
        "event": event,
        "stream_date": norm.extracted_date.isoformat() if norm.extracted_date else None,
        "stream_time": norm.extracted_time.strftime("%H:%M:%S") if norm.extracted_time else None,
        "stream_tz": norm.extracted_tz,
    }
    return [m["segment"] for m in expand_racing_segments([match], None, "America/New_York")]


class TestSessionWordsMidName:
    @pytest.mark.parametrize(
        ("stream", "category"),
        [
            (
                "TSN+ 04: Formula 1 On-Board Camera: Charles Leclerc - Spanish Grand Prix Practice #3 @ 12 Sep 06:20 AM ET",
                "fp3",
            ),
            (
                "Apple TV F1 3: AppleTV 3 | Formula 1: Spain: Qualifying - Charles Leclerc (English) @ 12 Sep 10:00AM ET",
                "qualifying",
            ),
            (
                "Apple TV F1 9: AppleTV 9 | Formula 1: Spain: Practice 1 - Main Broadcast (English) (UHD) @ 11 Sep 07:30AM ET",
                "fp1",
            ),
            ("NEXT: SINGAPORE: SPRINT: Sat 3 Oct 4:00 EDT (US)", "sprint"),
            ("Formula 1 Sprint Qualifying - Qatar Grand Prix", "sprint_qualifying"),
            # No session word: "Race" alone is deliberately not a mid-name signal.
            ("F1 TV 26: [4K] Ferrari: Charles Leclerc @ 13 Sep 09:00 AM", None),
            ("F1 TV 01: [4K] 2613 Spanish GP - Pre-Race Show @ 13 Sep 07:50 AM", None),
        ],
    )
    def test_category(self, stream, category):
        assert _session_category_from_stream_name(stream) == category

    def test_trailing_label_shapes_still_work(self):
        # The pre-existing NASCAR/TSN+ convention, now with metadata behind it.
        assert (
            _session_category_from_stream_name("NASCAR Cup Series Qualifying @ 12 Sep 5:00 PM ET")
            == "qualifying"
        )
        assert (
            _session_category_from_stream_name(
                "AU (STAN 36) | Free Practice 3: 6 Hours of Sao Paulo WEC 2026 (2026-09-12 10:20:00)"
            )
            == "fp3"
        )

    def test_metadata_strip_is_detection_only(self):
        assert (
            strip_stream_metadata("X - Practice #3 @ 12 Sep 06:20 AM ET [1080p] (English)")
            == "X - Practice #3"
        )


class TestTimestampFallback:
    def test_driver_only_name_lands_on_the_session_its_time_points_at(self):
        stream = "F1 TV 26: [4K] Ferrari: Charles Leclerc @ 13 Sep 09:00 AM"
        classified = classify_stream(stream, "event", None, None, None, event_league_sport="racing")
        assert _sessions_for(stream, classified) == ["race"]

    def test_stream_tz_is_honoured_over_the_group_tz(self):
        # 06:20 AM ET = 10:20 UTC, ten minutes before FP3 — not qualifying.
        stream = "TSN+ 02: Formula 1 Bonus Pit Lane - Spanish Grand Prix @ 12 Sep 06:20 AM ET"
        classified = classify_stream(stream, "event", None, None, None, event_league_sport="racing")
        assert _sessions_for(stream, classified) == ["fp3"]

    def test_no_time_keeps_the_fan_out(self):
        stream = "Sky Sports F1 HD"
        classified = classify_stream(stream, "event", None, None, None, event_league_sport="racing")
        assert _sessions_for(stream, classified) == ["qualifying", "race"]

    def test_time_far_from_every_session_keeps_the_fan_out(self):
        stream = "F1 TV 99: Ferrari: Charles Leclerc @ 13 Sep 02:00 AM"
        classified = classify_stream(stream, "event", None, None, None, event_league_sport="racing")
        assert _sessions_for(stream, classified) == ["qualifying", "race"]


class TestEvidenceOnTheSingleEventPath:
    def test_driver_name_binds_a_gp_less_stream_when_feeds_are_configured(self, feeds_db):
        result, _ = _match(
            "F1 TV 26: [4K] Ferrari: Charles Leclerc @ 13 Sep 09:00 AM", db_factory=feeds_db
        )
        assert result.category is ResultCategory.MATCHED
        assert result.event is SPANISH_GP

    def test_without_feeds_the_same_stream_binds_by_timestamp(self):
        # "F1 TV" is series evidence and 09:00 AM ET on race day sits inside
        # the race window, so the timed path carries it even with no roster.
        result, _ = _match("F1 TV 26: [4K] Ferrari: Charles Leclerc @ 13 Sep 09:00 AM")
        assert result.category is ResultCategory.MATCHED

    def test_bare_world_feed_binds_by_timestamp(self):
        result, _ = _match("F1 TV 05: F1 LIVE @ 13 Sep 09:00 AM")
        assert result.category is ResultCategory.MATCHED

    def test_country_shape_binds_through_the_venue(self):
        result, _ = _match(
            "Apple TV F1 9: AppleTV 9 | Formula 1: Spain: Qualifying - Main Broadcast (English) (UHD) @ 12 Sep 10:00AM ET"
        )
        assert result.category is ResultCategory.MATCHED

    def test_placeholder_rows_never_match(self, feeds_db):
        result, _ = _match("Apple TV F1 1: NO EVENT", db_factory=feeds_db)
        assert result.category is not ResultCategory.MATCHED

    def test_series_evidence_without_a_time_in_a_session_still_fails(self, feeds_db):
        # "F1 LIVE" at 02:00 AM ET race day: series named, nothing airing → no bind.
        result, _ = _match("F1 TV 05: F1 LIVE @ 13 Sep 02:00 AM", db_factory=feeds_db)
        assert result.category is not ResultCategory.MATCHED

    def test_two_covering_events_defer_to_name_scores(self, feeds_db):
        # Evidence is never a selector: with two events covering the date the
        # GP-less stream has nothing to choose by and must not pick one.
        second = Event(
            **{
                **SPANISH_GP.__dict__,
                "id": "403",
                "name": "Other Grand Prix",
                "short_name": "Other GP",
            }
        )
        result, _ = _match(
            "F1 TV 26: [4K] Ferrari: Charles Leclerc @ 13 Sep 09:00 AM",
            events=(SPANISH_GP, second),
            db_factory=feeds_db,
        )
        assert result.category is not ResultCategory.MATCHED
