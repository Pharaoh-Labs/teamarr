"""Keyword channel ordering enforcement.

Ensures main channel (no exception_keyword) has lower channel number
than keyword channels (Spanish, French, etc.) for the same event.

When to use:
- After channel creation, numbers may be assigned in wrong order
- Main channel should always come before its sub-channels in EPG guides
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OrderingResult:
    """Result of keyword ordering enforcement."""

    reordered: list[dict] = field(default_factory=list)
    already_correct: int = 0
    errors: list[dict] = field(default_factory=list)

    @property
    def reordered_count(self) -> int:
        return len(self.reordered)

    def to_dict(self) -> dict:
        return {
            "reordered": self.reordered,
            "already_correct": self.already_correct,
            "errors": self.errors,
            "summary": {
                "reordered": self.reordered_count,
                "correct": self.already_correct,
                "errors": len(self.errors),
            },
        }


class KeywordOrderingEnforcer:
    """Enforces channel ordering: main before keyword channels.

    For each event with multiple channels (main + keyword variants),
    ensures the main channel (no exception_keyword) has a lower
    channel number than keyword channels.

    This is important for EPG guide ordering - users expect to see
    the main English feed before Spanish/French variants.
    """

    def __init__(
        self,
        db_factory: Any,
        channel_manager: Any = None,
    ):
        """Initialize the enforcer.

        Args:
            db_factory: Factory returning database connection
            channel_manager: Optional ChannelManager for Dispatcharr sync
        """
        self._db_factory = db_factory
        self._channel_manager = channel_manager
        self._dispatcharr_lock = threading.Lock()

    def enforce(self) -> OrderingResult:
        """Run keyword ordering enforcement.

        Finds events where keyword channel has lower number than main,
        and swaps their channel numbers.

        Returns:
            OrderingResult with reorder details
        """
        from teamarr.database.channels import (
            log_channel_history,
            update_managed_channel,
        )

        result = OrderingResult()

        try:
            with self._db_factory() as conn:
                # Find channel pairs needing reorder
                pairs = self._get_channels_needing_reorder(conn)

                for pair in pairs:
                    main_channel = pair["main_channel"]
                    keyword_channel = pair["keyword_channel"]

                    main_number = main_channel["channel_number"]
                    keyword_number = keyword_channel["channel_number"]

                    try:
                        # Swap in Dispatcharr
                        if self._channel_manager:
                            with self._dispatcharr_lock:
                                # Set main to keyword's (lower) number
                                self._channel_manager.update_channel(
                                    main_channel["dispatcharr_channel_id"],
                                    {"channel_number": keyword_number},
                                )
                                # Set keyword to main's (higher) number
                                self._channel_manager.update_channel(
                                    keyword_channel["dispatcharr_channel_id"],
                                    {"channel_number": main_number},
                                )

                        # Swap in database
                        update_managed_channel(
                            conn,
                            main_channel["id"],
                            {"channel_number": keyword_number},
                        )
                        update_managed_channel(
                            conn,
                            keyword_channel["id"],
                            {"channel_number": main_number},
                        )

                        # Log history
                        log_channel_history(
                            conn=conn,
                            managed_channel_id=main_channel["id"],
                            change_type="number_swapped",
                            change_source="keyword_ordering",
                            field_name="channel_number",
                            old_value=str(main_number),
                            new_value=str(keyword_number),
                            notes="Swapped with keyword channel for main-first ordering",
                        )
                        log_channel_history(
                            conn=conn,
                            managed_channel_id=keyword_channel["id"],
                            change_type="number_swapped",
                            change_source="keyword_ordering",
                            field_name="channel_number",
                            old_value=str(keyword_number),
                            new_value=str(main_number),
                            notes="Swapped with main channel for main-first ordering",
                        )

                        result.reordered.append(
                            {
                                "event_id": main_channel["event_id"],
                                "main_channel": main_channel["channel_name"],
                                "keyword_channel": keyword_channel["channel_name"],
                                "keyword": keyword_channel["exception_keyword"],
                                "old_main_number": main_number,
                                "new_main_number": keyword_number,
                            }
                        )

                        logger.info(
                            f"Reordered: main #{keyword_number} <-> "
                            f"keyword '{keyword_channel['exception_keyword']}' #{main_number} "
                            f"(event: {main_channel['event_id']})"
                        )

                    except Exception as e:
                        logger.warning(f"Failed to reorder channels: {e}")
                        result.errors.append(
                            {
                                "event_id": main_channel["event_id"],
                                "error": str(e),
                            }
                        )

                conn.commit()

        except Exception as e:
            logger.exception("Error during keyword ordering enforcement")
            result.errors.append({"error": str(e)})

        if result.reordered_count > 0:
            logger.info(f"Keyword ordering: reordered {result.reordered_count} channel pair(s)")

        return result

    def _get_channels_needing_reorder(self, conn) -> list[dict]:
        """Find events where keyword channel has lower number than main.

        Returns list of dicts with 'main_channel' and 'keyword_channel'.
        """
        # Find pairs: main (no keyword) vs keyword, where keyword number < main number
        cursor = conn.execute(
            """
            SELECT
                m.id as main_id,
                m.channel_number as main_number,
                m.dispatcharr_channel_id as main_dispatcharr_id,
                m.channel_name as main_name,
                m.event_id,
                k.id as keyword_id,
                k.channel_number as keyword_number,
                k.dispatcharr_channel_id as keyword_dispatcharr_id,
                k.channel_name as keyword_name,
                k.exception_keyword
            FROM managed_channels m
            JOIN managed_channels k ON m.event_id = k.event_id
                                   AND m.event_epg_group_id = k.event_epg_group_id
            WHERE m.deleted_at IS NULL
              AND k.deleted_at IS NULL
              AND (m.exception_keyword IS NULL OR m.exception_keyword = '')
              AND k.exception_keyword IS NOT NULL
              AND k.exception_keyword != ''
              AND CAST(k.channel_number AS INTEGER) < CAST(m.channel_number AS INTEGER)
            """
        )

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "main_channel": {
                        "id": row["main_id"],
                        "channel_number": int(row["main_number"]),
                        "dispatcharr_channel_id": row["main_dispatcharr_id"],
                        "channel_name": row["main_name"],
                        "event_id": row["event_id"],
                    },
                    "keyword_channel": {
                        "id": row["keyword_id"],
                        "channel_number": int(row["keyword_number"]),
                        "dispatcharr_channel_id": row["keyword_dispatcharr_id"],
                        "channel_name": row["keyword_name"],
                        "exception_keyword": row["exception_keyword"],
                    },
                }
            )

        return results
