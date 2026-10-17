"""Recurring franchise schedules, team imports and season boundaries (#1069)."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from teamarr.providers.espn.client import ESPNClient
from teamarr.providers.espn.provider import ESPNProvider

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "espn_cricket_franchises.json").read_text()
)
SERIES = {"mlc": "21266", "ipl": "8048", "bbl": "8044", "sa20": "21275"}


def provider_for(league):
    payload = copy.deepcopy(FIXTURE[league])
    client = MagicMock()
    year = 2027 if league == "sa20" else 2026
    client.get_cricket_season.side_effect = lambda slug, season=None: (
        payload if season in (None, year) else None
    )
    source = MagicMock()
    source.get_mapping.return_value = SimpleNamespace(
        sport="cricket", provider_league_id=f"cricket/{SERIES[league]}"
    )
    return ESPNProvider(client=client, league_mapping_source=source), payload


@pytest.mark.parametrize("league,count", [("mlc", 6), ("ipl", 10), ("bbl", 8), ("sa20", 6)])
def test_import_and_lookup_use_full_scoreboard_team_list(league, count):
    provider, payload = provider_for(league)
    teams = provider.get_league_teams(league)
    assert len(teams) == count
    assert all(t.name and t.provider == "espn" and t.league == league for t in teams)
    assert provider.get_team(teams[0].id, league) == teams[0]
    assert provider.get_team("unknown", league) is None
    assert provider.get_team_stats(teams[0].id, league) is None
    provider._client.get_teams.assert_not_called()
    provider._client.get_team.assert_not_called()
    payload["teams"].append({"id": "984779", "name": "TBA"})
    assert len(provider.get_league_teams(league)) == count


@pytest.mark.parametrize("league", SERIES)
def test_events_parse_and_dedupe_default_against_explicit_season(league):
    provider, payload = provider_for(league)
    raw = payload["events"][0]
    day = date.fromisoformat(raw["date"][:10])
    payload["events"].append({})  # a real ESPN empty-slot shape
    events = provider.get_events(league, day)
    assert len(events) == 1
    event = events[0]
    assert event.id == raw["id"] and event.sport == "cricket"
    assert event.series_slug == SERIES[league]
    assert event.home_score is None and event.away_score is None
    assert event.game_event_note == "1st Match"
    assert event.status.state == ("final" if league in {"mlc", "ipl"} else "scheduled")
    provider._client.get_scoreboard.assert_not_called()
    provider._client.get_team_schedule.assert_not_called()


def test_mlc_night_is_in_utc_bucket_not_espn_local_day():
    provider, _ = provider_for("mlc")
    assert provider.get_events("mlc", date(2026, 6, 18)) == []
    (event,) = provider.get_events("mlc", date(2026, 6, 19))
    assert event.start_time == datetime(2026, 6, 19, 0, 30, tzinfo=UTC)


def test_mlc_night_reaches_local_day_through_real_service_seam(monkeypatch):
    from teamarr.services.sports_data import SportsDataService

    provider, _ = provider_for("mlc")
    zone = ZoneInfo("America/Chicago")
    for module in ("teamarr.utilities.event_dates", "teamarr.services.sports_data"):
        monkeypatch.setattr(f"{module}.get_user_timezone", lambda: zone)
    # Keep this test independent of the production persistent cache/database.
    cache = {}
    fake_cache = MagicMock()
    fake_cache.get.side_effect = cache.get
    fake_cache.set.side_effect = lambda key, value, *args: cache.update({key: value})
    monkeypatch.setattr("teamarr.services.sports_data._get_shared_cache", lambda: fake_cache)
    service = SportsDataService(providers=[provider])
    events = service.get_events("mlc", date(2026, 6, 18))
    assert [event.id for event in events] == ["1528557"]
    assert events[0].start_time.astimezone(zone).date() == date(2026, 6, 18)


def test_team_lookup_keeps_scoreboard_logo():
    provider, _ = provider_for("mlc")
    assert provider.get_team("1381359", "mlc").logo_url.endswith("/1381359.png")


def test_january_bbl_still_looks_in_previous_start_year():
    provider, payload = provider_for("bbl")
    raw = payload["events"][0]
    raw["date"] = raw["competitions"][0]["date"] = "2027-01-01T08:00Z"
    assert len(provider.get_events("bbl", date(2027, 1, 1))) == 1
    assert ("8044", 2026) in [c.args for c in provider._client.get_cricket_season.call_args_list]


def test_missing_sa20_label_does_not_hide_announced_next_season():
    provider, _ = provider_for("sa20")
    # Reading previews in Oct 2026 discovers 2027 via the default series link.
    with patch("teamarr.providers.espn.provider.date") as today:
        today.today.return_value = date(2026, 10, 15)
        events = provider.get_sample_candidates("sa20")
    assert len(events) == 1 and events[0].start_time.year == 2027


def test_team_schedule_includes_history_and_future_without_schedule_endpoint():
    provider, _ = provider_for("bbl")
    with patch("teamarr.providers.espn.cricket.date") as today:
        today.today.return_value = date(2026, 12, 10)
        assert len(provider.get_team_schedule("509671", "bbl", days_ahead=4)) == 1
        assert provider.get_team_schedule("509671", "bbl", days_ahead=1) == []
        assert provider.get_team_schedule("509667", "bbl", days_ahead=4) == []
    provider._client.get_team_schedule.assert_not_called()
    provider._client.get_scoreboard.assert_not_called()


def test_last_completed_match_is_available_in_offseason_without_range_scan():
    provider, _ = provider_for("mlc")
    with patch("teamarr.providers.espn.cricket.date") as today:
        today.today.return_value = date(2026, 10, 15)
        assert provider.get_recent_final("mlc").id == "1528557"
        assert len(provider.get_team_schedule("1381353", "mlc")) == 1
    provider._client.get_scoreboard.assert_not_called()


def test_season_cache_single_flights_and_expires():
    client = ESPNClient()
    with patch.object(client, "_request", return_value=FIXTURE["mlc"]) as request:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: client.get_cricket_season("21266", 2026), range(16)))
        assert all(r == FIXTURE["mlc"] for r in results)
        request.assert_called_once_with(
            "https://site.api.espn.com/apis/site/v2/sports/cricket/21266/scoreboard",
            {"season": 2026},
        )
        client._cricket_season_cache.clear()
        client.get_cricket_season("21266", 2026)
        assert request.call_count == 2


def test_failed_season_has_short_cooldown_not_successful_empty_payload():
    client = ESPNClient()
    with patch.object(client, "_request", side_effect=[None, FIXTURE["mlc"]]) as request:
        assert client.get_cricket_season("21266", 2026) is None
        assert client.get_cricket_season("21266", 2026) is None
        assert request.call_count == 1
        entry = client._cricket_season_cache._cache["21266:2026"]
        assert (entry.expires_at - entry.last_accessed).total_seconds() <= 30
        client._cricket_season_cache.clear()
        assert client.get_cricket_season("21266", 2026) == FIXTURE["mlc"]


def test_empty_success_is_cached_but_invalid_payload_is_not_a_schedule():
    client = ESPNClient()
    with patch.object(client, "_request", return_value={"events": []}) as request:
        assert client.get_cricket_season("21266", 2028) == {"events": []}
        assert client.get_cricket_season("21266", 2028) == {"events": []}
        assert request.call_count == 1
    with patch.object(client, "_request", return_value={"error": "bad"}):
        assert client.get_cricket_season("21266", 2029) is None
