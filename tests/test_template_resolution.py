"""Test template resolution for subscription templates.

Validates that get_subscription_template_for_event correctly resolves
templates based on specificity: leagues > sports > default.
"""

import sqlite3

import pytest


@pytest.fixture
def test_db():
    """Create an in-memory database with test schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    # Create minimal schema
    conn.executescript("""
        CREATE TABLE templates (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE subscription_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            sports JSON,
            leagues JSON,
            FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
        );
    """)

    # Insert test templates
    conn.executescript("""
        INSERT INTO templates (id, name) VALUES
            (1, 'Default Template'),
            (2, 'Soccer Template'),
            (3, 'UFC Template'),
            (4, 'NFL Template'),
            (5, 'Combat Sports Template');
    """)

    yield conn
    conn.close()


class TestTemplateResolution:
    """Tests for get_subscription_template_for_event function."""

    def test_league_match_has_highest_priority(self, test_db):
        """League-specific template should take priority over sport and default."""
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template_for_event,
        )

        add_subscription_template(test_db, template_id=1)  # Default
        add_subscription_template(test_db, template_id=5, sports=["mma"])  # Sport
        add_subscription_template(test_db, template_id=3, leagues=["ufc"])  # League

        result = get_subscription_template_for_event(test_db, "mma", "ufc")
        assert result == 3, "League-specific template should take priority"

    def test_sport_match_over_default(self, test_db):
        """Sport-specific template should take priority over default."""
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template_for_event,
        )

        add_subscription_template(test_db, template_id=1)  # Default
        add_subscription_template(test_db, template_id=2, sports=["soccer"])  # Sport

        result = get_subscription_template_for_event(test_db, "soccer", "eng.1")
        assert result == 2, "Sport-specific template should take priority over default"

    def test_default_when_no_specific_match(self, test_db):
        """Default template should be used when no specific match."""
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template_for_event,
        )

        add_subscription_template(test_db, template_id=1)  # Default
        add_subscription_template(test_db, template_id=4, leagues=["nfl"])  # NFL only

        result = get_subscription_template_for_event(test_db, "basketball", "nba")
        assert result == 1, "Default template should be used when no specific match"

    def test_multiple_leagues_in_one_assignment(self, test_db):
        """Template with multiple leagues should match any of them."""
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template_for_event,
        )

        add_subscription_template(test_db, template_id=1)  # Default
        add_subscription_template(
            test_db,
            template_id=2,
            leagues=["eng.1", "esp.1", "ger.1", "ita.1", "fra.1"],
        )

        assert get_subscription_template_for_event(test_db, "soccer", "eng.1") == 2
        assert get_subscription_template_for_event(test_db, "soccer", "esp.1") == 2
        assert get_subscription_template_for_event(test_db, "soccer", "ger.1") == 2

        # MLS not in list, should fall back to default
        assert get_subscription_template_for_event(test_db, "soccer", "usa.1") == 1

    def test_no_template_configured(self, test_db):
        """No templates at all should return None."""
        from teamarr.database.subscription import get_subscription_template_for_event

        result = get_subscription_template_for_event(test_db, "any", "any")
        assert result is None, "Should return None when no template configured"

    def test_empty_sport_league_in_event(self, test_db):
        """Events with empty sport/league should only match default."""
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template_for_event,
        )

        add_subscription_template(test_db, template_id=1)  # Default
        add_subscription_template(test_db, template_id=4, leagues=["nfl"])

        result = get_subscription_template_for_event(test_db, "", "")
        assert result == 1, "Empty sport/league should match default"

    def test_sport_and_league_on_same_assignment(self, test_db):
        """Assignment with both sport and league — league check runs first."""
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template_for_event,
        )

        add_subscription_template(test_db, template_id=1)  # Default
        add_subscription_template(
            test_db,
            template_id=2,
            sports=["mma"],
            leagues=["ufc"],
        )

        # UFC should match (league takes priority in resolution)
        result = get_subscription_template_for_event(test_db, "mma", "ufc")
        assert result == 2

        # Bellator (different league) should try sport match
        result = get_subscription_template_for_event(test_db, "mma", "bellator")
        assert result == 2, "Should match via sport when league doesn't match"


class TestTemplateResolutionIntegration:
    """Integration tests for full resolution workflow."""

    def test_full_workflow(self, test_db):
        """Test complete workflow: add templates, resolve."""
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template_for_event,
            get_subscription_templates,
        )

        # Setup: Add various template assignments
        add_subscription_template(test_db, template_id=1)  # Default
        add_subscription_template(test_db, template_id=2, sports=["soccer"])
        add_subscription_template(test_db, template_id=3, leagues=["ufc"])
        add_subscription_template(test_db, template_id=4, leagues=["nfl", "ncaaf"])

        # Verify assignments were created
        assignments = get_subscription_templates(test_db)
        assert len(assignments) == 4

        # Test resolution for various events
        test_cases = [
            # (sport, league, expected_template, description)
            ("mma", "ufc", 3, "UFC gets UFC template"),
            ("mma", "bellator", 1, "Bellator falls back to default"),
            ("soccer", "eng.1", 2, "EPL gets soccer template"),
            ("soccer", "usa.1", 2, "MLS gets soccer template"),
            ("football", "nfl", 4, "NFL gets NFL template"),
            ("football", "ncaaf", 4, "NCAAF gets NFL template"),
            ("basketball", "nba", 1, "NBA falls back to default"),
        ]

        for sport, league, expected, desc in test_cases:
            result = get_subscription_template_for_event(test_db, sport, league)
            assert result == expected, f"Failed: {desc} - got {result}, expected {expected}"
