"""Event group processing service facade.

Only the match preview is exposed here. Groups are never processed on their
own — they run inside a full generation (``run_full_generation``), where
each group's counters roll up into the parent ``full_epg`` run (#645).
"""

from collections.abc import Callable
from datetime import date
from typing import Any


class GroupService:
    """Service for event group operations.

    Wraps the consumer layer EventGroupProcessor.
    """

    def __init__(
        self,
        db_factory: Callable[[], Any],
        dispatcharr_client: Any | None = None,
    ):
        """Initialize with database factory and optional Dispatcharr client."""
        self._db_factory = db_factory
        self._client = dispatcharr_client

    def preview_group(
        self,
        group_id: int,
        target_date: date | None = None,
    ):
        """Preview stream matching for a group without creating channels.

        Args:
            group_id: Group ID to preview
            target_date: Target date (defaults to today)

        Returns:
            PreviewResult from the processor
        """
        from teamarr.consumers.event_group_processor import preview_event_group

        return preview_event_group(
            db_factory=self._db_factory,
            group_id=group_id,
            dispatcharr_client=self._client,
            target_date=target_date,
        )


def create_group_service(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None = None,
) -> GroupService:
    """Factory function to create group service."""
    return GroupService(db_factory, dispatcharr_client)
