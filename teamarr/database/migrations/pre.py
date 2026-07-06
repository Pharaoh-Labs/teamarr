"""Structural pre-migrations — run BEFORE schema reconciliation/executescript.

These can't be handled by reconciliation: they rename columns, or back up and
drop a table so executescript can recreate it with new CHECK constraints
(the matching restore blocks live in the versioned migrations). Every function
is idempotent — it inspects the live schema and no-ops when already applied.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def run_pre_migrations(conn: sqlite3.Connection) -> None:
    """Run all structural pre-migrations in order."""
    _rename_league_id_column_if_needed(conn)
    _migrate_exception_keywords_columns(conn)
    _migrate_settings_for_v65(conn)
    _migrate_detection_keywords_check(conn)
    _migrate_stream_match_cache_check(conn)


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


def _migrate_detection_keywords_check(conn: sqlite3.Connection) -> None:
    """Pre-migration: rebuild detection_keywords if its category CHECK is stale.

    The 'combat_sports' category was renamed to 'event_type_keywords'. SQLite bakes
    CHECK constraints at table creation, so databases created before the rename
    still reject 'event_type_keywords' inserts even though the v47 data migration
    ran — i.e. users can't add Event Type Detection keywords. Detect the stale
    constraint and drop the table so executescript recreates it with the current
    CHECK; data is backed up to _detection_keywords_backup and restored (mapping
    combat_sports -> event_type_keywords) in _run_migrations.
    """
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='detection_keywords'"
        ).fetchone()
    except Exception:
        return  # Table doesn't exist yet (fresh install)
    if not row or not row[0]:
        return
    if "event_type_keywords" in row[0]:
        return  # Constraint already current — nothing to do

    conn.execute("DROP TABLE IF EXISTS _detection_keywords_backup")
    conn.execute(
        "CREATE TABLE _detection_keywords_backup AS SELECT * FROM detection_keywords"
    )
    conn.execute("DROP TABLE detection_keywords")
    logger.info(
        "[PRE-MIGRATE] detection_keywords dropped to refresh stale category CHECK constraint"
    )


def _migrate_stream_match_cache_check(conn: sqlite3.Connection) -> None:
    """Pre-migration: rebuild stream_match_cache if its match_method CHECK is stale.

    The RacingMatcher (v2.8.0) and TennisMatcher (mf7) cache matches with
    match_method='direct', but databases created before v77 bake a CHECK that
    rejects it — every direct-match cache write fails (logged, non-fatal), so
    those matches silently never cache. Detect the stale constraint and drop
    the table so executescript recreates it with the current CHECK. Only
    user-corrected rows are backed up (_stream_match_cache_backup) and
    restored in _run_migrations — algorithmic rows are disposable cache and
    re-derive on the next run.
    """
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='stream_match_cache'"
        ).fetchone()
    except Exception:
        return  # Table doesn't exist yet (fresh install)
    if not row or not row[0]:
        return
    if "'direct'" in row[0]:
        return  # Constraint already current — nothing to do

    conn.execute("DROP TABLE IF EXISTS _stream_match_cache_backup")
    conn.execute(
        "CREATE TABLE _stream_match_cache_backup AS "
        "SELECT * FROM stream_match_cache WHERE user_corrected = 1"
    )
    conn.execute("DROP TABLE stream_match_cache")
    logger.info(
        "[PRE-MIGRATE] stream_match_cache dropped to refresh stale "
        "match_method CHECK constraint (user corrections backed up)"
    )

