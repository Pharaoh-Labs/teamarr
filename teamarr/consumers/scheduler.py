"""Background scheduler for EPG generation.

Uses cron expressions for scheduling (like V1).
Runs periodic EPG generation using the unified run_full_generation() function
which handles everything:
- EPG generation (teams, groups, XMLTV)
- Dispatcharr integration
- Channel lifecycle (deletions, reconciliation, cleanup)

Integrates with FastAPI lifespan for clean startup/shutdown.
"""

import logging
import threading
from datetime import datetime
from typing import Any

from croniter import croniter

logger = logging.getLogger(__name__)


class SubTaskScheduler:
    """Lightweight scheduler that runs a single task on its own cron.

    Runs independently of the main EPG scheduler so tasks like backup
    and channel reset fire at exactly the right time regardless of
    EPG schedule alignment.
    """

    def __init__(self, name: str, task_fn: Any, cron_expression: str):
        self._name = name
        self._task_fn = task_fn
        self._cron = cron_expression
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._next_run: datetime | None = None

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def cron_expression(self) -> str:
        return self._cron

    @property
    def next_run(self) -> datetime | None:
        return self._next_run

    def start(self) -> bool:
        if self.is_running:
            return False
        try:
            croniter(self._cron)
        except (KeyError, ValueError) as e:
            logger.error("[CRON:%s] Invalid expression '%s': %s", self._name, self._cron, e)
            return False
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"cron-{self._name}",
            daemon=True,
        )
        self._thread.start()
        logger.info("[CRON:%s] Started: %s", self._name, self._cron)
        return True

    def stop(self, timeout: float = 10.0) -> bool:
        if not self.is_running:
            return True
        logger.debug("[CRON:%s] Stopping...", self._name)
        self._stop_event.set()
        self._running = False
        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("[CRON:%s] Thread did not stop in time", self._name)
                return False
        return True

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            cron = croniter(self._cron, datetime.now())
            self._next_run = cron.get_next(datetime)
            wait_seconds = (self._next_run - datetime.now()).total_seconds()
            logger.debug(
                "[CRON:%s] Next run: %s (%.0fs)",
                self._name,
                self._next_run.strftime("%Y-%m-%d %H:%M:%S"),
                wait_seconds,
            )
            while wait_seconds > 0 and not self._stop_event.is_set():
                self._stop_event.wait(min(1.0, wait_seconds))
                wait_seconds = (self._next_run - datetime.now()).total_seconds()
            if self._stop_event.is_set():
                return
            try:
                logger.info("[CRON:%s] Running scheduled task", self._name)
                self._task_fn()
            except Exception as e:
                logger.exception("[CRON:%s] Task failed: %s", self._name, e)


class CronScheduler:
    """Background scheduler using cron expressions.

    Runs tasks at times specified by a cron expression.

    Usage:
        scheduler = CronScheduler(
            db_factory=get_db,
            cron_expression="0 * * * *",  # Every hour
        )
        scheduler.start()
        # ... application runs ...
        scheduler.stop()

    FastAPI integration:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            scheduler = CronScheduler(get_db, "0 * * * *")
            scheduler.start()
            yield
            scheduler.stop()
    """

    def __init__(
        self,
        db_factory: Any,
        cron_expression: str = "0 * * * *",
        dispatcharr_client: Any = None,
        run_on_start: bool = True,
    ):
        """Initialize the scheduler.

        Args:
            db_factory: Factory function returning database connection
            cron_expression: Cron expression (e.g., "0 * * * *" for hourly)
            dispatcharr_client: Optional DispatcharrClient for Dispatcharr operations
            run_on_start: Whether to run tasks immediately on start
        """
        self._db_factory = db_factory
        self._cron_expression = cron_expression
        self._dispatcharr_client = dispatcharr_client
        self._run_on_start = run_on_start

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._last_run: datetime | None = None
        self._next_run: datetime | None = None
        self._sub_schedulers: dict[str, SubTaskScheduler] = {}

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def last_run(self) -> datetime | None:
        """Get time of last task run."""
        return self._last_run

    @property
    def next_run(self) -> datetime | None:
        """Get time of next scheduled run."""
        return self._next_run

    @property
    def cron_expression(self) -> str:
        """Get the cron expression."""
        return self._cron_expression

    def start(self) -> bool:
        """Start the scheduler.

        Returns:
            True if started, False if already running
        """
        if self.is_running:
            logger.warning("[CRON] Scheduler already running")
            return False

        # Validate cron expression
        try:
            croniter(self._cron_expression)
        except (KeyError, ValueError) as e:
            logger.error("[CRON] Invalid expression '%s': %s", self._cron_expression, e)
            return False

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="cron-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("[CRON] Scheduler started: %s", self._cron_expression)

        # Start independent sub-schedulers for backup and channel reset
        self._start_sub_schedulers()

        return True

    def stop(self, timeout: float = 30.0) -> bool:
        """Stop the scheduler gracefully.

        Args:
            timeout: Maximum seconds to wait for thread to stop

        Returns:
            True if stopped, False if timeout
        """
        if not self.is_running:
            return True

        # Stop sub-schedulers first
        for _name, sub in self._sub_schedulers.items():
            sub.stop(timeout=5.0)
        self._sub_schedulers.clear()

        logger.debug("[CRON] Stopping scheduler...")
        self._stop_event.set()
        self._running = False

        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("[CRON] Scheduler thread did not stop in time")
                return False

        logger.info("[CRON] Scheduler stopped")
        return True

    def _start_sub_schedulers(self) -> None:
        """Start independent sub-schedulers for backup and channel reset."""
        from teamarr.database.settings import get_backup_settings, get_scheduler_settings

        with self._db_factory() as conn:
            backup_settings = get_backup_settings(conn)
            scheduler_settings = get_scheduler_settings(conn)

        if backup_settings.enabled:
            sub = SubTaskScheduler("backup", self._task_backup, backup_settings.cron)
            if sub.start():
                self._sub_schedulers["backup"] = sub

        if scheduler_settings.channel_reset_enabled and scheduler_settings.channel_reset_cron:
            sub = SubTaskScheduler(
                "channel-reset", self._task_channel_reset, scheduler_settings.channel_reset_cron
            )
            if sub.start():
                self._sub_schedulers["channel_reset"] = sub

    def restart_sub_task(self, task_name: str) -> None:
        """Restart a sub-scheduler after settings change."""
        # Stop existing if running
        if task_name in self._sub_schedulers:
            self._sub_schedulers[task_name].stop(timeout=5.0)
            del self._sub_schedulers[task_name]

        if task_name == "backup":
            from teamarr.database.settings import get_backup_settings

            with self._db_factory() as conn:
                settings = get_backup_settings(conn)
            if settings.enabled:
                sub = SubTaskScheduler("backup", self._task_backup, settings.cron)
                if sub.start():
                    self._sub_schedulers["backup"] = sub
        elif task_name == "channel_reset":
            from teamarr.database.settings import get_scheduler_settings

            with self._db_factory() as conn:
                settings = get_scheduler_settings(conn)
            if settings.channel_reset_enabled and settings.channel_reset_cron:
                sub = SubTaskScheduler(
                    "channel-reset", self._task_channel_reset, settings.channel_reset_cron
                )
                if sub.start():
                    self._sub_schedulers["channel_reset"] = sub

    def run_once(self) -> dict:
        """Run all scheduled tasks once (for testing/manual trigger).

        Returns:
            Dict with task results
        """
        results = self._run_tasks()
        # Also run sub-tasks synchronously for manual trigger
        try:
            results["backup"] = self._task_backup()
        except Exception as e:
            results["backup"] = {"error": str(e)}
        try:
            results["channel_reset"] = self._task_channel_reset()
        except Exception as e:
            results["channel_reset"] = {"error": str(e)}
        return results

    def _run_loop(self) -> None:
        """Main scheduler loop - runs in background thread."""
        # Run immediately on startup if configured
        if self._run_on_start:
            try:
                logger.info("[CRON] Running initial scheduled tasks")
                self._run_tasks()
            except Exception as e:
                logger.exception("[CRON] Error in initial run: %s", e)

        while not self._stop_event.is_set():
            # Calculate next run time
            cron = croniter(self._cron_expression, datetime.now())
            self._next_run = cron.get_next(datetime)

            wait_seconds = (self._next_run - datetime.now()).total_seconds()
            logger.debug(
                "[CRON] Next run: %s (%.0fs)",
                self._next_run.strftime("%Y-%m-%d %H:%M:%S"),
                wait_seconds,
            )

            # Wait until next run time (checking stop event every second)
            while wait_seconds > 0 and not self._stop_event.is_set():
                self._stop_event.wait(min(1.0, wait_seconds))
                wait_seconds = (self._next_run - datetime.now()).total_seconds()

            if self._stop_event.is_set():
                return

            # Run tasks
            try:
                logger.info("[CRON] Scheduled run triggered")
                self._run_tasks()
            except Exception as e:
                logger.exception("[CRON] Error in scheduled run: %s", e)

    def _run_tasks(self) -> dict:
        """Run EPG-related scheduled tasks.

        Backup and channel reset run on their own independent sub-schedulers
        and are NOT part of the EPG tick. They are only called here via run_once().

        Returns:
            Dict with task results
        """
        self._last_run = datetime.now()
        results = {
            "started_at": self._last_run.isoformat(),
            "cache_refresh": {},
            "epg_generation": {},
        }

        # Daily cache refresh (only refreshes if > 1 day old)
        try:
            results["cache_refresh"] = self._task_refresh_cache()
        except Exception as e:
            logger.warning("[CRON] Cache refresh task failed: %s", e)
            results["cache_refresh"] = {"error": str(e)}

        try:
            # Single unified generation call - does everything
            results["epg_generation"] = self._task_generate_epg()
        except Exception as e:
            logger.warning("[CRON] EPG generation task failed: %s", e)
            results["epg_generation"] = {"error": str(e)}

        results["completed_at"] = datetime.now().isoformat()
        return results

    def _task_channel_reset(self) -> dict:
        """Reset all Teamarr channels.

        Called by its own sub-scheduler at the configured cron time.
        Purges all Teamarr channels from Dispatcharr.

        This helps users with Jellyfin logo caching issues - by scheduling
        reset right before Jellyfin's guide refresh, channel logos get
        re-downloaded fresh.

        Returns:
            Dict with reset status
        """
        from teamarr.database.settings import get_scheduler_settings

        with self._db_factory() as conn:
            settings = get_scheduler_settings(conn)

        if not settings.channel_reset_enabled:
            return {"skipped": True, "reason": "Channel reset not enabled"}

        if not settings.channel_reset_cron:
            return {"skipped": True, "reason": "No reset cron expression configured"}

        logger.info("[CRON] Running scheduled channel reset")

        from teamarr.dispatcharr import ChannelManager, get_dispatcharr_client

        client = get_dispatcharr_client(self._db_factory)
        if not client:
            return {"skipped": True, "reason": "Dispatcharr not connected"}

        manager = ChannelManager(client)
        all_channels = manager.get_channels()

        deleted_count = 0
        errors: list[str] = []

        for ch in all_channels:
            tvg_id = ch.tvg_id or ""
            if not tvg_id.startswith("teamarr-event-"):
                continue

            result = manager.delete_channel(ch.id)
            if result.success:
                deleted_count += 1
            else:
                errors.append(f"Failed to delete {ch.name}: {result.error}")

        # Mark all managed_channels as deleted
        with self._db_factory() as conn:
            conn.execute(
                """UPDATE managed_channels
                   SET deleted_at = CURRENT_TIMESTAMP
                   WHERE deleted_at IS NULL"""
            )
            conn.commit()

        logger.info("[CRON] Channel reset complete: deleted %d channels", deleted_count)

        return {
            "executed": True,
            "deleted_count": deleted_count,
            "error_count": len(errors),
            "errors": errors if errors else None,
        }

    def _task_backup(self) -> dict:
        """Run scheduled backup.

        Called by its own sub-scheduler at the configured cron time.

        Returns:
            Dict with backup status
        """
        from teamarr.database.settings import get_backup_settings

        with self._db_factory() as conn:
            settings = get_backup_settings(conn)

        if not settings.enabled:
            return {"skipped": True, "reason": "Scheduled backups not enabled"}

        logger.info("[CRON] Running scheduled backup")

        from teamarr.services.backup_service import create_backup_service

        backup_service = create_backup_service(self._db_factory, settings.path)
        result = backup_service.create_backup(manual=False)

        if not result.success:
            logger.error("[CRON] Scheduled backup failed: %s", result.error)
            return {"executed": True, "success": False, "error": result.error}

        # Rotate old backups
        rotation = backup_service.rotate_backups(settings.max_count)

        logger.info(
            "[CRON] Scheduled backup complete: %s (%d bytes), rotated %d",
            result.filename,
            result.size_bytes or 0,
            rotation.deleted_count,
        )

        return {
            "executed": True,
            "success": True,
            "filename": result.filename,
            "size_bytes": result.size_bytes,
            "rotated": rotation.deleted_count,
        }

    def _task_refresh_cache(self) -> dict:
        """Refresh team/league cache if stale (daily).

        Cache is also refreshed unconditionally on every startup and
        can be triggered manually via the UI. This scheduled check
        catches staleness for long-running instances that haven't
        restarted in over a day.

        Returns:
            Dict with refresh status
        """
        from teamarr.services import create_cache_service

        cache_service = create_cache_service(self._db_factory)
        refreshed = cache_service.refresh_if_needed(max_age_days=1)

        if refreshed:
            stats = cache_service.get_stats()
            logger.info(
                "[CRON] Daily cache refresh: %d leagues, %d teams",
                stats.leagues_count,
                stats.teams_count,
            )
            return {
                "refreshed": True,
                "leagues_count": stats.leagues_count,
                "teams_count": stats.teams_count,
            }
        else:
            logger.debug("[CRON] Cache refresh skipped: not stale")
            return {"refreshed": False, "reason": "Cache not stale yet"}

    def _task_generate_epg(self) -> dict:
        """Generate EPG using the unified generation workflow.

        Uses run_full_generation() which handles:
        - M3U refresh
        - Team and event group processing
        - XMLTV merging and file output
        - Dispatcharr integration
        - Channel lifecycle (deletions, reconciliation, cleanup)

        Returns:
            Dict with generation stats
        """
        from teamarr.api.generation_status import (
            complete_generation,
            fail_generation,
            start_generation,
            update_status,
        )
        from teamarr.consumers.generation import run_full_generation

        # Mark generation as started (enables UI polling)
        if not start_generation():
            logger.warning("[CRON] EPG generation skipped: already in progress")
            return {"success": False, "error": "Generation already in progress"}

        def progress_callback(
            phase: str,
            percent: int,
            message: str,
            current: int,
            total: int,
            item_name: str,
        ):
            """Update global status for UI polling."""
            update_status(
                status="progress",
                phase=phase,
                percent=percent,
                message=message,
                current=current,
                total=total,
                item_name=item_name,
            )

        # Get fresh Dispatcharr connection from factory
        # (stored reference may be stale if settings were updated)
        from teamarr.dispatcharr import get_dispatcharr_connection

        dispatcharr_client = get_dispatcharr_connection(self._db_factory)

        # Run the unified generation with progress tracking
        result = run_full_generation(
            db_factory=self._db_factory,
            dispatcharr_client=dispatcharr_client,
            progress_callback=progress_callback,
        )

        # Update global status on completion
        if result.success:
            complete_generation(
                {
                    "success": True,
                    "programmes_count": result.programmes_total,
                    "teams_processed": result.teams_processed,
                    "groups_processed": result.groups_processed,
                    "duration_seconds": result.duration_seconds,
                    "run_id": result.run_id,
                }
            )
        else:
            fail_generation(result.error or "Unknown error")

        # Convert to dict format for backward compatibility
        return {
            "success": result.success,
            "error": result.error,
            "programmes_generated": result.programmes_total,
            "teams_processed": result.teams_processed,
            "teams_programmes": result.teams_programmes,
            "groups_processed": result.groups_processed,
            "groups_programmes": result.groups_programmes,
            "file_written": result.file_written,
            "file_path": result.file_path,
            "file_size": result.file_size,
            "duration_seconds": result.duration_seconds,
            "m3u_refresh": result.m3u_refresh,
            "epg_refresh": result.epg_refresh,
            "epg_association": result.epg_association,
            "deletions": result.deletions,
            "reconciliation": result.reconciliation,
            "cleanup": result.cleanup,
            "run_id": result.run_id,
        }


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

# Keep old name for backward compatibility
LifecycleScheduler = CronScheduler

_scheduler: CronScheduler | None = None


def start_lifecycle_scheduler(
    db_factory: Any,
    cron_expression: str | None = None,
    dispatcharr_client: Any = None,
) -> bool:
    """Start the global cron scheduler.

    Args:
        db_factory: Factory function returning database connection
        cron_expression: Cron expression (None = use settings)
        dispatcharr_client: Optional DispatcharrClient instance

    Returns:
        True if started, False if already running or disabled
    """
    global _scheduler

    from teamarr.database.settings import get_epg_settings, get_scheduler_settings

    # Get settings
    with db_factory() as conn:
        scheduler_settings = get_scheduler_settings(conn)
        epg_settings = get_epg_settings(conn)

    if not scheduler_settings.enabled:
        logger.info("[CRON] Scheduler disabled in settings")
        return False

    # Use provided cron expression or fall back to settings
    cron = cron_expression or epg_settings.cron_expression or "0 * * * *"

    if _scheduler and _scheduler.is_running:
        logger.warning("[CRON] Scheduler already running")
        return False

    _scheduler = CronScheduler(
        db_factory=db_factory,
        cron_expression=cron,
        dispatcharr_client=dispatcharr_client,
        run_on_start=False,  # Don't run EPG generation on startup
    )
    return _scheduler.start()


def stop_lifecycle_scheduler(timeout: float = 30.0) -> bool:
    """Stop the global cron scheduler.

    Args:
        timeout: Maximum seconds to wait

    Returns:
        True if stopped
    """
    global _scheduler

    if not _scheduler:
        return True

    result = _scheduler.stop(timeout)
    _scheduler = None
    return result


def is_scheduler_running() -> bool:
    """Check if the global scheduler is running."""
    return _scheduler is not None and _scheduler.is_running


def get_scheduler_status() -> dict:
    """Get status of the global scheduler."""
    if not _scheduler:
        return {"running": False}

    status = {
        "running": _scheduler.is_running,
        "cron_expression": _scheduler.cron_expression,
        "last_run": _scheduler.last_run.isoformat() if _scheduler.last_run else None,
        "next_run": _scheduler.next_run.isoformat() if _scheduler.next_run else None,
        "sub_tasks": {},
    }

    for name, sub in _scheduler._sub_schedulers.items():
        status["sub_tasks"][name] = {
            "running": sub.is_running,
            "cron_expression": sub.cron_expression,
            "next_run": sub.next_run.isoformat() if sub.next_run else None,
        }

    return status


def restart_scheduler_sub_task(task_name: str) -> bool:
    """Restart a sub-scheduler task (e.g., after settings change).

    Args:
        task_name: "backup" or "channel_reset"

    Returns:
        True if restarted, False if scheduler not running
    """
    if not _scheduler or not _scheduler.is_running:
        return False
    _scheduler.restart_sub_task(task_name)
    return True


