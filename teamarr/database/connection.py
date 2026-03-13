"""Database connection management.

Simple SQLite connection handling with schema initialization.
"""

import json
import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from teamarr.database.checkpoint_v43 import apply_checkpoint_v43

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "teamarr.db"

# Schema file location
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Global flag for V1 database detection (set during init, checked by migration)
_v1_database_detected = False


def is_v1_database_detected() -> bool:
    """Check if a V1 database was detected during initialization."""
    return _v1_database_detected


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a database connection.

    Args:
        db_path: Path to database file. Uses DEFAULT_DB_PATH if not specified.

    Returns:
        SQLite connection with row factory set to sqlite3.Row
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH

    # timeout=30: Wait up to 30 seconds if database is locked by another connection
    # check_same_thread=False: Allow connection to be used across threads (required for FastAPI)
    conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Enable Write-Ahead Logging for better concurrent access
    # WAL allows readers to not block writers and vice versa
    conn.execute("PRAGMA journal_mode=WAL")

    # Wait up to 30 seconds if a table is locked (milliseconds)
    conn.execute("PRAGMA busy_timeout=30000")

    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


@contextmanager
def get_db(db_path: Path | str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections.

    Usage:
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM teams")
            teams = cursor.fetchall()
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize database with schema.

    Creates tables if they don't exist. Safe to call multiple times.
    Also seeds TSDB cache from distributed seed file if needed.

    Args:
        db_path: Path to database file. Uses DEFAULT_DB_PATH if not specified.

    Raises:
        RuntimeError: If database file exists but is not a valid V2 database
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    schema_sql = SCHEMA_PATH.read_text()

    try:
        with get_db(db_path) as conn:
            # First, verify this is a valid V2-compatible database by checking integrity
            # and querying a core table. This catches both corruption AND V1 databases.
            _verify_database_integrity(conn, path)

            # If V1 database detected, skip schema initialization - only migration endpoints work
            if _v1_database_detected:
                logger.info("[MIGRATE] Skipping V2 schema initialization for V1 database")
                return

            # Pre-migration: rename league_id_alias -> league_id before schema.sql runs
            # (schema.sql references league_id column in INSERT OR REPLACE)
            _rename_league_id_column_if_needed(conn)

            # Pre-migration: add league_alias column before schema.sql runs
            # (schema.sql INSERT OR REPLACE references league_alias column)
            _add_league_alias_column_if_needed(conn)

            # Pre-migration: add gracenote_category column before schema.sql runs
            # (schema.sql INSERT OR REPLACE references gracenote_category column)
            _add_gracenote_category_column_if_needed(conn)

            # Pre-migration: add logo_url_dark column before schema.sql runs
            # (schema.sql INSERT OR REPLACE references logo_url_dark column)
            _add_logo_url_dark_column_if_needed(conn)

            # Pre-migration: add series_slug_pattern column before schema.sql runs
            # (schema.sql UPDATE statements reference series_slug_pattern column)
            _add_series_slug_pattern_column_if_needed(conn)

            # Pre-migration: add fallback_provider and fallback_league_id columns
            # (schema.sql INSERT OR REPLACE references these columns)
            _add_fallback_columns_if_needed(conn)

            # Pre-migration: add tsdb_tier column before schema.sql runs
            # (schema.sql INSERT OR REPLACE references tsdb_tier column)
            _add_tsdb_tier_column_if_needed(conn)

            # Pre-migration: rename exception keywords columns before schema.sql runs
            # (schema.sql INSERT OR IGNORE references label and match_terms columns)
            _migrate_exception_keywords_columns(conn)

            # Pre-migration: ensure tsdb_api_key column exists before startup queries
            # (get_display_settings selects this column; missing for some upgrade paths)
            _add_column_if_not_exists(conn, "settings", "tsdb_api_key", "TEXT")

            # Pre-migration: recreate settings table for v62 lifecycle timing overhaul
            # (SQLite CHECK constraints require table recreation to update)
            _migrate_settings_for_v65(conn)

            # Pre-migration: add feed_team_id column before schema.sql runs
            # (schema.sql unique index idx_mc_unique_event_v2 references this column)
            _add_column_if_not_exists(conn, "managed_channels", "feed_team_id", "TEXT")

            # Apply schema (creates tables if missing, INSERT OR REPLACE updates seed data)
            conn.executescript(schema_sql)
            # Run remaining migrations for existing databases
            _run_migrations(conn)
            # Seed TSDB cache if empty or incomplete
            _seed_tsdb_cache_if_needed(conn)

            # Final verification: ensure settings table exists and is queryable
            conn.execute("SELECT id FROM settings LIMIT 1")
    except sqlite3.DatabaseError as e:
        if "file is not a database" in str(e):
            logger.error(
                f"Database file '{path}' exists but is not compatible with Teamarr V2. "
                "This usually means you're trying to use a V1 database. "
                "V2 requires a fresh database - please either:\n"
                "  1. Use a different data directory for V2, or\n"
                "  2. Backup and delete the existing database file"
            )
            raise RuntimeError(
                f"Incompatible database file at '{path}'. "
                "V2 is not compatible with V1 databases. "
                "Please use a fresh data directory or delete the existing database."
            ) from e
        raise


def _verify_database_integrity(conn: sqlite3.Connection, path: Path) -> None:
    """Verify database is valid and compatible with V2.

    This runs BEFORE schema initialization to catch:
    1. Corrupt database files ("file is not a database")
    2. V1 databases (different schema, incompatible)

    Args:
        conn: Database connection
        path: Path to database file for error messages

    Raises:
        RuntimeError: If database is a V1 database
        sqlite3.DatabaseError: If database file is corrupt
    """
    # Force an actual read from the file to detect corruption early
    # PRAGMA integrity_check would be thorough but slow; just query sqlite_master
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 100")
        existing_tables = {row["name"] for row in cursor.fetchall()}
    except sqlite3.DatabaseError:
        # Let the outer handler deal with "file is not a database" errors
        raise

    # Check for V1-specific tables that indicate an incompatible database
    # These tables exist only in V1 and NOT in V2
    v1_indicators = {
        "schedule_cache",  # V1 caching
        "league_config",  # V1 league configuration
        "h2h_cache",  # V1 head-to-head (removed in V2)
        "error_log",  # V1 error logging
        "soccer_cache_meta",  # V1 soccer-specific cache
        "team_stats_cache",  # V1 stats cache
    }
    v1_tables_found = v1_indicators & existing_tables

    if v1_tables_found:
        logger.warning(
            f"Database file '{path}' appears to be a V1 database. "
            f"Found V1-specific tables: {v1_tables_found}. "
            "V2 migration page will be shown to the user."
        )
        # Set global flag for V1 detection - don't raise error, let migration handle it
        global _v1_database_detected
        _v1_database_detected = True


def _rename_league_id_column_if_needed(conn: sqlite3.Connection) -> None:
    """Rename league_id_alias -> league_id if needed.

    This MUST run before schema.sql because schema.sql INSERT OR REPLACE
    statements reference the new column name.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if old column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "league_id_alias" in columns and "league_id" not in columns:
        conn.execute("ALTER TABLE leagues RENAME COLUMN league_id_alias TO league_id")
        logger.info("[MIGRATE] Renamed leagues.league_id_alias -> league_id")


def _add_league_alias_column_if_needed(conn: sqlite3.Connection) -> None:
    """Add league_alias column if it doesn't exist.

    This MUST run before schema.sql because schema.sql INSERT OR REPLACE
    statements reference the league_alias column.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "league_alias" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN league_alias TEXT")
        logger.info("[MIGRATE] Added leagues.league_alias column")


def _add_gracenote_category_column_if_needed(conn: sqlite3.Connection) -> None:
    """Add gracenote_category column if it doesn't exist.

    This MUST run before schema.sql because schema.sql INSERT OR REPLACE
    statements reference the gracenote_category column.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "gracenote_category" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN gracenote_category TEXT")
        logger.info("[MIGRATE] Added leagues.gracenote_category column")


def _add_logo_url_dark_column_if_needed(conn: sqlite3.Connection) -> None:
    """Add logo_url_dark column if it doesn't exist.

    This MUST run before schema.sql because schema.sql INSERT OR REPLACE
    statements reference the logo_url_dark column.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "logo_url_dark" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN logo_url_dark TEXT")
        logger.info("[MIGRATE] Added leagues.logo_url_dark column")


def _add_series_slug_pattern_column_if_needed(conn: sqlite3.Connection) -> None:
    """Add series_slug_pattern column if it doesn't exist.

    This is needed for Cricbuzz auto-discovery of current season series IDs.
    MUST run before schema.sql because UPDATE statements reference this column.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    # Check if column exists
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "series_slug_pattern" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN series_slug_pattern TEXT")
        logger.info("[MIGRATE] Added leagues.series_slug_pattern column")


def _add_fallback_columns_if_needed(conn: sqlite3.Connection) -> None:
    """Add fallback_provider and fallback_league_id columns if they don't exist.

    These columns enable provider fallback for leagues where the primary provider
    may have limited availability (e.g., TSDB premium vs free tier for cricket).
    MUST run before schema.sql because INSERT OR REPLACE references these columns.
    """
    # Check if leagues table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct columns

    # Check which columns exist
    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "fallback_provider" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN fallback_provider TEXT")
        logger.info("[MIGRATE] Added leagues.fallback_provider column")

    if "fallback_league_id" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN fallback_league_id TEXT")
        logger.info("[MIGRATE] Added leagues.fallback_league_id column")


def _add_tsdb_tier_column_if_needed(conn: sqlite3.Connection) -> None:
    """Add tsdb_tier column if it doesn't exist.

    MUST run before schema.sql because INSERT OR REPLACE references this column.
    """
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'")
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct column

    cursor = conn.execute("PRAGMA table_info(leagues)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "tsdb_tier" not in columns:
        conn.execute("ALTER TABLE leagues ADD COLUMN tsdb_tier TEXT")
        logger.info("[MIGRATE] Added leagues.tsdb_tier column")


def _migrate_exception_keywords_columns(conn: sqlite3.Connection) -> None:
    """Migrate exception keywords table: keywords -> match_terms, display_name -> label.

    MUST run before schema.sql because INSERT OR IGNORE references the new column names.
    This pre-migration recreates the table with new column names and migrates data.
    """
    # Check if table exists
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='consolidation_exception_keywords'"  # noqa: E501
    )
    if not cursor.fetchone():
        return  # Fresh database, schema.sql will create table with correct columns

    # Check if migration needed (old columns exist)
    cursor = conn.execute("PRAGMA table_info(consolidation_exception_keywords)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "label" in columns and "match_terms" in columns:
        return  # Already migrated

    if "keywords" not in columns:
        return  # Unknown schema, skip

    logger.info(
        "[PRE-MIGRATE] Migrating exception keywords: keywords -> match_terms, display_name -> label"
    )

    # Get existing data
    cursor = conn.execute("""
        SELECT id, created_at, keywords, behavior, display_name, enabled
        FROM consolidation_exception_keywords
    """)
    existing_rows = cursor.fetchall()

    # Drop old table
    conn.execute("DROP TABLE consolidation_exception_keywords")

    # Create new table with updated schema
    conn.execute("""
        CREATE TABLE consolidation_exception_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            label TEXT NOT NULL UNIQUE,
            match_terms TEXT NOT NULL,
            behavior TEXT NOT NULL DEFAULT 'consolidate'
                CHECK(behavior IN ('consolidate', 'separate', 'ignore')),
            enabled BOOLEAN DEFAULT 1
        )
    """)

    # Migrate data - use display_name as label if set, otherwise first keyword
    for row in existing_rows:
        keywords = row["keywords"] or ""
        display_name = row["display_name"]

        # Determine label: use display_name if set, otherwise first keyword
        if display_name:
            label = display_name
        else:
            first_keyword = keywords.split(",")[0].strip() if keywords else "Unknown"
            label = first_keyword

        conn.execute(
            """INSERT INTO consolidation_exception_keywords
               (id, created_at, label, match_terms, behavior, enabled)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                row["id"],
                row["created_at"],
                label,
                keywords,
                row["behavior"],
                row["enabled"],
            ),
        )

    # Recreate indexes
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exception_keywords_enabled
        ON consolidation_exception_keywords(enabled)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exception_keywords_behavior
        ON consolidation_exception_keywords(behavior)
    """)

    logger.info("[PRE-MIGRATE] Migrated %d exception keywords", len(existing_rows))


def _migrate_settings_for_v65(conn: sqlite3.Connection) -> None:
    """Pre-migration: Recreate settings table for v65 lifecycle timing overhaul.

    SQLite CHECK constraints are baked at table creation and can't be altered.
    The v65 migration changes channel_create_timing CHECK from 6 options to 2,
    and channel_delete_timing CHECK from 7 options to 2. This requires dropping
    and recreating the table so executescript can recreate it with new constraints.

    Data is backed up to _settings_v65_backup and restored in _run_migrations.
    """
    try:
        row = conn.execute(
            "SELECT schema_version FROM settings WHERE id = 1"
        ).fetchone()
        if not row or row[0] >= 65:
            return
    except Exception:
        return  # Table doesn't exist yet (fresh install)

    # Add new columns first so backup includes them
    for col in ["channel_pre_buffer_minutes", "channel_post_buffer_minutes"]:
        try:
            conn.execute(
                f"ALTER TABLE settings ADD COLUMN {col} INTEGER DEFAULT 60"
            )
        except Exception:
            pass  # Already exists

    # Backup all settings data (CREATE TABLE AS copies data, no constraints)
    conn.execute("DROP TABLE IF EXISTS _settings_v65_backup")
    conn.execute(
        "CREATE TABLE _settings_v65_backup "
        "AS SELECT * FROM settings"
    )

    # Drop settings table — executescript will recreate with new CHECK constraints
    conn.execute("DROP TABLE settings")

    logger.info(
        "[PRE-MIGRATE] Settings table dropped for v65 lifecycle timing migration"
    )


def _seed_tsdb_cache_if_needed(conn: sqlite3.Connection) -> None:
    """Seed TSDB cache from distributed seed file if needed."""
    from teamarr.database.seed import seed_if_needed

    result = seed_if_needed(conn)
    if result and result.get("seeded"):
        logger.info(
            f"Seeded TSDB cache: {result.get('teams_added', 0)} teams, "
            f"{result.get('leagues_added', 0)} leagues"
        )


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run database migrations for existing databases.

    Uses schema_version in settings table to track applied migrations.
    Safe to call multiple times - checks version before running.

    Schema versions:
    - 2: Initial V2 schema
    - 3: Teams consolidated (league -> primary_league + leagues array)
    - 4: Added eng.2 (Championship), eng.3 (League One), nrl leagues; fixed NRL logo
    - 5: Renamed league_id_alias -> league_id
    - 6: Added league_alias column, fixed managed_channels UNIQUE constraint
    - 7: Added gracenote_category column
    - 8: Added custom_regex_date/time columns to event_epg_groups
    - 9: Added keyword_ordering to change_source CHECK constraint
    - 10: Updated channel timing CHECK constraints
    - 11: Removed UNIQUE constraint from tvg_id
    - 12: Removed per-group timing settings
    - 13: Added display_name to event_epg_groups
    - 14: Added streams_excluded to event_epg_groups
    - 15: Renamed filtered_no_match -> failed_count (clearer stat categories)
    - 16-22: Various additions (see individual migrations)
    - 23: Added default_channel_profile_ids to settings
    - 24: Added excluded and exclusion_reason to epg_matched_streams
    - 25: Changed event_epg_groups name uniqueness from global to per-account
    - 46: Added stream_profile_id to event_epg_groups
    - 47: Added stream_timezone to event_epg_groups
    - 48: Added channel_reset_enabled and channel_reset_cron to settings
    - 49: Added combat sports custom regex columns (fighters, event_name, config)
    """
    # Get current schema version
    try:
        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        current_version = row["schema_version"] if row else 2
    except Exception:
        current_version = 2

    # ==========================================================================
    # CHECKPOINT v43: Consolidated migration for versions 2-43
    # ==========================================================================
    # Instead of running 43 individual procedural migrations, we use a single
    # idempotent checkpoint that ensures the v43 schema state regardless of
    # starting version. This is safer and handles partial migrations better.
    #
    # The checkpoint replaces all v3-v43 migrations below. The old migration
    # code is preserved but will be skipped since version becomes 43.
    # ==========================================================================
    if current_version < 43:
        logger.info("[MIGRATE] Applying v43 checkpoint (from v%d)", current_version)
        apply_checkpoint_v43(conn, current_version)
        current_version = 43
        logger.info("[MIGRATE] Checkpoint complete, now at v43")

    # Legacy v3-v43 migrations removed — checkpoint system stable since v2.1.0.

    # ==========================================================================
    # v44+: NEW MIGRATIONS (using checkpoint patterns)
    # ==========================================================================

    # v44: Update Check Settings
    # Adds settings for update notifications (GitHub releases/commits)
    if current_version < 44:
        _add_column_if_not_exists(conn, "settings", "update_check_enabled", "BOOLEAN DEFAULT 1")
        _add_column_if_not_exists(conn, "settings", "update_notify_stable", "BOOLEAN DEFAULT 1")
        _add_column_if_not_exists(conn, "settings", "update_notify_dev", "BOOLEAN DEFAULT 1")
        _add_column_if_not_exists(
            conn, "settings", "update_github_owner", "TEXT DEFAULT 'Pharaoh-Labs'"
        )
        _add_column_if_not_exists(conn, "settings", "update_github_repo", "TEXT DEFAULT 'teamarr'")
        _add_column_if_not_exists(conn, "settings", "update_dev_branch", "TEXT DEFAULT 'dev'")
        _add_column_if_not_exists(
            conn, "settings", "update_auto_detect_branch", "BOOLEAN DEFAULT 1"
        )
        conn.execute("UPDATE settings SET schema_version = 44 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 44 (update check settings)")
        current_version = 44

    # ==========================================================================
    # v45: Logo Cleanup Setting
    # ==========================================================================
    # Adds cleanup_unused_logos setting to call Dispatcharr's bulk cleanup API
    # after EPG generation instead of per-channel logo deletion
    if current_version < 45:
        _add_column_if_not_exists(
            conn, "settings", "cleanup_unused_logos", "BOOLEAN DEFAULT 0"
        )
        conn.execute("UPDATE settings SET schema_version = 45 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 45 (logo cleanup setting)")
        current_version = 45

    # ==========================================================================
    # v46: Stream Profile Support
    # ==========================================================================
    # Adds stream_profile_id to settings (global default) and event_epg_groups (per-group override)
    if current_version < 46:
        _add_column_if_not_exists(
            conn, "settings", "default_stream_profile_id", "INTEGER"
        )
        _add_column_if_not_exists(
            conn, "event_epg_groups", "stream_profile_id", "INTEGER"
        )
        conn.execute("UPDATE settings SET schema_version = 46 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 46 (stream profile support)")
        current_version = 46

    # ==========================================================================
    # v47: Stream Timezone Support
    # ==========================================================================
    # Adds stream_timezone to event_epg_groups for interpreting dates/times in stream names
    # when providers use a different timezone than the user's local timezone
    if current_version < 47:
        _add_column_if_not_exists(conn, "event_epg_groups", "stream_timezone", "TEXT")
        conn.execute("UPDATE settings SET schema_version = 47 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 47 (stream timezone support)")
        current_version = 47

    # ==========================================================================
    # v48: Scheduled Channel Reset
    # ==========================================================================
    # Adds channel_reset_enabled and channel_reset_cron to settings for scheduling
    # periodic channel purges (helps users with Jellyfin logo caching issues)
    if current_version < 48:
        _add_column_if_not_exists(conn, "settings", "channel_reset_enabled", "BOOLEAN DEFAULT 0")
        _add_column_if_not_exists(conn, "settings", "channel_reset_cron", "TEXT")
        conn.execute("UPDATE settings SET schema_version = 48 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 48 (scheduled channel reset)")
        current_version = 48

    # ==========================================================================
    # v49: Combat Sports Custom Regex Columns
    # ==========================================================================
    # Adds custom regex columns for EVENT_CARD type events (UFC, Boxing, MMA)
    # - custom_regex_fighters: Extract fighter names from stream titles
    # - custom_regex_event_name: Extract event name from stream titles
    # - custom_regex_config: JSON structure for organized event-type regex patterns
    if current_version < 49:
        _add_column_if_not_exists(conn, "event_epg_groups", "custom_regex_fighters", "TEXT")
        _add_column_if_not_exists(
            conn, "event_epg_groups", "custom_regex_fighters_enabled", "BOOLEAN DEFAULT 0"
        )
        _add_column_if_not_exists(conn, "event_epg_groups", "custom_regex_event_name", "TEXT")
        _add_column_if_not_exists(
            conn, "event_epg_groups", "custom_regex_event_name_enabled", "BOOLEAN DEFAULT 0"
        )
        _add_column_if_not_exists(conn, "event_epg_groups", "custom_regex_config", "JSON")
        conn.execute("UPDATE settings SET schema_version = 49 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 49 (combat sports custom regex)")
        current_version = 49

    # ==========================================================================
    # v50: Soccer Selection Modes
    # ==========================================================================
    # Adds soccer_mode column for granular soccer league selection:
    # - 'all': Subscribe to all soccer leagues, auto-include new ones
    # - 'teams': Follow selected teams across their competitions
    # - 'manual': Explicit league selection (preserves trimmed selections)
    # - NULL: Non-soccer groups
    #
    # Migration logic:
    # - Groups with ALL available soccer leagues -> 'all'
    # - Groups with a SUBSET of soccer leagues -> 'manual' (preserve user's work)
    if current_version < 50:
        _add_column_if_not_exists(conn, "event_epg_groups", "soccer_mode", "TEXT")

        # Get all available soccer leagues from the leagues table
        # Wrap in try-except for minimal test databases that may not have leagues table
        all_soccer_leagues: set[str] = set()
        try:
            cursor = conn.execute(
                "SELECT league_code FROM leagues WHERE sport = 'soccer' AND enabled = 1"
            )
            all_soccer_leagues = {row[0] for row in cursor.fetchall()}
        except sqlite3.OperationalError:
            # Table doesn't exist or missing columns - skip migration logic
            pass

        total_soccer_count = len(all_soccer_leagues)

        if total_soccer_count > 0:
            # Migrate existing groups that contain soccer leagues
            cursor = conn.execute(
                "SELECT id, leagues FROM event_epg_groups WHERE leagues IS NOT NULL"
            )
            for row in cursor.fetchall():
                group_id = row[0]
                try:
                    leagues_json = row[1]
                    if not leagues_json:
                        continue
                    group_leagues = set(json.loads(leagues_json))

                    # Find soccer leagues in this group
                    group_soccer = group_leagues & all_soccer_leagues

                    if not group_soccer:
                        # No soccer leagues in this group - leave soccer_mode as NULL
                        continue

                    if group_soccer == all_soccer_leagues:
                        # Has ALL soccer leagues -> 'all' mode
                        conn.execute(
                            "UPDATE event_epg_groups SET soccer_mode = 'all' WHERE id = ?",
                            (group_id,),
                        )
                    else:
                        # Has SUBSET of soccer leagues -> 'manual' mode (preserve their selection)
                        conn.execute(
                            "UPDATE event_epg_groups SET soccer_mode = 'manual' WHERE id = ?",
                            (group_id,),
                        )
                except (json.JSONDecodeError, TypeError):
                    # Skip groups with invalid JSON
                    continue

        conn.execute("UPDATE settings SET schema_version = 50 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 50 (soccer selection modes)")
        current_version = 50

    # v51: Add soccer_followed_teams for 'teams' mode
    # Stores [{provider, team_id, name}] for teams the user wants to follow
    # Leagues are auto-discovered from team_cache at processing time
    if current_version < 51:
        _add_column_if_not_exists(conn, "event_epg_groups", "soccer_followed_teams", "TEXT")
        conn.execute("UPDATE settings SET schema_version = 51 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 51 (soccer followed teams)")
        current_version = 51

    # v52: Bypass team filter for playoffs (issue #70)
    # Global default in settings, per-group override in event_epg_groups
    if current_version < 52:
        _add_column_if_not_exists(
            conn, "settings", "default_bypass_filter_for_playoffs", "BOOLEAN DEFAULT 0"
        )
        _add_column_if_not_exists(
            conn, "event_epg_groups", "bypass_filter_for_playoffs", "BOOLEAN"
        )
        conn.execute("UPDATE settings SET schema_version = 52 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 52 (playoff filter bypass)")
        current_version = 52

    # v53: Bump api_timeout default from 10 to 30
    # The DispatcharrClient always used 30s effectively, but the DB setting
    # (which was never wired up) defaulted to 10. Now that we wire it up,
    # bump existing users from 10 → 30 to avoid a timeout regression.
    if current_version < 53:
        conn.execute("UPDATE settings SET api_timeout = 30 WHERE api_timeout = 10 AND id = 1")
        conn.execute("UPDATE settings SET api_retry_count = 5 WHERE api_retry_count = 3 AND id = 1")
        conn.execute("UPDATE settings SET schema_version = 53 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 53 (api timeout/retry defaults)")
        current_version = 53

    # v54: Add scheduled backup settings columns
    # Automatic database backups with rotation and protection
    if current_version < 54:
        _add_column_if_not_exists(
            conn, "settings", "scheduled_backup_enabled", "BOOLEAN DEFAULT 0"
        )
        _add_column_if_not_exists(
            conn, "settings", "scheduled_backup_cron", "TEXT DEFAULT '0 3 * * *'"
        )
        _add_column_if_not_exists(
            conn, "settings", "scheduled_backup_max_count", "INTEGER DEFAULT 7"
        )
        _add_column_if_not_exists(
            conn, "settings", "scheduled_backup_path", "TEXT DEFAULT './data/backups'"
        )
        conn.execute("UPDATE settings SET schema_version = 54 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 54 (scheduled backup settings)")
        current_version = 54

    # v55: Gold Zone (Olympics Special Feature)
    # Consolidates "Gold Zone" streams into a single channel with external EPG
    if current_version < 55:
        _add_column_if_not_exists(conn, "settings", "gold_zone_enabled", "BOOLEAN DEFAULT 0")
        _add_column_if_not_exists(conn, "settings", "gold_zone_channel_number", "INTEGER")
        conn.execute("UPDATE settings SET schema_version = 55 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 55 (gold zone)")
        current_version = 55

    if current_version < 56:
        _add_column_if_not_exists(conn, "settings", "gold_zone_channel_group_id", "INTEGER")
        _add_column_if_not_exists(conn, "settings", "gold_zone_channel_profile_ids", "TEXT")
        _add_column_if_not_exists(conn, "settings", "gold_zone_stream_profile_id", "INTEGER")
        conn.execute("UPDATE settings SET schema_version = 56 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 56 (gold zone profiles)")
        current_version = 56

    # v57: Re-apply v52 columns for databases affected by PR #142 merge
    # PR #142 (backup feature) was branched before v52 existed. When merged,
    # it deleted the v52 migration but still advanced schema_version past 52,
    # so the restored v52 migration was skipped on affected databases.
    # This idempotently adds the columns that v52 should have created.
    if current_version < 57:
        _add_column_if_not_exists(
            conn, "settings", "default_bypass_filter_for_playoffs", "BOOLEAN DEFAULT 0"
        )
        _add_column_if_not_exists(
            conn, "event_epg_groups", "bypass_filter_for_playoffs", "BOOLEAN"
        )
        conn.execute("UPDATE settings SET schema_version = 57 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 57 (re-apply v52 playoff bypass columns)")
        current_version = 57

    # ==========================================================================
    # v58: Sports Subscription — Decouple sports from event groups
    # ==========================================================================
    # Replaces per-group sport/league/template configuration with a single
    # global subscription. Groups become sport-agnostic stream suppliers.
    # Removes parent-child hierarchy.
    #
    # Steps:
    # 1. Create sports_subscription + subscription_templates tables
    # 2. Collect all unique leagues from enabled groups → subscription
    # 3. Merge soccer config (prefer 'all' > 'teams' with team union > 'manual')
    # 4. Migrate group_templates → subscription_templates (deduplicate)
    # 5. Migrate legacy template_id → subscription_templates defaults
    # 6. Set all groups: group_mode='multi', parent_group_id=NULL
    # 7. Update each group's leagues to match subscription (downgrade safety)
    if current_version < 58:
        # 1. Create new tables (idempotent via IF NOT EXISTS)
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
                leagues JSON,
                FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
            );
        """)

        # 2. Collect all unique leagues from ALL enabled groups
        all_leagues: set[str] = set()
        cursor = conn.execute(
            "SELECT leagues FROM event_epg_groups WHERE enabled = 1 AND leagues IS NOT NULL"
        )
        for row in cursor.fetchall():
            try:
                group_leagues = json.loads(row[0])
                if isinstance(group_leagues, list):
                    all_leagues.update(group_leagues)
            except (json.JSONDecodeError, TypeError):
                continue

        # Also include leagues from disabled groups (user may re-enable)
        cursor = conn.execute(
            "SELECT leagues FROM event_epg_groups WHERE enabled = 0 AND leagues IS NOT NULL"
        )
        for row in cursor.fetchall():
            try:
                group_leagues = json.loads(row[0])
                if isinstance(group_leagues, list):
                    all_leagues.update(group_leagues)
            except (json.JSONDecodeError, TypeError):
                continue

        subscription_leagues = sorted(all_leagues)
        logger.info(
            "[MIGRATE v58] Collected %d unique leagues from all groups: %s",
            len(subscription_leagues),
            subscription_leagues[:10],
        )

        # 3. Merge soccer config across all groups
        # Priority: 'all' > 'teams' (merge all followed teams) > 'manual'
        best_soccer_mode = None
        merged_followed_teams: list[dict] = []
        seen_team_keys: set[str] = set()

        cursor = conn.execute(
            "SELECT soccer_mode, soccer_followed_teams FROM event_epg_groups "
            "WHERE soccer_mode IS NOT NULL"
        )
        for row in cursor.fetchall():
            mode = row[0]
            if mode == "all":
                best_soccer_mode = "all"
            elif mode == "teams":
                if best_soccer_mode != "all":
                    best_soccer_mode = "teams"
                # Merge followed teams from this group
                if row[1]:
                    try:
                        teams = json.loads(row[1])
                        if isinstance(teams, list):
                            for team in teams:
                                key = f"{team.get('provider', '')}:{team.get('team_id', '')}"
                                if key not in seen_team_keys:
                                    seen_team_keys.add(key)
                                    merged_followed_teams.append(team)
                    except (json.JSONDecodeError, TypeError):
                        pass
            elif mode == "manual":
                if best_soccer_mode is None:
                    best_soccer_mode = "manual"

        # Write subscription
        conn.execute(
            """UPDATE sports_subscription SET
                leagues = ?,
                soccer_mode = ?,
                soccer_followed_teams = ?,
                updated_at = CURRENT_TIMESTAMP
               WHERE id = 1""",
            (
                json.dumps(subscription_leagues),
                best_soccer_mode,
                json.dumps(merged_followed_teams) if merged_followed_teams else None,
            ),
        )

        logger.info(
            "[MIGRATE v58] Sports subscription: %d leagues, soccer_mode=%s, %d followed teams",
            len(subscription_leagues),
            best_soccer_mode,
            len(merged_followed_teams),
        )

        # 4. Migrate group_templates → subscription_templates (deduplicate)
        # Deduplicate by (template_id, sports, leagues) — keep unique combos
        seen_template_keys: set[str] = set()
        try:
            cursor = conn.execute(
                "SELECT template_id, sports, leagues FROM group_templates ORDER BY id"
            )
            for row in cursor.fetchall():
                template_id = row[0]
                sports_val = row[1]  # Already JSON string or NULL
                leagues_val = row[2]  # Already JSON string or NULL
                dedup_key = f"{template_id}:{sports_val}:{leagues_val}"
                if dedup_key not in seen_template_keys:
                    seen_template_keys.add(dedup_key)
                    conn.execute(
                        """INSERT INTO subscription_templates (template_id, sports, leagues)
                           VALUES (?, ?, ?)""",
                        (template_id, sports_val, leagues_val),
                    )
        except sqlite3.OperationalError:
            # group_templates table might not exist in minimal test databases
            pass

        logger.info(
            "[MIGRATE v58] Migrated %d unique template assignments to subscription_templates",
            len(seen_template_keys),
        )

        # 5. Migrate legacy template_id from groups without group_templates entries
        # These become default subscription templates (sports=NULL, leagues=NULL)
        try:
            cursor = conn.execute(
                """SELECT DISTINCT template_id FROM event_epg_groups
                   WHERE template_id IS NOT NULL
                     AND id NOT IN (SELECT DISTINCT group_id FROM group_templates)"""
            )
            for row in cursor.fetchall():
                template_id = row[0]
                dedup_key = f"{template_id}:None:None"
                if dedup_key not in seen_template_keys:
                    seen_template_keys.add(dedup_key)
                    conn.execute(
                        """INSERT INTO subscription_templates (template_id, sports, leagues)
                           VALUES (?, NULL, NULL)""",
                        (template_id,),
                    )
                    logger.info(
                        "[MIGRATE v58] Migrated legacy template_id=%d as default",
                        template_id,
                    )
        except sqlite3.OperationalError:
            pass

        # 6. Set all groups: group_mode='multi', parent_group_id=NULL
        conn.execute(
            "UPDATE event_epg_groups SET group_mode = 'multi', parent_group_id = NULL"
        )
        logger.info("[MIGRATE v58] All groups set to group_mode='multi', parent_group_id=NULL")

        # 7. Update each group's leagues to match subscription (downgrade safety)
        # If a user rolls back to an older version, groups still have valid leagues
        if subscription_leagues:
            conn.execute(
                "UPDATE event_epg_groups SET leagues = ?",
                (json.dumps(subscription_leagues),),
            )
            logger.info(
                "[MIGRATE v58] Updated all group leagues for downgrade safety"
            )

        conn.execute("UPDATE settings SET schema_version = 58 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 58 (sports subscription)")
        current_version = 58

    # ==========================================================================
    # v59: Channel Numbering & Consolidation Overhaul
    # ==========================================================================
    # Moves channel numbering, consolidation, and ordering from per-group to
    # global settings. Groups become pure stream suppliers.
    #
    # Steps:
    # 1. Add new columns: global_channel_mode, league_channel_starts,
    #    global_consolidation_mode
    # 2. Migrate: if ANY enabled group is manual → global_channel_mode='manual'
    # 3. Build league_channel_starts JSON from manual groups
    # 4. Set global_consolidation_mode from default_duplicate_event_handling
    # 5. Force channel_sorting_scope='global', channel_sort_by='sport_league_time'
    if current_version < 59:
        # 1. Add new columns
        _add_column_if_not_exists(
            conn, "settings", "global_channel_mode",
            "TEXT DEFAULT 'auto' CHECK(global_channel_mode IN ('auto', 'manual'))"
        )
        _add_column_if_not_exists(
            conn, "settings", "league_channel_starts", "JSON DEFAULT '{}'"
        )
        _add_column_if_not_exists(
            conn, "settings", "global_consolidation_mode",
            "TEXT DEFAULT 'consolidate'"  # CHECK added in schema.sql
        )

        # 2. Determine global channel mode from existing groups
        has_manual = 0
        try:
            has_manual = conn.execute(
                """SELECT COUNT(*) FROM event_epg_groups
                   WHERE channel_assignment_mode = 'manual' AND enabled = 1"""
            ).fetchone()[0]
        except sqlite3.OperationalError:
            pass  # Column may not exist in fresh databases

        global_mode = "manual" if has_manual > 0 else "auto"
        conn.execute(
            "UPDATE settings SET global_channel_mode = ? WHERE id = 1",
            (global_mode,),
        )
        logger.info(
            "[MIGRATE v59] Global channel mode set to '%s' (%d manual groups)",
            global_mode, has_manual,
        )

        # 3. Build league_channel_starts from manual groups
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
                logger.info(
                    "[MIGRATE v59] Built league_channel_starts: %d leagues",
                    len(league_starts),
                )

        # 4. Set global_consolidation_mode from default_duplicate_event_handling
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
                logger.info("[MIGRATE v59] Consolidation mode set to '%s'", mode)
        except sqlite3.OperationalError:
            pass  # Column may not exist in fresh databases

        # 5. Force global sorting with sport_league_time
        try:
            conn.execute(
                """UPDATE settings SET
                    channel_sorting_scope = 'global',
                    channel_sort_by = 'sport_league_time'
                   WHERE id = 1"""
            )
            logger.info("[MIGRATE v59] Locked sorting: scope=global, sort_by=sport_league_time")
        except sqlite3.OperationalError:
            pass  # Columns may not exist in fresh databases

        conn.execute("UPDATE settings SET schema_version = 59 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 59 (channel numbering overhaul)")
        current_version = 59

    # v60: Per-group subscription overrides (NULL = inherit global)
    if current_version < 60:
        _add_column_if_not_exists(
            conn, "event_epg_groups", "subscription_leagues", "JSON"
        )
        _add_column_if_not_exists(
            conn, "event_epg_groups", "subscription_soccer_mode", "TEXT"
        )
        _add_column_if_not_exists(
            conn, "event_epg_groups", "subscription_soccer_followed_teams", "JSON"
        )
        conn.execute("UPDATE settings SET schema_version = 60 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 60 (per-group subscription overrides)")
        current_version = 60

    if current_version < 61:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscription_league_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_code TEXT NOT NULL UNIQUE,
                channel_profile_ids JSON DEFAULT NULL,
                channel_group_id INTEGER DEFAULT NULL,
                channel_group_mode TEXT DEFAULT NULL
                    CHECK(channel_group_mode IS NULL
                          OR channel_group_mode IN ('static', 'sport', 'league'))
            )
        """)
        conn.execute("UPDATE settings SET schema_version = 61 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 61 (subscription league config)")
        current_version = 61

    # v62: Global default channel group settings + relax CHECK constraint on league config
    if current_version < 62:
        _add_column_if_not_exists(
            conn, "settings", "default_channel_group_id", "INTEGER"
        )
        _add_column_if_not_exists(
            conn, "settings", "default_channel_group_mode", "TEXT DEFAULT 'static'"
        )

        # Recreate subscription_league_config without CHECK constraint on channel_group_mode
        # to allow custom patterns like "{sport} | {league}"
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscription_league_config_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    league_code TEXT NOT NULL UNIQUE,
                    channel_profile_ids JSON DEFAULT NULL,
                    channel_group_id INTEGER DEFAULT NULL,
                    channel_group_mode TEXT DEFAULT NULL
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO subscription_league_config_new
                    (id, league_code, channel_profile_ids, channel_group_id, channel_group_mode)
                SELECT id, league_code, channel_profile_ids, channel_group_id, channel_group_mode
                FROM subscription_league_config
            """)
            conn.execute("DROP TABLE subscription_league_config")
            conn.execute(
                "ALTER TABLE subscription_league_config_new RENAME TO subscription_league_config"
            )
            logger.info("[MIGRATE v62] Recreated subscription_league_config (no CHECK)")
        except sqlite3.OperationalError as e:
            logger.warning("[MIGRATE v62] Could not recreate subscription_league_config: %s", e)

        conn.execute("UPDATE settings SET schema_version = 62 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 62 (global default channel group)")
        current_version = 62

    # v63: Make event_epg_group_id nullable + change FK from CASCADE to SET NULL
    # Channels are owned by events, not groups. Groups are just stream sources.
    # Deleting a group should NULL the provenance link, not cascade-delete channels.
    if current_version < 63:
        # Check if managed_channels table exists (test schemas may not have it)
        has_mc = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='managed_channels'"
        ).fetchone()[0]

        if not has_mc:
            logger.info(
                "[MIGRATE v63] managed_channels table not found, skipping rebuild"
            )
        else:
            try:
                # SQLite requires table rebuild to change NOT NULL and FK actions
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute("""
                    CREATE TABLE managed_channels_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        event_epg_group_id INTEGER,
                        event_id TEXT NOT NULL,
                        event_provider TEXT NOT NULL,
                        tvg_id TEXT NOT NULL,
                        channel_name TEXT NOT NULL,
                        channel_number TEXT,
                        logo_url TEXT,
                        dispatcharr_channel_id INTEGER,
                        dispatcharr_uuid TEXT,
                        dispatcharr_logo_id INTEGER,
                        channel_group_id INTEGER,
                        channel_profile_ids TEXT,
                        primary_stream_id INTEGER,
                        exception_keyword TEXT,
                        home_team TEXT,
                        home_team_abbrev TEXT,
                        home_team_logo TEXT,
                        away_team TEXT,
                        away_team_abbrev TEXT,
                        away_team_logo TEXT,
                        event_date TIMESTAMP,
                        event_name TEXT,
                        league TEXT,
                        sport TEXT,
                        venue TEXT,
                        broadcast TEXT,
                        scheduled_delete_at TIMESTAMP,
                        deleted_at TIMESTAMP,
                        delete_reason TEXT,
                        sync_status TEXT DEFAULT 'pending'
                            CHECK(sync_status IN (
                                'pending', 'created', 'in_sync',
                                'drifted', 'orphaned', 'error'
                            )),
                        sync_message TEXT,
                        last_verified_at TIMESTAMP,
                        expires_at TIMESTAMP,
                        external_channel_id INTEGER,
                        FOREIGN KEY (event_epg_group_id)
                            REFERENCES event_epg_groups(id) ON DELETE SET NULL
                    )
                """)
                conn.execute("""
                    INSERT INTO managed_channels_new
                    SELECT id, created_at, updated_at, event_epg_group_id,
                           event_id, event_provider, tvg_id, channel_name,
                           channel_number, logo_url, dispatcharr_channel_id,
                           dispatcharr_uuid, dispatcharr_logo_id,
                           channel_group_id, channel_profile_ids,
                           primary_stream_id, exception_keyword,
                           home_team, home_team_abbrev, home_team_logo,
                           away_team, away_team_abbrev, away_team_logo,
                           event_date, event_name, league, sport, venue,
                           broadcast, scheduled_delete_at, deleted_at,
                           delete_reason, sync_status, sync_message,
                           last_verified_at, expires_at, external_channel_id
                    FROM managed_channels
                """)
                conn.execute("DROP TABLE managed_channels")
                conn.execute(
                    "ALTER TABLE managed_channels_new "
                    "RENAME TO managed_channels"
                )
                # Recreate indexes
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_managed_channels_group
                    ON managed_channels(event_epg_group_id)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_managed_channels_event
                    ON managed_channels(event_id, event_provider)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_managed_channels_expires
                    ON managed_channels(expires_at)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_managed_channels_delete
                    ON managed_channels(scheduled_delete_at)
                    WHERE deleted_at IS NULL
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_managed_channels_dispatcharr
                    ON managed_channels(dispatcharr_channel_id)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_managed_channels_tvg
                    ON managed_channels(tvg_id)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_managed_channels_sync
                    ON managed_channels(sync_status)
                """)
                # Keep group-scoped unique index (changed to event-scoped in zo8.4)
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_mc_unique_event
                    ON managed_channels(
                        event_epg_group_id, event_id, event_provider,
                        COALESCE(exception_keyword, ''), primary_stream_id
                    )
                    WHERE deleted_at IS NULL
                """)
                # Recreate trigger
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS
                        update_managed_channels_timestamp
                    AFTER UPDATE ON managed_channels
                    BEGIN
                        UPDATE managed_channels
                        SET updated_at = CURRENT_TIMESTAMP
                        WHERE id = NEW.id;
                    END
                """)
                # Add sport/league index for new primary access pattern
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS
                        idx_managed_channels_sport_league
                    ON managed_channels(sport, league)
                    WHERE deleted_at IS NULL
                """)
                conn.execute("PRAGMA foreign_keys = ON")
                logger.info(
                    "[MIGRATE v63] Rebuilt managed_channels: "
                    "event_epg_group_id nullable, FK ON DELETE SET NULL"
                )
            except sqlite3.OperationalError as e:
                conn.execute("PRAGMA foreign_keys = ON")
                # Old schemas may have different columns — clean up temp table
                conn.execute(
                    "DROP TABLE IF EXISTS managed_channels_new"
                )
                logger.warning(
                    "[MIGRATE v63] Could not rebuild managed_channels "
                    "(schema mismatch): %s", e
                )

        conn.execute("UPDATE settings SET schema_version = 63 WHERE id = 1")
        logger.info(
            "[MIGRATE] Schema upgraded to version 63 "
            "(channel ownership: nullable source group)"
        )
        current_version = 63

    # v64: Dedup cross-group duplicate channels + event-scoped unique index
    # Channels are now identified by (event_id, event_provider, keyword, stream_id)
    # regardless of which source group created them.
    if current_version < 64:
        # Check if managed_channels table exists
        has_mc = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='managed_channels'"
        ).fetchone()[0]

        if has_mc:
            try:
                _dedup_cross_group_channels(conn)
            except Exception as e:
                logger.warning(
                    "[MIGRATE v64] Dedup failed (non-fatal): %s", e
                )

            # Replace group-scoped unique index with event-scoped one
            try:
                conn.execute("DROP INDEX IF EXISTS idx_mc_unique_event")
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_mc_unique_event
                    ON managed_channels(
                        event_id, event_provider,
                        COALESCE(exception_keyword, ''),
                        primary_stream_id
                    )
                    WHERE deleted_at IS NULL
                """)
                logger.info(
                    "[MIGRATE v64] Replaced group-scoped unique index "
                    "with event-scoped unique index"
                )
            except sqlite3.OperationalError as e:
                logger.warning(
                    "[MIGRATE v64] Could not create event-scoped "
                    "unique index: %s", e
                )

        conn.execute("UPDATE settings SET schema_version = 64 WHERE id = 1")
        logger.info(
            "[MIGRATE] Schema upgraded to version 64 "
            "(event-scoped unique index)"
        )
        current_version = 64

    # v65: Event-anchored channel lifecycle timing overhaul
    # Restore settings from pre-migration backup with mapped timing values.
    # Check for backup table existence (not schema_version) because the
    # pre-migration drops the settings table, executescript recreates it with
    # DEFAULT schema_version=65, making version-based checks unreliable.
    has_v65_backup = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='_settings_v65_backup'"
    ).fetchone()[0]
    if has_v65_backup:
        try:
            # Map old timing values to new values in the backup table
            # (backup has no CHECK constraints, so these UPDATEs work)
            conn.execute("""
                UPDATE _settings_v65_backup SET
                    channel_pre_buffer_minutes = CASE channel_create_timing
                        WHEN 'stream_available' THEN 0
                        WHEN 'day_before' THEN 1440
                        WHEN '2_days_before' THEN 2880
                        WHEN '3_days_before' THEN 4320
                        WHEN '1_week_before' THEN 10080
                        ELSE COALESCE(channel_pre_buffer_minutes, 60)
                        END,
                    channel_create_timing = CASE channel_create_timing
                        WHEN 'stream_available' THEN 'before_event'
                        WHEN 'day_before' THEN 'before_event'
                        WHEN '2_days_before' THEN 'before_event'
                        WHEN '3_days_before' THEN 'before_event'
                        WHEN '1_week_before' THEN 'before_event'
                        ELSE 'same_day' END,
                    channel_post_buffer_minutes = CASE channel_delete_timing
                        WHEN 'stream_removed' THEN 0
                        WHEN '6_hours_after' THEN 360
                        WHEN 'day_after' THEN 1440
                        WHEN '2_days_after' THEN 2880
                        WHEN '3_days_after' THEN 4320
                        WHEN '1_week_after' THEN 10080
                        ELSE COALESCE(channel_post_buffer_minutes, 60)
                        END,
                    channel_delete_timing = CASE channel_delete_timing
                        WHEN 'stream_removed' THEN 'after_event'
                        WHEN '6_hours_after' THEN 'after_event'
                        WHEN 'day_after' THEN 'after_event'
                        WHEN '2_days_after' THEN 'after_event'
                        WHEN '3_days_after' THEN 'after_event'
                        WHEN '1_week_after' THEN 'after_event'
                        ELSE 'same_day' END
            """)

            # Restore: find columns common to both tables
            backup_cols = [
                r[1] for r in
                conn.execute("PRAGMA table_info(_settings_v65_backup)")
            ]
            settings_cols = [
                r[1] for r in
                conn.execute("PRAGMA table_info(settings)")
            ]
            common = [c for c in settings_cols if c in backup_cols]
            col_list = ", ".join(common)

            # Delete the defaults row inserted by executescript
            conn.execute("DELETE FROM settings WHERE id = 1")

            # Restore mapped data
            conn.execute(
                f"INSERT INTO settings ({col_list}) "
                f"SELECT {col_list} FROM _settings_v65_backup"
            )

            # Ensure schema_version is set correctly after restore
            conn.execute(
                "UPDATE settings SET schema_version = 65 WHERE id = 1"
            )

            # Cleanup
            conn.execute("DROP TABLE _settings_v65_backup")
            logger.info(
                "[MIGRATE v65] Restored settings with mapped "
                "lifecycle timing values"
            )

        except Exception as e:
            logger.warning(
                "[MIGRATE v65] Settings restore failed: %s", e
            )
            conn.execute("DROP TABLE IF EXISTS _settings_v65_backup")

    # Always bump to v65 for databases below it (e.g. v64 with no timing changes)
    if current_version < 65:
        conn.execute("UPDATE settings SET schema_version = 65 WHERE id = 1")
        logger.info(
            "[MIGRATE] Schema upgraded to version 65 "
            "(event-anchored lifecycle timing)"
        )
        current_version = 65

    # ==========================================================================
    # v66: TSDB Tiered Provider Model
    # ==========================================================================
    # Add tsdb_tier column to leagues table for free/premium classification.
    # Free tier leagues work within TSDB free limits (5 events/day/league).
    # Premium tier leagues need a premium key for full event coverage.
    # The INSERT OR REPLACE in schema.sql handles new installs; this migration
    # adds the column and sets values for existing databases.
    if current_version < 66:
        _add_column_if_not_exists(conn, "leagues", "tsdb_tier", "TEXT")

        # Tag existing TSDB leagues with their tier
        # Wrapped in try-except for minimal test databases without leagues table
        try:
            free_leagues = [
                "cfl", "unrivaled", "norwegian-hockey",
                "boxing",
            ]
            premium_leagues = ["ipl", "bbl", "sa20", "afl", "nrl", "super-rugby"]

            for code in free_leagues:
                conn.execute(
                    "UPDATE leagues SET tsdb_tier = 'free' WHERE league_code = ?",
                    (code,),
                )
            for code in premium_leagues:
                conn.execute(
                    "UPDATE leagues SET tsdb_tier = 'premium' WHERE league_code = ?",
                    (code,),
                )
        except sqlite3.OperationalError:
            pass  # Table doesn't exist in minimal test databases

        conn.execute("UPDATE settings SET schema_version = 66 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 66 (TSDB tiered provider model)")
        current_version = 66

    # ==========================================================================
    # v67: Remove Cricbuzz provider
    # ==========================================================================
    # Cricbuzz and cricket_hybrid providers fully removed. Cricket leagues now
    # use TSDB exclusively. Clear fallback references from existing databases.
    if current_version < 67:
        try:
            conn.execute(
                """UPDATE leagues SET fallback_provider = NULL, fallback_league_id = NULL,
                   series_slug_pattern = NULL
                   WHERE fallback_provider = 'cricbuzz'"""
            )
        except sqlite3.OperationalError:
            pass  # Table doesn't exist in minimal test databases

        conn.execute("UPDATE settings SET schema_version = 67 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 67 (remove Cricbuzz provider)")
        current_version = 67

    # ==========================================================================
    # v68: Feed Separation settings (HOME/AWAY stream detection)
    # ==========================================================================
    if current_version < 68:
        new_cols = {
            "feed_separation_enabled": "BOOLEAN DEFAULT 0",
            "feed_home_terms": "JSON DEFAULT '[\"HOME\"]'",
            "feed_away_terms": "JSON DEFAULT '[\"AWAY\"]'",
            "feed_detect_team_names": "BOOLEAN DEFAULT 1",
            "feed_label_style": "TEXT DEFAULT 'team_name'",
        }
        for col, defn in new_cols.items():
            _add_column_if_not_exists(conn, "settings", col, defn)

        conn.execute("UPDATE settings SET schema_version = 68 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 68 (feed separation settings)")
        current_version = 68

    # v69: Feed team channel discrimination
    # Add feed_team_id column to managed_channels and rebuild unique index
    if current_version < 69:
        # Check if managed_channels table exists (test schemas may not have it)
        has_mc = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='managed_channels'"
        ).fetchone()[0]

        if has_mc:
            _add_column_if_not_exists(conn, "managed_channels", "feed_team_id", "TEXT")

            # Drop old unique index and create new one including feed_team_id
            conn.execute("DROP INDEX IF EXISTS idx_mc_unique_event")
            try:
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_mc_unique_event_v2
                    ON managed_channels(event_id, event_provider,
                        COALESCE(exception_keyword, ''), COALESCE(feed_team_id, ''),
                        primary_stream_id)
                    WHERE deleted_at IS NULL
                """)
            except Exception as e:
                logger.warning("[MIGRATE v69] Could not create unique index: %s", e)

        conn.execute("UPDATE settings SET schema_version = 69 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 69 (feed team channel discrimination)")
        current_version = 69

    # ==========================================================================
    # v70: NFHS High School Sports settings
    # ==========================================================================
    if current_version < 70:
        _add_column_if_not_exists(
            conn,
            "settings",
            "nfhs_enabled",
            "BOOLEAN DEFAULT 0",
        )

        _add_column_if_not_exists(
            conn,
            "settings",
            "nfhs_state_codes",
            "JSON DEFAULT '[]'",
        )

        conn.execute("UPDATE settings SET schema_version = 70 WHERE id = 1")
        logger.info("[MIGRATE] Schema upgraded to version 70 (NFHS settings)")
        current_version = 70


def _dedup_cross_group_channels(conn: sqlite3.Connection) -> None:
    """Merge duplicate channels that exist for the same event across groups.

    For each set of duplicates (same event_id + provider + keyword + stream_id),
    keeps the earliest-created channel and merges streams from losers.
    """
    # Find duplicate sets (active channels only)
    cursor = conn.execute("""
        SELECT event_id, event_provider,
               COALESCE(exception_keyword, '') AS kw,
               primary_stream_id,
               COUNT(*) AS cnt
        FROM managed_channels
        WHERE deleted_at IS NULL
        GROUP BY event_id, event_provider,
                 COALESCE(exception_keyword, ''),
                 primary_stream_id
        HAVING cnt > 1
    """)
    dup_groups = cursor.fetchall()

    if not dup_groups:
        logger.info("[MIGRATE v64] No duplicate channels found")
        return

    total_merged = 0
    for dup in dup_groups:
        event_id = dup[0]
        event_provider = dup[1]
        kw = dup[2]
        stream_id = dup[3]

        # Get all channels in this duplicate set, ordered by created_at
        channels = conn.execute(
            """SELECT id, event_epg_group_id, channel_name,
                      dispatcharr_channel_id, created_at
               FROM managed_channels
               WHERE event_id = ? AND event_provider = ?
                 AND COALESCE(exception_keyword, '') = ?
                 AND primary_stream_id IS ?
                 AND deleted_at IS NULL
               ORDER BY created_at ASC""",
            (event_id, event_provider, kw, stream_id),
        ).fetchall()

        if len(channels) < 2:
            continue

        # Winner = first created
        winner_id = channels[0][0]
        winner_name = channels[0][2]

        for loser in channels[1:]:
            loser_id = loser[0]
            loser_name = loser[2]

            # Move streams from loser to winner (skip duplicates)
            conn.execute(
                """INSERT OR IGNORE INTO managed_channel_streams
                   (managed_channel_id, dispatcharr_stream_id,
                    stream_name, source_group_id, source_group_type,
                    priority, m3u_account_id, m3u_account_name)
                   SELECT ?, dispatcharr_stream_id,
                          stream_name, source_group_id,
                          source_group_type, priority,
                          m3u_account_id, m3u_account_name
                   FROM managed_channel_streams
                   WHERE managed_channel_id = ?""",
                (winner_id, loser_id),
            )

            # Soft-delete the loser
            conn.execute(
                """UPDATE managed_channels
                   SET deleted_at = CURRENT_TIMESTAMP,
                       delete_reason = 'migration_dedup_v64'
                   WHERE id = ?""",
                (loser_id,),
            )
            total_merged += 1
            logger.info(
                "[MIGRATE v64] Merged channel '%s' (id=%d) into "
                "'%s' (id=%d) for event %s",
                loser_name, loser_id, winner_name, winner_id,
                event_id,
            )

    logger.info(
        "[MIGRATE v64] Dedup complete: %d duplicate(s) merged "
        "from %d duplicate group(s)",
        total_merged, len(dup_groups),
    )


# =============================================================================
# LEGACY MIGRATION HELPER FUNCTIONS
# =============================================================================
# STATUS: DEPRECATED - Scheduled for removal with legacy migrations above
#
# These helper functions are only called by the legacy v3-v43 migrations.
# They are preserved as part of the safety fallback.
# Delete these when removing the legacy migration code above.
# =============================================================================






























def _add_column_if_not_exists(
    conn: sqlite3.Connection, table: str, column: str, column_def: str
) -> None:
    """Add a column to a table if it doesn't exist.

    Args:
        conn: Database connection
        table: Table name
        column: Column name to add
        column_def: Column definition (type and default)
    """
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = {row["name"] for row in cursor.fetchall()}
    if not columns:
        # Table doesn't exist yet — schema.sql will create it with all columns
        return
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")










def reset_db(db_path: Path | str | None = None) -> None:
    """Reset database - drops all tables and reinitializes.

    WARNING: This deletes all data!

    Args:
        db_path: Path to database file. Uses DEFAULT_DB_PATH if not specified.
    """
    path = Path(db_path) if db_path else DEFAULT_DB_PATH

    if path.exists():
        path.unlink()

    init_db(path)
