"""Backup service for database backup operations.

Provides functionality for:
- Creating manual and scheduled backups
- Listing existing backups with metadata
- Deleting backups (with protection support)
- Protecting/unprotecting backups from rotation
- Rotating old backups based on max count
"""

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BackupInfo:
    """Information about a backup file."""

    filename: str
    filepath: str
    size_bytes: int
    created_at: datetime
    is_protected: bool
    backup_type: str  # 'scheduled' or 'manual'


@dataclass
class BackupResult:
    """Result of a backup operation."""

    success: bool
    filename: str | None = None
    filepath: str | None = None
    size_bytes: int | None = None
    error: str | None = None


@dataclass
class RotationResult:
    """Result of backup rotation."""

    deleted_count: int
    deleted_files: list[str]
    kept_count: int
    protected_count: int


class BackupService:
    """Service for managing database backups.

    Backups are SQLite database copies stored in a configurable directory.
    Protected backups have a .protected marker file alongside them.

    Naming convention:
    - Scheduled: teamarr_scheduled_YYYYMMDD_HHMMSS.db
    - Manual: teamarr_manual_YYYYMMDD_HHMMSS.db
    """

    def __init__(
        self,
        db_factory: Callable[[], Any],
        backup_path: str = "./data/backups",
    ):
        """Initialize backup service.

        Args:
            db_factory: Factory function returning database connection context manager
            backup_path: Directory for storing backups
        """
        self._db_factory = db_factory
        self._backup_path = Path(backup_path)

    def _ensure_backup_dir(self) -> None:
        """Ensure backup directory exists."""
        self._backup_path.mkdir(parents=True, exist_ok=True)

    def _get_db_path(self) -> Path:
        """Get the current database file path."""
        from teamarr.database.connection import resolve_db_path

        return resolve_db_path(None)

    def _generate_filename(self, backup_type: str) -> str:
        """Generate backup filename with timestamp.

        Args:
            backup_type: 'scheduled' or 'manual'

        Returns:
            Filename like 'teamarr_manual_20240115_143052.db'
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"teamarr_{backup_type}_{timestamp}.db"

    def _get_protected_marker_path(self, backup_path: Path) -> Path:
        """Get path to protection marker file.

        Args:
            backup_path: Path to backup file

        Returns:
            Path to .protected marker file
        """
        return backup_path.with_suffix(".db.protected")

    def _is_protected(self, backup_path: Path) -> bool:
        """Check if a backup is protected.

        Args:
            backup_path: Path to backup file

        Returns:
            True if protected
        """
        return self._get_protected_marker_path(backup_path).exists()

    def _parse_backup_filename(self, filename: str) -> tuple[str, datetime] | None:
        """Parse backup filename to extract type and timestamp.

        Args:
            filename: Backup filename

        Returns:
            Tuple of (backup_type, datetime) or None if invalid
        """
        if not filename.startswith("teamarr_") or not filename.endswith(".db"):
            return None

        try:
            # teamarr_TYPE_YYYYMMDD_HHMMSS.db
            parts = filename[8:-3].split("_")  # Remove 'teamarr_' and '.db'
            if len(parts) < 3:
                return None

            backup_type = parts[0]
            if backup_type not in ("scheduled", "manual"):
                return None

            date_str = parts[1]
            time_str = parts[2]
            dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            return (backup_type, dt)
        except (ValueError, IndexError):
            return None

    def create_backup(self, manual: bool = True) -> BackupResult:
        """Create a new backup of the database.

        Args:
            manual: True for manual backup, False for scheduled

        Returns:
            BackupResult with success status and file info
        """
        self._ensure_backup_dir()

        backup_type = "manual" if manual else "scheduled"
        filename = self._generate_filename(backup_type)
        backup_filepath = self._backup_path / filename

        try:
            db_path = self._get_db_path()

            if not db_path.exists():
                return BackupResult(
                    success=False,
                    error=f"Database file not found: {db_path}",
                )

            # Use sqlite3.backup() for safe copy of live database
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(str(backup_filepath))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()

            # Get file size
            size_bytes = backup_filepath.stat().st_size

            logger.info(
                "[BACKUP] Created %s backup: %s (%d bytes)",
                backup_type,
                filename,
                size_bytes,
            )

            return BackupResult(
                success=True,
                filename=filename,
                filepath=str(backup_filepath),
                size_bytes=size_bytes,
            )

        except Exception as e:
            logger.error("[BACKUP] Failed to create backup: %s", e)
            # Clean up partial backup if it exists
            if backup_filepath.exists():
                backup_filepath.unlink()
            return BackupResult(
                success=False,
                error=str(e),
            )

    def list_backups(self) -> list[BackupInfo]:
        """List all backup files with metadata.

        Returns:
            List of BackupInfo sorted by creation time (newest first)
        """
        self._ensure_backup_dir()

        backups = []
        for file_path in self._backup_path.glob("teamarr_*.db"):
            parsed = self._parse_backup_filename(file_path.name)
            if not parsed:
                continue

            backup_type, created_at = parsed

            try:
                stat = file_path.stat()
                backups.append(
                    BackupInfo(
                        filename=file_path.name,
                        filepath=str(file_path),
                        size_bytes=stat.st_size,
                        created_at=created_at,
                        is_protected=self._is_protected(file_path),
                        backup_type=backup_type,
                    )
                )
            except OSError:
                continue

        # Sort by creation time, newest first
        backups.sort(key=lambda b: b.created_at, reverse=True)
        return backups

    def delete_backup(self, filename: str, force: bool = False) -> bool:
        """Delete a backup file.

        Args:
            filename: Backup filename
            force: If True, delete even if protected

        Returns:
            True if deleted, False if not found or protected
        """
        backup_path = self._backup_path / filename

        if not backup_path.exists():
            logger.warning("[BACKUP] Backup not found: %s", filename)
            return False

        if not force and self._is_protected(backup_path):
            logger.warning("[BACKUP] Cannot delete protected backup: %s", filename)
            return False

        try:
            # Remove backup file
            backup_path.unlink()

            # Remove protection marker if exists
            marker_path = self._get_protected_marker_path(backup_path)
            if marker_path.exists():
                marker_path.unlink()

            logger.info("[BACKUP] Deleted backup: %s", filename)
            return True

        except OSError as e:
            logger.error("[BACKUP] Failed to delete backup %s: %s", filename, e)
            return False

    def protect_backup(self, filename: str) -> bool:
        """Protect a backup from rotation deletion.

        Args:
            filename: Backup filename

        Returns:
            True if protected, False if not found
        """
        backup_path = self._backup_path / filename

        if not backup_path.exists():
            logger.warning("[BACKUP] Backup not found: %s", filename)
            return False

        marker_path = self._get_protected_marker_path(backup_path)

        try:
            marker_path.touch()
            logger.info("[BACKUP] Protected backup: %s", filename)
            return True
        except OSError as e:
            logger.error("[BACKUP] Failed to protect backup %s: %s", filename, e)
            return False

    def unprotect_backup(self, filename: str) -> bool:
        """Remove protection from a backup.

        Args:
            filename: Backup filename

        Returns:
            True if unprotected, False if not found or not protected
        """
        backup_path = self._backup_path / filename

        if not backup_path.exists():
            logger.warning("[BACKUP] Backup not found: %s", filename)
            return False

        marker_path = self._get_protected_marker_path(backup_path)

        if not marker_path.exists():
            logger.debug("[BACKUP] Backup already unprotected: %s", filename)
            return True

        try:
            marker_path.unlink()
            logger.info("[BACKUP] Unprotected backup: %s", filename)
            return True
        except OSError as e:
            logger.error("[BACKUP] Failed to unprotect backup %s: %s", filename, e)
            return False

    def rotate_backups(self, max_count: int) -> RotationResult:
        """Delete oldest unprotected backups exceeding max count.

        Protected backups don't count toward the limit and are never deleted.

        Args:
            max_count: Maximum number of unprotected backups to keep

        Returns:
            RotationResult with deletion stats
        """
        backups = self.list_backups()

        # Separate protected and unprotected
        protected = [b for b in backups if b.is_protected]
        unprotected = [b for b in backups if not b.is_protected]

        # Unprotected are already sorted newest first
        to_delete = unprotected[max_count:]
        deleted_files = []

        for backup in to_delete:
            if self.delete_backup(backup.filename):
                deleted_files.append(backup.filename)

        result = RotationResult(
            deleted_count=len(deleted_files),
            deleted_files=deleted_files,
            kept_count=min(len(unprotected), max_count),
            protected_count=len(protected),
        )

        if deleted_files:
            logger.info(
                "[BACKUP] Rotation complete: deleted %d, kept %d, protected %d",
                result.deleted_count,
                result.kept_count,
                result.protected_count,
            )

        return result

    def restore_backup(self, filename: str) -> tuple[bool, str, str | None]:
        """Restore database from a backup file.

        Creates a pre-restore backup in the configured backup directory,
        validates the backup file is valid SQLite, then replaces the active DB.

        Args:
            filename: Backup filename to restore from

        Returns:
            Tuple of (success, message, pre_restore_backup_path)
        """
        backup_path = self._backup_path / filename
        if not backup_path.exists():
            return False, "Backup not found", None

        # Validate the backup is a valid SQLite database
        try:
            conn = sqlite3.connect(str(backup_path))
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            if result[0] != "ok":
                return False, f"Backup file failed integrity check: {result[0]}", None
        except sqlite3.DatabaseError as e:
            return False, f"Backup file is not a valid SQLite database: {e}", None

        db_path = self._get_db_path()

        # Create pre-restore backup in the configured backup directory
        pre_restore_path = None
        if db_path.exists():
            self._ensure_backup_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_path = self._backup_path / f"teamarr_pre_restore_{timestamp}.db"
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(str(pre_restore_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            logger.info("[RESTORE] Created pre-restore backup at %s", pre_restore_path)

        # Validate passes — copy backup to active DB path
        src = sqlite3.connect(str(backup_path))
        dst = sqlite3.connect(str(db_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        logger.info("[RESTORE] Database restored from %s", filename)
        return (
            True,
            "Database restored. Please restart the application for changes to take effect.",
            str(pre_restore_path) if pre_restore_path else None,
        )

    def get_backup_filepath(self, filename: str) -> Path | None:
        """Get full path to a backup file.

        Args:
            filename: Backup filename

        Returns:
            Path if exists, None otherwise
        """
        backup_path = self._backup_path / filename
        if backup_path.exists():
            return backup_path
        return None


def create_backup_service(
    db_factory: Callable[[], Any],
    backup_path: str | None = None,
) -> BackupService:
    """Factory function to create backup service.

    Args:
        db_factory: Database connection factory
        backup_path: Optional backup directory path (uses settings if None)

    Returns:
        Configured BackupService instance
    """
    if backup_path is None:
        # Get path from settings
        from teamarr.database.settings import get_backup_settings

        with db_factory() as conn:
            settings = get_backup_settings(conn)
            backup_path = settings.path

    return BackupService(db_factory, backup_path)
