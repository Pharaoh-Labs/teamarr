"""Backup and restore API endpoints."""

import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from teamarr.consumers.scheduler import restart_scheduler_sub_task
from teamarr.database import get_db
from teamarr.database.connection import resolve_db_path
from teamarr.database.migration import validate_backup_file
from teamarr.services.backup_service import create_backup_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backup")


# =============================================================================
# VALIDATION HELPERS
# =============================================================================


def _validate_backup_filename(filename: str) -> None:
    """Validate backup filename to prevent path traversal and invalid names.

    Raises HTTPException if filename is invalid.
    """
    if (
        not filename.startswith("teamarr_")
        or not filename.endswith(".db")
        or "/" in filename
        or "\\" in filename
        or ".." in filename
        or "\x00" in filename
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid backup filename",
        )


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class RestoreResponse(BaseModel):
    success: bool
    message: str
    backup_path: str | None = None


class BackupInfoResponse(BaseModel):
    filename: str
    filepath: str
    size_bytes: int
    created_at: str
    is_protected: bool
    backup_type: str


class BackupListResponse(BaseModel):
    backups: list[BackupInfoResponse]
    total: int


class BackupCreateResponse(BaseModel):
    success: bool
    filename: str | None = None
    filepath: str | None = None
    size_bytes: int | None = None
    error: str | None = None


class BackupDeleteResponse(BaseModel):
    success: bool
    message: str


class BackupProtectResponse(BaseModel):
    success: bool
    is_protected: bool


class BackupSettingsResponse(BaseModel):
    enabled: bool
    cron: str
    max_count: int
    path: str


class BackupSettingsUpdate(BaseModel):
    enabled: bool | None = None
    cron: str | None = None
    max_count: int | None = None
    path: str | None = None


# =============================================================================
# BACKUP MANAGEMENT ENDPOINTS
# =============================================================================


@router.get("/list", response_model=BackupListResponse)
def list_backups():
    """List all backup files.

    Returns backup files sorted by creation date (newest first).
    """

    backup_service = create_backup_service(get_db)
    backups = backup_service.list_backups()

    return BackupListResponse(
        backups=[
            BackupInfoResponse(
                filename=b.filename,
                filepath=b.filepath,
                size_bytes=b.size_bytes,
                created_at=b.created_at.isoformat(),
                is_protected=b.is_protected,
                backup_type=b.backup_type,
            )
            for b in backups
        ],
        total=len(backups),
    )


@router.post("/create", response_model=BackupCreateResponse)
def create_backup():
    """Create a manual backup of the database.

    Creates a new backup file in the configured backup directory.
    """

    backup_service = create_backup_service(get_db)
    result = backup_service.create_backup(manual=True)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "Failed to create backup",
        )

    return BackupCreateResponse(
        success=True,
        filename=result.filename,
        filepath=result.filepath,
        size_bytes=result.size_bytes,
    )


@router.delete("/{filename}", response_model=BackupDeleteResponse)
def delete_backup(filename: str):
    """Delete a backup file.

    Protected backups cannot be deleted. Unprotect them first.
    """

    _validate_backup_filename(filename)

    backup_service = create_backup_service(get_db)

    # Check if backup exists
    backup_path = backup_service.get_backup_filepath(filename)
    if not backup_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )

    # Try to delete
    if not backup_service.delete_backup(filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete protected backup. Unprotect it first.",
        )

    return BackupDeleteResponse(
        success=True,
        message=f"Backup {filename} deleted",
    )


@router.post("/{filename}/protect", response_model=BackupProtectResponse)
def protect_backup(filename: str):
    """Protect a backup from rotation deletion.

    Protected backups are not counted toward the max backup limit
    and will not be deleted during automatic rotation.
    """

    _validate_backup_filename(filename)

    backup_service = create_backup_service(get_db)

    if not backup_service.protect_backup(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )

    return BackupProtectResponse(success=True, is_protected=True)


@router.post("/{filename}/unprotect", response_model=BackupProtectResponse)
def unprotect_backup(filename: str):
    """Remove protection from a backup.

    After unprotecting, the backup may be deleted during rotation
    if it exceeds the maximum backup count.
    """

    _validate_backup_filename(filename)

    backup_service = create_backup_service(get_db)

    if not backup_service.unprotect_backup(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )

    return BackupProtectResponse(success=True, is_protected=False)


@router.post("/{filename}/restore", response_model=RestoreResponse)
def restore_from_backup(filename: str):
    """Restore database from an existing backup file.

    Creates a pre-restore backup of the current database before restoring.
    The application will need to be restarted for changes to take effect.
    """

    _validate_backup_filename(filename)

    backup_service = create_backup_service(get_db)
    success, message, pre_restore_path = backup_service.restore_backup(filename)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return RestoreResponse(
        success=True,
        message=message,
        backup_path=pre_restore_path,
    )


@router.get("/file/{filename}", response_class=FileResponse)
def download_specific_backup(filename: str):
    """Download a specific backup file.

    Args:
        filename: The backup filename to download
    """

    _validate_backup_filename(filename)

    backup_service = create_backup_service(get_db)
    backup_path = backup_service.get_backup_filepath(filename)

    if not backup_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup not found",
        )

    return FileResponse(
        path=str(backup_path),
        filename=filename,
        media_type="application/x-sqlite3",
    )


# =============================================================================
# BACKUP SETTINGS ENDPOINTS
# =============================================================================


@router.get("/settings", response_model=BackupSettingsResponse)
def get_backup_settings():
    """Get scheduled backup settings."""
    from teamarr.database.settings import get_backup_settings

    with get_db() as conn:
        settings = get_backup_settings(conn)

    return BackupSettingsResponse(
        enabled=settings.enabled,
        cron=settings.cron,
        max_count=settings.max_count,
        path=settings.path,
    )


@router.put("/settings", response_model=BackupSettingsResponse)
def update_backup_settings(update: BackupSettingsUpdate):
    """Update scheduled backup settings."""
    from croniter import croniter

    from teamarr.database.settings import get_backup_settings, update_backup_settings

    # Validate cron expression if provided
    if update.cron:
        try:
            croniter(update.cron)
        except (KeyError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid cron expression: {e}",
            ) from None

    # Validate max_count if provided
    if update.max_count is not None and update.max_count < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="max_count must be at least 1",
        )

    # Validate backup path if provided
    if update.path is not None:
        resolved = Path(update.path).resolve()
        # Block obvious system paths
        blocked = ("/etc", "/proc", "/sys", "/dev", "/bin", "/sbin", "/usr")
        if any(str(resolved).startswith(b) for b in blocked):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Backup path cannot be a system directory",
            )
        # Check if directory is writable (or can be created)
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            if not os.access(resolved, os.W_OK):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Backup path is not writable: {update.path}",
                )
        except OSError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot create backup path: {e}",
            ) from None

    with get_db() as conn:
        update_backup_settings(
            conn,
            enabled=update.enabled,
            cron=update.cron,
            max_count=update.max_count,
            path=update.path,
        )

    # Restart backup sub-scheduler with new settings

    restart_scheduler_sub_task("backup")

    # Return updated settings
    with get_db() as conn:
        settings = get_backup_settings(conn)

    return BackupSettingsResponse(
        enabled=settings.enabled,
        cron=settings.cron,
        max_count=settings.max_count,
        path=settings.path,
    )


# =============================================================================
# LEGACY BACKUP/RESTORE ENDPOINTS
# =============================================================================


@router.get("", response_class=FileResponse)
def download_backup():
    """Download a backup of the database.

    Returns the SQLite database file as a downloadable attachment.
    """
    if not resolve_db_path(None).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database file not found",
        )

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"teamarr_backup_{timestamp}.db"

    logger.info("[BACKUP] Downloading backup as %s", filename)

    return FileResponse(
        path=str(resolve_db_path(None)),
        filename=filename,
        media_type="application/x-sqlite3",
    )


@router.post("", response_model=RestoreResponse)
async def restore_backup(file: UploadFile = File(...)):
    """Restore database from uploaded backup.

    The uploaded file must be a valid SQLite database.
    A backup of the current database is created before restoring.

    WARNING: This will replace ALL current data!
    """
    # Validate file extension
    if not file.filename or not file.filename.endswith(".db"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Please upload a .db file.",
        )

    content = await file.read()

    # Everything past the upload read is blocking file/sqlite work — run it
    # off the event loop so a large restore doesn't stall other requests.
    return await run_in_threadpool(_restore_from_content, content)


def _restore_from_content(content: bytes) -> RestoreResponse:
    """Validate uploaded backup bytes and swap in the new database."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        tmp_path = Path(tmp.name)
        try:
            # Write uploaded content to temp file
            tmp.write(content)
            tmp.flush()

            try:
                validate_backup_file(tmp_path)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                ) from e

            # Create backup of current database before restoring
            backup_path = None
            if resolve_db_path(None).exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = resolve_db_path(None).parent / f"teamarr_pre_restore_{timestamp}.db"
                shutil.copy2(resolve_db_path(None), backup_path)
                logger.info("[RESTORE] Created pre-restore backup at %s", backup_path)

            # Replace database with uploaded file
            shutil.copy2(tmp_path, resolve_db_path(None))
            logger.info("[RESTORE] Database restored from uploaded backup")

            return RestoreResponse(
                success=True,
                message="Database restored. Please restart the application for changes to take effect.",  # noqa: E501
                backup_path=str(backup_path) if backup_path else None,
            )

        finally:
            # Clean up temp file
            tmp_path.unlink(missing_ok=True)
