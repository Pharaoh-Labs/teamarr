"""Channel lifecycle service.

Full channel lifecycle management with Dispatcharr integration.
Handles channel creation, deletion, settings sync, and EPG association.

Package layout (iua3.7):
- service.py — ChannelLifecycleService coordinator: shared state, the
  closed-loop `_safe_update_channel` contract, profile-change batching,
  keyword/template lookups
- creator.py — ChannelCreator: matched-stream driver, duplicate modes,
  channel creation
- syncer.py  — ChannelSyncer: settings/profiles/logo/stream-profile sync,
  EPG association
- cleanup.py — ChannelCleanup: scheduled deletions, missing/rotated stream
  cleanup, orphan + disabled-group sweeps
- naming.py  — ChannelNaming: name/logo/template resolution shared by the
  creation and sync paths
"""

import json
import logging
import threading
from sqlite3 import Connection
from typing import Any

from teamarr.templates import ContextBuilder, TemplateResolver
from teamarr.utilities.art_url import read_art_base_url

from .cleanup import ChannelCleanup
from .creator import ChannelCreator
from .dynamic_resolver import DynamicResolver
from .naming import ChannelNaming
from .syncer import ChannelSyncer
from .timing import ChannelLifecycleManager
from .types import CreateTiming, DeleteTiming

logger = logging.getLogger(__name__)


class ChannelLifecycleService(
    ChannelCreator,
    ChannelNaming,
    ChannelSyncer,
    ChannelCleanup,
):
    """Full channel lifecycle management with Dispatcharr integration.

    Handles:
    - Channel creation from matched streams
    - Channel deletion based on timing
    - Settings sync (name, number, streams, logo, profiles)
    - EPG association after refresh
    - Duplicate handling (consolidate, separate, ignore)
    - Exception keyword handling

    Sync Reliability
    ================
    All Dispatcharr ``update_channel`` calls go through ``_safe_update_channel``
    which checks ``OperationResult.success`` before allowing local DB writes.
    On API failure the DB is left unchanged, so the next generation run
    re-detects the drift and retries naturally — no retry queue needed.

    Profile sync additionally compares against Dispatcharr's actual state
    (``current_channel.channel_profile_ids``) for self-healing: if the
    Dispatcharr side drifted from what the DB recorded, the correct
    profiles are pushed even when the DB appears in sync.

    Architecture — Parallel Paths
    =============================
    Three code paths resolve channel settings. They MUST stay in sync:

    1. **Creation** (`ChannelCreator._create_channel`):
       Entry: `process_matched_streams` → new channel → `_create_channel`
       Resolves: name, tvg_id, logo, channel_group, channel_profiles,
                 stream_profile, channel_number, delete_time
       Context available: event, template, matched_keyword, segment,
                          group_config (m3u_account), dispatcharr_settings,
                          per-league subscription configs

    2. **Sync** (`ChannelSyncer._sync_channel_settings`):
       Entry: `_handle_existing_channel` → existing channel → `_sync_channel_settings`
       Re-resolves: name, channel_number, channel_group, streams, tvg_id,
                    delete_time, channel_profiles, logo, stream_profile
       Context available: event, template, existing (DB record), segment,
                          group_config (m3u_account), dispatcharr_settings

    3. **EPG Generator** (`event_epg.py:generate_for_matched_streams`):
       Entry: `event_group_processor` XMLTV rendering → EPG channel names/logos
       Resolves: channel name, channel icon (logo URL)
       Context available: event, template (EventTemplateConfig), segment,
                          exception_keyword (annotated by event_group_processor)

    Shared resolution methods (ChannelNaming, naming.py):
    - `_generate_channel_name(event, template, keyword, segment)` — used by #1 and #2
    - `_resolve_logo_url(event, template, keyword, segment)` — used by #1 and #2
    - `_resolve_template(template_str, event, extra_vars, card_segment)` — core resolver
    - `_dynamic_resolver.resolve_channel_group/profiles(...)` — used by #1 and #2

    When adding new context (e.g., a new template variable), ensure it flows
    through ALL paths that resolve the affected field.

    Usage:
        from teamarr.dispatcharr import DispatcharrClient, ChannelManager, EPGManager, LogoManager
        from teamarr.database import get_db

        with DispatcharrClient(url, username, password) as client:
            service = ChannelLifecycleService(
                db_factory=get_db,
                channel_manager=ChannelManager(client),
                logo_manager=LogoManager(client),
                epg_manager=EPGManager(client),
                create_timing='same_day',
                delete_timing='day_after',
            )

            # Process matched streams
            result = service.process_matched_streams(matches, group_config)

            # Delete expired channels
            result = service.process_scheduled_deletions()
    """

    def __init__(
        self,
        db_factory: Any,
        sports_service: Any,
        channel_manager: Any = None,
        logo_manager: Any = None,
        epg_manager: Any = None,
        create_timing: CreateTiming = "same_day",
        delete_timing: DeleteTiming = "same_day",
        pre_buffer_minutes: int = 60,
        post_buffer_minutes: int = 60,
        default_duration_hours: float = 3.0,
        sport_durations: dict[str, float] | None = None,
        timezone: str = "America/New_York",
        include_final_events: bool = False,
    ):
        """Initialize the lifecycle service.

        Args:
            db_factory: Factory function that returns a database connection
            sports_service: SportsDataService for template variable resolution (required)
            channel_manager: ChannelManager instance for Dispatcharr operations
            logo_manager: LogoManager instance for logo operations
            epg_manager: EPGManager instance for EPG operations
            create_timing: When to create channels ('same_day' or 'before_event')
            delete_timing: When to delete channels ('same_day' or 'after_event')
            pre_buffer_minutes: Minutes before event start for before_event mode
            post_buffer_minutes: Minutes after event end for after_event/midnight crossover
            default_duration_hours: Default event duration
            sport_durations: Per-sport duration mapping (basketball, football, etc.)
            timezone: User timezone for timing calculations
            include_final_events: Whether to include completed/final events in EPG

        Raises:
            ValueError: If sports_service is not provided
        """
        if sports_service is None:
            raise ValueError("sports_service is required for template variable resolution")

        self._db_factory = db_factory
        self._sports_service = sports_service
        self._channel_manager = channel_manager
        self._logo_manager = logo_manager
        self._epg_manager = epg_manager
        self._timezone = timezone

        # Timing manager for create/delete decisions
        self._timing_manager = ChannelLifecycleManager(
            create_timing=create_timing,
            delete_timing=delete_timing,
            pre_buffer_minutes=pre_buffer_minutes,
            post_buffer_minutes=post_buffer_minutes,
            default_duration_hours=default_duration_hours,
            sport_durations=sport_durations,
            include_final_events=include_final_events,
        )

        # Thread lock for Dispatcharr operations
        self._dispatcharr_lock = threading.Lock()

        # Cache exception keywords
        self._exception_keywords: list | None = None

        # Pending profile changes for bulk application
        # Structure: {profile_id: {"add": set(channel_ids), "remove": set(channel_ids)}}
        self._pending_profile_changes: dict[int, dict[str, set[int]]] = {}

        # Template engine — art_base_url injected so channel-logo reconstruction
        # matches the EPG icon (epic z02s).

        self._context_builder = ContextBuilder(sports_service)
        self._resolver = TemplateResolver(read_art_base_url(db_factory))

        # External channel numbers from Dispatcharr (non-Teamarr channels)
        # Computed lazily via compute_external_occupied() and cached for the run
        self._external_occupied: set[int] | None = None

        # Dynamic group/profile resolver
        self._dynamic_resolver = DynamicResolver()

        # Per-run counters for observability (reset in clear_caches)
        self._dispatcharr_failure_count = 0
        self._stream_drift_fix_count = 0

    def _safe_update_channel(
        self,
        channel_id: int,
        data: dict,
        context: str,
    ) -> bool:
        """Update a Dispatcharr channel with result checking.

        Closed-loop contract: callers MUST check the return value before
        persisting corresponding state to the local DB.  When the API call
        fails the local DB is left unchanged so the drift is re-detected
        and retried on the next generation run — no retry queue needed.

        Args:
            channel_id: Dispatcharr channel ID to update.
            data: Fields to send to the PATCH endpoint.
            context: Human-readable label for log messages
                     (e.g. "bulk settings sync", "logo assignment").

        Returns:
            True if Dispatcharr confirmed the update, False otherwise.
        """
        if not self._channel_manager:
            return False

        try:
            # DIAG: Log every stream list mutation for debugging stream loss
            if "streams" in data:
                logger.info(
                    "[STREAM_AUDIT] update_channel(%d) ctx=%s streams=%s count=%d",
                    channel_id,
                    context,
                    data["streams"],
                    len(data["streams"]),
                )

            result = self._channel_manager.update_channel(channel_id, data)
            if result and result.success:
                return True

            error_msg = result.error if result else "no response"
            logger.warning(
                "[LIFECYCLE] Dispatcharr update failed (%s) for channel %d: %s",
                context,
                channel_id,
                error_msg,
            )
            self._dispatcharr_failure_count += 1
            return False
        except Exception as exc:
            logger.warning(
                "[LIFECYCLE] Dispatcharr update exception (%s) for channel %d: %s",
                context,
                channel_id,
                exc,
            )
            self._dispatcharr_failure_count += 1
            return False

    def compute_external_occupied(self) -> set[int]:
        """Compute channel numbers in Dispatcharr NOT managed by Teamarr.

        Delegates to the standalone compute_external_occupied() function.
        Result is cached on the service instance for the duration of the run.

        Returns:
            Set of channel numbers occupied by non-Teamarr channels.
        """
        if self._external_occupied is not None:
            return self._external_occupied

        from teamarr.consumers.lifecycle import (
            compute_external_occupied as _compute,
        )

        self._external_occupied = _compute(self._db_factory, self._channel_manager)
        return self._external_occupied

    @property
    def dispatcharr_enabled(self) -> bool:
        """Check if Dispatcharr integration is enabled."""
        return self._channel_manager is not None

    def clear_caches(self) -> None:
        """Clear all Dispatcharr caches.

        Should be called at the start of EPG generation to ensure fresh data.
        """
        if self._channel_manager:
            self._channel_manager.clear_cache()
        if self._logo_manager:
            self._logo_manager.clear_cache()
        self._exception_keywords = None
        self._pending_profile_changes = {}
        self._dispatcharr_failure_count = 0
        self._stream_drift_fix_count = 0

    def _collect_profile_change(
        self,
        profile_id: int,
        channel_id: int,
        action: str,
    ) -> None:
        """Collect a profile change for bulk application later.

        Args:
            profile_id: Profile ID to modify
            channel_id: Channel ID to add/remove
            action: "add" or "remove"
        """
        if profile_id not in self._pending_profile_changes:
            self._pending_profile_changes[profile_id] = {"add": set(), "remove": set()}
        self._pending_profile_changes[profile_id][action].add(channel_id)

    def _apply_pending_profile_changes(self) -> dict:
        """Apply all pending profile changes using bulk API.

        Returns:
            Dict with stats: {profiles_updated, channels_added, channels_removed, errors}
        """
        if not self._pending_profile_changes or not self._channel_manager:
            return {"profiles_updated": 0, "channels_added": 0, "channels_removed": 0}

        stats = {"profiles_updated": 0, "channels_added": 0, "channels_removed": 0, "errors": []}

        with self._dispatcharr_lock:
            for profile_id, changes in self._pending_profile_changes.items():
                add_ids = list(changes["add"])
                remove_ids = list(changes["remove"])

                if not add_ids and not remove_ids:
                    continue

                try:
                    result = self._channel_manager.bulk_update_profile_channels(
                        profile_id=profile_id,
                        add_channel_ids=add_ids if add_ids else None,
                        remove_channel_ids=remove_ids if remove_ids else None,
                    )
                    if result.success:
                        stats["profiles_updated"] += 1
                        stats["channels_added"] += len(add_ids)
                        stats["channels_removed"] += len(remove_ids)
                        logger.debug(
                            f"Bulk profile update for profile {profile_id}: "
                            f"+{len(add_ids)} -{len(remove_ids)} channels"
                        )
                    else:
                        stats["errors"].append(f"Profile {profile_id}: {result.error}")
                        logger.warning(
                            "[LIFECYCLE] Bulk profile update failed for profile %d: %s",
                            profile_id,
                            result.error,
                        )
                except Exception as e:
                    stats["errors"].append(f"Profile {profile_id}: {e}")
                    logger.warning(
                        "[LIFECYCLE] Bulk profile update error for profile %d: %s", profile_id, e
                    )

        # Clear pending changes after applying
        self._pending_profile_changes = {}

        if stats["profiles_updated"] > 0:
            logger.info(
                f"Bulk profile updates: {stats['profiles_updated']} profiles, "
                f"+{stats['channels_added']} -{stats['channels_removed']} channel assignments"
            )

        return stats

    def _get_exception_keywords(self, conn: Connection) -> list:
        """Get exception keywords with caching."""
        if self._exception_keywords is None:
            from teamarr.database.channels import get_exception_keywords

            self._exception_keywords = get_exception_keywords(conn)
        return self._exception_keywords

    def _check_exception_keyword(
        self,
        stream_name: str,
        conn: Connection,
    ) -> tuple[str | None, str | None]:
        """Check if stream name matches any exception keyword.

        Returns:
            Tuple of (matched_keyword, behavior) or (None, None)
        """
        from teamarr.database.channels import check_exception_keyword

        keywords = self._get_exception_keywords(conn)
        return check_exception_keyword(stream_name, keywords)

    def _resolve_event_template(
        self,
        conn: Connection,
        event,
        fallback_template,
    ):
        """Resolve the best template for a specific event.

        Uses sport/league-specific templates from global subscription_templates,
        otherwise falls back to the provided fallback_template.

        Args:
            conn: Database connection
            event: Event object with sport and league attributes
            fallback_template: Template to use if no specific template found

        Returns:
            Template config (dict or EventTemplateConfig) or None
        """
        from teamarr.database.subscription import (
            get_subscription_template_for_event,
        )
        from teamarr.database.templates import get_template, template_to_event_config

        event_sport = getattr(event, "sport", None) or ""
        event_league = getattr(event, "league", None) or ""

        # Resolve template from global subscription
        template_id = get_subscription_template_for_event(
            conn, event_sport, event_league
        )

        if template_id:
            template = get_template(conn, template_id)
            if template:
                config = template_to_event_config(template)
                if not config.channel_name_format:
                    logger.warning(
                        "[LIFECYCLE] Template %d (%s) resolved for event %s "
                        "(sport=%r, league=%r) but has no channel_name_format "
                        "(event_channel_name=%r)",
                        template_id,
                        template.name,
                        event.id,
                        event_sport,
                        event_league,
                        template.event_channel_name,
                    )
                return config
            logger.warning(
                "[LIFECYCLE] Template %s not found for event %s",
                template_id,
                event.id,
            )
        else:
            logger.warning(
                "[LIFECYCLE] No template matched for event %s "
                "(sport=%r, league=%r), fallback=%s",
                event.id,
                event_sport,
                event_league,
                type(fallback_template).__name__ if fallback_template else None,
            )

        # Fall back to the provided template
        return fallback_template

    def _parse_profile_ids(self, raw: Any) -> list[int]:
        """Parse channel profile IDs from various formats."""
        if not raw:
            return []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return []
        if isinstance(raw, list):
            return [int(x) for x in raw if x]
        return []
