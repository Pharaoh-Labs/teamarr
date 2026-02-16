"""Tests for Formula 1 team-based EPG support.

Validates that Formula 1 can be treated as a "Team" for persistent channels,
returning the full league schedule.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from teamarr.core import LeagueMapping, LeagueMappingSource
from teamarr.providers.espn.client import ESPNClient
from teamarr.providers.espn.provider import ESPNProvider

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestF1TeamChannel:
    """Tests for F1 team channel support in ESPNProvider."""

    @pytest.fixture
    def mock_client(self):
        return MagicMock(spec=ESPNClient)

    @pytest.fixture
    def mock_mapping_source(self):
        source = MagicMock(spec=LeagueMappingSource)
        # Mock F1 mapping
        source.get_mapping.return_value = LeagueMapping(
            league_code="f1",
            provider="espn",
            provider_league_id="racing/f1",
            provider_league_name="Formula 1",
            sport="Racing",
            display_name="Formula 1",
            logo_url="https://a.espncdn.com/i/teamlogos/leagues/500/f1.png",
        )
        return source

    @pytest.fixture
    def provider(self, mock_client, mock_mapping_source):
        return ESPNProvider(client=mock_client, league_mapping_source=mock_mapping_source)

    def test_get_league_teams_returns_virtual_f1_team(self, provider):
        """get_league_teams should return a virtual 'Formula 1' team for the f1 league."""
        teams = provider.get_league_teams("f1")
        
        assert len(teams) == 1
        f1_team = teams[0]
        assert f1_team.id == "f1"
        assert f1_team.name == "Formula 1"
        assert f1_team.league == "f1"
        assert f1_team.sport == "Racing"

    def test_get_team_returns_virtual_f1_team(self, provider):
        """get_team should return the virtual F1 team."""
        f1_team = provider.get_team("f1", "f1")
        
        assert f1_team is not None
        assert f1_team.id == "f1"
        assert f1_team.name == "Formula 1"

    def test_get_team_schedule_returns_all_f1_events(self, provider, mock_client):
        """get_team_schedule for the F1 team should return all events in the league."""
        # Mock scoreboard responses for 2 days
        today = date.today()
        tomorrow = today + timedelta(days=1)
        
        event1 = {
            "id": "1",
            "name": "Bahrain Grand Prix - Practice 1",
            "date": today.strftime("%Y-%m-%dT15:00:00Z"),
            "competitions": [{"venue": {"fullName": "Bahrain International Circuit"}}]
        }
        event2 = {
            "id": "2",
            "name": "Bahrain Grand Prix - Practice 2",
            "date": tomorrow.strftime("%Y-%m-%dT18:00:00Z"),
            "competitions": [{"venue": {"fullName": "Bahrain International Circuit"}}]
        }
        
        # mock_client.get_scoreboard is called for each day
        def get_scoreboard_side_effect(league, date_str, sport_league=None):
            if date_str == today.strftime("%Y%m%d"):
                return {"events": [event1]}
            if date_str == tomorrow.strftime("%Y%m%d"):
                return {"events": [event2]}
            return {"events": []}
            
        mock_client.get_scoreboard.side_effect = get_scoreboard_side_effect

        # Request 2 days of schedule
        events = provider.get_team_schedule("f1", "f1", days_ahead=2)
        
        assert len(events) == 2
        assert events[0].name == "Bahrain Grand Prix - Practice 1"
        assert events[1].name == "Bahrain Grand Prix - Practice 2"
        # Verify both are from the 'f1' league
        assert events[0].league == "f1"
        assert events[1].league == "f1"
