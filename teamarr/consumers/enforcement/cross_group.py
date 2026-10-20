"""Cross-group stream consolidation enforcement.

NO-OP since zo8.3/zo8.4: Channel creation is now event-scoped, so duplicate
channels across groups cannot be created. The unique index
(event_id, event_provider, keyword, stream_id) prevents it at the DB level.

This module is retained for API compatibility. The enforce() method returns
an empty result immediately.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CrossGroupResult:
    """Result of cross-group consolidation."""

    streams_moved: list[dict] = field(default_factory=list)
    channels_deleted: list[dict] = field(default_factory=list)
    channels_skipped: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    @property
    def moved_count(self) -> int:
        return len(self.streams_moved)

    @property
    def deleted_count(self) -> int:
        return len(self.channels_deleted)

    def to_dict(self) -> dict:
        return {
            "streams_moved": self.streams_moved,
            "channels_deleted": self.channels_deleted,
            "channels_skipped": self.channels_skipped,
            "errors": self.errors,
            "summary": {
                "moved": self.moved_count,
                "deleted": self.deleted_count,
                "skipped": len(self.channels_skipped),
                "errors": len(self.errors),
            },
        }


class CrossGroupEnforcer:
    """No-op: cross-group consolidation is handled at channel creation time.

    Channel lookups are event-scoped (zo8.3) and the unique index (zo8.4)
    prevents duplicate channels for the same event. No post-hoc merging needed.
    """

    def __init__(
        self,
        db_factory: Any,
        channel_manager: Any = None,
    ):
        self._db_factory = db_factory
        self._channel_manager = channel_manager

    def enforce(self, group_ids: list[int] | None = None) -> CrossGroupResult:
        """No-op — returns empty result.

        Cross-group duplicates cannot exist since channel creation is
        event-scoped. Retained for API compatibility.
        """
        logger.debug(
            "[CROSS_GROUP] No-op — event-scoped channel creation prevents cross-group duplicates"
        )
        return CrossGroupResult()
