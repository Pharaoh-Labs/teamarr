"""Service layer backfills missing team fields from team_cache (#201).

team_cache is seeded from each provider's /teams endpoint where short_name and
abbreviation are reliably populated. When an event arrives with degraded team
data (e.g. short_name=None from ESPN's summary endpoint, or any future shape
we haven't accounted for), the service layer patches the team from team_cache
before handing it back to consumers.

This makes team_cache the canonical source of identity, decoupling it from
whatever shape a given event endpoint happens to return today.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from teamarr.core.types import Event, EventStatus, Team
from teamarr.database.connection import get_db, init_db
from teamarr.services.sports_data import (
    _backfill_team_from_cache,
    _enrich_event_teams,
)


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Init a fresh DB and seed team_cache with one canonical team."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    init_db()
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO team_cache
            (team_name, team_abbrev, team_short_name, provider, provider_team_id, league, sport)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Tampa Bay Rays", "TB", "Rays", "espn", "12", "mlb", "baseball"),
        )
        conn.commit()
    yield db_path


class TestBackfillTeam:
    def test_missing_short_name_filled_from_cache(self, seeded_db):
        # Mimics the post-summary-refresh degraded team.
        team = Team(
            id="12",
            provider="espn",
            name="Tampa Bay Rays",
            short_name=None,
            abbreviation="TB",
            league="mlb",
            sport="Baseball",
        )
        result = _backfill_team_from_cache(team, "mlb")
        assert result.short_name == "Rays"
        # Existing fields are not modified by the backfill.
        assert result.name == "Tampa Bay Rays"
        assert result.abbreviation == "TB"

    def test_empty_short_name_filled_from_cache(self, seeded_db):
        team = Team(
            id="12",
            provider="espn",
            name="Tampa Bay Rays",
            short_name="",
            abbreviation="TB",
            league="mlb",
            sport="Baseball",
        )
        result = _backfill_team_from_cache(team, "mlb")
        assert result.short_name == "Rays"

    def test_no_op_when_all_fields_populated(self, seeded_db):
        team = Team(
            id="12",
            provider="espn",
            name="Tampa Bay Rays",
            short_name="Rays",
            abbreviation="TB",
            league="mlb",
            sport="Baseball",
        )
        result = _backfill_team_from_cache(team, "mlb")
        # Should be the same object — fast path skips the DB lookup.
        assert result is team

    def test_no_op_when_team_not_in_cache(self, seeded_db):
        # Team id 99 isn't seeded → backfill returns the original team unchanged.
        team = Team(
            id="99",
            provider="espn",
            name="Unknown",
            short_name=None,
            abbreviation="UNK",
            league="mlb",
            sport="Baseball",
        )
        result = _backfill_team_from_cache(team, "mlb")
        assert result.short_name is None  # Cache miss leaves it as-is.

    def test_handles_none_team(self, seeded_db):
        assert _backfill_team_from_cache(None, "mlb") is None

    def test_handles_team_without_id(self, seeded_db):
        # Placeholder/synthetic teams (UFC undecided fighter slots, etc.).
        team = Team(
            id="",
            provider="espn",
            name="TBD",
            short_name=None,
            abbreviation="",
            league="mlb",
            sport="Baseball",
        )
        result = _backfill_team_from_cache(team, "mlb")
        assert result is team  # No id → no lookup.

    def test_db_failure_returns_original(self):
        # If the DB connection blows up, the backfill must not crash callers.
        # get_db is imported lazily inside the function, so we patch the
        # source module.
        team = Team(
            id="12",
            provider="espn",
            name="X",
            short_name=None,
            abbreviation="X",
            league="mlb",
            sport="Baseball",
        )
        with patch("teamarr.database.get_db", side_effect=Exception("nope")):
            result = _backfill_team_from_cache(team, "mlb")
        # Lookup failed → original team returned unchanged.
        assert result is team


class TestEnrichEventTeams:
    def test_event_with_degraded_teams_gets_backfilled(self, seeded_db):
        home = Team(
            id="12",
            provider="espn",
            name="Tampa Bay Rays",
            short_name=None,
            abbreviation="TB",
            league="mlb",
            sport="Baseball",
        )
        away = Team(
            id="99",
            provider="espn",
            name="Other",
            short_name="Other",
            abbreviation="OTH",
            league="mlb",
            sport="Baseball",
        )
        event = Event(
            id="1",
            provider="espn",
            name="X at Y",
            short_name="X @ Y",
            league="mlb",
            sport="Baseball",
            start_time=datetime(2026, 5, 6, tzinfo=UTC),
            status=EventStatus(state="scheduled"),
            home_team=home,
            away_team=away,
        )
        result = _enrich_event_teams(event)
        assert result.home_team.short_name == "Rays"  # Backfilled.
        assert result.away_team.short_name == "Other"  # Already populated.

    def test_no_op_when_already_complete(self, seeded_db):
        home = Team(
            id="12",
            provider="espn",
            name="Tampa Bay Rays",
            short_name="Rays",
            abbreviation="TB",
            league="mlb",
            sport="Baseball",
        )
        away = Team(
            id="14",
            provider="espn",
            name="Toronto Blue Jays",
            short_name="Blue Jays",
            abbreviation="TOR",
            league="mlb",
            sport="Baseball",
        )
        event = Event(
            id="1",
            provider="espn",
            name="X at Y",
            short_name="X @ Y",
            league="mlb",
            sport="Baseball",
            start_time=datetime(2026, 5, 6, tzinfo=UTC),
            status=EventStatus(state="scheduled"),
            home_team=home,
            away_team=away,
        )
        result = _enrich_event_teams(event)
        # Both teams unchanged → same Event instance returned (no realloc).
        assert result is event

    def test_handles_none(self):
        assert _enrich_event_teams(None) is None
