"""Tennis ESPN endpoint guards (#282).

ESPN has no summary or teams endpoints for tennis — atp/wta return HTTP 400
for /summary, /teams/{id}, and /teams/{id}/schedule. Tennis player ids are
also synthetic name slugs (player_*) fabricated by TennisParserMixin because
scoreboard athlete ids are null, so ESPN could never resolve them anyway.
These tests pin the guards that keep those dead calls from ever leaving the
provider, and the base-client rule that deterministic 4xx is not retried.
"""

import httpx

from teamarr.providers import base_client
from teamarr.providers.base_client import BaseHTTPClient
from teamarr.providers.espn.provider import ESPNProvider


class _StubClient(BaseHTTPClient):
    PROVIDER = "stub"
    LOG_TAG = "STUB"


def test_4xx_does_not_retry(monkeypatch):
    monkeypatch.setattr(base_client.time, "sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(400)

    client = _StubClient(retry_count=3)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert client._request_json("https://api.test/x") is None
    assert len(calls) == 1


def test_tennis_leagues_in_guard_sets():
    assert {"atp", "wta"} <= ESPNProvider.LEAGUES_WITHOUT_SUMMARY
    assert {"atp", "wta"} <= ESPNProvider.LEAGUES_WITHOUT_TEAMS


def test_get_event_skips_summary_for_tennis():
    provider = ESPNProvider()
    # No HTTP mock needed: the guard must return before any request is built.
    provider._client = None
    assert provider.get_event("401700001", "atp") is None


def test_get_team_skips_teams_endpoint_for_tennis():
    provider = ESPNProvider()
    provider._client = None
    assert provider.get_team("player_taylor_fritz", "atp") is None


def test_get_team_schedule_skips_past_games_for_player_ids(monkeypatch):
    provider = ESPNProvider()

    def _boom(*args, **kwargs):
        raise AssertionError("/teams/{id}/schedule must not be called for player_* ids")

    monkeypatch.setattr(provider, "_get_past_games_from_schedule", _boom)
    monkeypatch.setattr(provider, "_get_sport_league_from_db", lambda league: None)
    monkeypatch.setattr(
        provider, "_scan_scoreboard_for_team", lambda *a, **k: []
    )
    assert provider.get_team_schedule("player_taylor_fritz", "atp") == []
