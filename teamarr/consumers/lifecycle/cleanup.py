"""Channel/stream cleanup paths — deletions and stale-source sweeps.

Owns scheduled deletions (with delete-time recalculation), missing/rotated
stream cleanup, orphan Dispatcharr channels and disabled-group cleanup.
"""

import logging
from sqlite3 import Connection

from teamarr.utilities.sports import get_sport_duration
from teamarr.utilities.time_blocks import crosses_midnight
from teamarr.utilities.tz import to_user_tz

from ._host import _LifecycleHost
from .types import StreamProcessResult

logger = logging.getLogger(__name__)


class ChannelCleanup(_LifecycleHost):
    """Deletes expired/stale channels and detaches dead streams.

    Mixin for ChannelLifecycleService — relies on the coordinator's managers,
    lock and timing manager.
    """

    def _remove_stream_from_dispatcharr_channel(
        self,
        dispatcharr_channel_id: int,
        stream_id: int,
    ) -> bool:
        """Remove a stream from a Dispatcharr channel's stream list.

        Args:
            dispatcharr_channel_id: The Dispatcharr channel ID
            stream_id: The stream ID to remove

        Returns:
            True if the stream was removed, False otherwise
        """
        if not self._channel_manager:
            return False

        with self._dispatcharr_lock:
            current = self._channel_manager.get_channel(dispatcharr_channel_id)
            if not current:
                return False

            # streams is tuple[int, ...] of IDs
            current_ids = list(current.streams) if current.streams else []
            if stream_id not in current_ids:
                return False

            current_ids.remove(stream_id)
            return self._safe_update_channel(
                dispatcharr_channel_id,
                {"streams": current_ids},
                "stream removal",
            )

    def delete_managed_channel(
        self,
        conn: Connection,
        managed_channel_id: int,
        reason: str = "scheduled",
    ) -> bool:
        """Delete a managed channel from Dispatcharr and mark as deleted in DB.

        Note: Logos are cleaned up by Dispatcharr's bulk cleanup API if the
        cleanup_unused_logos setting is enabled, not per-channel.

        Args:
            conn: Database connection
            managed_channel_id: Managed channel ID
            reason: Deletion reason

        Returns:
            True if deleted successfully
        """
        from teamarr.database.channels import (
            get_managed_channel,
            log_channel_history,
            mark_channel_deleted,
        )

        channel = get_managed_channel(conn, managed_channel_id)
        if not channel:
            return False

        # Delete channel from Dispatcharr
        if self._channel_manager and channel.dispatcharr_channel_id:
            with self._dispatcharr_lock:
                result = self._channel_manager.delete_channel(channel.dispatcharr_channel_id)
                if not result.success:
                    logger.warning(
                        f"Failed to delete channel {channel.dispatcharr_channel_id} "
                        f"from Dispatcharr: {result.error}"
                    )

        # Mark as deleted in DB
        mark_channel_deleted(conn, managed_channel_id, reason)

        # Log history
        log_channel_history(
            conn=conn,
            managed_channel_id=managed_channel_id,
            change_type="deleted",
            change_source="lifecycle",
            notes=f"Deleted: {reason}",
        )

        conn.commit()
        logger.info("[LIFECYCLE] Deleted channel '%s' (%s)", channel.channel_name, reason)
        return True

    def process_scheduled_deletions(self) -> StreamProcessResult:
        """Process all channels past their scheduled delete time.

        First recalculates scheduled_delete_at for all active channels based on
        current settings (handles settings changes), then deletes any that are past due.

        Returns:
            StreamProcessResult with deleted channels
        """
        from teamarr.database.channels import (
            get_channels_pending_deletion,
        )

        result = StreamProcessResult()

        try:
            with self._db_factory() as conn:
                # Step 1: Recalculate scheduled_delete_at for all active channels
                # This handles settings changes (e.g., day_after -> 6_hours_after)
                self._recalculate_deletion_times(conn)

                # Step 2: Get channels that are now past their delete time
                channels = get_channels_pending_deletion(conn)

                for channel in channels:
                    success = self.delete_managed_channel(
                        conn,
                        channel.id,
                        reason="scheduled_delete",
                    )

                    if success:
                        result.deleted.append(
                            {
                                "channel_id": channel.id,
                                "channel_name": channel.channel_name,
                                "tvg_id": channel.tvg_id,
                            }
                        )
                    else:
                        result.errors.append(
                            {
                                "channel_id": channel.id,
                                "channel_name": channel.channel_name,
                                "error": "Failed to delete",
                            }
                        )

        except Exception as e:
            logger.exception("Error processing scheduled deletions")
            result.errors.append({"error": str(e)})

        if result.deleted:
            logger.info("[LIFECYCLE] Deleted %d expired channels", len(result.deleted))

        return result

    def _recalculate_deletion_times(self, conn) -> int:
        """Recalculate scheduled_delete_at for all active channels.

        This handles settings changes by recalculating deletion times based
        on current settings (same_day vs after_event with buffer minutes).

        Args:
            conn: Database connection

        Returns:
            Number of channels updated
        """
        from datetime import datetime, timedelta

        from dateutil import parser

        from teamarr.database.channels import get_all_managed_channels, update_managed_channel

        channels = get_all_managed_channels(conn, include_deleted=False)
        updated_count = 0

        # Get timing settings
        delete_timing = self._timing_manager.delete_timing
        post_buffer_minutes = self._timing_manager.post_buffer_minutes
        sport_durations = self._timing_manager.sport_durations
        default_duration = self._timing_manager.default_duration_hours

        for channel in channels:
            # Skip channels without event_date (can't calculate delete time)
            if not channel.event_date:
                continue

            try:
                # Parse event date
                event_start = parser.parse(str(channel.event_date))
                event_start = to_user_tz(event_start)

                # Calculate event end time using sport-specific duration
                sport = channel.sport or "other"
                duration_hours = get_sport_duration(sport, sport_durations, default_duration)
                event_end = event_start + timedelta(hours=duration_hours)

                # Calculate delete threshold based on timing setting
                if delete_timing == "after_event":
                    expected_delete_time = event_end + timedelta(minutes=post_buffer_minutes)
                else:
                    # same_day mode
                    if crosses_midnight(event_start, event_end):
                        # Midnight crossover: use event_end + buffer
                        expected_delete_time = event_end + timedelta(minutes=post_buffer_minutes)
                    else:
                        # Normal: end of day 23:59:59
                        expected_delete_time = datetime.combine(
                            event_end.date(),
                            datetime.max.time(),
                        ).replace(tzinfo=event_end.tzinfo)

                expected_delete_str = expected_delete_time.isoformat()
                stored_delete_str = (
                    str(channel.scheduled_delete_at) if channel.scheduled_delete_at else None
                )

                # Update if different
                if expected_delete_str != stored_delete_str:
                    update_managed_channel(
                        conn, channel.id, {"scheduled_delete_at": expected_delete_str}
                    )
                    updated_count += 1
                    logger.debug(
                        f"Updated scheduled_delete_at for '{channel.channel_name}': "
                        f"{stored_delete_str} -> {expected_delete_str}"
                    )

            except Exception as e:
                logger.debug(
                    "[LIFECYCLE] Error recalculating delete time for channel %d: %s", channel.id, e
                )
                continue

        if updated_count > 0:
            logger.info(
                "[LIFECYCLE] Recalculated scheduled_delete_at for %d channels", updated_count
            )

        return updated_count

    def cleanup_deleted_streams(
        self,
        group_id: int,
        current_streams: dict[int, dict],
        matched_streams: list[dict] | None = None,
    ) -> StreamProcessResult:
        """Clean up channels for streams that no longer exist, changed content, or rotated events.

        Runs regardless of delete_timing because missing/rotated streams should
        trigger immediate removal.

        When matched_streams is provided, performs event-aware validation:
        - Streams matched to a different event than the channel → removed (content rotated)
        - Streams with changed names but same event → name updated, kept
        - Streams with changed names and no event match data → removed (suspicious)

        When matched_streams is None, falls back to fingerprint-only behavior.

        Args:
            group_id: Event EPG group ID
            current_streams: Dict mapping stream_id -> stream_data with 'name' field
            matched_streams: Optional list of matched stream dicts with event data

        Returns:
            StreamProcessResult with deleted channels and errors
        """
        from teamarr.consumers.stream_match_cache import compute_fingerprint
        from teamarr.database.channels import (
            get_channel_streams,
            get_managed_channels_for_group,
            log_channel_history,
            remove_stream_from_channel,
            update_stream_name,
        )

        result = StreamProcessResult()
        current_ids_set = set(current_streams.keys())

        # Reverse index: stream_id → event_ids (from current match results).
        # Multi-valued (#316): a fanned stream (tennis court/round feed, EPG
        # time-share) legitimately matches MANY events per run — a single-value
        # map kept only the last one, so every other channel it fed looked
        # "rotated" and was deleted and recreated each generation.
        stream_event_map: dict[int, set[str]] = {}
        if matched_streams:
            for ms in matched_streams:
                stream_info = ms.get("stream", {})
                sid = stream_info.get("id") if isinstance(stream_info, dict) else None
                event = ms.get("event")
                segment = ms.get("card_segment")
                if sid and event:
                    eid = f"{event.id}-{segment}" if segment else str(event.id)
                    stream_event_map.setdefault(sid, set()).add(eid)

        try:
            with self._db_factory() as conn:
                # Get all active channels for the group (including cross-group streams)
                channels = get_managed_channels_for_group(conn, group_id)

                for channel in channels:
                    # Get streams associated with this channel
                    streams = get_channel_streams(conn, channel.id)

                    if not streams:
                        # Legacy fallback: check primary_stream_id
                        primary_id = getattr(channel, "primary_stream_id", None)
                        if primary_id and primary_id not in current_ids_set:
                            success = self.delete_managed_channel(
                                conn,
                                channel.id,
                                reason="primary stream removed",
                            )
                            if success:
                                result.deleted.append(
                                    {
                                        "channel_id": channel.dispatcharr_channel_id,
                                        "channel_number": channel.channel_number,
                                        "channel_name": channel.channel_name,
                                        "reason": "primary stream no longer exists",
                                    }
                                )
                        continue

                    # Determine channel's event identity for rotation detection
                    channel_event_id = getattr(channel, "event_id", None)
                    if channel_event_id:
                        channel_event_id = str(channel_event_id)

                    # Categorize streams: valid, missing, changed/rotated
                    valid_streams = []
                    missing_streams = []
                    changed_streams = []

                    for s in streams:
                        stream_id = getattr(s, "dispatcharr_stream_id", None)
                        stored_name = getattr(s, "stream_name", None)

                        if not stream_id:
                            continue

                        # Cross-group stream: not in this group's M3U pool
                        is_cross_group = (
                            s.source_group_id is not None and s.source_group_id != group_id
                        )

                        if is_cross_group:
                            # Cross-group stream: skip "missing from M3U" check
                            # But still check event rotation if we have match data
                            if stream_event_map and channel_event_id:
                                matched_events = stream_event_map.get(stream_id)
                                if matched_events and channel_event_id not in matched_events:
                                    changed_streams.append(
                                        {
                                            "stream": s,
                                            "old_name": stored_name,
                                            "new_name": f"rotated: {sorted(matched_events)[0]}",
                                            "reason": "event_rotated",
                                        }
                                    )
                                    continue
                            valid_streams.append(s)
                            continue

                        if stream_id not in current_ids_set:
                            # Stream no longer in M3U
                            missing_streams.append(s)
                            continue

                        # Stream exists in M3U — check for event rotation or name change
                        current_stream = current_streams.get(stream_id, {})
                        current_name = current_stream.get("name", "")

                        # Event-aware validation (when match data available).
                        # Rotation = the stream's current match set no longer
                        # CONTAINS this channel's event (fanned feeds match many).
                        if stream_event_map and channel_event_id:
                            matched_events = stream_event_map.get(stream_id)
                            if matched_events and channel_event_id not in matched_events:
                                # Stream now matches different event(s) → content rotated
                                changed_streams.append(
                                    {
                                        "stream": s,
                                        "old_name": stored_name,
                                        "new_name": current_name,
                                        "reason": "event_rotated",
                                    }
                                )
                                logger.debug(
                                    "[LIFECYCLE] Stream %d rotated: "
                                    "channel event=%s, now matched to=%s",
                                    stream_id,
                                    channel_event_id,
                                    sorted(matched_events),
                                )
                                continue

                        # Name change detection
                        if stored_name and current_name and stored_name != current_name:
                            # Name changed — check if it's still the same event
                            if stream_event_map:
                                matched_events = stream_event_map.get(stream_id)
                                if matched_events and (
                                    not channel_event_id
                                    or channel_event_id in matched_events
                                ):
                                    # Same event, just renamed — update stored name, keep
                                    update_stream_name(conn, channel.id, stream_id, current_name)
                                    valid_streams.append(s)
                                    continue

                            # Fingerprint-based fallback (no match data or unmatched stream)
                            stored_fp = compute_fingerprint(group_id, stream_id, stored_name)
                            current_fp = compute_fingerprint(group_id, stream_id, current_name)

                            if stored_fp != current_fp:
                                changed_streams.append(
                                    {
                                        "stream": s,
                                        "old_name": stored_name,
                                        "new_name": current_name,
                                        "reason": "content_changed",
                                    }
                                )
                                continue

                        valid_streams.append(s)

                    # Combine missing and changed streams for removal
                    streams_to_remove = missing_streams + [c["stream"] for c in changed_streams]

                    if not valid_streams and streams_to_remove:
                        # All streams gone or changed - delete channel
                        reasons = []
                        if missing_streams:
                            reasons.append(f"{len(missing_streams)} missing")
                        rotated = [
                            c for c in changed_streams if c.get("reason") == "event_rotated"
                        ]
                        content = [
                            c for c in changed_streams if c.get("reason") == "content_changed"
                        ]
                        if rotated:
                            reasons.append(f"{len(rotated)} rotated")
                        if content:
                            reasons.append(f"{len(content)} content-changed")
                        reason_str = ", ".join(reasons) or "all streams removed"

                        success = self.delete_managed_channel(
                            conn,
                            channel.id,
                            reason=reason_str,
                        )
                        if success:
                            result.deleted.append(
                                {
                                    "channel_id": channel.dispatcharr_channel_id,
                                    "channel_number": channel.channel_number,
                                    "channel_name": channel.channel_name,
                                    "reason": reason_str,
                                }
                            )
                        else:
                            result.errors.append(
                                {
                                    "channel_id": channel.dispatcharr_channel_id,
                                    "error": "Failed to delete channel",
                                }
                            )

                    elif streams_to_remove:
                        # Some streams gone/changed - remove them from channel
                        for s in missing_streams:
                            stream_id = getattr(s, "dispatcharr_stream_id", None)
                            if stream_id:
                                remove_stream_from_channel(conn, channel.id, stream_id)
                                if channel.dispatcharr_channel_id:
                                    self._remove_stream_from_dispatcharr_channel(
                                        channel.dispatcharr_channel_id,
                                        stream_id,
                                    )
                                log_channel_history(
                                    conn=conn,
                                    managed_channel_id=channel.id,
                                    change_type="stream_removed",
                                    change_source="lifecycle",
                                    notes=f"Stream {stream_id} no longer exists in M3U",
                                )

                        for changed in changed_streams:
                            s = changed["stream"]
                            stream_id = getattr(s, "dispatcharr_stream_id", None)
                            reason = changed.get("reason", "content_changed")
                            if stream_id:
                                remove_stream_from_channel(conn, channel.id, stream_id)
                                if channel.dispatcharr_channel_id:
                                    self._remove_stream_from_dispatcharr_channel(
                                        channel.dispatcharr_channel_id,
                                        stream_id,
                                    )
                                if reason == "event_rotated":
                                    notes = f"Stream {stream_id} rotated to different event"
                                else:
                                    notes = f"Stream {stream_id} content changed: '{changed['old_name']}' -> '{changed['new_name']}'"  # noqa: E501
                                log_channel_history(
                                    conn=conn,
                                    managed_channel_id=channel.id,
                                    change_type="stream_removed",
                                    change_source="lifecycle",
                                    notes=notes,
                                )
                                logger.debug(
                                    "Removed stream %d from channel '%s': %s",
                                    stream_id,
                                    channel.channel_name,
                                    reason,
                                )

                        result.streams_removed.append(
                            {
                                "channel_id": channel.dispatcharr_channel_id,
                                "channel_name": channel.channel_name,
                                "streams_removed": len(streams_to_remove),
                                "missing": len(missing_streams),
                                "content_changed": len(changed_streams),
                            }
                        )

        except Exception as e:
            logger.exception(f"Error cleaning up deleted streams for group {group_id}")
            result.errors.append({"error": str(e)})

        if result.deleted:
            logger.info(
                "[LIFECYCLE] Deleted %d channels with missing/changed/rotated streams",
                len(result.deleted),
            )

        return result

    def cleanup_orphan_dispatcharr_channels(self) -> dict:
        """Clean up orphan channels in Dispatcharr.

        V1 Parity: Runs every EPG generation to find and delete orphan channels.

        Orphan channels are Dispatcharr channels with teamarr-event-* tvg_id
        that aren't tracked (or are tracked as deleted) in our DB.

        These can occur when:
        - Dispatcharr delete API call failed but DB was marked deleted
        - Same event got a new channel, old one wasn't cleaned up
        - Manual intervention or bugs

        Returns:
            Dict with 'deleted' count and 'errors' list
        """
        from teamarr.database.channels import get_all_managed_channels

        result = {"deleted": 0, "errors": []}

        if not self._channel_manager:
            return result

        try:
            with self._db_factory() as conn:
                # Get all teamarr channels from Dispatcharr
                with self._dispatcharr_lock:
                    all_dispatcharr = self._channel_manager.get_channels()

                teamarr_channels = [
                    c for c in all_dispatcharr
                    if (c.tvg_id or "").startswith("teamarr-event-")
                ]

                if not teamarr_channels:
                    return result

                # Get active DB channels (by dispatcharr_channel_id and UUID)
                db_channels = get_all_managed_channels(conn, include_deleted=False)
                active_ids = {
                    c.dispatcharr_channel_id for c in db_channels if c.dispatcharr_channel_id
                }
                active_uuids = {c.dispatcharr_uuid for c in db_channels if c.dispatcharr_uuid}

                # Find orphans
                orphans = [
                    c
                    for c in teamarr_channels
                    if c.id not in active_ids and (not c.uuid or c.uuid not in active_uuids)
                ]

                if not orphans:
                    return result

                logger.info(
                    "[LIFECYCLE] Found %d orphan Dispatcharr channel(s) to clean up", len(orphans)
                )

                for orphan in orphans:
                    try:
                        with self._dispatcharr_lock:
                            delete_result = self._channel_manager.delete_channel(orphan.id)

                        is_success = delete_result.success
                        is_not_found = "not found" in str(delete_result.error or "").lower()
                        if is_success or is_not_found:
                            result["deleted"] += 1
                            logger.debug(
                                f"Deleted orphan channel #{orphan.channel_number} - {orphan.name}"
                            )
                        else:
                            result["errors"].append(
                                {
                                    "channel_id": orphan.id,
                                    "channel_name": orphan.name,
                                    "error": delete_result.error,
                                }
                            )
                    except Exception as e:
                        result["errors"].append(
                            {
                                "channel_id": orphan.id,
                                "channel_name": orphan.name,
                                "error": str(e),
                            }
                        )

        except Exception as e:
            logger.exception("Error cleaning up orphan Dispatcharr channels")
            result["errors"].append({"error": str(e)})

        if result["deleted"] > 0:
            logger.info("[LIFECYCLE] Cleaned up %d orphan Dispatcharr channels", result["deleted"])

        return result

    def cleanup_disabled_groups(self) -> dict:
        """Clean up streams/channels from disabled event groups.

        When a group is DISABLED, its contribution is cleaned up at the next EPG
        generation (so users can re-enable without losing everything). The cleanup
        is STREAM-LEVEL: detach only the disabled group's streams from each channel,
        then delete the channel only if it has no active streams left. This protects
        consolidated/multi-source channels — disabling one source must not delete a
        channel still fed by other enabled groups (teamarrv2-5xou).

        Returns:
            Dict with 'deleted', 'detached', and 'errors' lists/counts
        """
        from teamarr.database.channels import (
            get_channel_streams,
            get_managed_channels_for_group,
            remove_stream_from_channel,
        )
        from teamarr.database.groups import get_all_groups

        result: dict = {"deleted": [], "detached": 0, "errors": []}

        try:
            with self._db_factory() as conn:
                all_groups = get_all_groups(conn, include_disabled=True)
                disabled_groups = [g for g in all_groups if not g.enabled]
                if not disabled_groups:
                    return result

                logger.info(
                    f"Checking {len(disabled_groups)} disabled group(s) for channel cleanup..."
                )

                for group in disabled_groups:
                    group_id = group.id
                    group_name = group.name

                    # Channels touched by this group (created by it OR carrying its streams).
                    channels = get_managed_channels_for_group(conn, group_id, include_deleted=False)

                    for channel in channels:
                        try:
                            active = get_channel_streams(conn, channel.id)
                            from_group = [
                                s for s in active if s.source_group_id == group_id
                            ]

                            # Detach only this group's streams (Dispatcharr + DB).
                            for stream in from_group:
                                if channel.dispatcharr_channel_id:
                                    self._remove_stream_from_dispatcharr_channel(
                                        channel.dispatcharr_channel_id,
                                        stream.dispatcharr_stream_id,
                                    )
                                remove_stream_from_channel(
                                    conn,
                                    channel.id,
                                    stream.dispatcharr_stream_id,
                                    reason=f"Group '{group_name}' disabled",
                                )
                                result["detached"] += 1

                            # Delete the channel only if nothing else feeds it now.
                            remaining = [s for s in active if s.source_group_id != group_id]
                            if not remaining:
                                if self.delete_managed_channel(
                                    conn, channel.id, reason=f"Group '{group_name}' disabled"
                                ):
                                    result["deleted"].append(
                                        {
                                            "group": group_name,
                                            "channel_number": channel.channel_number,
                                            "channel_name": channel.channel_name,
                                        }
                                    )
                            else:
                                conn.commit()
                        except Exception as e:
                            result["errors"].append(
                                {
                                    "group": group_name,
                                    "channel_id": channel.dispatcharr_channel_id,
                                    "error": str(e),
                                }
                            )

        except Exception as e:
            logger.exception("Error cleaning up disabled groups")
            result["errors"].append({"error": str(e)})

        if result["deleted"] or result["detached"]:
            logger.info(
                "Disabled-group cleanup: detached %d stream(s), deleted %d channel(s)",
                result["detached"],
                len(result["deleted"]),
            )

        return result
