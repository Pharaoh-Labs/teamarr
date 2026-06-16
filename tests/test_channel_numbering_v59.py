"""Tests for v59 channel numbering overhaul.

Covers:
- Migration from v58 → v59 (mode detection, league starts, consolidation)
- Global channel mode (auto/manual) behavior
- Global consolidation mode behavior
- Settings API read/write round-trip
"""

import json
import sqlite3

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def v58_db():
    """Create a v58-like database for migration testing."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row

    # Minimal settings table with v58 columns
    db.execute("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            schema_version INTEGER DEFAULT 58,
            channel_range_start INTEGER DEFAULT 101,
            channel_range_end INTEGER,
            channel_numbering_mode TEXT DEFAULT 'strict_block',
            channel_sorting_scope TEXT DEFAULT 'per_group',
            channel_sort_by TEXT DEFAULT 'time',
            default_duplicate_event_handling TEXT DEFAULT 'consolidate'
        )
    """)
    db.execute("""
        INSERT INTO settings (id, schema_version, channel_range_start)
        VALUES (1, 58, 101)
    """)

    # Groups table with per-group channel settings
    db.execute("""
        CREATE TABLE event_epg_groups (
            id INTEGER PRIMARY KEY,
            name TEXT,
            leagues JSON,
            channel_assignment_mode TEXT DEFAULT 'auto',
            channel_start_number INTEGER,
            enabled INTEGER DEFAULT 1
        )
    """)

    return db


@pytest.fixture
def v59_db():
    """Create a fresh v59 database for unit testing."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row

    db.execute("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            schema_version INTEGER DEFAULT 59,
            channel_range_start INTEGER DEFAULT 101,
            channel_range_end INTEGER,
            global_channel_mode TEXT DEFAULT 'auto'
                CHECK(global_channel_mode IN ('auto', 'manual')),
            league_channel_starts JSON DEFAULT '{}',
            global_consolidation_mode TEXT DEFAULT 'consolidate'
                CHECK(global_consolidation_mode IN ('consolidate', 'separate'))
        )
    """)
    db.execute("""
        INSERT INTO settings (id, schema_version, channel_range_start,
                              global_channel_mode, league_channel_starts,
                              global_consolidation_mode)
        VALUES (1, 59, 101, 'auto', '{}', 'consolidate')
    """)

    db.execute("""
        CREATE TABLE event_epg_groups (
            id INTEGER PRIMARY KEY,
            name TEXT,
            sort_order INTEGER DEFAULT 0,
            total_stream_count INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        )
    """)

    db.execute("""
        CREATE TABLE managed_channels (
            id INTEGER PRIMARY KEY,
            event_epg_group_id INTEGER,
            channel_number TEXT,
            deleted_at TEXT,
            dispatcharr_channel_id INTEGER,
            channel_name TEXT,
            sport TEXT,
            league TEXT,
            event_start_time TEXT
        )
    """)

    db.execute("""
        CREATE TABLE channel_sort_priorities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sport TEXT NOT NULL,
            league TEXT,
            priority INTEGER NOT NULL DEFAULT 999,
            UNIQUE(sport, league)
        )
    """)

    return db


def _add_column_if_not_exists(conn, table, column, definition):
    """Helper matching connection.py's _add_column_if_not_exists."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError:
        pass


def _run_v59_migration(conn):
    """Run the v59 migration logic (mirrors connection.py)."""
    _add_column_if_not_exists(
        conn,
        "settings",
        "global_channel_mode",
        "TEXT DEFAULT 'auto' CHECK(global_channel_mode IN ('auto', 'manual'))",
    )
    _add_column_if_not_exists(conn, "settings", "league_channel_starts", "JSON DEFAULT '{}'")
    _add_column_if_not_exists(
        conn,
        "settings",
        "global_consolidation_mode",
        "TEXT DEFAULT 'consolidate'",
    )

    # Determine global channel mode from existing groups
    has_manual = 0
    try:
        has_manual = conn.execute(
            """SELECT COUNT(*) FROM event_epg_groups
               WHERE channel_assignment_mode = 'manual' AND enabled = 1"""
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pass

    global_mode = "manual" if has_manual > 0 else "auto"
    conn.execute(
        "UPDATE settings SET global_channel_mode = ? WHERE id = 1",
        (global_mode,),
    )

    # Build league_channel_starts from manual groups
    league_starts: dict[str, int] = {}
    if has_manual > 0:
        try:
            cursor = conn.execute(
                """SELECT leagues, channel_start_number
                   FROM event_epg_groups
                   WHERE channel_assignment_mode = 'manual'
                     AND channel_start_number IS NOT NULL
                     AND enabled = 1"""
            )
            for row in cursor.fetchall():
                try:
                    group_leagues = json.loads(row[0])
                    start_num = row[1]
                    if isinstance(group_leagues, list) and start_num:
                        for lc in group_leagues:
                            existing = league_starts.get(lc)
                            if existing is None or start_num < existing:
                                league_starts[lc] = start_num
                except (json.JSONDecodeError, TypeError):
                    continue
        except sqlite3.OperationalError:
            pass

        if league_starts:
            conn.execute(
                "UPDATE settings SET league_channel_starts = ? WHERE id = 1",
                (json.dumps(league_starts),),
            )

    # Set global_consolidation_mode from default_duplicate_event_handling
    try:
        row = conn.execute(
            "SELECT default_duplicate_event_handling FROM settings WHERE id = 1"
        ).fetchone()
        if row and row[0]:
            mode = row[0] if row[0] in ("consolidate", "separate") else "consolidate"
            conn.execute(
                "UPDATE settings SET global_consolidation_mode = ? WHERE id = 1",
                (mode,),
            )
    except sqlite3.OperationalError:
        pass

    # Force global sorting
    try:
        conn.execute(
            """UPDATE settings SET
                channel_sorting_scope = 'global',
                channel_sort_by = 'sport_league_time'
               WHERE id = 1"""
        )
    except sqlite3.OperationalError:
        pass

    conn.execute("UPDATE settings SET schema_version = 59 WHERE id = 1")


# ==========================================================================
# Migration tests: v58 → v59
# ==========================================================================


class TestV59MigrationAutoMode:
    """Migration when all groups use auto assignment."""

    def test_no_groups_defaults_to_auto(self, v58_db):
        _run_v59_migration(v58_db)
        row = v58_db.execute("SELECT global_channel_mode FROM settings WHERE id = 1").fetchone()
        assert row[0] == "auto"

    def test_auto_groups_stay_auto(self, v58_db):
        v58_db.execute(
            "INSERT INTO event_epg_groups (name, leagues, channel_assignment_mode, enabled) "
            "VALUES ('NHL', '[\"nhl\"]', 'auto', 1)"
        )
        _run_v59_migration(v58_db)
        row = v58_db.execute("SELECT global_channel_mode FROM settings WHERE id = 1").fetchone()
        assert row[0] == "auto"

    def test_disabled_manual_groups_ignored(self, v58_db):
        v58_db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, channel_assignment_mode, channel_start_number, enabled) "
            "VALUES ('NFL', '[\"nfl\"]', 'manual', 5001, 0)"
        )
        _run_v59_migration(v58_db)
        row = v58_db.execute("SELECT global_channel_mode FROM settings WHERE id = 1").fetchone()
        assert row[0] == "auto"


class TestV59MigrationManualMode:
    """Migration when manual groups exist."""

    def test_manual_group_sets_global_manual(self, v58_db):
        v58_db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, channel_assignment_mode, channel_start_number, enabled) "
            "VALUES ('NFL', '[\"nfl\"]', 'manual', 5001, 1)"
        )
        _run_v59_migration(v58_db)
        row = v58_db.execute("SELECT global_channel_mode FROM settings WHERE id = 1").fetchone()
        assert row[0] == "manual"

    def test_league_starts_built_from_manual_groups(self, v58_db):
        v58_db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, channel_assignment_mode, channel_start_number, enabled) "
            "VALUES ('NFL', '[\"nfl\"]', 'manual', 5001, 1)"
        )
        v58_db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, channel_assignment_mode, channel_start_number, enabled) "
            "VALUES ('NBA', '[\"nba\"]', 'manual', 6001, 1)"
        )
        _run_v59_migration(v58_db)
        row = v58_db.execute("SELECT league_channel_starts FROM settings WHERE id = 1").fetchone()
        starts = json.loads(row[0])
        assert starts == {"nfl": 5001, "nba": 6001}

    def test_lowest_start_wins_for_same_league(self, v58_db):
        """If two groups cover the same league, take the lower start number."""
        v58_db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, channel_assignment_mode, channel_start_number, enabled) "
            "VALUES ('Group A', '[\"nfl\"]', 'manual', 5001, 1)"
        )
        v58_db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, channel_assignment_mode, channel_start_number, enabled) "
            "VALUES ('Group B', '[\"nfl\"]', 'manual', 4001, 1)"
        )
        _run_v59_migration(v58_db)
        starts = json.loads(
            v58_db.execute("SELECT league_channel_starts FROM settings WHERE id = 1").fetchone()[0]
        )
        assert starts["nfl"] == 4001

    def test_multi_league_group_applies_start_to_all(self, v58_db):
        v58_db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, channel_assignment_mode, channel_start_number, enabled) "
            "VALUES ('Sports', '[\"nfl\", \"nba\", \"mlb\"]', 'manual', 3001, 1)"
        )
        _run_v59_migration(v58_db)
        starts = json.loads(
            v58_db.execute("SELECT league_channel_starts FROM settings WHERE id = 1").fetchone()[0]
        )
        assert starts == {"nfl": 3001, "nba": 3001, "mlb": 3001}

    def test_null_start_number_skipped(self, v58_db):
        v58_db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, channel_assignment_mode, channel_start_number, enabled) "
            "VALUES ('NFL', '[\"nfl\"]', 'manual', NULL, 1)"
        )
        _run_v59_migration(v58_db)
        starts = json.loads(
            v58_db.execute("SELECT league_channel_starts FROM settings WHERE id = 1").fetchone()[0]
        )
        assert starts == {}


class TestV59MigrationConsolidation:
    """Migration of consolidation mode."""

    def test_consolidate_preserved(self, v58_db):
        v58_db.execute(
            "UPDATE settings SET default_duplicate_event_handling = 'consolidate' WHERE id = 1"
        )
        _run_v59_migration(v58_db)
        row = v58_db.execute(
            "SELECT global_consolidation_mode FROM settings WHERE id = 1"
        ).fetchone()
        assert row[0] == "consolidate"

    def test_separate_preserved(self, v58_db):
        v58_db.execute(
            "UPDATE settings SET default_duplicate_event_handling = 'separate' WHERE id = 1"
        )
        _run_v59_migration(v58_db)
        row = v58_db.execute(
            "SELECT global_consolidation_mode FROM settings WHERE id = 1"
        ).fetchone()
        assert row[0] == "separate"

    def test_unknown_value_defaults_to_consolidate(self, v58_db):
        v58_db.execute(
            "UPDATE settings SET default_duplicate_event_handling = 'weird_value' WHERE id = 1"
        )
        _run_v59_migration(v58_db)
        row = v58_db.execute(
            "SELECT global_consolidation_mode FROM settings WHERE id = 1"
        ).fetchone()
        assert row[0] == "consolidate"


class TestV59MigrationSchemaVersion:
    """Schema version bump."""

    def test_version_bumped_to_59(self, v58_db):
        _run_v59_migration(v58_db)
        row = v58_db.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        assert row[0] == 59


class TestV59MigrationIdempotent:
    """Running migration twice is safe."""

    def test_double_migration_safe(self, v58_db):
        v58_db.execute(
            "INSERT INTO event_epg_groups "
            "(name, leagues, channel_assignment_mode, channel_start_number, enabled) "
            "VALUES ('NFL', '[\"nfl\"]', 'manual', 5001, 1)"
        )
        _run_v59_migration(v58_db)
        _run_v59_migration(v58_db)  # Should not error
        row = v58_db.execute(
            "SELECT global_channel_mode, league_channel_starts FROM settings WHERE id = 1"
        ).fetchone()
        assert row[0] == "manual"
        assert json.loads(row[1]) == {"nfl": 5001}


# ==========================================================================
# Settings read/write round-trip tests
# ==========================================================================


class TestChannelNumberingSettings:
    """Test the settings dataclass read/write."""

    def test_read_defaults(self, v59_db):
        from teamarr.database.settings.read import get_channel_numbering_settings

        settings = get_channel_numbering_settings(v59_db)
        assert settings.global_channel_mode == "auto"
        assert settings.league_channel_starts == {}
        assert settings.global_consolidation_mode == "consolidate"

    def test_read_manual_with_starts(self, v59_db):
        from teamarr.database.settings.read import get_channel_numbering_settings

        v59_db.execute(
            "UPDATE settings SET global_channel_mode = 'manual', "
            "league_channel_starts = ? WHERE id = 1",
            (json.dumps({"nfl": 5001, "nba": 6001}),),
        )
        settings = get_channel_numbering_settings(v59_db)
        assert settings.global_channel_mode == "manual"
        assert settings.league_channel_starts == {"nfl": 5001, "nba": 6001}

    def test_read_separate_consolidation(self, v59_db):
        from teamarr.database.settings.read import get_channel_numbering_settings

        v59_db.execute("UPDATE settings SET global_consolidation_mode = 'separate' WHERE id = 1")
        settings = get_channel_numbering_settings(v59_db)
        assert settings.global_consolidation_mode == "separate"

    def test_read_malformed_json_defaults_empty(self, v59_db):
        from teamarr.database.settings.read import get_channel_numbering_settings

        v59_db.execute("UPDATE settings SET league_channel_starts = 'not-json' WHERE id = 1")
        settings = get_channel_numbering_settings(v59_db)
        assert settings.league_channel_starts == {}


# ==========================================================================
# Global consolidation mode behavior tests
# ==========================================================================


class TestGlobalConsolidationMode:
    """Test get_global_consolidation_mode function."""

    def test_returns_consolidate_default(self, v59_db):
        from teamarr.database.channel_numbers import get_global_consolidation_mode

        assert get_global_consolidation_mode(v59_db) == "consolidate"

    def test_returns_separate_when_set(self, v59_db):
        from teamarr.database.channel_numbers import get_global_consolidation_mode

        v59_db.execute("UPDATE settings SET global_consolidation_mode = 'separate' WHERE id = 1")
        assert get_global_consolidation_mode(v59_db) == "separate"


# ==========================================================================
# Global channel mode behavior tests
# ==========================================================================


class TestGlobalChannelMode:
    """Test get_global_channel_mode function."""

    def test_returns_auto_default(self, v59_db):
        from teamarr.database.channel_numbers import get_global_channel_mode

        assert get_global_channel_mode(v59_db) == "auto"

    def test_returns_manual_when_set(self, v59_db):
        from teamarr.database.channel_numbers import get_global_channel_mode

        v59_db.execute("UPDATE settings SET global_channel_mode = 'manual' WHERE id = 1")
        assert get_global_channel_mode(v59_db) == "manual"
