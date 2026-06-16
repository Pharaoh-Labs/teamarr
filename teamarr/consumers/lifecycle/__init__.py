"""Channel lifecycle management for event-based EPG.

Handles creation and deletion timing for event channels.
Channels are created before events and deleted after.

EPG Association Flow:
1. Generate consistent tvg_id: teamarr-event-{event_id}
2. Create channel in Dispatcharr with this tvg_id
3. Generate XMLTV with matching channel id
4. After EPG refresh, look up EPGData by tvg_id
5. Call set_channel_epg(channel_id, epg_data_id) to associate
"""

import logging
from dataclasses import asdict
from sqlite3 import Connection
from typing import Any

from .service import ChannelLifecycleService
from .timing import ChannelLifecycleManager
from .types import (
    ChannelCreationResult,
    CreateTiming,
    DeleteTiming,
    DuplicateMode,
    LifecycleDecision,
    StreamProcessResult,
    generate_event_tvg_id,
    slugify_keyword,
)

logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_lifecycle_settings(conn: Connection) -> dict:
    """Get global channel lifecycle settings from the settings table.

    Returns:
        Dict with create_timing, delete_timing, duplicate_handling settings
    """
    cursor = conn.execute(
        """SELECT channel_create_timing, channel_delete_timing,
                  channel_pre_buffer_minutes, channel_post_buffer_minutes,
                  default_duplicate_event_handling
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if row:
        return {
            "create_timing": row["channel_create_timing"] or "same_day",
            "delete_timing": row["channel_delete_timing"] or "same_day",
            "pre_buffer_minutes": (
                row["channel_pre_buffer_minutes"]
                if row["channel_pre_buffer_minutes"] is not None
                else 60
            ),
            "post_buffer_minutes": (
                row["channel_post_buffer_minutes"]
                if row["channel_post_buffer_minutes"] is not None
                else 60
            ),
            "duplicate_handling": row["default_duplicate_event_handling"] or "consolidate",
        }

    return {
        "create_timing": "same_day",
        "delete_timing": "same_day",
        "pre_buffer_minutes": 60,
        "post_buffer_minutes": 60,
        "duplicate_handling": "consolidate",
    }


def compute_external_occupied(
    db_factory: Any,
    channel_manager: Any = None,
) -> set[int]:
    """Compute channel numbers in Dispatcharr NOT managed by Teamarr.

    Compares the Dispatcharr channel cache against Teamarr's managed_channels
    table to identify external channels whose numbers must be avoided.

    Called once at the start of a generation run. Zero extra API calls —
    uses the already-warm Dispatcharr channel cache.

    Args:
        db_factory: Factory function returning database connection
        channel_manager: ChannelManager with populated cache

    Returns:
        Set of channel numbers occupied by non-Teamarr channels.
    """
    # Get all channel numbers from Dispatcharr
    dispatcharr_numbers: set[int] = set()
    if channel_manager:
        for ch in channel_manager.get_channels():
            if ch.channel_number:
                try:
                    dispatcharr_numbers.add(int(float(ch.channel_number)))
                except (ValueError, TypeError):
                    pass

    # Get all channel numbers Teamarr manages
    teamarr_numbers: set[int] = set()
    with db_factory() as conn:
        rows = conn.execute(
            """SELECT channel_number FROM managed_channels
               WHERE deleted_at IS NULL AND channel_number IS NOT NULL"""
        ).fetchall()
        for row in rows:
            try:
                teamarr_numbers.add(int(float(row["channel_number"])))
            except (ValueError, TypeError):
                pass

    external = dispatcharr_numbers - teamarr_numbers

    if external:
        max_ext = max(external)
        logger.info(
            "[CHANNEL_NUM] External channels detected: %d numbers occupied (highest: #%d)",
            len(external),
            max_ext,
        )
    else:
        logger.debug("[CHANNEL_NUM] No external channels detected in Dispatcharr")

    return external


def create_lifecycle_service(
    db_factory: Any,
    sports_service: Any,
    dispatcharr_client: Any = None,
) -> ChannelLifecycleService:
    """Create a ChannelLifecycleService with optional Dispatcharr integration.

    Args:
        db_factory: Factory function returning database connection
        sports_service: SportsDataService for template resolution (required)
        dispatcharr_client: Optional DispatcharrClient instance

    Returns:
        Configured ChannelLifecycleService

    Raises:
        ValueError: If sports_service is not provided
    """
    from teamarr.database.channels import get_dispatcharr_settings
    from teamarr.database.settings import get_all_settings

    with db_factory() as conn:
        settings = get_dispatcharr_settings(conn)
        lifecycle = get_lifecycle_settings(conn)
        all_settings = get_all_settings(conn)

    # Build sport durations dict from settings - dynamically from DurationSettings
    sport_durations = asdict(all_settings.durations)

    channel_manager = None
    logo_manager = None
    epg_manager = None

    if dispatcharr_client and settings.get("enabled"):
        from teamarr.dispatcharr import ChannelManager, EPGManager, LogoManager
        from teamarr.dispatcharr.factory import DispatcharrConnection

        # Extract raw client if we received a DispatcharrConnection
        raw_client = (
            dispatcharr_client.client
            if isinstance(dispatcharr_client, DispatcharrConnection)
            else dispatcharr_client
        )

        channel_manager = ChannelManager(raw_client)
        logo_manager = LogoManager(raw_client)
        epg_manager = EPGManager(raw_client)

    return ChannelLifecycleService(
        db_factory=db_factory,
        sports_service=sports_service,
        channel_manager=channel_manager,
        logo_manager=logo_manager,
        epg_manager=epg_manager,
        create_timing=lifecycle["create_timing"],
        delete_timing=lifecycle["delete_timing"],
        pre_buffer_minutes=lifecycle["pre_buffer_minutes"],
        post_buffer_minutes=lifecycle["post_buffer_minutes"],
        default_duration_hours=all_settings.durations.default,
        sport_durations=sport_durations,
        # Final/complete events are always included (no longer a user setting —
        # the toggle was removed in the v2.7.0 EPG overhaul).
        include_final_events=True,
    )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Types
    "CreateTiming",
    "DeleteTiming",
    "DuplicateMode",
    "LifecycleDecision",
    "ChannelCreationResult",
    "StreamProcessResult",
    # Classes
    "ChannelLifecycleManager",
    "ChannelLifecycleService",
    # Functions
    "generate_event_tvg_id",
    "slugify_keyword",
    "get_lifecycle_settings",
    "create_lifecycle_service",
]
