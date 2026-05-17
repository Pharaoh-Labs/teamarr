"""EPG sources database connection management.

Separate SQLite database for external EPG source data.
Follows the same patterns as the main database connection.
"""

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from teamarr.database.reconciliation import reconcile_schema

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "epg_sources.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_epg_sources_db(
    db_path: Path | str | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_epg_sources_db(db_path: Path | str | None = None) -> None:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    conn = get_connection(path)
    try:
        result = reconcile_schema(conn, schema_sql)
        if result.columns_added > 0:
            logger.info(
                "[EPG_SOURCES] Schema reconciliation added %d columns",
                result.columns_added,
            )
        conn.executescript(schema_sql)
        conn.commit()
        logger.info("[EPG_SOURCES] Database initialized at %s", path)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
