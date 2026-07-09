"""Channel lifecycle and reconciliation service facade.

This module provides a clean API for channel management operations.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from sqlite3 import Connection
from typing import Any

from teamarr.services.sports_data import SportsDataService


@dataclass
class DeletionResult:
    """Result of channel deletion processing."""

    deleted: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


@dataclass
class ReconciliationIssue:
    """A detected reconciliation issue."""

    issue_type: str
    severity: str
    managed_channel_id: int | None = None
    dispatcharr_channel_id: int | None = None
    channel_name: str | None = None
    event_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    suggested_action: str | None = None
    auto_fixable: bool = False


@dataclass
class ReconciliationSummary:
    """Summary of reconciliation results."""

    orphan_teamarr: int = 0
    orphan_dispatcharr: int = 0
    duplicates: int = 0
    drift: int = 0


@dataclass
class ReconciliationResult:
    """Result of reconciliation operation."""

    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: ReconciliationSummary = field(default_factory=ReconciliationSummary)
    issues_found: list[ReconciliationIssue] = field(default_factory=list)
    issues_fixed: list[dict] = field(default_factory=list)
    issues_skipped: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ChannelService:
    """Service for channel lifecycle and reconciliation.

    Wraps consumer layer lifecycle and reconciliation classes.
    """

    def __init__(
        self,
        db_factory: Callable[[], AbstractContextManager[Connection]],
        sports_service: SportsDataService,
        dispatcharr_client: Any | None = None,
    ):
        """Initialize with database factory and services."""
        self._db_factory = db_factory
        self._sports_service = sports_service
        self._client = dispatcharr_client

    def delete_channel(self, conn: Connection, channel_id: int, reason: str = "manual") -> bool:
        """Delete a managed channel.

        Args:
            conn: Database connection
            channel_id: ID of managed channel to delete
            reason: Reason for deletion

        Returns:
            True if deleted successfully
        """
        from teamarr.consumers.channel_lifecycle import create_lifecycle_service

        service = create_lifecycle_service(
            self._db_factory,
            self._sports_service,
            self._client,
        )
        return service.delete_managed_channel(conn, channel_id, reason=reason)

    def process_scheduled_deletions(self) -> DeletionResult:
        """Process channels scheduled for deletion.

        Returns:
            DeletionResult with list of deleted channel IDs and errors
        """
        from teamarr.consumers.channel_lifecycle import create_lifecycle_service

        service = create_lifecycle_service(
            self._db_factory,
            self._sports_service,
            self._client,
        )
        result = service.process_scheduled_deletions()

        return DeletionResult(
            deleted=result.deleted,
            errors=result.errors,
        )

    def reconcile(
        self,
        auto_fix: bool = False,
    ) -> ReconciliationResult:
        """Run channel reconciliation across all channels.

        Args:
            auto_fix: Whether to automatically fix issues

        Returns:
            ReconciliationResult with issues found and fixed
        """
        from teamarr.consumers.reconciliation import create_reconciler

        reconciler = create_reconciler(self._db_factory, self._client)
        result = reconciler.reconcile(auto_fix=auto_fix)

        # Convert consumer types to service types
        issues = [
            ReconciliationIssue(
                issue_type=i.issue_type,
                severity=i.severity,
                managed_channel_id=i.managed_channel_id,
                dispatcharr_channel_id=i.dispatcharr_channel_id,
                channel_name=i.channel_name,
                event_id=i.event_id,
                details=i.details,
                suggested_action=i.suggested_action,
                auto_fixable=i.auto_fixable,
            )
            for i in result.issues_found
        ]

        summary = ReconciliationSummary(
            orphan_teamarr=result.summary.get("orphan_teamarr", 0),
            orphan_dispatcharr=result.summary.get("orphan_dispatcharr", 0),
            duplicates=result.summary.get("duplicates", 0),
            drift=result.summary.get("drift", 0),
        )

        return ReconciliationResult(
            started_at=result.started_at,
            completed_at=result.completed_at,
            summary=summary,
            issues_found=issues,
            issues_fixed=result.issues_fixed,
            issues_skipped=result.issues_skipped,
            errors=result.errors,
        )


def create_channel_service(
    db_factory: Callable[[], AbstractContextManager[Connection]],
    sports_service: SportsDataService,
    dispatcharr_client: Any | None = None,
) -> ChannelService:
    """Factory function to create channel service."""
    return ChannelService(db_factory, sports_service, dispatcharr_client)
