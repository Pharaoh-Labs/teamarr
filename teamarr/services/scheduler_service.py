"""Scheduler service facade.

This module provides a clean API for scheduler operations.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SchedulerStatus:
    """Status of the scheduler."""

    running: bool = False
    cron_expression: str = "0 * * * *"
    last_run: datetime | None = None
    next_run: datetime | None = None


@dataclass
class SchedulerRunResult:
    """Result of a scheduler run."""

    started_at: datetime | None = None
    completed_at: datetime | None = None
    epg_generation: dict = field(default_factory=dict)
    deletions: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)
    cleanup: dict = field(default_factory=dict)


class SchedulerService:
    """Service for scheduler operations.

    Wraps the consumer layer CronScheduler.
    """

    def __init__(
        self,
        db_factory: Callable[[], Any],
        dispatcharr_client: Any | None = None,
    ):
        """Initialize with database factory and optional Dispatcharr client."""
        self._db_factory = db_factory
        self._client = dispatcharr_client

    def start(self, cron_expression: str | None = None) -> bool:
        """Start the cron scheduler.

        Args:
            cron_expression: Cron expression (None = use settings)

        Returns:
            True if started, False if already running or disabled
        """
        from teamarr.consumers.scheduler import start_lifecycle_scheduler

        return start_lifecycle_scheduler(
            self._db_factory,
            cron_expression=cron_expression,
            dispatcharr_client=self._client,
        )

    def stop(self, timeout: float = 30.0) -> bool:
        """Stop the cron scheduler.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if stopped
        """
        from teamarr.consumers.scheduler import stop_lifecycle_scheduler

        return stop_lifecycle_scheduler(timeout)

    def get_status(self) -> SchedulerStatus:
        """Get scheduler status.

        Returns:
            SchedulerStatus with running state, cron expression, and run times
        """
        from teamarr.consumers.scheduler import get_scheduler_status

        status = get_scheduler_status()
        return SchedulerStatus(
            running=status.get("running", False),
            cron_expression=status.get("cron_expression", "0 * * * *"),
            last_run=(
                datetime.fromisoformat(status["last_run"])
                if status.get("last_run")
                else None
            ),
            next_run=(
                datetime.fromisoformat(status["next_run"])
                if status.get("next_run")
                else None
            ),
        )

    def run_once(self) -> SchedulerRunResult:
        """Run all scheduled tasks once (for testing/manual trigger).

        Returns:
            SchedulerRunResult with task results
        """
        from teamarr.consumers.scheduler import CronScheduler

        scheduler = CronScheduler(
            self._db_factory,
            dispatcharr_client=self._client,
            run_on_start=False,
        )
        result = scheduler.run_once()

        return SchedulerRunResult(
            started_at=(
                datetime.fromisoformat(result["started_at"])
                if result.get("started_at")
                else None
            ),
            completed_at=(
                datetime.fromisoformat(result["completed_at"])
                if result.get("completed_at")
                else None
            ),
            epg_generation=result.get("epg_generation", {}),
            deletions=result.get("deletions", {}),
            reconciliation=result.get("reconciliation", {}),
            cleanup=result.get("cleanup", {}),
        )


def create_scheduler_service(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None = None,
) -> SchedulerService:
    """Factory function to create scheduler service."""
    return SchedulerService(db_factory, dispatcharr_client)
