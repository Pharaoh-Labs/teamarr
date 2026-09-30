"""Database maintenance: size reporting and compaction (#906).

SQLite never returns freed pages to the filesystem on its own, so cutting
the run-history retention shrinks the database internally but leaves the
file the same size; only VACUUM rewrites it. VACUUM needs roughly the compacted
size again as free space and holds writers out for its duration, so it
runs here as an explicit, single-flight background job that refuses to
overlap a generation run (it takes the generation lock, so a scheduled run
that fires mid-compaction is skipped as "already in progress" rather than
failing on a locked database).
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from teamarr.database.connection import resolve_db_path
from teamarr.utilities.tz import now_utc, to_db_utc

logger = logging.getLogger(__name__)

# The two per-stream history tables that dominate database size.
_DETAIL_TABLES = ("epg_matched_streams", "epg_failed_matches")


@dataclass
class CompactionState:
    """Single-flight compaction job state, reported by get_database_status."""

    running: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    before_bytes: int | None = None
    after_bytes: int | None = None
    error: str | None = None


_state = CompactionState()
_state_lock = threading.Lock()


def _file_bytes(path: Path) -> int:
    """Size of the database file plus its WAL (what the volume actually holds)."""
    total = path.stat().st_size if path.exists() else 0
    wal = path.with_name(path.name + "-wal")
    if wal.exists():
        total += wal.stat().st_size
    return total


def _free_disk_bytes(path: Path) -> int | None:
    """Free space on the volume holding the database (None if unreadable)."""
    try:
        return shutil.disk_usage(path.parent).free
    except OSError:
        return None


def get_database_status(db_path: Path | str | None = None) -> dict:
    """Report file size, reclaimable free pages, history row counts and the
    compaction job state."""
    path = resolve_db_path(db_path)
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
        counts = {}
        for table in _DETAIL_TABLES:
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                counts[table] = 0
        try:
            runs = conn.execute("SELECT COUNT(*) FROM processing_runs").fetchone()[0]
        except sqlite3.Error:
            runs = 0
    finally:
        conn.close()
    with _state_lock:
        state = asdict(_state)
    return {
        "path": str(path),
        "file_bytes": _file_bytes(path),
        "reclaimable_bytes": page_size * freelist,
        "live_bytes": page_size * (page_count - freelist),
        "free_disk_bytes": _free_disk_bytes(path),
        "run_count": runs,
        "detail_rows": counts,
        "compaction": state,
    }


def _run_vacuum(path: Path) -> None:
    # isolation_level=None: VACUUM cannot run inside a transaction, and the
    # sqlite3 module would otherwise open one implicitly.
    conn = sqlite3.connect(path, timeout=30.0, isolation_level=None)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    finally:
        conn.close()


def compact_database(db_path: Path | str | None = None, *, wait: bool = False) -> dict:
    """Start a VACUUM in the background (single-flight, generation-exclusive).

    Returns the compaction state. ``wait=True`` runs synchronously (tests).

    Raises:
        RuntimeError: a compaction or a generation run is already in progress,
            or the volume is too full for the rewrite.
    """
    from teamarr.consumers.generation import _generation_lock

    path = resolve_db_path(db_path)
    # VACUUM writes the compacted copy back through the WAL, so the volume
    # needs the *live* size free (file minus reclaimable pages), not the file
    # size. Refuse up front: a VACUUM that fills the disk halfway fails just
    # the same, after holding generation out for the whole attempt.
    try:
        status = get_database_status(path)
        free, needed = status["free_disk_bytes"], status["live_bytes"]
    except sqlite3.Error:
        free, needed = None, 0  # unreadable file: let the job report it
    if free is not None and free < needed:
        raise RuntimeError(
            f"Not enough free disk space to compact: needs about {needed // 2**20} MB, "
            f"{free // 2**20} MB free. Freed space inside the file is still reused by "
            "new rows without compacting."
        )
    with _state_lock:
        if _state.running:
            raise RuntimeError("Compaction already in progress")
        if not _generation_lock.acquire(blocking=False):
            raise RuntimeError("Generation in progress — try again when it finishes")
        _state.running = True
        _state.started_at = to_db_utc(now_utc())
        _state.finished_at = None
        _state.before_bytes = _file_bytes(path)
        _state.after_bytes = None
        _state.error = None

    def _job() -> None:
        try:
            logger.info(
                "[MAINTENANCE] Compacting database %s (%d bytes)", path, _state.before_bytes
            )
            _run_vacuum(path)
            after = _file_bytes(path)
            with _state_lock:
                _state.after_bytes = after
            logger.info(
                "[MAINTENANCE] Compaction done: %d → %d bytes",
                _state.before_bytes or 0,
                after,
            )
        except Exception as e:  # noqa: BLE001 — surfaced to the UI via state
            logger.error("[MAINTENANCE] Compaction failed: %s", e)
            with _state_lock:
                _state.error = str(e)
        finally:
            with _state_lock:
                _state.running = False
                _state.finished_at = to_db_utc(now_utc())
            _generation_lock.release()

    if wait:
        _job()
    else:
        threading.Thread(target=_job, name="db-compaction", daemon=True).start()
    with _state_lock:
        return asdict(_state)


__all__ = ["CompactionState", "compact_database", "get_database_status"]
