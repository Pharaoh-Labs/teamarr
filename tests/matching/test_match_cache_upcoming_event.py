"""A cached UPCOMING event is served only while this run still lists it (#1264).

The positive cache used to serve today's event only; every upcoming event was
matched again on each run. Serving an upcoming event from the cache saves that
work, and is safe under two conditions the first version did not check:

* the run still lists the event, and the listed object — not the cached copy —
  is what the stream gets, so a rescheduled game shows its new start;
* the stream's own date is the event's day, not the day beside it. The
  matcher's one-day slack lets "(Nov 21)" match the Nov 20 game while that is
  the only one listed; the Nov 21 game must be able to take the stream when it
  is published.

Both sequences below are real: Notre Dame at Ohio State and Penn State at
Wisconsin, men's college hockey, 20-21 Nov 2026. Each run builds a new
TeamMatcher over the same cache table, as a generation does.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.result import MatchMethod
from teamarr.consumers.matching.team_matcher import TeamMatcher
from teamarr.consumers.stream_match_cache import StreamMatchCache
from teamarr.core.types import Event, EventStatus, Team

NY = ZoneInfo("America/New_York")
LEAGUE = "mens-college-hockey"


def _team(name: str, short: str, abbr: str) -> Team:
    return Team(
        id=abbr.lower(),
        provider="espn",
        name=name,
        short_name=short,
        abbreviation=abbr,
        league=LEAGUE,
        sport="hockey",
    )


def _event(eid: str, away: Team, home: Team, start: str) -> Event:
    return Event(
        id=eid,
        provider="espn",
        name=f"{away.name} at {home.name}",
        short_name=f"{away.abbreviation} @ {home.abbreviation}",
        start_time=datetime.fromisoformat(start).replace(tzinfo=NY),
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league=LEAGUE,
        sport="hockey",
    )


NOTRE_DAME = _team("Notre Dame Fighting Irish", "Notre Dame", "ND")
OHIO_STATE = _team("Ohio State Buckeyes", "Ohio State", "OSU")
PENN_STATE = _team("Penn State Nittany Lions", "Penn State", "PSU")
WISCONSIN = _team("Wisconsin Badgers", "Wisconsin", "WIS")

FRIDAY = _event("401923160", NOTRE_DAME, OHIO_STATE, "2026-11-20T18:30")
SATURDAY = _event("401923163", NOTRE_DAME, OHIO_STATE, "2026-11-21T17:00")


class _Runs:
    """One stream matched run after run against a shared cache table."""

    def __init__(self, db_factory, stream_name: str):
        self._db_factory = db_factory
        self._cache = StreamMatchCache(db_factory)
        self._stream_name = stream_name
        self._generation = 0

    def run(self, target: date, listed: list[Event]) -> tuple[str, datetime, MatchMethod]:
        self._generation += 1
        service = MagicMock()
        service.get_team_schedule.return_value = []
        service.get_provider_name.return_value = "espn"
        matcher = TeamMatcher(service, self._cache, db_factory=self._db_factory, days_ahead=3)
        outcome = matcher.match_multi_league(
            classify_stream(self._stream_name),
            [LEAGUE],
            target,
            1,
            1,
            self._generation,
            NY,
            prefetched_events={LEAGUE: list(listed)},
        )
        assert outcome.is_matched
        return outcome.event.id, outcome.event.start_time, outcome.match_method


def test_later_published_game_on_the_streams_date_takes_the_stream(db_factory):
    runs = _Runs(db_factory, "Notre Dame at Ohio State (Nov 21)")

    # Only Friday's game is listed: one day off the stream's date, accepted.
    assert runs.run(date(2026, 11, 19), [FRIDAY])[0] == FRIDAY.id
    # Saturday's game is published. Friday's is still listed, and cached —
    # and must not be served: the stream names Saturday.
    event_id, _, method = runs.run(date(2026, 11, 19), [FRIDAY, SATURDAY])
    assert event_id == SATURDAY.id
    assert method is not MatchMethod.CACHE
    # Saturday's game is on the stream's date and still listed: now a hit.
    assert runs.run(date(2026, 11, 20), [FRIDAY, SATURDAY]) == (
        SATURDAY.id,
        SATURDAY.start_time,
        MatchMethod.CACHE,
    )
    assert runs.run(date(2026, 11, 21), [FRIDAY, SATURDAY])[0] == SATURDAY.id


def test_rescheduled_game_shows_its_new_start_on_the_next_run(db_factory):
    original = _event("401923164", PENN_STATE, WISCONSIN, "2026-11-21T19:00")
    moved = replace(original, start_time=original.start_time + timedelta(days=1))
    runs = _Runs(db_factory, "Penn State at Wisconsin (Nov 21)")

    assert runs.run(date(2026, 11, 19), [original])[:2] == (original.id, original.start_time)
    # Same id, start moved a day. The cached copy still says Nov 21.
    for target in (date(2026, 11, 20), date(2026, 11, 21), date(2026, 11, 22)):
        assert runs.run(target, [moved])[:2] == (moved.id, moved.start_time)


def test_new_start_on_the_same_day_is_served_from_the_listed_event(db_factory):
    later = replace(SATURDAY, start_time=SATURDAY.start_time + timedelta(hours=2))
    runs = _Runs(db_factory, "Notre Dame at Ohio State (Nov 21)")

    runs.run(date(2026, 11, 19), [SATURDAY])

    assert runs.run(date(2026, 11, 20), [later]) == (
        SATURDAY.id,
        later.start_time,
        MatchMethod.CACHE,
    )


def test_upcoming_event_the_run_no_longer_lists_is_matched_again(db_factory):
    runs = _Runs(db_factory, "Notre Dame at Ohio State (Nov 21)")
    runs.run(date(2026, 11, 19), [SATURDAY])

    # Saturday's game left the list (cancelled); Friday's is what remains.
    event_id, _, method = runs.run(date(2026, 11, 20), [FRIDAY])

    assert event_id == FRIDAY.id
    assert method is not MatchMethod.CACHE


@pytest.mark.parametrize("still_listed", [True, False])
def test_single_league_path_asks_the_service_for_the_cached_events_day(db_factory, still_listed):
    cache = StreamMatchCache(db_factory)
    later = replace(SATURDAY, start_time=SATURDAY.start_time + timedelta(hours=2))
    listing = [SATURDAY]

    def _get_events(league, day, cache_only=False):
        return [e for e in listing if e.start_time.astimezone(NY).date() == day]

    def _run(target: date, generation: int):
        service = MagicMock()
        service.get_provider_name.return_value = "espn"
        service.get_team_schedule.return_value = []
        service.get_events.side_effect = _get_events
        matcher = TeamMatcher(service, cache, db_factory=db_factory, days_ahead=3)
        return matcher.match_single_league(
            classify_stream("Notre Dame at Ohio State (Nov 21)"),
            LEAGUE,
            target,
            1,
            1,
            generation,
            NY,
        )

    assert _run(date(2026, 11, 19), 1).event.id == SATURDAY.id

    listing[:] = [later] if still_listed else [FRIDAY]
    outcome = _run(date(2026, 11, 20), 2)

    if still_listed:
        assert outcome.match_method is MatchMethod.CACHE
        assert outcome.event.start_time == later.start_time
    else:
        assert outcome.match_method is not MatchMethod.CACHE
        assert outcome.event.id == FRIDAY.id
