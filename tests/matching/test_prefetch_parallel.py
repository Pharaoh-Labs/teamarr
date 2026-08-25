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


def _flaky(broken_league: str, *, only_live: bool = True):
    """A service whose fetches for one league raise."""

    class _FlakyService(_FakeService):
        def get_events(self, league, target_date, cache_only=False):
            if league == broken_league and (not cache_only or not only_live):
                raise RuntimeError("provider exploded")
            return super().get_events(league, target_date, cache_only=cache_only)

    return _FlakyService()


def test_a_failing_league_does_not_lose_the_batch():
    """One league's outage must not cost every other league its events."""
    target_date = date(2026, 8, 25)

    matcher = _matcher(_flaky("lg1"), {}, set(LEAGUES))
    matcher._prefetch_events(target_date)

    healthy = [lg for lg in LEAGUES if lg != "lg1"]
    assert any(lg in matcher._prefetched_events for lg in healthy)


def test_a_failed_fetch_is_never_published_to_shared_events():
    """A failure is an absence of knowledge, not an empty day.

    `shared_events` treats an empty-but-freshly-fetched entry as authoritative
    (`shared_events or not was_cache_only or ...`), so publishing a failed
    slot's empty list would silently blank that league/date for every later
    group in the run — the silent-missing-match failure mode of #599/#601 —
    instead of letting them retry.

    The poisoning condition is precisely "empty AND not cache_only", so that
    is what this asserts. An empty cache-only entry is fine and pre-existing:
    the reuse check already rejects it for any group that needs the league.
    """
    target_date = date(2026, 8, 25)
    shared: dict = {}

    matcher = _matcher(_flaky("lg1"), shared, set(LEAGUES))
    matcher._prefetch_events(target_date)

    poisoned = [
        key
        for key, (events, was_cache_only) in shared.items()
        if key.startswith("lg1:") and not events and not was_cache_only
    ]
    assert not poisoned, (
        f"failed fetches were cached as authoritative empty days: {poisoned}"
    )
    # ...and the leagues that answered are still cached as normal.
    assert any(k.startswith("lg2:") for k in shared)


def test_a_later_group_retries_a_league_whose_fetch_failed():
    """The point of not publishing: the next group gets a real fetch."""
    target_date = date(2026, 8, 25)
    shared: dict = {}

    _matcher(_flaky("lg1"), shared, set(LEAGUES))._prefetch_events(target_date)

    healthy = _FakeService()
    second = _matcher(healthy, shared, set(LEAGUES))
    second._prefetch_events(target_date)

    retried = [c for c in healthy.calls if c[0] == "lg1"]
    assert retried, "lg1 was never retried — the failure was cached after all"
    assert "lg1" in second._prefetched_events


def test_a_failing_tsdb_league_does_not_kill_the_prefetch():
    """TSDB fetches run inline, and are the flakiest call we make.

    They must be isolated exactly like the concurrent ones — letting a
    rate-limited TSDB league propagate would take down the prefetch for every
    other league in the run.
    """
    target_date = date(2026, 8, 25)
    broken = next(iter(TSDB_LEAGUES))
    shared: dict = {}

    # Subscribed, so TSDB actually fetches rather than going cache-only.
    matcher = _matcher(_flaky(broken, only_live=False), shared, set(LEAGUES))
    matcher._prefetch_events(target_date)  # must not raise

    healthy = [lg for lg in LEAGUES if lg not in TSDB_LEAGUES]
    assert any(lg in matcher._prefetched_events for lg in healthy)
    assert not [k for k in shared if k.startswith(f"{broken}:")]


def test_a_failing_cache_only_fetch_is_isolated_too():
    """Cache-only slots run inline as well and get the same treatment."""
    target_date = date(2026, 8, 25)
    shared: dict = {}

    # No league subscribed -> every slot is cache-only and runs inline.
    matcher = _matcher(_flaky("lg1", only_live=False), shared, set())
    matcher._prefetch_events(target_date)  # must not raise

    assert not [k for k in shared if k.startswith("lg1:")]


def test_the_candidate_list_is_shared_and_immutable():
    """Every stream in a batch gets the same object back, and cannot edit it.

    `TeamMatcher._prefetched_candidates` memoizes the flattened
    `[(league, event)]` list so it is built once per batch rather than once per
    stream. That makes it shared state: a caller that mutated it would corrupt
    the candidates of every stream matched after it. Returning a tuple turns
    that into a TypeError instead of a quietly wrong guide.
    """
    from teamarr.consumers.matching.team_matcher import TeamMatcher

    target_date = date(2026, 8, 25)
    matcher = _matcher(_FakeService(), {}, set(LEAGUES))
    matcher._prefetch_events(target_date)

    tm = TeamMatcher(service=None, cache=None, db_factory=None)
    first = tm._prefetched_candidates(matcher._prefetched_events, LEAGUES)
    second = tm._prefetched_candidates(matcher._prefetched_events, LEAGUES)

    assert first is second, "the candidate list was rebuilt instead of memoized"
    assert isinstance(first, tuple)
    with pytest.raises(AttributeError):
        first.append(("lg0", None))  # type: ignore[attr-defined]


def test_a_new_prefetch_invalidates_the_candidate_memo():
    """The memo keys on the prefetch dict's identity, so a fresh prefetch
    (a new dict) must not be served the previous batch's candidates."""
    from teamarr.consumers.matching.team_matcher import TeamMatcher

    target_date = date(2026, 8, 25)
    tm = TeamMatcher(service=None, cache=None, db_factory=None)

    first_matcher = _matcher(_FakeService(), {}, set(LEAGUES))
    first_matcher._prefetch_events(target_date)
    first = tm._prefetched_candidates(first_matcher._prefetched_events, LEAGUES)

    second_matcher = _matcher(_FakeService(), {}, set(LEAGUES))
    second_matcher._prefetch_events(target_date + timedelta(days=1))
    second = tm._prefetched_candidates(second_matcher._prefetched_events, LEAGUES)

    assert first is not second
    assert {e.id for _, e in second} != {e.id for _, e in first}
