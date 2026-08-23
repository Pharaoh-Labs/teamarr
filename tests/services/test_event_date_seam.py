"""Date membership is decided ONCE, at the service seam (#590).

Providers return ±1-day supersets; `sports_data.get_events` filters them
through the user-local day window. These tests pin:

- `user_day_window`: user-tz day → UTC interval, DST-safe
- `event_intersects`: pure instant math over sessions/segments/start + tail
- the seam itself: superset in, exact user-day slate out, filtered result
  cached (the #588 boxing case end-to-end)
"""

import contextlib
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from teamarr.core import Event, EventStatus, RacingSession, Team
from teamarr.services.sports_data import SportsDataService
from teamarr.utilities.event_dates import event_intersects, user_day_window

NY = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _ny_user(monkeypatch):
    monkeypatch.setattr("teamarr.utilities.tz.get_user_timezone", lambda: NY)


def _team(name: str) -> Team:
    return Team(
        id=name.lower(),
        provider="tsdb",
        name=name,
        short_name=name,
        abbreviation=name[:3].upper(),
        league="boxing",
        sport="boxing",
    )


def _event(event_id: str, start: datetime, **kwargs) -> Event:
    return Event(
        id=event_id,
        provider="tsdb",
        name=f"Event {event_id}",
        short_name=f"E{event_id}",
        start_time=start,
        home_team=_team("Romero"),
        away_team=_team("Lopez"),
        status=EventStatus(state="scheduled"),
        league="boxing",
        sport="boxing",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# user_day_window
# ---------------------------------------------------------------------------


def test_day_window_is_user_local():
    start, end = user_day_window(date(2026, 8, 22))
    assert start == datetime(2026, 8, 22, 4, 0, tzinfo=UTC)  # EDT = UTC-4
    assert end == datetime(2026, 8, 23, 4, 0, tzinfo=UTC)


def test_day_window_handles_dst():
    # US spring-forward 2026-03-08: a 23-hour day
    start, end = user_day_window(date(2026, 3, 8))
    assert end - start == timedelta(hours=23)
    # US fall-back 2026-11-01: a 25-hour day
    start, end = user_day_window(date(2026, 11, 1))
    assert end - start == timedelta(hours=25)


# ---------------------------------------------------------------------------
# event_intersects
# ---------------------------------------------------------------------------


def test_utc_boundary_event_belongs_to_user_day():
    """The #588 case: Sat 9pm ET fight is Sunday in UTC — it's Saturday."""
    fight = _event("2528767", datetime(2026, 8, 23, 1, 0, tzinfo=UTC))
    assert event_intersects(fight, user_day_window(date(2026, 8, 22)))
    assert not event_intersects(fight, user_day_window(date(2026, 8, 24)))


def test_far_utc_event_is_not_on_user_day():
    """Neither raw calendar matches the user's: Tokyo Sat morning card.

    Sat 10:00 JST = Fri 01:00Z = THU 9pm ET — dateEvent (Fri) and
    dateEventLocal (Sat) both miss the New York user's Thursday.
    """
    tokyo_card = _event("t1", datetime(2026, 8, 21, 1, 0, tzinfo=UTC))
    assert event_intersects(tokyo_card, user_day_window(date(2026, 8, 20)))
    assert not event_intersects(tokyo_card, user_day_window(date(2026, 8, 22)))


def test_sessions_span_all_their_days():
    """Race weekend: practice Friday, race Sunday — belongs to Fri, Sat, Sun."""
    weekend = _event(
        "5620",
        datetime(2026, 8, 21, 22, 0, tzinfo=UTC),
        sessions=[
            RacingSession(
                code="practice",
                name="Practice",
                start_time=datetime(2026, 8, 21, 22, 0, tzinfo=UTC),
            ),
            RacingSession(
                code="race", name="Race", start_time=datetime(2026, 8, 23, 18, 30, tzinfo=UTC)
            ),
        ],
    )
    for day in (date(2026, 8, 21), date(2026, 8, 22), date(2026, 8, 23)):
        assert event_intersects(weekend, user_day_window(day)), day
    assert not event_intersects(weekend, user_day_window(date(2026, 8, 20)))


def test_late_start_spills_into_next_day_via_tail():
    """A 23:30 ET start still counts as (late) viewing on the next day."""
    late_game = _event("lg", datetime(2026, 8, 23, 3, 30, tzinfo=UTC))  # 23:30 EDT Aug 22
    assert event_intersects(late_game, user_day_window(date(2026, 8, 22)))
    assert event_intersects(late_game, user_day_window(date(2026, 8, 23)))


# ---------------------------------------------------------------------------
# The seam in SportsDataService.get_events
# ---------------------------------------------------------------------------


class _FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)

    @contextlib.contextmanager
    def lock_key(self, key):
        yield


class _SupersetProvider:
    """Provider honouring the #590 contract: over-returns, never filters."""

    def __init__(self, events):
        self.events = events

    @property
    def name(self):
        return "fake"

    def supports_league(self, league):
        return True

    def get_events(self, league, target_date):
        return list(self.events)


def _service(events) -> SportsDataService:
    service = SportsDataService(providers=[])
    service._cache = _FakeCache()
    service.add_provider(_SupersetProvider(events))
    return service


def test_seam_filters_provider_superset_to_user_day():
    saturday_fight = _event("sat", datetime(2026, 8, 23, 1, 0, tzinfo=UTC))  # Sat 9pm ET
    sunday_fight = _event("sun", datetime(2026, 8, 23, 23, 0, tzinfo=UTC))  # Sun 7pm ET
    service = _service([saturday_fight, sunday_fight])

    assert [e.id for e in service.get_events("boxing", date(2026, 8, 22))] == ["sat"]
    assert [e.id for e in service.get_events("boxing", date(2026, 8, 23))] == ["sun"]


def test_seam_caches_the_filtered_slate():
    saturday_fight = _event("sat", datetime(2026, 8, 23, 1, 0, tzinfo=UTC))
    off_day = _event("off", datetime(2026, 8, 26, 1, 0, tzinfo=UTC))
    service = _service([saturday_fight, off_day])

    service.get_events("boxing", date(2026, 8, 22))

    (cached,) = service._cache.store.values()
    assert [e["id"] for e in cached] == ["sat"]


def test_cache_key_carries_tz_and_namespace_version():
    service = _service([])
    service.get_events("boxing", date(2026, 8, 22))

    (key,) = service._cache.store.keys()
    assert key == "events_v2:boxing:2026-08-22:America/New_York"
