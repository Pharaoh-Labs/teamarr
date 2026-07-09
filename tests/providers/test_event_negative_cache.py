"""get_event negative-caches provider misses (teamarrv2-t82y).

A failed event fetch (e.g. ESPN 404 on a dead summary endpoint) previously
cached nothing, so every per-channel refresh_event_status of that event fell
through to another serial provider call — 2,900+ live 404s in one generation
run for a single F1 event id. get_event now stores a short-TTL negative
marker so the per-channel fan-out is absorbed within the coalesce window.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from teamarr.core.types import Event, EventStatus, Team
from teamarr.services.sports_data import REFRESH_COALESCE_TTL, SportsDataService
from tests.fakes import FakeCache


def _service_with_missing_event():
    provider = MagicMock()
    provider.supports_league.return_value = True
    provider.get_event.return_value = None
    service = SportsDataService(providers=[provider])
    service._cache = FakeCache()
    return service, provider


def _make_event() -> Event:
    team = Team(
        id="1",
        provider="espn",
        name="Max Verstappen",
        short_name="Verstappen",
        abbreviation="VER",
        league="f1",
        sport="Racing",
    )
    return Event(
        id="600057437",
        provider="espn",
        name="British Grand Prix",
        short_name="GBR GP",
        league="f1",
        sport="Racing",
        start_time=datetime(2026, 7, 5, 14, 0, tzinfo=UTC),
        home_team=team,
        away_team=team,
        status=EventStatus(state="in"),
    )


class TestGetEventNegativeCache:
    def test_provider_miss_fetches_once_within_window(self):
        service, provider = _service_with_missing_event()
        for _ in range(3):
            assert service.get_event("600057437", "f1") is None
        assert provider.get_event.call_count == 1

    def test_negative_entry_uses_short_ttl(self):
        service, _ = _service_with_missing_event()
        service.get_event("600057437", "f1")
        _, value, ttl = service._cache.set_calls[-1]
        assert value.get("__event_not_found__")
        assert ttl == REFRESH_COALESCE_TTL

    def test_repeated_refresh_of_dead_event_hits_provider_once(self):
        """The generation-run shape: one event refreshed once per channel."""
        service, provider = _service_with_missing_event()
        event = _make_event()
        for _ in range(5):
            assert service.refresh_event_status(event) is event
        assert provider.get_event.call_count == 1

    def test_successful_fetch_still_cached_normally(self):
        service, provider = _service_with_missing_event()
        provider.get_event.return_value = _make_event()
        result = service.get_event("600057437", "f1")
        assert result is not None
        assert result.id == "600057437"
        # Cached copy served on the second call — provider hit once.
        assert service.get_event("600057437", "f1") is not None
        assert provider.get_event.call_count == 1
