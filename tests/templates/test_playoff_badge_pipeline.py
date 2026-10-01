"""Playoff art URLs across provider refresh, preview, EPG and lifecycle naming."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.consumers.event_epg import EventEPGGenerator, EventEPGOptions
from teamarr.consumers.lifecycle.naming import ChannelNaming
from teamarr.core.types import Event, EventStatus, Team
from teamarr.database.templates import EventTemplateConfig
from teamarr.services import league_mappings as lm
from teamarr.services.sports_data import SportsDataService
from teamarr.templates.context_builder import ContextBuilder
from teamarr.templates.resolver import TemplateResolver

ART_BASE = "https://art.example.test"
ART_PATH = (
    "{league_code}/{away_team|pascal}/{home_team|pascal}/thumb.png"
    "?aspect=16-9&style=6&badge={series_game|url}"
)
LOGO_PATH = (
    "{league_code}/{away_team|pascal}/{home_team|pascal}/logo.png?style=1&badge={series_game|url}"
)
PLAYOFF_ROW = {
    "condition": "is_playoff",
    "priority": 15,
    "template": "",
    "program_art_url": ART_PATH,
    "event_channel_logo_url": LOGO_PATH,
    "subtitle": "{series_summary_short} ({series_score})",
}


@pytest.fixture(autouse=True)
def real_league_service(db_factory):
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


def _event(*, postseason: bool, series_summary: str = "") -> Event:
    home = Team(
        id="1",
        provider="espn",
        name="New York Yankees",
        short_name="Yankees",
        abbreviation="NYY",
        league="mlb",
        sport="baseball",
    )
    away = Team(
        id="2",
        provider="espn",
        name="Boston Red Sox",
        short_name="Red Sox",
        abbreviation="BOS",
        league="mlb",
        sport="baseball",
    )
    return Event(
        id="game-2",
        provider="espn",
        name="Boston Red Sox at New York Yankees",
        short_name="BOS @ NYY",
        start_time=datetime(2026, 10, 2, 20, tzinfo=UTC),
        home_team=home,
        away_team=away,
        status=EventStatus(state="pre"),
        league="mlb",
        sport="baseball",
        season_type="postseason" if postseason else "regular",
        game_event_note="ALDS - Game 2" if postseason else "",
        series_summary=series_summary,
    )


def _options() -> EventEPGOptions:
    return EventEPGOptions(
        template=EventTemplateConfig(
            title_format="{away_team} at {home_team}",
            subtitle_format="Regular season",
            description_format="Base description",
            program_art_url="mlb/default/cover.png",
            event_channel_logo_url="mlb/default/logo.png",
            conditional_descriptions=[PLAYOFF_ROW, {"priority": 100, "template": "Default"}],
        )
    )


def test_refreshed_series_and_badge_reach_epg_and_managed_channel_logo():
    service = SportsDataService(providers=[])
    scoreboard_event = _event(postseason=True)
    summary_event = replace(scoreboard_event, series_summary="NYY leads series 2-1")

    with (
        patch.object(service, "get_event", return_value=summary_event),
        patch.object(service._cache, "delete"),
    ):
        event = service.refresh_event_status(scoreboard_event)

    # No extra API calls in generation: the event refreshed by the provider
    # already carries the series data (and keeps the scoreboard's season type).
    with (
        patch.object(service, "enrich_event_preview", side_effect=lambda e: e),
        patch.object(service, "get_team_stats", return_value=None),
    ):
        generator = EventEPGGenerator(service, art_base_url=ART_BASE)
        programmes, channels = generator.generate_for_matched_streams(
            [{"stream": {"name": "BOS @ NYY HD"}, "event": event}],
            _options(),
        )

        naming = ChannelNaming()
        naming._context_builder = ContextBuilder(service)
        naming._resolver = TemplateResolver(ART_BASE)
        managed_logo = naming._resolve_logo_url(event, _options().template)

    assert len(programmes) == len(channels) == 1
    assert programmes[0].icon == (
        f"{ART_BASE}/mlb/BostonRedSox/NewYorkYankees/thumb.png?aspect=16-9&style=6&badge=Game%202"
    )
    expected_logo = f"{ART_BASE}/mlb/BostonRedSox/NewYorkYankees/logo.png?style=1&badge=Game%202"
    assert channels[0].icon == managed_logo == expected_logo
    assert programmes[0].subtitle == "BOS 1 - NYY 2 (1-2)"
    assert programmes[0].description == "Default"


def test_regular_season_keeps_default_art_without_empty_badge():
    service = SportsDataService(providers=[])
    with (
        patch.object(service, "enrich_event_preview", side_effect=lambda e: e),
        patch.object(service, "get_team_stats", return_value=None),
    ):
        generator = EventEPGGenerator(service, art_base_url=ART_BASE)
        programmes, channels = generator.generate_for_matched_streams(
            [{"stream": {"name": "BOS @ NYY HD"}, "event": _event(postseason=False)}],
            _options(),
        )

    assert programmes[0].icon == f"{ART_BASE}/mlb/default/cover.png"
    assert channels[0].icon == f"{ART_BASE}/mlb/default/logo.png"
    assert programmes[0].subtitle == "Regular season"


def test_live_preview_resolves_playoff_badge_and_series_from_refreshed_event():
    service = SportsDataService(providers=[])
    scoreboard_event = _event(postseason=True)
    summary_event = replace(scoreboard_event, series_summary="NYY leads series 2-1")

    with (
        patch.object(service, "get_event", return_value=summary_event),
        patch.object(service._cache, "delete"),
    ):
        refreshed = service.refresh_event_status(scoreboard_event)

    with (
        patch("teamarr.api.routes.templates.build_live_context") as build_context,
        patch(
            "teamarr.api.routes.templates.TemplateResolver",
            return_value=TemplateResolver(ART_BASE),
        ),
        patch.object(service, "enrich_event_preview", side_effect=lambda e: e),
        patch.object(service, "get_team_stats", return_value=None),
    ):
        build_context.return_value = ContextBuilder(service).build_for_event(
            refreshed,
            refreshed.home_team.id,
            refreshed.league,
        )
        response = TestClient(app).post(
            "/api/v1/templates/preview",
            json={
                "league": "mlb",
                "live": True,
                "template_type": "event",
                "fields": {},
                "conditional_descriptions": [PLAYOFF_ROW, {"priority": 100, "template": "Default"}],
            },
        )

    assert response.status_code == 200
    conditional = response.json()["conditional"]
    assert conditional["rendered_art_url"] == (
        f"{ART_BASE}/mlb/BostonRedSox/NewYorkYankees/thumb.png?aspect=16-9&style=6&badge=Game%202"
    )
    assert conditional["rendered_channel_logo_url"] == (
        f"{ART_BASE}/mlb/BostonRedSox/NewYorkYankees/logo.png?style=1&badge=Game%202"
    )
    assert conditional["rendered_subtitle"] == "BOS 1 - NYY 2 (1-2)"
    assert conditional["selected_art_url_index"] == 0
    assert conditional["selected_channel_logo_index"] == 0
