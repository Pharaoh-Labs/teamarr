"""Tests for Formula 1 (Tournament) stream matching.

Validates that F1 streams match correctly via the new TournamentMatcher
path, which uses fuzzy matching on event names instead of team separators.
"""

import sqlite3
from datetime import UTC, datetime, date
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.matching import StreamMatcher
from teamarr.consumers.matching.classifier import StreamCategory
from teamarr.core.types import Event, EventStatus, Team
from teamarr.services.sports_data import SportsDataService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tournament_event(name: str, start_time: datetime, league: str = "f1") -> Event:
    """Create a minimal tournament Event for testing."""
    # Tournament events use same team for home/away in TournamentParserMixin
    tournament_team = Team(
        id=f"tournament_f1_{name.lower().replace(' ', '_')}",
        provider="espn",
        name=name,
        short_name=name[:20],
        abbreviation="F1",
        league=league,
        sport="racing",
    )
    
    return Event(
        id=f"evt-{name.lower().replace(' ', '_')}",
        provider="espn",
        name=name,
        short_name=name[:20],
        start_time=start_time,
        home_team=tournament_team,
        away_team=tournament_team,
        status=EventStatus(state="scheduled"),
        league=league,
        sport="racing",
    )

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestF1Matching:
    """Integration tests for F1 matching via StreamMatcher."""

    @pytest.fixture
    def db_factory(self):
        """In-memory database for settings/leagues lookup."""
        def _factory():
            # Use isolation_level=None to allow explicit transaction control (BEGIN EXCLUSIVE)
            conn = sqlite3.connect(":memory:", isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, event_match_days_ahead INTEGER, epg_generation_counter INTEGER DEFAULT 0)")
            conn.execute("INSERT INTO settings (id, event_match_days_ahead, epg_generation_counter) VALUES (1, 3, 0)")
            
            conn.execute("""
                CREATE TABLE leagues (
                    league_code TEXT PRIMARY KEY,
                    provider TEXT,
                    provider_league_id TEXT,
                    provider_league_name TEXT,
                    display_name TEXT,
                    sport TEXT,
                    event_type TEXT,
                    enabled INTEGER
                )
            """)
            conn.execute("""
                INSERT INTO leagues (league_code, provider, provider_league_id, display_name, sport, event_type, enabled)
                VALUES ('f1', 'espn', 'racing/f1', 'Formula 1', 'racing', 'event', 1)
            """)

            # Add missing tables needed by matchers
            conn.execute("CREATE TABLE team_aliases (alias TEXT, league TEXT, provider TEXT, team_id TEXT, team_name TEXT)")
            conn.execute("CREATE TABLE stream_match_cache (fingerprint TEXT PRIMARY KEY, group_id INTEGER, stream_id INTEGER, stream_name TEXT, event_id TEXT, league TEXT, cached_event_data TEXT, match_method TEXT, user_corrected BOOLEAN, corrected_at TIMESTAMP, last_seen_generation INTEGER, created_at TIMESTAMP, updated_at TIMESTAMP)")
            
            return conn
        return _factory

    @pytest.fixture
    def service(self):
        """Mock SportsDataService."""
        service = MagicMock(spec=SportsDataService)
        service.get_provider_name.return_value = "espn"
        return service

    def test_basic_f1_race_match(self, service, db_factory):
        """F1: Bahrain Grand Prix → Bahrain Grand Prix."""
        target_date = date(2026, 3, 1)
        event = _make_tournament_event(
            "Bahrain Grand Prix", 
            datetime(2026, 3, 1, 15, 0, tzinfo=UTC)
        )
        service.get_events.return_value = [event]

        matcher = StreamMatcher(
            service=service,
            db_factory=db_factory,
            group_id=1,
            search_leagues=["f1"],
        )

        streams = [{"id": 1, "name": "F1: Bahrain Grand Prix"}]
        result = matcher.match_all(streams, target_date)

        assert result.matched_count == 1
        res = result.results[0]
        assert res.matched is True
        assert res.event.id == event.id
        assert res.category == StreamCategory.EVENT

    def test_f1_qualifying_match(self, service, db_factory):
        """Formula 1: Qualifying - Saudi Arabian Grand Prix → Saudi Arabian Grand Prix - Qualifying."""
        target_date = date(2026, 3, 7)
        event = _make_tournament_event(
            "Saudi Arabian Grand Prix - Qualifying", 
            datetime(2026, 3, 7, 18, 0, tzinfo=UTC)
        )
        service.get_events.return_value = [event]

        matcher = StreamMatcher(
            service=service,
            db_factory=db_factory,
            group_id=1,
            search_leagues=["f1"],
        )

        streams = [{"id": 1, "name": "Formula 1: Qualifying - Saudi Arabian Grand Prix"}]
        result = matcher.match_all(streams, target_date)

        assert result.matched_count == 1
        res = result.results[0]
        assert res.matched is True
        assert res.event.id == event.id

    def test_f1_sessions_disambiguation(self, service, db_factory):
        """Ensure Practice 1 doesn't match Race if both are available on same day (unlikely but possible)."""
        target_date = date(2026, 3, 6)
        p1 = _make_tournament_event("Saudi Arabian Grand Prix - Practice 1", datetime(2026, 3, 6, 13, 0, tzinfo=UTC))
        p2 = _make_tournament_event("Saudi Arabian Grand Prix - Practice 2", datetime(2026, 3, 6, 17, 0, tzinfo=UTC))
        service.get_events.return_value = [p1, p2]

        matcher = StreamMatcher(
            service=service,
            db_factory=db_factory,
            group_id=1,
            search_leagues=["f1"],
        )

        # Match Practice 1
        streams = [{"id": 1, "name": "F1: Saudi Arabian Grand Prix Practice 1"}]
        result = matcher.match_all(streams, target_date)
        assert result.results[0].event.id == p1.id

        # Match Practice 2
        streams = [{"id": 2, "name": "F1: Saudi Arabian Grand Prix Practice 2"}]
        result = matcher.match_all(streams, target_date)
        assert result.results[0].event.id == p2.id

    def test_unrelated_racing_event(self, service, db_factory):
        """Nascar stream should NOT match F1 event if categorized as EVENT but names differ too much."""
        target_date = date(2026, 3, 1)
        event = _make_tournament_event("Bahrain Grand Prix", datetime(2026, 3, 1, 15, 0, tzinfo=UTC))
        service.get_events.return_value = [event]

        matcher = StreamMatcher(
            service=service,
            db_factory=db_factory,
            group_id=1,
            search_leagues=["f1"],
        )

        # "Nascar Cup Series" is classified as EVENT because "nascar" is in EVENT_TYPE_KEYWORDS
        streams = [{"id": 1, "name": "Nascar Cup Series"}]
        result = matcher.match_all(streams, target_date)

        assert result.matched_count == 0
        assert result.results[0].matched is False
