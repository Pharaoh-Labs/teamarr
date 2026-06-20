"""ESPN team-schedule scans share one scoreboard fetch per league/day.

Regression guard for the call-volume bug class called out in
``teamarr.utilities.call_metrics``: the future-day team scan used to fetch each
day's full-league scoreboard once *per team*, so a league with N teams hit the
scoreboard N x days_ahead times. SportsDataService now injects its cached,
league-wide ``get_events`` into the provider so each day is fetched once per run
and shared across every team (and with event-group matching).
"""

from teamarr.providers.espn.provider import ESPNProvider
from teamarr.services import sports_data
from teamarr.services.sports_data import SportsDataService
from teamarr.utilities.cache import PersistentTTLCache


class _StubMapping:
    provider_league_id = "basketball/nba"
    sport = "basketball"


class _StubMappingSource:
    def supports_league(self, league, provider):
        return True

    def get_mapping(self, league, provider):
        return _StubMapping()

    def get_mapping_by_league(self, league):
        return _StubMapping()

    def get_league_sport(self, league):
        return "basketball"

    def register_discovered_league(self, **kwargs):
        pass


class _CountingClient:
    def __init__(self):
        self.scoreboard_calls = 0

    def get_scoreboard(self, league, date_str=None, sport_league=None):
        self.scoreboard_calls += 1
        return {"events": [], "leagues": [{"name": "NBA"}]}

    def get_team_schedule(self, league, team_id, sport_league=None):
        return {"events": []}


def _build(monkeypatch, *, optimized):
    # Isolated, hermetic cache per service: stub SQLite load/flush so the shared
    # cache starts empty and never reads from or pollutes the real service_cache
    # DB, then reset the process-global singleton so a fresh one is built.
    monkeypatch.setattr(PersistentTTLCache, "_load_from_sqlite", lambda self: None)
    monkeypatch.setattr(PersistentTTLCache, "flush", lambda self: 0)
    monkeypatch.setattr(sports_data, "_shared_cache", None)
    client = _CountingClient()
    provider = ESPNProvider(client=client, league_mapping_source=_StubMappingSource())
    service = SportsDataService(providers=[provider])
    if not optimized:
        provider.set_cached_events_fn(None)  # simulate pre-fix behavior
    return client, service


def test_scoreboard_fetched_once_per_day_across_teams(monkeypatch):
    days_ahead = 14
    n_teams = 6

    client_opt, service_opt = _build(monkeypatch, optimized=True)
    for i in range(n_teams):
        service_opt.get_team_schedule(f"team{i}", "verify-on", days_ahead=days_ahead)

    # Flat at days_ahead regardless of team count — the whole point.
    assert client_opt.scoreboard_calls == days_ahead


def test_optimization_cuts_redundant_fetches(monkeypatch):
    days_ahead = 14
    n_teams = 6

    client_off, service_off = _build(monkeypatch, optimized=False)
    for i in range(n_teams):
        service_off.get_team_schedule(f"team{i}", "verify-off", days_ahead=days_ahead)

    client_on, service_on = _build(monkeypatch, optimized=True)
    for i in range(n_teams):
        service_on.get_team_schedule(f"team{i}", "verify-on", days_ahead=days_ahead)

    assert client_off.scoreboard_calls == n_teams * days_ahead
    assert client_on.scoreboard_calls == days_ahead
    assert client_on.scoreboard_calls < client_off.scoreboard_calls
