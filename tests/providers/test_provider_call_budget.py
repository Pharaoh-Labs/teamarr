"""Per-run provider fetch-count regression guard (#285, teamarrv2-ddpi.5).

Call-volume regressions ship silently: #254's per-event refetch made 2,027
summary calls per run instead of ~289, and the pre-t82y miss storms fired
2,900+ serial 404s for one dead event id — both passed every functional test
because nothing pins HOW MANY provider calls a code path may make. These
tests pin the service-layer dedup seams at the provider-call level, so
reintroducing that bug class fails CI instead of hiding as a performance
cliff.

The pins are exact (== not <=): a legitimate change to fetch behavior should
consciously update the expected count, not slide past a loose bound.
"""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

from teamarr.core.types import Event, EventStatus, Team
from teamarr.services.sports_data import SportsDataService
from tests.fakes import FakeCache


def _team(team_id: str, name: str, abbr: str) -> Team:
    # All identity fields populated so _enrich_event_teams takes its early
    # return instead of falling through to the team_cache DB backfill.
    return Team(
        id=team_id,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=abbr,
        league="nfl",
        sport="football",
    )


def _event(event_id: str) -> Event:
    return Event(
        id=event_id,
        provider="espn",
        name=f"Game {event_id}",
        short_name=f"G{event_id}",
        league="nfl",
        sport="football",
        start_time=datetime(2026, 7, 8, 20, 0, tzinfo=UTC),
        home_team=_team("1", "Team A", "TA"),
        away_team=_team("2", "Team B", "TB"),
        status=EventStatus(state="in"),
    )


def _service(provider: MagicMock) -> SportsDataService:
    provider.supports_league.return_value = True
    service = SportsDataService(providers=[provider])
    service._cache = FakeCache()
    return service


class TestEventRefreshFanout:
    """refresh_event_status: the #254 seam.

    One event is matched to many channels and re-checked by the filler, so a
    single generation run refreshes the same event dozens-to-hundreds of
    times. The coalesce marker must absorb that fan-out into one provider
    fetch per event per window.
    """

    def test_repeated_refreshes_of_one_event_fetch_once(self):
        provider = MagicMock()
        provider.get_event.return_value = _event("100")
        service = _service(provider)

        event = _event("100")
        for _ in range(50):
            refreshed = service.refresh_event_status(event)
            assert refreshed.status is not None

        assert provider.get_event.call_count == 1

    def test_fanout_scales_with_events_not_channels(self):
        """5 events x 30 channels each -> 5 fetches, not 150 (the #254 shape)."""
        provider = MagicMock()
        provider.get_event.side_effect = lambda event_id, league: _event(event_id)
        service = _service(provider)

        events = [_event(str(i)) for i in range(5)]
        # Interleave like the per-channel matching pass does (channel-major,
        # not event-major) so the pin covers the real access pattern.
        for _channel in range(30):
            for event in events:
                service.refresh_event_status(event)

        assert provider.get_event.call_count == len(events)


class TestScoreboardFanout:
    """get_events: the per-(league, date) seam PR #261 extends."""

    def test_repeated_get_events_fetch_once(self):
        provider = MagicMock()
        provider.get_events.return_value = [_event("100")]
        service = _service(provider)

        for _ in range(10):
            events = service.get_events("nfl", date(2026, 7, 8))
            assert len(events) == 1

        assert provider.get_events.call_count == 1

    def test_empty_slate_is_cached(self):
        """A no-games day must cache the empty list, not re-poll the provider."""
        provider = MagicMock()
        provider.get_events.return_value = []
        service = _service(provider)

        for _ in range(10):
            assert service.get_events("nfl", date(2026, 7, 8)) == []

        assert provider.get_events.call_count == 1

    def test_distinct_dates_fetch_separately(self):
        """Sanity: the cache key includes the date — dedup must not over-merge."""
        provider = MagicMock()
        provider.get_events.return_value = [_event("100")]
        service = _service(provider)

        service.get_events("nfl", date(2026, 7, 8))
        service.get_events("nfl", date(2026, 7, 9))

        assert provider.get_events.call_count == 2
