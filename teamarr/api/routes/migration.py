"""V1 to V2 migration detection and database archival.

Detects V1 database format and provides options for users to:
1. Archive V1 database and start fresh with V2
2. Download their archived V1 database
"""

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from teamarr.database.connection import get_connection, DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/migration", tags=["migration"])


class MigrationStatus(BaseModel):
    """V1 migration status."""

    is_v1_database: bool
    has_archived_backup: bool
    database_path: str
    backup_path: str | None


class ArchiveResult(BaseModel):
    """Result of archiving V1 database."""

    success: bool
    message: str
    backup_path: str | None


def detect_v1_database() -> bool:
    """Detect if current database is V1 format.

    V1 databases have tables like:
    - schedule_cache
    - h2h_cache
    - epg_history
    - league_config

    V2 databases have tables like:
    - leagues
    - team_cache
    - league_cache
    - processing_runs
    """
    db_path = Path(DEFAULT_DB_PATH)
    if not db_path.exists():
        return False

    try:
        conn = get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schedule_cache'"
        )
        has_schedule_cache = cursor.fetchone() is not None

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='leagues'"
        )
        has_leagues = cursor.fetchone() is not None

        # V1 has schedule_cache but not leagues table
        return has_schedule_cache and not has_leagues
    except Exception as e:
        logger.error(f"Error detecting database version: {e}")
        return False


def get_backup_path() -> Path:
    """Get the path for V1 backup."""
    return Path(DEFAULT_DB_PATH).parent / ".teamarr.v1.bak"


@router.get("/status", response_model=MigrationStatus)
async def get_migration_status():
    """Check if database is V1 format and needs migration."""
    db_path = Path(DEFAULT_DB_PATH)
    backup_path = get_backup_path()

    return MigrationStatus(
        is_v1_database=detect_v1_database(),
        has_archived_backup=backup_path.exists(),
        database_path=str(db_path),
        backup_path=str(backup_path) if backup_path.exists() else None,
    )


@router.post("/archive", response_model=ArchiveResult)
async def archive_v1_database():
    """Archive V1 database and prepare for fresh V2 start.

    Moves the V1 database to .teamarr.v1.bak and allows
    the app to create a fresh V2 database on next startup.
    """
    db_path = Path(DEFAULT_DB_PATH)
    backup_path = get_backup_path()

    if not db_path.exists():
        raise HTTPException(status_code=404, detail="No database found to archive")

    if not detect_v1_database():
        raise HTTPException(
            status_code=400,
            detail="Current database is not V1 format. Cannot archive.",
        )

    try:
        # Move database to backup location
        shutil.move(str(db_path), str(backup_path))

        logger.info(f"Archived V1 database to {backup_path}")

        return ArchiveResult(
            success=True,
            message="V1 database archived successfully. Restart the application to initialize V2.",
            backup_path=str(backup_path),
        )
    except Exception as e:
        logger.error(f"Failed to archive V1 database: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to archive database: {str(e)}"
        )


@router.get("/download-backup")
async def download_v1_backup():
    """Download the archived V1 database backup."""
    backup_path = get_backup_path()

    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="No V1 backup found")

    return FileResponse(
        path=str(backup_path),
        filename="teamarr-v1-backup.db",
        media_type="application/x-sqlite3",
    )
