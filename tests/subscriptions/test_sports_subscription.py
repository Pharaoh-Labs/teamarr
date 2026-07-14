"""Tests for sports subscription CRUD and template resolution (BEAD 5).

Tests the subscription.py database module and API endpoints for
the global sports subscription system.
"""

import sqlite3

import pytest


def _create_subscription_schema(conn):
    """Create the subscription tables for testing."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sports_subscription (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            leagues JSON NOT NULL DEFAULT '[]',
            soccer_mode TEXT DEFAULT NULL
                CHECK(soccer_mode IS NULL OR soccer_mode IN ('all', 'teams', 'manual')),
            soccer_followed_teams JSON DEFAULT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO sports_subscription (id) VALUES (1);

        CREATE TABLE IF NOT EXISTS subscription_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            sports JSON,
            leagues JSON
        );

        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );

        -- Known-league universe for save-time validation (#408). league_cache
        -- left empty by default so validation is skipped unless a test seeds it.
        CREATE TABLE IF NOT EXISTS leagues (
            league_code TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS league_cache (
            league_slug TEXT NOT NULL,
            provider TEXT NOT NULL,
            sport TEXT NOT NULL,
            PRIMARY KEY (league_slug, provider)
        );
    """)
    conn.commit()


@pytest.fixture
def db():
    """Create in-memory SQLite database with subscription schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_subscription_schema(conn)
    # Seed some templates for FK references
    conn.execute("INSERT INTO templates (id, name) VALUES (1, 'Default')")
    conn.execute("INSERT INTO templates (id, name) VALUES (2, 'Soccer')")
    conn.execute("INSERT INTO templates (id, name) VALUES (3, 'UFC')")
    conn.execute("INSERT INTO templates (id, name) VALUES (4, 'NFL')")
    conn.commit()
    yield conn
    conn.close()


class TestSubscriptionCRUD:
    """Test get/update for the global subscription."""

    def test_get_default_subscription(self, db):
        from teamarr.database.subscription import get_subscription

        sub = get_subscription(db)
        assert sub.id == 1
        assert sub.leagues == []
        assert sub.soccer_mode is None
        assert sub.soccer_followed_teams is None

    def test_update_leagues(self, db):
        from teamarr.database.subscription import get_subscription, update_subscription

        update_subscription(db, leagues=["nhl", "nba", "nfl"])
        sub = get_subscription(db)
        assert sorted(sub.leagues) == ["nba", "nfl", "nhl"]

    def test_update_leagues_drops_unknown_codes(self, db):
        """Zombie slugs absent from leagues ∪ league_cache are dropped on save (#408)."""
        from teamarr.database.subscription import get_subscription, update_subscription

        db.execute(
            "INSERT INTO league_cache (league_slug, provider, sport) VALUES "
            "('nhl', 'espn', 'hockey'), ('eng.1', 'espn', 'soccer')"
        )
        db.execute("INSERT INTO leagues (league_code) VALUES ('sui.1')")
        db.commit()

        update_subscription(
            db, leagues=["nhl", "eng.1", "sui.1", "bra.carioca.groupa", "afc.challenge_cup"]
        )
        sub = get_subscription(db)
        assert sorted(sub.leagues) == ["eng.1", "nhl", "sui.1"]

    def test_update_leagues_validation_is_case_insensitive(self, db):
        from teamarr.database.subscription import get_subscription, update_subscription

        db.execute(
            "INSERT INTO league_cache (league_slug, provider, sport) "
            "VALUES ('nhl', 'espn', 'hockey')"
        )
        db.commit()

        update_subscription(db, leagues=["NHL"])
        sub = get_subscription(db)
        assert sub.leagues == ["NHL"]

    def test_update_leagues_skips_validation_when_cache_empty(self, db):
        """Empty league_cache (fresh install / mid-refresh) must not purge the list."""
        from teamarr.database.subscription import get_subscription, update_subscription

        update_subscription(db, leagues=["nhl", "bra.carioca.groupa"])
        sub = get_subscription(db)
        assert sorted(sub.leagues) == ["bra.carioca.groupa", "nhl"]

    def test_update_soccer_mode(self, db):
        from teamarr.database.subscription import get_subscription, update_subscription

        update_subscription(db, soccer_mode="all")
        sub = get_subscription(db)
        assert sub.soccer_mode == "all"

    def test_update_soccer_followed_teams(self, db):
        from teamarr.database.subscription import get_subscription, update_subscription

        teams = [{"provider": "espn", "team_id": "1", "name": "Arsenal"}]
        update_subscription(db, soccer_mode="teams", soccer_followed_teams=teams)
        sub = get_subscription(db)
        assert sub.soccer_mode == "teams"
        assert len(sub.soccer_followed_teams) == 1
        assert sub.soccer_followed_teams[0]["team_id"] == "1"

    def test_clear_soccer_mode(self, db):
        from teamarr.database.subscription import get_subscription, update_subscription

        update_subscription(db, soccer_mode="all")
        update_subscription(db, soccer_mode=None)
        sub = get_subscription(db)
        assert sub.soccer_mode is None


class TestSubscriptionTemplateCRUD:
    """Test CRUD for subscription template assignments."""

    def test_add_template(self, db):
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_templates,
        )

        add_subscription_template(db, template_id=1)
        templates = get_subscription_templates(db)
        assert len(templates) == 1
        assert templates[0].template_id == 1
        assert templates[0].sports is None
        assert templates[0].leagues is None

    def test_add_template_with_sports(self, db):
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_templates,
        )

        add_subscription_template(db, template_id=2, sports=["soccer"])
        templates = get_subscription_templates(db)
        assert len(templates) == 1
        assert templates[0].sports == ["soccer"]

    def test_add_template_with_leagues(self, db):
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_templates,
        )

        add_subscription_template(db, template_id=3, leagues=["ufc", "bellator"])
        templates = get_subscription_templates(db)
        assert len(templates) == 1
        assert templates[0].leagues == ["ufc", "bellator"]

    def test_update_template(self, db):
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template,
            update_subscription_template,
        )

        aid = add_subscription_template(db, template_id=1)
        update_subscription_template(db, aid, template_id=2)
        t = get_subscription_template(db, aid)
        assert t.template_id == 2

    def test_delete_template(self, db):
        from teamarr.database.subscription import (
            add_subscription_template,
            delete_subscription_template,
            get_subscription_templates,
        )

        aid = add_subscription_template(db, template_id=1)
        assert delete_subscription_template(db, aid)
        assert len(get_subscription_templates(db)) == 0

    def test_delete_nonexistent(self, db):
        from teamarr.database.subscription import delete_subscription_template

        assert not delete_subscription_template(db, 999)

    def test_get_single_template(self, db):
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template,
        )

        aid = add_subscription_template(db, template_id=1, sports=["hockey"])
        t = get_subscription_template(db, aid)
        assert t is not None
        assert t.id == aid
        assert t.template_id == 1
        assert t.sports == ["hockey"]

    def test_get_nonexistent_template(self, db):
        from teamarr.database.subscription import get_subscription_template

        assert get_subscription_template(db, 999) is None


class TestTemplateResolution:
    """Test get_subscription_template_for_event specificity resolution."""

    def _setup_templates(self, db):
        """Set up a typical template hierarchy for testing."""
        from teamarr.database.subscription import add_subscription_template

        # Default (both NULL)
        add_subscription_template(db, template_id=1)
        # Soccer sport match
        add_subscription_template(db, template_id=2, sports=["soccer"])
        # UFC league match (most specific)
        add_subscription_template(db, template_id=3, leagues=["ufc"])
        # Football sport match
        add_subscription_template(db, template_id=4, sports=["football"])

    def test_league_match_wins(self, db):
        """League match is most specific and should win."""
        from teamarr.database.subscription import get_subscription_template_for_event

        self._setup_templates(db)
        result = get_subscription_template_for_event(db, "mma", "ufc")
        assert result == 3

    def test_sport_match_fallback(self, db):
        """Sport match when no league match."""
        from teamarr.database.subscription import get_subscription_template_for_event

        self._setup_templates(db)
        result = get_subscription_template_for_event(db, "soccer", "eng.1")
        assert result == 2

    def test_default_fallback(self, db):
        """Default template when no league or sport match."""
        from teamarr.database.subscription import get_subscription_template_for_event

        self._setup_templates(db)
        result = get_subscription_template_for_event(db, "basketball", "nba")
        assert result == 1

    def test_no_templates(self, db):
        """No templates configured returns None."""
        from teamarr.database.subscription import get_subscription_template_for_event

        result = get_subscription_template_for_event(db, "hockey", "nhl")
        assert result is None

    def test_resolution_order(self, db):
        """Test full resolution priority chain."""
        from teamarr.database.subscription import get_subscription_template_for_event

        self._setup_templates(db)

        test_cases = [
            # (sport, league, expected_template, description)
            ("mma", "ufc", 3, "UFC gets UFC template (league match)"),
            ("mma", "bellator", 1, "Bellator falls back to default"),
            ("soccer", "eng.1", 2, "EPL gets soccer template (sport match)"),
            ("soccer", "usa.1", 2, "MLS gets soccer template (sport match)"),
            ("football", "nfl", 4, "NFL gets football template (sport match)"),
            ("football", "ncaaf", 4, "NCAAF gets football template (sport match)"),
            ("basketball", "nba", 1, "NBA falls back to default"),
        ]

        for sport, league, expected, desc in test_cases:
            result = get_subscription_template_for_event(db, sport, league)
            assert result == expected, f"Failed: {desc} - got {result}, expected {expected}"

    def test_only_default_template(self, db):
        """Single default template matches everything."""
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template_for_event,
        )

        add_subscription_template(db, template_id=1)
        assert get_subscription_template_for_event(db, "hockey", "nhl") == 1
        assert get_subscription_template_for_event(db, "soccer", "eng.1") == 1

    def test_only_sport_template(self, db):
        """Sport-only template matches that sport, returns None for others."""
        from teamarr.database.subscription import (
            add_subscription_template,
            get_subscription_template_for_event,
        )

        add_subscription_template(db, template_id=2, sports=["soccer"])
        assert get_subscription_template_for_event(db, "soccer", "eng.1") == 2
        assert get_subscription_template_for_event(db, "hockey", "nhl") is None
