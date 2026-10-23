"""Manual fixtures are schedules, not provider caches or permanent team games."""

from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teamarr.api.routes import manual_events as routes
from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.team_matcher import TeamMatcher
from teamarr.consumers.stream_match_cache import StreamMatchCache, event_to_cache_data
from teamarr.core import EventStatus
from teamarr.database.manual_events import get_manual_event, list_manual_events
from teamarr.services import sports_data
from teamarr.services.manual_events import (
    ManualFixtureInput,
    cancel_manual_fixture,
    write_manual_fixture,
)
from teamarr.services.sports_data import SportsDataService
from tests.fakes import FakeCache

DAY = date(2026, 10, 23)


@pytest.fixture
def setup(db_factory, monkeypatch):
    monkeypatch.setattr(sports_data, "_get_shared_cache", FakeCache)
    monkeypatch.setattr(sports_data, "get_user_timezone", lambda: ZoneInfo("UTC"))
    monkeypatch.setattr("teamarr.utilities.event_dates.get_user_timezone", lambda: ZoneInfo("UTC"))
    with db_factory() as conn:
        for team_id, name, abbrev in [("1", "Boston Celtics", "BOS"), ("2", "Miami Heat", "MIA")]:
            conn.execute(
                """INSERT INTO team_cache
                   (team_name, team_short_name, team_abbrev, provider, provider_team_id,
                    league, sport) VALUES (?, ?, ?, 'espn', ?, 'nba', 'basketball')""",
                (name, name, abbrev, team_id),
            )
    data = ManualFixtureInput(
        league="nba",
        home_team={"provider": "espn", "id": "1"},
        away_team={"provider": "espn", "id": "2"},
        start_time=datetime(2026, 10, 23, 20, tzinfo=UTC),
    )
    service = SportsDataService(providers=[], supplemental_db_factory=db_factory)
    return db_factory, data, service


def save(setup, **changes):
    factory, data, _ = setup
    with factory() as conn:
        return write_manual_fixture(conn, data.model_copy(update=changes))


def test_fixture_survives_service_recreation_and_preserves_provider_team_identity(setup):
    factory, _, _ = setup
    event = save(setup)
    service = SportsDataService(supplemental_db_factory=factory)
    fetched = service.get_event(event.id, "nba")
    assert fetched == event
    assert fetched.provider == "manual"
    assert fetched.home_team.provider == "espn"
    assert fetched.home_team.id == "1"
    assert fetched.status == EventStatus(state="scheduled")
    assert service.get_event(event.id, "nfl") is None


@pytest.mark.parametrize("cache_only", [False, True])
def test_provider_empty_cache_does_not_hide_new_or_edited_manual_fixtures(setup, cache_only):
    factory, data, service = setup
    provider = Mock()
    provider.name = "espn"
    provider.supports_league.return_value = True
    provider.get_events.return_value = []
    service.add_provider(provider)
    assert service.get_events("nba", DAY) == []  # warm an empty provider day
    calls = provider.get_events.call_count
    event = save(setup)
    assert service.get_events("nba", DAY, cache_only=cache_only) == [event]
    with factory() as conn:
        changed = write_manual_fixture(
            conn, data.model_copy(update={"name": "Preseason showcase"}), event.id
        )
    assert service.get_events("nba", DAY, cache_only=cache_only) == [changed]
    assert provider.get_events.call_count == calls
    assert not any(
        isinstance(value, list) and any(item.get("provider") == "manual" for item in value)
        for value in service._cache.data.values()
    )


def test_manual_and_provider_candidates_coexist(setup, monkeypatch):
    _, _, service = setup
    manual = save(setup)
    upstream = replace(manual, id="espn-event", provider="espn")
    monkeypatch.setattr(service, "_get_provider_events", lambda *args: [upstream])
    assert {e.id for e in service.get_events("nba", DAY)} == {manual.id, upstream.id}


def test_cache_only_local_fixture_works_without_any_provider(setup):
    _, _, service = setup
    manual = save(setup)
    assert service.get_events("nba", DAY, cache_only=True) == [manual]
    assert service.get_events("nfl", DAY, cache_only=True) == []


def test_user_day_window_handles_utc_crossing_and_tail(setup, monkeypatch):
    _, _, service = setup
    monkeypatch.setattr(
        "teamarr.utilities.event_dates.get_user_timezone", lambda: ZoneInfo("America/New_York")
    )
    event = save(setup, start_time=datetime(2026, 10, 24, 2, tzinfo=UTC))
    assert service.get_events("nba", DAY, cache_only=True) == [event]
    assert service.get_events("nba", date(2026, 10, 24), cache_only=True) == [event]
    assert service.get_events("nba", date(2026, 10, 25), cache_only=True) == []


def test_edit_and_cancel_are_authoritative_over_stale_match_snapshots(setup):
    factory, data, service = setup
    event = save(setup)
    snapshot = event_to_cache_data(event)
    matcher = TeamMatcher(service, StreamMatchCache(factory), db_factory=factory)
    with factory() as conn:
        changed = write_manual_fixture(
            conn,
            data.model_copy(update={"start_time": datetime(2026, 10, 24, 20, tzinfo=UTC)}),
            event.id,
        )
    assert matcher._reconstruct_event(snapshot) == changed
    assert service.refresh_event_status(event) == changed
    assert service.get_events("nba", DAY, cache_only=True) == []
    with factory() as conn:
        cancelled = cancel_manual_fixture(conn, event.id, "nba")
    assert service.get_event(event.id, "nba") == cancelled
    assert service.refresh_event_status(changed) == cancelled
    assert matcher._reconstruct_event(snapshot) is None
    assert service.get_events("nba", date(2026, 10, 24), cache_only=True) == []
    with factory() as conn:
        assert list_manual_events(conn) == [cancelled]


def test_missing_manual_identity_never_calls_upstream_or_revives_a_snapshot(setup):
    _, _, service = setup
    event = save(setup)
    provider = Mock()
    service.add_provider(provider)
    assert service.get_event("manual:missing", "nba") is None
    provider.get_event.assert_not_called()
    missing = replace(event, id="manual:missing")
    assert service.refresh_event_status(missing).status.state == "cancelled"


def test_writes_clear_failures_and_own_algorithmic_matches_but_preserve_pins(setup):
    factory, data, _ = setup
    event = save(setup)
    with factory() as conn:
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'Source', '[\"nba\"]')"
        )
    cache = StreamMatchCache(factory)
    for stream_id, event_id, pinned in [
        (1, "__FAILED__", False),
        (2, event.id, False),
        (3, event.id, True),
        (4, "__SKIPPED__", True),
        (5, "provider-event", False),
    ]:
        cache.set(1, stream_id, str(stream_id), event_id, "nba", {}, 1)
        if pinned:
            with factory() as conn:
                conn.execute(
                    "UPDATE stream_match_cache SET user_corrected = 1 WHERE stream_id = ?",
                    (stream_id,),
                )
    with factory() as conn:
        write_manual_fixture(conn, data, event.id)
        rows = conn.execute(
            "SELECT stream_id FROM stream_match_cache ORDER BY stream_id"
        ).fetchall()
    assert [row["stream_id"] for row in rows] == [3, 4, 5]


def test_team_schedule_callback_is_provider_only(setup):
    factory, _, _ = setup
    manual = save(setup)
    provider = Mock()
    provider.name = "espn"
    provider.supports_league.return_value = True
    provider.get_events.return_value = []
    provider.get_team_schedule.return_value = []
    service = SportsDataService(providers=[provider], supplemental_db_factory=factory)
    callback = provider.set_cached_events_fn.call_args.args[0]
    assert callback("nba", DAY) == []
    assert service.get_events("nba", DAY) == [manual]
    assert service.get_team_schedule("1", "nba") == []


def test_real_team_matcher_finds_missing_fixture_without_stream_assignment(setup):
    factory, _, service = setup
    event = save(setup)
    with factory() as conn:
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'Source', '[\"nba\"]')"
        )
    matcher = TeamMatcher(service, StreamMatchCache(factory), db_factory=factory, days_ahead=0)
    classified = classify_stream("NBA: Miami Heat vs Boston Celtics")
    result = matcher.match_single_league(classified, "nba", DAY, 1, 42, 1, ZoneInfo("UTC"))
    assert result.is_matched, result
    assert result.event.id == event.id
    # A second run replays a successful match against the authoritative local
    # fixture. Cancellation cannot revive the previously cached event.
    with factory() as conn:
        cancel_manual_fixture(conn, event.id, "nba")
    result = matcher.match_single_league(classified, "nba", DAY, 1, 42, 2, ZoneInfo("UTC"))
    assert not result.is_matched


def test_production_factory_enables_supplemental_schedules(setup, monkeypatch):
    factory, _, _ = setup
    event = save(setup)
    monkeypatch.setattr(sports_data, "get_db", factory)
    monkeypatch.setattr(sports_data, "_ensure_registry_initialized", lambda: None)
    monkeypatch.setattr(sports_data.ProviderRegistry, "get_all", lambda: [])
    service = sports_data.create_default_service()
    assert service.get_events("nba", DAY, cache_only=True) == [event]


def test_api_crud_validation_and_cancel(setup, monkeypatch):
    factory, data, service = setup
    monkeypatch.setattr(routes, "get_db", factory)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/manual-events")
    with TestClient(app) as client:
        url = "/api/v1/manual-events"
        payload = data.model_dump(mode="json")
        response = client.post(url, json=payload)
        assert response.status_code == 201, response.text
        event_id = response.json()["id"]
        assert client.get(url).json()["total"] == 1
        # The uuid id is a surrogate key: league is an optional check, never a
        # required lookup half (#1131 review).
        assert client.get(f"{url}/{event_id}").status_code == 200
        assert client.get(f"{url}/{event_id}", params={"league": "nba"}).status_code == 200
        assert client.get(f"{url}/{event_id}", params={"league": "nfl"}).status_code == 404
        changed = client.put(f"{url}/{event_id}", json={**payload, "name": "Showcase"})
        assert changed.status_code == 200
        assert changed.json()["id"] == event_id
        assert changed.json()["name"] == "Showcase"
        assert client.put(f"{url}/manual:missing", json=payload).status_code == 404
        naive = {**payload, "start_time": "2026-10-23T20:00"}
        assert client.post(url, json=naive).status_code == 422
        assert client.post(url, json={**payload, "surprise": 1}).status_code == 422
        same_teams = {**payload, "away_team": payload["home_team"]}
        assert client.post(url, json=same_teams).status_code == 422
        wrong_team = {**payload, "away_team": {"provider": "espn", "id": "99999"}}
        assert client.post(url, json=wrong_team).status_code == 400
        assert "Away team" in client.post(url, json=wrong_team).json()["detail"]
        assert client.post(url, json={**payload, "league": "f1"}).status_code == 400
        # Mixed-case league codes normalize to the lowercase slug every other
        # table stores — a raw "NBA" row would be invisible to every candidate
        # query (#1131 review).
        upper = client.post(url, json={**payload, "league": "NBA"})
        assert upper.status_code == 201
        assert service.get_events("nba", DAY, cache_only=True)
        upper_id = upper.json()["id"]
        assert client.get(url, params={"league": "nfl"}).json()["total"] == 0
        # PUT must not resurrect a cancelled fixture (#1131 review).
        assert client.delete(f"{url}/{event_id}").status_code == 200
        assert client.put(f"{url}/{event_id}", json=payload).status_code == 400
        assert client.delete(f"{url}/{upper_id}").status_code == 200
        assert client.delete(f"{url}/{event_id}").status_code == 200
    assert service.get_events("nba", DAY, cache_only=True) == []
    with factory() as conn:
        assert get_manual_event(conn, event_id).status.state == "cancelled"


def test_soccer_and_neutral_fixtures_use_vs_conventions(setup):
    factory, data, service = setup
    with factory() as conn:
        conn.execute("UPDATE team_cache SET sport = 'soccer' WHERE league = 'nba'")
        soccer = write_manual_fixture(
            conn,
            data.model_copy(update={"neutral_site": True, "name": None}),
        )
    assert soccer.name == "Miami Heat vs Boston Celtics"
    assert soccer.short_name == "MIA vs BOS"
    assert service.get_events("nba", DAY, cache_only=True)[0].name == soccer.name


def test_failed_cache_purge_is_league_scoped_and_skipped_on_cancel(setup):
    """One fixture write must not thrash every other league's failure cache,
    and cancelling cannot make unmatched streams match (#1131 review)."""
    factory, data, service = setup
    event = save(setup)
    cache = StreamMatchCache(factory)
    for league in ("nba", "nfl"):
        cache.set(1, 10, f"{league}-fail", "__FAILED__", league, {}, 1)
        cache.set(1, 11, f"{league}-keep", f"{league}-event", league, {}, 1)
    with factory() as conn:
        write_manual_fixture(conn, data, event.id)
        rows = {
            r["stream_name"]: r["event_id"]
            for r in conn.execute("SELECT stream_name, event_id FROM stream_match_cache")
        }
    expected_kept = {"nba-keep": "nba-event", "nfl-keep": "nfl-event"}
    assert rows == {"nfl-fail": "__FAILED__", **expected_kept}
    with factory() as conn:
        cancel_manual_fixture(conn, event.id, "nba")
        rows = {
            r["stream_name"]: r["event_id"]
            for r in conn.execute("SELECT stream_name, event_id FROM stream_match_cache")
        }
    assert rows == {"nfl-fail": "__FAILED__", **expected_kept}
    # The cancelled fixture's own stale algorithmic rows are gone, though.
    with factory() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM stream_match_cache WHERE event_id = ?", (event.id,)
        ).fetchone()[0]
    assert count == 0
