"""Tests for schema reconciliation engine."""

import sqlite3

import pytest

from teamarr.database.reconciliation import reconcile_schema

# Minimal schema.sql for testing — defines expected column state
MINI_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version INTEGER DEFAULT 71,
    api_timeout INTEGER DEFAULT 30,
    feed_separation_enabled BOOLEAN DEFAULT 0
);
INSERT OR IGNORE INTO settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS event_epg_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    leagues JSON NOT NULL,
    subscription_leagues JSON,
    subscription_soccer_mode TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_team_id TEXT,
    sport TEXT
);
"""


@pytest.fixture
def conn():
    """Create an in-memory database connection."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


class TestReconcileSchema:
    """Tests for reconcile_schema()."""

    def test_fresh_database_no_changes(self, conn):
        """When all tables have all columns, reconciliation is a no-op."""
        conn.executescript(MINI_SCHEMA)
        result = reconcile_schema(conn, MINI_SCHEMA)
        assert result.tables_checked >= 3
        assert result.columns_added == 0
        assert result.columns_by_table == {}
        assert result.errors == []

    def test_missing_single_column(self, conn):
        """Adds a missing column to an existing table."""
        # Create settings without feed_separation_enabled
        conn.execute("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                schema_version INTEGER DEFAULT 71,
                api_timeout INTEGER DEFAULT 30
            )
        """)
        conn.execute("INSERT INTO settings (id) VALUES (1)")
        # Create other tables with all columns
        conn.execute("""
            CREATE TABLE event_epg_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                leagues JSON NOT NULL,
                subscription_leagues JSON,
                subscription_soccer_mode TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_team_id TEXT,
                sport TEXT
            )
        """)
        conn.commit()

        result = reconcile_schema(conn, MINI_SCHEMA)
        assert result.columns_added == 1
        assert "settings" in result.columns_by_table
        assert "feed_separation_enabled" in result.columns_by_table["settings"]

        # Verify column actually exists and has correct default
        row = conn.execute("SELECT feed_separation_enabled FROM settings WHERE id = 1").fetchone()
        assert row[0] == 0  # BOOLEAN DEFAULT 0

    def test_missing_multiple_columns_across_tables(self, conn):
        """Adds missing columns across multiple tables (simulates #178)."""
        # Settings is fine
        conn.executescript("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                schema_version INTEGER DEFAULT 71,
                api_timeout INTEGER DEFAULT 30,
                feed_separation_enabled BOOLEAN DEFAULT 0
            );
            INSERT INTO settings (id) VALUES (1);
        """)
        # event_epg_groups is missing subscription columns (the #178 bug)
        conn.execute("""
            CREATE TABLE event_epg_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                leagues JSON NOT NULL
            )
        """)
        # teams missing sport column
        conn.execute("""
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_team_id TEXT
            )
        """)
        conn.commit()

        result = reconcile_schema(conn, MINI_SCHEMA)
        assert result.columns_added == 3  # 2 on event_epg_groups + 1 on teams
        assert "event_epg_groups" in result.columns_by_table
        assert "subscription_leagues" in result.columns_by_table["event_epg_groups"]
        assert "subscription_soccer_mode" in result.columns_by_table["event_epg_groups"]
        assert "teams" in result.columns_by_table
        assert "sport" in result.columns_by_table["teams"]

    def test_table_not_in_real_db_skipped(self, conn):
        """Tables in schema but not in real DB are skipped (executescript creates them)."""
        # Only create settings — event_epg_groups and teams don't exist
        conn.execute("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                schema_version INTEGER DEFAULT 71,
                api_timeout INTEGER DEFAULT 30,
                feed_separation_enabled BOOLEAN DEFAULT 0
            )
        """)
        conn.execute("INSERT INTO settings (id) VALUES (1)")
        conn.commit()

        result = reconcile_schema(conn, MINI_SCHEMA)
        assert result.tables_checked == 1  # Only settings
        assert result.columns_added == 0

    def test_extra_columns_in_real_db_preserved(self, conn):
        """Extra columns in real DB are NOT dropped (could be user additions)."""
        conn.execute("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                schema_version INTEGER DEFAULT 71,
                api_timeout INTEGER DEFAULT 30,
                feed_separation_enabled BOOLEAN DEFAULT 0,
                custom_user_column TEXT DEFAULT 'keep_me'
            )
        """)
        conn.execute("INSERT INTO settings (id) VALUES (1)")
        conn.execute("""
            CREATE TABLE event_epg_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                leagues JSON NOT NULL,
                subscription_leagues JSON,
                subscription_soccer_mode TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_team_id TEXT,
                sport TEXT
            )
        """)
        conn.commit()

        result = reconcile_schema(conn, MINI_SCHEMA)
        assert result.columns_added == 0

        # Verify custom column still exists
        row = conn.execute("SELECT custom_user_column FROM settings WHERE id = 1").fetchone()
        assert row[0] == "keep_me"

    def test_idempotent(self, conn):
        """Running reconciliation twice produces the same result."""
        conn.execute("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                schema_version INTEGER DEFAULT 71
            )
        """)
        conn.execute("INSERT INTO settings (id) VALUES (1)")
        conn.execute("""
            CREATE TABLE event_epg_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                leagues JSON NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_team_id TEXT
            )
        """)
        conn.commit()

        result1 = reconcile_schema(conn, MINI_SCHEMA)
        assert result1.columns_added > 0

        result2 = reconcile_schema(conn, MINI_SCHEMA)
        assert result2.columns_added == 0  # All columns now exist

    def test_bad_schema_sql_returns_error(self, conn):
        """Invalid schema SQL returns an error result instead of crashing."""
        conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY)")
        conn.commit()

        result = reconcile_schema(conn, "THIS IS NOT VALID SQL;")
        assert len(result.errors) > 0
        assert result.tables_checked == 0

    def test_internal_tables_skipped(self, conn):
        """Tables starting with _ are skipped (backup tables etc)."""
        conn.executescript(MINI_SCHEMA)
        # Create a backup table that looks like a real table
        conn.execute("""
            CREATE TABLE _settings_v65_backup (
                id INTEGER PRIMARY KEY,
                schema_version INTEGER
            )
        """)
        conn.commit()

        result = reconcile_schema(conn, MINI_SCHEMA)
        assert result.columns_added == 0
        assert "_settings_v65_backup" not in result.columns_by_table


class TestV65SchemaVersionCorrection:
    """Tests for the v65 schema_version fix in _run_migrations."""

    def test_corrects_version_from_backup(self):
        """When v65 backup exists, schema_version is corrected from backup."""
        from teamarr.database.migrations import _run_migrations

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row

        # Simulate post-v65-pre-migration state:
        # Settings table recreated with schema_version=71 (DEFAULT)
        conn.executescript("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                schema_version INTEGER DEFAULT 71
            );
            INSERT INTO settings (id, schema_version) VALUES (1, 71);

            CREATE TABLE _settings_v65_backup (
                id INTEGER PRIMARY KEY,
                schema_version INTEGER
            );
            INSERT INTO _settings_v65_backup (id, schema_version) VALUES (1, 55);

            CREATE TABLE event_epg_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                leagues JSON NOT NULL,
                enabled BOOLEAN DEFAULT 1,
                soccer_mode TEXT,
                soccer_followed_teams TEXT,
                group_mode TEXT DEFAULT 'single',
                parent_group_id INTEGER,
                template_id INTEGER,
                channel_assignment_mode TEXT DEFAULT 'auto',
                channel_start_number INTEGER,
                bypass_filter_for_playoffs BOOLEAN
            );

            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_epg_group_id INTEGER
            );
        """)
        conn.commit()

        _run_migrations(conn)

        # Schema version should have progressed through all migrations
        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        version = row[0]
        # Should be at least 65 (v65 restore sets it to 65, then later migrations bump it)
        assert version >= 65

        # Backup table should be cleaned up by v65 restore
        backup_exists = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='_settings_v65_backup'"
        ).fetchone()[0]
        assert backup_exists == 0

        conn.close()


class TestFullSchemaReconciliation:
    """Integration test: reconciliation with real schema.sql."""

    def test_with_real_schema(self):
        """Reconciliation works with the actual schema.sql file."""
        from tests.helpers import SCHEMA_PATH

        schema_sql = SCHEMA_PATH.read_text()

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row

        # Create a minimal old database
        conn.executescript("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                schema_version INTEGER DEFAULT 2
            );
            INSERT INTO settings (id, schema_version) VALUES (1, 2);

            CREATE TABLE event_epg_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                leagues JSON NOT NULL
            );
        """)
        conn.commit()

        result = reconcile_schema(conn, schema_sql)

        # Should have added many columns to settings and event_epg_groups
        assert result.columns_added > 20
        assert "settings" in result.columns_by_table
        assert "event_epg_groups" in result.columns_by_table

        # Verify a specific column that caused #178
        cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(event_epg_groups)").fetchall()
        }
        assert "subscription_leagues" in cols
        assert "subscription_soccer_mode" in cols
        assert "subscription_soccer_followed_teams" in cols

        conn.close()


class TestConstraintPreservation:
    """Added columns must carry the verbatim schema.sql constraints.

    Regression tests for the reconciliation foot-gun: PRAGMA-based column
    rebuilding dropped NOT NULL/CHECK, so upgraded databases diverged from
    fresh installs (iua3.4).
    """

    REF_SCHEMA = """
    CREATE TABLE IF NOT EXISTS widgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'auto' CHECK (mode IN ('auto', 'manual')),
        weight INTEGER NOT NULL DEFAULT 1,
        note TEXT  -- trailing comment, with a comma: a, b
    );
    """

    def _upgraded(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE widgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );
            INSERT INTO widgets (name) VALUES ('existing');
        """)
        result = reconcile_schema(conn, self.REF_SCHEMA)
        assert result.errors == []
        assert sorted(result.columns_by_table["widgets"]) == ["mode", "note", "weight"]
        return conn

    def test_check_constraint_preserved(self):
        conn = self._upgraded()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO widgets (name, mode) VALUES ('bad', 'invalid-mode')"
            )
        conn.close()

    def test_not_null_preserved(self):
        conn = self._upgraded()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO widgets (name, weight) VALUES ('bad', NULL)")
        conn.close()

    def test_default_applied_to_existing_rows(self):
        conn = self._upgraded()
        row = conn.execute("SELECT mode, weight FROM widgets WHERE name='existing'").fetchone()
        assert row["mode"] == "auto"
        assert row["weight"] == 1
        conn.close()

    def test_illegal_alter_falls_back_without_error(self):
        """NOT NULL without default can't be ALTERed in — falls back to nullable."""
        ref = """
        CREATE TABLE things (
            id INTEGER PRIMARY KEY,
            label TEXT NOT NULL
        );
        """
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("CREATE TABLE things (id INTEGER PRIMARY KEY);")
        conn.execute("INSERT INTO things (id) VALUES (1)")
        result = reconcile_schema(conn, ref)
        assert result.errors == []
        assert result.columns_by_table["things"] == ["label"]
        # Column exists, degraded to nullable (existing rows have no value)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(things)").fetchall()}
        assert "label" in cols
        conn.close()

    def test_non_constant_default_falls_back(self):
        """DEFAULT CURRENT_TIMESTAMP is illegal in ADD COLUMN — degrade, don't fail."""
        ref = """
        CREATE TABLE stamps (
            id INTEGER PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("CREATE TABLE stamps (id INTEGER PRIMARY KEY);")
        result = reconcile_schema(conn, ref)
        assert result.errors == []
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(stamps)").fetchall()}
        assert "created_at" in cols
        conn.close()
