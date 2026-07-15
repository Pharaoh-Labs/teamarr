"""Database connection management.

Simple SQLite connection handling with schema initialization.
"""

import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from teamarr.database.migrations import _run_migrations, run_pre_migrations

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "teamarr.db"

# Schema file location
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def resolve_db_path(db_path: Path | str | None) -> Path:
    """Explicit argument > DATABASE_PATH env var > repo default.

    Read at call time (not import time) so tests can redirect the database
    with monkeypatch.setenv before touching any connection helper.
    """
    if db_path:
        return Path(db_path)
    env_path = os.environ.get("DATABASE_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Get a database connection.

    Args:
        db_path: Path to database file. Uses DATABASE_PATH env var or
            DEFAULT_DB_PATH if not specified.

    Returns:
        SQLite connection with row factory set to sqlite3.Row
    """
    path = resolve_db_path(db_path)

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
    path = resolve_db_path(db_path)
    schema_sql = SCHEMA_PATH.read_text()

    try:
        with get_db(db_path) as conn:
            # Probe the database before touching it so corrupt files fail
            # with a clear error instead of mid-migration.
            _verify_database_integrity(conn, path)

            # Structural pre-migrations (renames, table rebuilds) — these
            # can't be handled by reconciliation; see database/migrations/pre.py
            run_pre_migrations(conn)

            # ================================================================
            # Schema reconciliation — ensures ALL columns match schema.sql.
            # Replaces all individual _add_*_column_if_needed functions.
            # Adding a new column is now: just add it to schema.sql.
            # ================================================================
            from teamarr.database.reconciliation import reconcile_schema

            result = reconcile_schema(conn, schema_sql)
            if result.columns_added > 0:
                logger.info(
                    "[RECONCILE] Added %d missing columns across %d tables",
                    result.columns_added,
                    len(result.columns_by_table),
                )
            if result.errors:
                for err in result.errors:
                    logger.warning("[RECONCILE] %s", err)

            # Apply schema (creates tables if missing, INSERT OR REPLACE updates seed data)
            conn.executescript(schema_sql)
            # Run data migrations for existing databases
            _run_migrations(conn)
            # Seed TSDB cache if empty or incomplete
            _seed_tsdb_cache_if_needed(conn)
            # Seed/upgrade the curated default template set (idempotent;
            # add-missing-by-name + pristine-legacy upgrade — tvnk.1/#329).
            # Was previously defined but never wired, so fresh installs
            # shipped with zero templates.
            from teamarr.database.default_templates import seed_default_templates
            seed_default_templates(conn)

            # Final verification: ensure settings table exists and is queryable
            conn.execute("SELECT id FROM settings LIMIT 1")
    except sqlite3.DatabaseError as e:
        if "file is not a database" in str(e):
            logger.error(
                f"Database file '{path}' exists but is not a valid SQLite database. "
                "Move or delete the file and restart Teamarr to initialize a fresh database."
            )
            raise RuntimeError(
                f"Invalid database file at '{path}'. "
                "Move or delete the file and restart Teamarr."
            ) from e
        raise


def _verify_database_integrity(conn: sqlite3.Connection, path: Path) -> None:
    """Probe the database so corrupt files raise a clear error up front.

    Raises:
        sqlite3.DatabaseError: If database file is corrupt
    """
    conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")


def _seed_tsdb_cache_if_needed(conn: sqlite3.Connection) -> None:
    """Seed TSDB cache from distributed seed file if needed."""
    from teamarr.database.seed import seed_if_needed

    result = seed_if_needed(conn)
    if result and result.get("seeded"):
        logger.info(
            f"Seeded TSDB cache: {result.get('teams_added', 0)} teams, "
            f"{result.get('leagues_added', 0)} leagues"
        )




def reset_db(db_path: Path | str | None = None) -> None:
    """Reset database - drops all tables and reinitializes.

    WARNING: This deletes all data!

    Args:
        db_path: Path to database file. Uses DATABASE_PATH env var or
            DEFAULT_DB_PATH if not specified.
    """
    path = resolve_db_path(db_path)

    if path.exists():
        path.unlink()

    init_db(path)
