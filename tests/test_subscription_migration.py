"""Tests for v58 sports subscription migration (BEAD 3).

Verifies that the migration correctly:
- Collects league unions from all groups
- Merges soccer config (priority: all > teams > manual)
- Deduplicates group_templates into subscription_templates
- Migrates legacy template_id as default subscription templates
- Sets all groups to multi mode with NULL parent
- Updates group leagues for downgrade safety
"""

import json
import sqlite3

import pytest


def _create_base_schema(conn):
    """Create the minimal pre-v58 schema needed for migration testing."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            schema_version INTEGER DEFAULT 57
        );
        INSERT OR IGNORE INTO settings (id, schema_version) VALUES (1, 57);

        CREATE TABLE IF NOT EXISTS event_epg_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            leagues JSON DEFAULT '[]',
            soccer_mode TEXT DEFAULT NULL,
            soccer_followed_teams JSON DEFAULT NULL,
            group_mode TEXT DEFAULT 'single',
            parent_group_id INTEGER,
            template_id INTEGER,
            enabled INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS group_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            template_id INTEGER NOT NULL,
            sports JSON,
            leagues JSON
        );

        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS leagues (
            code TEXT PRIMARY KEY,
            name TEXT,
            sport TEXT
        );
    """)
    conn.commit()


def _run_v58_migration(conn):
    """Run just the v58 migration block from connection.py."""
    from teamarr.database.connection import _run_migrations

    _run_migrations(conn)


@pytest.fixture
def db():
    """Create in-memory SQLite database with pre-v58 schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_base_schema(conn)
    yield conn
    conn.close()


class TestLeagueUnion:
    """Migration collects unique leagues from all groups."""

    def test_unions_leagues_from_multiple_groups(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 1)",
            ("NHL", json.dumps(["nhl", "ahl"])),
        )
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 1)",
            ("NBA", json.dumps(["nba", "wnba"])),
        )
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 1)",
            ("Mixed", json.dumps(["nhl", "nba"])),
        )
        db.commit()

        _run_v58_migration(db)

        row = db.execute("SELECT leagues FROM sports_subscription WHERE id = 1").fetchone()
        leagues = json.loads(row[0])
        assert sorted(leagues) == ["ahl", "nba", "nhl", "wnba"]

    def test_includes_disabled_groups(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 1)",
            ("Active", json.dumps(["nhl"])),
        )
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 0)",
            ("Disabled", json.dumps(["nba"])),
        )
        db.commit()

        _run_v58_migration(db)

        row = db.execute("SELECT leagues FROM sports_subscription WHERE id = 1").fetchone()
        leagues = json.loads(row[0])
        assert "nba" in leagues
        assert "nhl" in leagues

    def test_empty_database(self, db):
        """Fresh install with no groups results in empty subscription."""
        _run_v58_migration(db)

        row = db.execute("SELECT leagues FROM sports_subscription WHERE id = 1").fetchone()
        leagues = json.loads(row[0])
        assert leagues == []

    def test_groups_with_null_leagues(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, NULL, 1)",
            ("Empty",),
        )
        db.commit()

        _run_v58_migration(db)

        row = db.execute("SELECT leagues FROM sports_subscription WHERE id = 1").fetchone()
        leagues = json.loads(row[0])
        assert leagues == []

    def test_groups_with_invalid_json(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 1)",
            ("Bad JSON", "not valid json"),
        )
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 1)",
            ("Good", json.dumps(["nhl"])),
        )
        db.commit()

        _run_v58_migration(db)

        row = db.execute("SELECT leagues FROM sports_subscription WHERE id = 1").fetchone()
        leagues = json.loads(row[0])
        assert leagues == ["nhl"]

    def test_single_group(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 1)",
            ("NHL Only", json.dumps(["nhl"])),
        )
        db.commit()

        _run_v58_migration(db)

        row = db.execute("SELECT leagues FROM sports_subscription WHERE id = 1").fetchone()
        leagues = json.loads(row[0])
        assert leagues == ["nhl"]


class TestSoccerConfigMerge:
    """Migration merges soccer config with correct priority."""

    def test_all_beats_teams(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, soccer_mode, enabled) "
            "VALUES (?, '[]', 'teams', 1)",
            ("Soccer Teams",),
        )
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, soccer_mode, enabled) "
            "VALUES (?, '[]', 'all', 1)",
            ("Soccer All",),
        )
        db.commit()

        _run_v58_migration(db)

        row = db.execute("SELECT soccer_mode FROM sports_subscription WHERE id = 1").fetchone()
        assert row[0] == "all"

    def test_teams_beats_manual(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, soccer_mode, enabled) "
            "VALUES (?, '[]', 'manual', 1)",
            ("Manual",),
        )
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, soccer_mode, enabled) "
            "VALUES (?, '[]', 'teams', 1)",
            ("Teams",),
        )
        db.commit()

        _run_v58_migration(db)

        row = db.execute("SELECT soccer_mode FROM sports_subscription WHERE id = 1").fetchone()
        assert row[0] == "teams"

    def test_merges_followed_teams(self, db):
        teams_a = [{"provider": "espn", "team_id": "1", "name": "Arsenal"}]
        teams_b = [
            {"provider": "espn", "team_id": "1", "name": "Arsenal"},
            {"provider": "espn", "team_id": "2", "name": "Chelsea"},
        ]
        db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, soccer_mode, soccer_followed_teams, enabled) "
            "VALUES (?, '[]', 'teams', ?, 1)",
            ("Group A", json.dumps(teams_a)),
        )
        db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, soccer_mode, soccer_followed_teams, enabled) "
            "VALUES (?, '[]', 'teams', ?, 1)",
            ("Group B", json.dumps(teams_b)),
        )
        db.commit()

        _run_v58_migration(db)

        row = db.execute(
            "SELECT soccer_followed_teams FROM sports_subscription WHERE id = 1"
        ).fetchone()
        teams = json.loads(row[0])
        # Should be deduplicated by provider:team_id
        assert len(teams) == 2
        team_ids = {t["team_id"] for t in teams}
        assert team_ids == {"1", "2"}

    def test_no_soccer_groups(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, '[]', 1)",
            ("NHL",),
        )
        db.commit()

        _run_v58_migration(db)

        row = db.execute("SELECT soccer_mode FROM sports_subscription WHERE id = 1").fetchone()
        assert row[0] is None


class TestTemplateMigration:
    """Migration deduplicates templates correctly."""

    def test_deduplicates_group_templates(self, db):
        db.execute("INSERT INTO templates (id, name) VALUES (1, 'Default')")
        db.execute("INSERT INTO templates (id, name) VALUES (2, 'Soccer')")
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, '[]', 1)",
            ("Group A",),
        )
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, '[]', 1)",
            ("Group B",),
        )
        # Same template assignment in both groups
        db.execute(
            "INSERT INTO group_templates (group_id, template_id, sports, leagues) "
            "VALUES (1, 1, NULL, NULL)"
        )
        db.execute(
            "INSERT INTO group_templates (group_id, template_id, sports, leagues) "
            "VALUES (2, 1, NULL, NULL)"
        )
        # Different assignment
        sports_json = json.dumps(["soccer"])
        db.execute(
            "INSERT INTO group_templates (group_id, template_id, sports, leagues) "
            "VALUES (1, 2, ?, NULL)",
            (sports_json,),
        )
        db.commit()

        _run_v58_migration(db)

        rows = db.execute("SELECT * FROM subscription_templates ORDER BY id").fetchall()
        # Should deduplicate: (1, NULL, NULL) appears once, (2, ["soccer"], NULL) once
        assert len(rows) == 2

    def test_legacy_template_id_migration(self, db):
        db.execute("INSERT INTO templates (id, name) VALUES (1, 'Default')")
        db.execute("INSERT INTO templates (id, name) VALUES (5, 'Legacy')")
        # Group with legacy template_id but no group_templates entry
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, template_id, enabled) "
            "VALUES (?, '[]', 5, 1)",
            ("Legacy Group",),
        )
        db.commit()

        _run_v58_migration(db)

        rows = db.execute(
            "SELECT template_id, sports, leagues FROM subscription_templates"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 5  # template_id
        assert rows[0][1] is None  # sports (default)
        assert rows[0][2] is None  # leagues (default)

    def test_no_templates(self, db):
        _run_v58_migration(db)

        rows = db.execute("SELECT * FROM subscription_templates").fetchall()
        assert len(rows) == 0


class TestGroupNormalization:
    """Migration normalizes all groups to multi mode."""

    def test_sets_all_groups_to_multi(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, group_mode, enabled) "
            "VALUES (?, '[]', 'single', 1)",
            ("Single",),
        )
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, group_mode, enabled) "
            "VALUES (?, '[]', 'multi', 1)",
            ("Multi",),
        )
        db.commit()

        _run_v58_migration(db)

        rows = db.execute("SELECT group_mode FROM event_epg_groups").fetchall()
        for row in rows:
            assert row[0] == "multi"

    def test_clears_parent_group_ids(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (id, name, leagues, enabled) VALUES (1, ?, '[]', 1)",
            ("Parent",),
        )
        db.execute(
            "INSERT INTO event_epg_groups (id, name, leagues, parent_group_id, enabled) "
            "VALUES (2, ?, '[]', 1, 1)",
            ("Child",),
        )
        db.commit()

        _run_v58_migration(db)

        rows = db.execute("SELECT parent_group_id FROM event_epg_groups").fetchall()
        for row in rows:
            assert row[0] is None

    def test_downgrade_safety_leagues(self, db):
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 1)",
            ("NHL", json.dumps(["nhl"])),
        )
        db.execute(
            "INSERT INTO event_epg_groups (name, leagues, enabled) VALUES (?, ?, 1)",
            ("NBA", json.dumps(["nba"])),
        )
        db.commit()

        _run_v58_migration(db)

        # All groups should have ALL subscription leagues for downgrade safety
        rows = db.execute("SELECT leagues FROM event_epg_groups").fetchall()
        for row in rows:
            leagues = json.loads(row[0])
            assert sorted(leagues) == ["nba", "nhl"]

    def test_schema_version_bumped(self, db):
        _run_v58_migration(db)

        row = db.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        assert row[0] == 76  # v59-v76 migrations run after v58
