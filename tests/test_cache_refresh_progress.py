"""Cache refresh lifecycle and progress tests."""

import time
from types import SimpleNamespace

from teamarr.api import cache_refresh_status
from teamarr.api.cache_refresh import start_cache_refresh
from teamarr.consumers.cache.refresh import CacheRefresher
from teamarr.services.cache_service import RefreshResult


def test_background_refresh_records_actual_work_progress(monkeypatch):
    """The progress denominator is the discovered league work, not a guess."""
    providers = [
        SimpleNamespace(name="alpha", get_supported_leagues=lambda: ["a", "b"]),
        SimpleNamespace(name="beta", get_supported_leagues=lambda: ["c"]),
    ]
    monkeypatch.setattr(
        "teamarr.consumers.cache.refresh.ProviderRegistry.get_all", lambda: providers
    )
    monkeypatch.setattr(CacheRefresher, "_set_refresh_in_progress", lambda *_: None)
    monkeypatch.setattr(
        CacheRefresher, "_merge_with_seed", lambda _, teams, leagues: (teams, leagues)
    )
    monkeypatch.setattr(CacheRefresher, "_save_cache", lambda *_: None)
    monkeypatch.setattr(CacheRefresher, "_refresh_soccer_team_leagues", lambda *_: 0)
    monkeypatch.setattr(CacheRefresher, "refresh_conferences", lambda *_: 0)
    monkeypatch.setattr(CacheRefresher, "_update_meta", lambda *_: None)

    def discover(_, provider, callback, leagues):
        callback("ignored", 100)
        return [], []

    monkeypatch.setattr(CacheRefresher, "_discover_from_provider", discover)
    updates: list[tuple[str, int]] = []

    CacheRefresher().refresh(lambda message, percent: updates.append((message, percent)))

    assert ("Fetching alpha: 0/3 leagues", 5) in updates
    assert ("Fetching alpha: 2/3 leagues", 65) in updates
    assert ("Fetching beta: 3/3 leagues", 95) in updates


def test_background_refresh_updates_shared_status_and_reloads_mappings(monkeypatch):
    """Startup and manual callers share one terminal refresh status."""
    cache_refresh_status._status.reset()
    reloaded = False

    class Service:
        def refresh(self, progress_callback):
            progress_callback("Fetching espn: 2/4 leagues", 50)
            return RefreshResult(leagues_added=4, teams_added=12, duration_seconds=0.1)

    class MappingService:
        def reload(self):
            nonlocal reloaded
            reloaded = True

    monkeypatch.setattr("teamarr.api.cache_refresh.create_cache_service", lambda _: Service())
    monkeypatch.setattr(
        "teamarr.api.cache_refresh.get_league_mapping_service", lambda: MappingService()
    )

    assert start_cache_refresh(lambda: None)
    assert not start_cache_refresh(lambda: None)

    for _ in range(20):
        status = cache_refresh_status.get_refresh_status()
        if status["status"] == "complete":
            break
        time.sleep(0.01)

    assert status["status"] == "complete"
    assert status["result"] == {
        "success": True,
        "leagues_count": 4,
        "teams_count": 12,
        "duration_seconds": 0.1,
    }
    assert reloaded
