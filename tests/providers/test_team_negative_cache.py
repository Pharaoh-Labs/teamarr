"""get_team / get_team_stats negative-cache provider misses.

Lookups that return nothing (off-season teams, leagues without records) were
never cached, so every generation run repeated the same failing provider
calls — a steady ~250+ `espn:teams` calls per hourly run. Both now store a
negative marker with CACHE_TTL_NEGATIVE so repeats within the window are
served from cache, while successful fetches keep their normal TTLs.
"""

from unittest.mock import MagicMock

from teamarr.core.types import Team, TeamStats
from teamarr.services.sports_data import SportsDataService
from teamarr.utilities.cache import CACHE_TTL_NEGATIVE
from tests.fakes import FakeCache


def _service(team=None, stats=None):
    provider = MagicMock()
    provider.supports_league.return_value = True
    provider.get_team.return_value = team
    provider.get_team_stats.return_value = stats
    service = SportsDataService(providers=[provider])
    service._cache = FakeCache()
    return service, provider


def _make_team() -> Team:
    return Team(
        id="8",
        provider="espn",
        name="Detroit Pistons",
        short_name="Pistons",
        abbreviation="DET",
        league="nba",
        sport="Basketball",
    )


class TestGetTeamNegativeCache:
    def test_provider_miss_fetches_once_within_window(self):
        service, provider = _service(team=None)
        for _ in range(3):
            assert service.get_team("8", "nba") is None
        assert provider.get_team.call_count == 1

    def test_negative_entry_uses_negative_ttl(self):
        service, _ = _service(team=None)
        service.get_team("8", "nba")
        _, value, ttl = service._cache.set_calls[-1]
        assert value.get("__not_found__")
        assert ttl == CACHE_TTL_NEGATIVE

    def test_successful_fetch_still_cached_normally(self):
        service, provider = _service(team=_make_team())
        assert service.get_team("8", "nba") is not None
        assert service.get_team("8", "nba") is not None
        assert provider.get_team.call_count == 1


class TestGetTeamStatsNegativeCache:
    def test_provider_miss_fetches_once_within_window(self):
        service, provider = _service(stats=None)
        for _ in range(3):
            assert service.get_team_stats("8", "nba") is None
        assert provider.get_team_stats.call_count == 1

    def test_negative_entry_uses_negative_ttl(self):
        service, _ = _service(stats=None)
        service.get_team_stats("8", "nba")
        _, value, ttl = service._cache.set_calls[-1]
        assert value.get("__not_found__")
        assert ttl == CACHE_TTL_NEGATIVE

    def test_successful_fetch_still_cached_normally(self):
        service, provider = _service(stats=TeamStats(record="10-5", wins=10, losses=5))
        assert service.get_team_stats("8", "nba") is not None
        assert service.get_team_stats("8", "nba") is not None
        assert provider.get_team_stats.call_count == 1
