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
    mode: str = "pre_match"  # "pre_match" | "cron"
    cron_expression: str = "0 * * * *"
    pre_match_lead_minutes: int = 30
    discovery_interval_hours: int = 4
    last_run: datetime | None = None
    next_run: datetime | None = None
    next_run_reason: str | None = None  # "pre_match" | "discovery" | "cron"
    next_match_start: datetime | None = None
    next_match_sport: str | None = None


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

    def start(
        self,
        mode: str | None = None,
        pre_match_lead_minutes: int | None = None,
        discovery_interval_hours: int | None = None,
        cron_expression: str | None = None,
    ) -> bool:
        """Start the scheduler.

        Args:
            mode: "pre_match" or "cron" (None = use settings)
            pre_match_lead_minutes: (pre_match mode) Minutes before a match
                to trigger generation (None = use settings)
            discovery_interval_hours: (pre_match mode) Fallback discovery
                cadence in hours (None = use settings)
            cron_expression: (cron mode) Cron expression (None = use settings)

        Returns:
            True if started, False if already running, disabled, or invalid
        """
        from teamarr.consumers.scheduler import start_lifecycle_scheduler

        return start_lifecycle_scheduler(
            self._db_factory,
            mode=mode,
            pre_match_lead_minutes=pre_match_lead_minutes,
            discovery_interval_hours=discovery_interval_hours,
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
            SchedulerStatus with running state, triggers, and run times
        """
        from teamarr.consumers.scheduler import get_scheduler_status

        status = get_scheduler_status()
        return SchedulerStatus(
            running=status.get("running", False),
            mode=status.get("mode", "pre_match"),
            cron_expression=status.get("cron_expression", "0 * * * *"),
            pre_match_lead_minutes=status.get("pre_match_lead_minutes", 30),
            discovery_interval_hours=status.get("discovery_interval_hours", 4),
            last_run=(
                datetime.fromisoformat(status["last_run"]) if status.get("last_run") else None
            ),
            next_run=(
                datetime.fromisoformat(status["next_run"]) if status.get("next_run") else None
            ),
            next_run_reason=status.get("next_run_reason"),
            next_match_start=(
                datetime.fromisoformat(status["next_match_start"])
                if status.get("next_match_start")
                else None
            ),
            next_match_sport=status.get("next_match_sport"),
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
                datetime.fromisoformat(result["started_at"]) if result.get("started_at") else None
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
