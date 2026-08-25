"""The parallel event prefetch must answer exactly as the serial one did.

`_prefetch_events` fans the (league x date) window out across threads. The
window is ~11 dates deep for every searched league, so serializing it was the
longest stretch of dead wall-clock time in a run — but the planning rules it
applies (which dates may hit the API, which are cache-only, which are already
answered by `shared_events`) are subtle enough that the fan-out is only safe if
it produces the same three things as before: the same per-league event lists,
the same `shared_events` state, and the same set of service calls.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

import pytest

from teamarr.consumers.matching.constants import MATCH_WINDOW_DAYS
from teamarr.consumers.matching.matcher import StreamMatcher
from teamarr.core import Event, Team

DAYS_AHEAD = 3
LEAGUES = [f"lg{i}" for i in range(12)]
TSDB_LEAGUES = {"lg3", "lg7"}


def _event(league: str, day: date, i: int) -> Event:
    def team(side: str) -> Team:
        return Team(
            id=f"{league}-{i}-{side}", provider="espn", name=f"{league} {side}",
            short_name=side, abbreviation=side[:3], league=league, sport="x",
        )

    return Event(
        id=f"{league}-{day.isoformat()}-{i}", provider="espn", name="g", short_name="g",
        start_time=datetime(day.year, day.month, day.day, 20, tzinfo=UTC),
        home_team=team("home"), away_team=team("away"), status="scheduled",
        league=league, sport="x",
    )


class _FakeService:
    """Records every call; returns a deterministic, league/date-derived result."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, date, bool]] = []
        self._lock = threading.Lock()

    def get_provider_name(self, league: str) -> str:
        return "tsdb" if league in TSDB_LEAGUES else "espn"

    def get_events(self, league: str, target_date: date, cache_only: bool = False):
        with self._lock:
            self.calls.append((league, target_date, cache_only))
        if hash((league, target_date.toordinal())) % 3 == 0:
            return [_event(league, target_date, k) for k in range(2)]
        return []


def _serial_reference(service, shared, include, target_date):
    """Verbatim port of the pre-fan-out loop."""
    prefetched: dict[str, list[Event]] = {}
    for league in LEAGUES:
        league_events: list[Event] = []
        is_tsdb = service.get_provider_name(league) == "tsdb"
        is_group_league = league in include
        for offset in range(-MATCH_WINDOW_DAYS, DAYS_AHEAD + 1):
            fetch_date = target_date + timedelta(days=offset)
            shared_key = f"{league}:{fetch_date.isoformat()}"
            if (is_tsdb and not is_group_league) or offset < -1:
                cache_only = True
            else:
                cache_only = not is_group_league
            if shared is not None and shared_key in shared:
                shared_events, was_cache_only = shared[shared_key]
                if shared_events or not was_cache_only or not is_group_league:
                    league_events.extend(shared_events)
                    continue
            events = service.get_events(league, fetch_date, cache_only=cache_only)
            league_events.extend(events)
            if shared is not None:
                shared[shared_key] = (events, cache_only)
        if league_events:
            prefetched[league] = league_events
    return prefetched


def _matcher(service, shared, include):
    m = StreamMatcher.__new__(StreamMatcher)
    m._service = service
    m._search_leagues = LEAGUES
    m._include_leagues = set(include)
    m._shared_events = shared
    m._days_ahead = DAYS_AHEAD
    m._prefetched_events = None
    return m


def _seed(target_date: date) -> dict:
    """A shared_events map as a prior group in the same run would leave it."""
    return {
        f"{lg}:{target_date.isoformat()}": ([_event(lg, target_date, 99)], False)
        for lg in LEAGUES[:6]
    }


def _ids(prefetched):
    return {lg: [e.id for e in evs] for lg, evs in prefetched.items()}


def _shared_ids(shared):
    return {k: ([e.id for e in v[0]], v[1]) for k, v in shared.items()}


@pytest.mark.parametrize(
    ("label", "include", "seed_shared"),
    [
        ("cold run, some leagues subscribed", set(LEAGUES[:4]), False),
        ("warm shared_events from a prior group", set(LEAGUES[:4]), True),
        ("every league subscribed", set(LEAGUES), False),
        ("no league subscribed", set(), False),
    ],
)
def test_matches_the_serial_prefetch(label, include, seed_shared):
    target_date = date(2026, 8, 25)

    serial_service = _FakeService()
    serial_shared = _seed(target_date) if seed_shared else {}
    expected = _serial_reference(serial_service, serial_shared, include, target_date)

    parallel_service = _FakeService()
    parallel_shared = _seed(target_date) if seed_shared else {}
    matcher = _matcher(parallel_service, parallel_shared, include)
    matcher._prefetch_events(target_date)

    assert _ids(matcher._prefetched_events) == _ids(expected), label
    assert _shared_ids(parallel_shared) == _shared_ids(serial_shared), label
    assert sorted(parallel_service.calls) == sorted(serial_service.calls), label


def test_tsdb_leagues_are_never_fetched_concurrently():
    """TSDB's client serializes on a rate limiter that sleeps under its lock, so
    concurrent callers would queue inside that sleep — all the cost of threads
    and none of the overlap. Its fetches must stay on the calling thread."""
    target_date = date(2026, 8, 25)

    class _ThreadRecordingService(_FakeService):
        def __init__(self):
            super().__init__()
            self.threads_by_league: dict[str, set[str]] = {}

        def get_events(self, league, target_date, cache_only=False):
            with self._lock:
                self.threads_by_league.setdefault(league, set()).add(
                    threading.current_thread().name
                )
            return super().get_events(league, target_date, cache_only=cache_only)

    service = _ThreadRecordingService()
    matcher = _matcher(service, {}, set(LEAGUES))
    matcher._prefetch_events(target_date)

    main = threading.current_thread().name
    for league in TSDB_LEAGUES:
        assert service.threads_by_league[league] == {main}, (
            f"{league} was fetched off the calling thread"
        )


def test_a_failing_league_does_not_lose_the_batch():
    """One league's outage must not cost every other league its events."""
    target_date = date(2026, 8, 25)

    class _FlakyService(_FakeService):
        def get_events(self, league, target_date, cache_only=False):
            if league == "lg1" and not cache_only:
                raise RuntimeError("provider exploded")
            return super().get_events(league, target_date, cache_only=cache_only)

    matcher = _matcher(_FlakyService(), {}, set(LEAGUES))
    matcher._prefetch_events(target_date)

    healthy = [lg for lg in LEAGUES if lg != "lg1"]
    assert any(lg in matcher._prefetched_events for lg in healthy)
