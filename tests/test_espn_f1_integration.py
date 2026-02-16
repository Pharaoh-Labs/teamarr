"""Integration tests for ESPN F1 provider support.

Verifies that the ESPN provider correctly constructs URLs and parses
tournament/racing data from the actual ESPN API structure.
"""

from datetime import date, UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from teamarr.core import LeagueMapping, LeagueMappingSource
from teamarr.providers.espn.client import ESPNClient
from teamarr.providers.espn.provider import ESPNProvider

@pytest.fixture(autouse=True)
def mock_user_timezone():
    """Ensure tests run in UTC for predictable date comparison."""
    # Patch to_user_tz to just return the datetime as-is (assuming it's already UTC)
    with patch("teamarr.providers.espn.tournament.to_user_tz") as mock_to_tz:
        mock_to_tz.side_effect = lambda dt: dt
        yield mock_to_tz

class TestESPNF1Integration:
    """Integration-style tests for ESPN F1 parsing logic."""

    @pytest.fixture
    def mock_client(self):
        """Mock client to verify URL parameters and provide real-world JSON samples."""
        return MagicMock(spec=ESPNClient)

    @pytest.fixture
    def mock_mapping_source(self):
        source = MagicMock(spec=LeagueMappingSource)
        # Mock F1 mapping - this is what triggers the 'racing/f1' logic
        source.get_mapping.return_value = LeagueMapping(
            league_code="f1",
            provider="espn",
            provider_league_id="racing/f1",
            provider_league_name="Formula 1",
            sport="Racing",
            display_name="Formula 1",
        )
        return source

    @pytest.fixture
    def provider(self, mock_client, mock_mapping_source):
        return ESPNProvider(client=mock_client, league_mapping_source=mock_mapping_source)

    def test_get_events_f1_path_construction(self, provider, mock_client):
        """Verify that F1 requests use the 'racing' sport and 'f1' league in the client."""
        target_date = date(2026, 3, 1)
        
        # Real-world snippet of ESPN tournament scoreboard response
        mock_client.get_scoreboard.return_value = {
            "leagues": [{"name": "Formula 1"}],
            "events": [
                {
                    "id": "401712345",
                    "name": "Bahrain Grand Prix",
                    "date": "2026-03-01T15:00Z",
                    "competitions": [
                        {
                            "id": "401712345",
                            "date": "2026-03-01T15:00Z",
                            "status": {"type": {"name": "STATUS_SCHEDULED", "description": "Scheduled"}},
                            "venue": {"fullName": "Bahrain International Circuit"},
                            "competitors": [
                                # Tournament competitors often have placeholder IDs or are just generic
                                {"id": "1", "homeAway": "home", "team": {"displayName": "Bahrain Grand Prix"}},
                                {"id": "2", "homeAway": "away", "team": {"displayName": "Bahrain Grand Prix"}}
                            ]
                        }
                    ]
                }
            ]
        }

        events = provider.get_events("f1", target_date)

        # Verify the client was called with the correct sport/league extracted from provider_league_id
        mock_client.get_scoreboard.assert_called_once_with(
            "f1", "20260301", ("racing", "f1")
        )

        assert len(events) == 1
        assert events[0].name == "Bahrain Grand Prix"
        assert events[0].sport == "Racing"
        assert events[0].venue.name == "Bahrain International Circuit"

    def test_f1_virtual_team_id_handling(self, provider, mock_client):
        """Verify that get_team_schedule for 'f1' uses tournament parsing."""
        target_date = date.today()
        date_str = target_date.strftime("%Y%m%d")
        
        mock_client.get_scoreboard.return_value = {"events": []}
        
        provider.get_team_schedule("f1", "f1", days_ahead=1)

        # Should call get_scoreboard for 'f1' league with 'racing/f1' sport_league
        mock_client.get_scoreboard.assert_called_with(
            "f1", date_str, ("racing", "f1")
        )

    def test_f1_multiple_sessions_parsing(self, provider, mock_client):
        """Verify that a Grand Prix with multiple competitions is expanded correctly."""
        target_date = date(2025, 12, 5) # FP1 date from real data
        
        mock_client.get_scoreboard.return_value = {
            "events": [
                {
                    "id": "401712345",
                    "name": "Abu Dhabi Grand Prix",
                    "competitions": [
                        {
                            "id": "1",
                            "date": "2025-12-05T09:30Z",
                            "type": {"abbreviation": "FP1", "shortDetail": "FP1"},
                            "status": {"type": {"state": "pre"}}
                        },
                        {
                            "id": "2",
                            "date": "2025-12-05T13:00Z",
                            "type": {"abbreviation": "FP2", "shortDetail": "FP2"},
                            "status": {"type": {"state": "pre"}}
                        },
                        {
                            "id": "5",
                            "date": "2025-12-07T13:00Z",
                            "type": {"abbreviation": "Race", "shortDetail": "Race"},
                            "status": {"type": {"state": "pre"}}
                        }
                    ]
                }
            ]
        }

        # Asking for the 5th (Practice day)
        events = provider.get_events("f1", target_date)

        # Should find 2 events (FP1 and FP2) because they both happen on target_date
        assert len(events) == 2
        fp1 = next(e for e in events if "Free Practice 1" in e.name)
        assert fp1.short_name == "Abu Dhabi Grand Prix - FP1"
        assert any(e.name == "Abu Dhabi Grand Prix - Free Practice 1" for e in events)
        assert any(e.name == "Abu Dhabi Grand Prix - Free Practice 2" for e in events)
        assert not any("Race" in e.name for e in events)

    def test_f1_sprint_sessions_parsing(self, provider, mock_client):
        """Verify that F1 Sprint sessions (SR, SS) are parsed correctly."""
        target_date = date(2024, 10, 19)
        
        mock_client.get_scoreboard.return_value = {
            "events": [
                {
                    "id": "401712345",
                    "name": "United States Grand Prix",
                    "competitions": [
                        {
                            "id": "10",
                            "date": "2024-10-18T21:30Z",
                            "type": {"abbreviation": "SS"},
                            "status": {"type": {"state": "post"}}
                        },
                        {
                            "id": "11",
                            "date": "2024-10-19T18:00Z",
                            "type": {"abbreviation": "SR"},
                            "status": {"type": {"state": "post"}}
                        }
                    ]
                }
            ]
        }

        events = provider.get_events("f1", target_date)

        # On the 19th, only the Sprint Race should match
        assert len(events) == 1
        assert events[0].name == "United States Grand Prix - Sprint Race"

    def test_f1_2026_sprint_abbreviation_parsing(self, provider, mock_client):
        """Verify that the 'Sprint' abbreviation used in 2026 is parsed as Sprint Qualifying."""
        target_date = date(2026, 3, 13)
        
        mock_client.get_scoreboard.return_value = {
            "events": [
                {
                    "id": "600057428",
                    "name": "Chinese Grand Prix",
                    "competitions": [
                        {
                            "id": "401839034",
                            "date": "2026-03-13T07:30Z",
                            "type": {"abbreviation": "Sprint"},
                            "status": {"type": {"state": "pre"}}
                        }
                    ]
                }
            ]
        }

        events = provider.get_events("f1", target_date)
        assert len(events) == 1
        assert events[0].name == "Chinese Grand Prix - Sprint Qualifying"

    def test_leagues_without_teams_f1(self, provider):
        """Verify F1 is correctly identified as a league without a standard /teams endpoint."""
        # This prevents the provider from trying to hit /teams/f1 which would 404
        assert "f1" in provider.LEAGUES_WITHOUT_TEAMS
        
        # Calling get_league_teams should return our virtual team instead of hitting the API
        teams = provider.get_league_teams("f1")
        assert len(teams) == 1
        assert teams[0].id == "f1"
