"""Tests for soccer match league template variables.

Validates that soccer_match_league, soccer_match_league_name,
soccer_match_league_id, and soccer_match_league_logo use the
LeagueMappingService correctly.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.variables.soccer import (
    extract_soccer_match_league,
    extract_soccer_match_league_id,
    extract_soccer_match_league_logo,
    extract_soccer_match_league_name,
)


@pytest.fixture
def mock_service():
    """Mock LeagueMappingService with realistic data."""
    service = MagicMock()
    service.get_league_alias.side_effect = lambda code: {
        "eng.1": "EPL",
        "uefa.champions": "UCL",
        "ger.1": "Bundesliga",
    }.get(code.lower(), code.upper())

    service.get_league_display_name.side_effect = lambda code: {
        "eng.1": "English Premier League",
        "uefa.champions": "UEFA Champions League",
        "ger.1": "Bundesliga",
    }.get(code.lower(), code.upper())

    service.get_league_logo.side_effect = lambda code: {
        "eng.1": "https://a.espncdn.com/i/leaguelogos/soccer/500/23.png",
        "uefa.champions": "https://a.espncdn.com/i/leaguelogos/soccer/500/2.png",
    }.get(code.lower(), "")

    return service


def _make_ctx(league: str) -> tuple[TemplateContext, GameContext]:
    """Create minimal context with an event in the given league."""
    event = Event(
        id="401547679",
        provider="espn",
        name="Arsenal vs Chelsea",
        short_name="ARS vs CHE",
        start_time=datetime(2026, 2, 15, 15, 0),
        league=league,
        sport="soccer",
        status=EventStatus(state="scheduled"),
        home_team=Team(
            id="1",
            provider="espn",
            name="Arsenal",
            short_name="Arsenal",
            abbreviation="ARS",
            league="eng.1",
            sport="soccer",
        ),
        away_team=Team(
            id="2",
            provider="espn",
            name="Chelsea",
            short_name="Chelsea",
            abbreviation="CHE",
            league="eng.1",
            sport="soccer",
        ),
    )
    game_ctx = GameContext(event=event)
    team_config = TeamChannelContext(
        team_id="1", league="eng.1", sport="soccer", team_name="Arsenal"
    )
    ctx = TemplateContext(game_context=game_ctx, team_config=team_config, team_stats=None)
    return ctx, game_ctx


class TestSoccerMatchLeague:
    """Tests for {soccer_match_league} — short alias via mapping service."""

    @patch("teamarr.services.league_mappings.get_league_mapping_service")
    def test_returns_alias(self, mock_get_svc, mock_service):
        mock_get_svc.return_value = mock_service
        ctx, game_ctx = _make_ctx("eng.1")
        assert extract_soccer_match_league(ctx, game_ctx) == "EPL"

    @patch("teamarr.services.league_mappings.get_league_mapping_service")
    def test_champions_league(self, mock_get_svc, mock_service):
        mock_get_svc.return_value = mock_service
        ctx, game_ctx = _make_ctx("uefa.champions")
        assert extract_soccer_match_league(ctx, game_ctx) == "UCL"

    def test_no_game_context(self):
        team_config = TeamChannelContext(
            team_id="1", league="eng.1", sport="soccer", team_name="Arsenal"
        )
        ctx = TemplateContext(game_context=None, team_config=team_config, team_stats=None)
        assert extract_soccer_match_league(ctx, None) == ""

    def test_no_event(self):
        team_config = TeamChannelContext(
            team_id="1", league="eng.1", sport="soccer", team_name="Arsenal"
        )
        ctx = TemplateContext(game_context=None, team_config=team_config, team_stats=None)
        game_ctx = GameContext(event=None)
        assert extract_soccer_match_league(ctx, game_ctx) == ""


class TestSoccerMatchLeagueName:
    """Tests for {soccer_match_league_name} — full display name."""

    @patch("teamarr.services.league_mappings.get_league_mapping_service")
    def test_returns_display_name(self, mock_get_svc, mock_service):
        mock_get_svc.return_value = mock_service
        ctx, game_ctx = _make_ctx("eng.1")
        assert extract_soccer_match_league_name(ctx, game_ctx) == "English Premier League"

    @patch("teamarr.services.league_mappings.get_league_mapping_service")
    def test_champions_league(self, mock_get_svc, mock_service):
        mock_get_svc.return_value = mock_service
        ctx, game_ctx = _make_ctx("uefa.champions")
        assert extract_soccer_match_league_name(ctx, game_ctx) == "UEFA Champions League"

    @patch("teamarr.services.league_mappings.get_league_mapping_service")
    def test_fallback_uppercase(self, mock_get_svc, mock_service):
        mock_get_svc.return_value = mock_service
        ctx, game_ctx = _make_ctx("bra.1")
        assert extract_soccer_match_league_name(ctx, game_ctx) == "BRA.1"

    def test_no_game_context(self):
        team_config = TeamChannelContext(
            team_id="1", league="eng.1", sport="soccer", team_name="Arsenal"
        )
        ctx = TemplateContext(game_context=None, team_config=team_config, team_stats=None)
        assert extract_soccer_match_league_name(ctx, None) == ""


class TestSoccerMatchLeagueId:
    """Tests for {soccer_match_league_id} — raw league code."""

    def test_returns_raw_code(self):
        ctx, game_ctx = _make_ctx("eng.1")
        assert extract_soccer_match_league_id(ctx, game_ctx) == "eng.1"

    def test_champions_league(self):
        ctx, game_ctx = _make_ctx("uefa.champions")
        assert extract_soccer_match_league_id(ctx, game_ctx) == "uefa.champions"

    def test_no_game_context(self):
        team_config = TeamChannelContext(
            team_id="1", league="eng.1", sport="soccer", team_name="Arsenal"
        )
        ctx = TemplateContext(game_context=None, team_config=team_config, team_stats=None)
        assert extract_soccer_match_league_id(ctx, None) == ""


class TestSoccerMatchLeagueLogo:
    """Tests for {soccer_match_league_logo} — logo URL from mapping service."""

    @patch("teamarr.services.league_mappings.get_league_mapping_service")
    def test_returns_logo_url(self, mock_get_svc, mock_service):
        mock_get_svc.return_value = mock_service
        ctx, game_ctx = _make_ctx("eng.1")
        assert "leaguelogos" in extract_soccer_match_league_logo(ctx, game_ctx)

    @patch("teamarr.services.league_mappings.get_league_mapping_service")
    def test_unknown_league_returns_empty(self, mock_get_svc, mock_service):
        mock_get_svc.return_value = mock_service
        ctx, game_ctx = _make_ctx("bra.1")
        assert extract_soccer_match_league_logo(ctx, game_ctx) == ""

    def test_no_game_context(self):
        team_config = TeamChannelContext(
            team_id="1", league="eng.1", sport="soccer", team_name="Arsenal"
        )
        ctx = TemplateContext(game_context=None, team_config=team_config, team_stats=None)
        assert extract_soccer_match_league_logo(ctx, None) == ""
