"""Channel creation path — matched-stream processing and duplicate handling.

`process_matched_streams` is the per-run driver: it walks the matched streams,
applies timing/keyword gates, dispatches duplicates to the effective mode
(consolidate/separate/ignore) via `_handle_existing_channel`, and creates new
channels via `_create_channel`.
"""

import logging
from datetime import datetime
from sqlite3 import Connection
from typing import Any

from teamarr.core import Event

from ._host import _LifecycleHost
from .timing import compute_stream_window, is_stream_in_window
from .types import (
    ChannelCreationResult,
    StreamProcessResult,
    generate_event_tvg_id,
)

logger = logging.getLogger(__name__)


class ChannelCreator(_LifecycleHost):
    """Creates channels from matched streams and handles duplicate modes.

    Mixin for ChannelLifecycleService — relies on the coordinator's managers,
    lock, timing manager, dynamic resolver and helper methods.
    """

    def process_matched_streams(
        self,
        matched_streams: list[dict],
        group_config: dict,
        template: dict | None = None,
    ) -> StreamProcessResult:
        """Process matched streams and create/update channels as needed.

        Handles all three duplicate modes:
        - consolidate: All streams for same event → one channel
        - separate: Each stream → its own channel
        - ignore: First stream wins, skip duplicates

        Args:
            matched_streams: List of dicts with 'stream', 'event' keys
            group_config: Event EPG group configuration
            template: Optional template for channel naming

        Returns:
            StreamProcessResult with created, existing, skipped, errors
        """
        from teamarr.database.channels import (
            find_existing_channel,
            log_channel_history,
        )

        result = StreamProcessResult()

        # Clear logo cache at start of batch to avoid stale references
        # Logos may have been deleted/changed in Dispatcharr since last run
        if self._logo_manager:
            self._logo_manager.clear_cache()

        try:
            with self._db_factory() as conn:
                # Initialize dynamic resolver for this batch
                self._dynamic_resolver.initialize(self._db_factory, conn)

                # Global consolidation mode (v59) replaces per-group duplicate_event_handling
                from teamarr.database.channel_numbers import get_global_consolidation_mode
                duplicate_mode = get_global_consolidation_mode(conn)

                # Profile IDs from global settings (per-league overrides below)
                from teamarr.database.settings import (
                    get_dispatcharr_settings,
                    get_feed_separation_settings,
                )

                dispatcharr_settings = get_dispatcharr_settings(conn)

                # EPG stream time-windowing buffers (183.5) — global pre-attach /
                # post-detach minutes applied to a matched EPG program slot.
                _buf_row = conn.execute(
                    "SELECT epg_stream_pre_buffer_minutes, epg_stream_post_buffer_minutes "
                    "FROM settings WHERE id = 1"
                ).fetchone()
                epg_pre_buffer = _buf_row["epg_stream_pre_buffer_minutes"] if _buf_row else 60
                epg_post_buffer = _buf_row["epg_stream_post_buffer_minutes"] if _buf_row else 60

                # Feed separation settings for channel naming
                feed_settings = get_feed_separation_settings(conn)
                feed_label_style = (
                    feed_settings.label_style if feed_settings.enabled else None
                )

                # Channel group defaults from global settings (per-league overrides in event loop)
                static_channel_group_id = dispatcharr_settings.default_channel_group_id
                channel_group_mode = dispatcharr_settings.default_channel_group_mode or "static"
                raw_profile_ids = dispatcharr_settings.default_channel_profile_ids

                # Load per-league subscription configs for override
                from teamarr.database.subscription import get_league_configs

                league_configs = {
                    lc.league_code: lc
                    for lc in get_league_configs(conn)
                }
                self._league_configs = league_configs

                # Stream profile: always global default
                stream_profile_id = dispatcharr_settings.default_stream_profile_id

                for matched in matched_streams:
                    try:
                        stream = matched.get("stream", {})
                        event = matched.get("event")

                        if not event:
                            result.errors.append(
                                {
                                    "stream": stream.get("name", "Unknown"),
                                    "error": "No event data",
                                }
                            )
                            continue

                        event_id = event.id
                        event_provider = getattr(event, "provider", "espn")
                        stream_name = stream.get("name", "")
                        stream_id = stream.get("id")

                        # UFC segment support: extract segment info if present
                        segment = matched.get("segment")  # e.g., "prelims", "main_card"
                        segment_display = matched.get("segment_display", "")
                        segment_start = matched.get("segment_start")  # Segment-specific start time
                        # For channel lookup/creation, use segment-aware event_id
                        # This treats each segment as a separate "sub-event"
                        effective_event_id = f"{event_id}-{segment}" if segment else event_id

                        # Feed team separation: extract resolved feed team
                        feed_team = matched.get("feed_team")
                        feed_team_id = feed_team.id if feed_team else None

                        # Stream type tag ('event' or 'team') for ordering rules
                        match_type = matched.get("match_type", "event")
                        # How the stream matched ('epg', 'fuzzy', …) for the
                        # epg_match ordering rule.
                        match_method = matched.get("match_method")

                        # Time-windowed membership (183.5): for EPG-matched linear
                        # streams, derive attach/detach from the program slot +/-
                        # buffers. None for name matches → full-life membership.
                        attach_at, detach_at = compute_stream_window(
                            matched.get("epg_program_start"),
                            matched.get("epg_program_end"),
                            epg_pre_buffer,
                            epg_post_buffer,
                        )
                        if attach_at is not None:
                            # Diagnostic for time-shared EPG streams: the window
                            # that gates whether this stream is live right now.
                            logger.debug(
                                "[EPG_WINDOW] stream='%s' event=%s window=[%s .. %s] "
                                "(pre=%dm post=%dm)",
                                stream_name[:32],
                                event_id,
                                attach_at,
                                detach_at,
                                epg_pre_buffer,
                                epg_post_buffer,
                            )

                        # Check if event should be excluded based on timing
                        logger.debug(
                            "[LIFECYCLE] Checking stream '%s' for event %s (status=%s)",
                            stream_name[:40],
                            event_id,
                            event.status.state if event.status else "N/A",
                        )
                        excluded_reason = self._timing_manager.categorize_event_timing(event)
                        if excluded_reason:
                            result.excluded.append(
                                {
                                    "stream": stream_name,
                                    "stream_id": stream_id,
                                    "event_id": event_id,
                                    "event_name": event.short_name or event.name,
                                    "reason": excluded_reason.value,
                                    "reason_display": {
                                        "event_past": "Event already ended",
                                        "event_final": "Event is final",
                                        "before_create_window": "Before create window",
                                    }.get(excluded_reason.value, excluded_reason.value),
                                }
                            )
                            continue

                        # Check exception keyword
                        matched_keyword, keyword_behavior = self._check_exception_keyword(
                            stream_name, conn
                        )

                        # V1 Parity: If behavior is 'ignore', skip stream entirely
                        # This must happen BEFORE any channel lookup/creation
                        if keyword_behavior == "ignore":
                            logger.debug(
                                f"Skipping stream '{stream_name}': "
                                f"keyword '{matched_keyword}' set to ignore"
                            )
                            result.skipped.append(
                                {
                                    "stream": stream_name,
                                    "stream_id": stream_id,
                                    "event_id": event_id,
                                    "reason": f"Exception keyword '{matched_keyword}' "
                                    "set to ignore",
                                }
                            )
                            continue

                        # Determine effective duplicate mode
                        effective_mode = keyword_behavior if keyword_behavior else duplicate_mode

                        # Resolve template for this specific event (may be sport/league-specific)
                        event_template = self._resolve_event_template(
                            conn, event, template
                        )

                        # Find existing channel by event identity (event-scoped)
                        # Searches across ALL groups — channels owned by events
                        existing = find_existing_channel(
                            conn=conn,
                            event_id=effective_event_id,
                            event_provider=event_provider,
                            exception_keyword=matched_keyword,
                            stream_id=stream_id,
                            mode=effective_mode,
                            feed_team_id=feed_team_id,
                        )

                        if existing:
                            # Handle based on effective mode
                            channel_result = self._handle_existing_channel(
                                conn=conn,
                                existing=existing,
                                stream=stream,
                                event=event,
                                effective_mode=effective_mode,
                                matched_keyword=matched_keyword,
                                group_config=group_config,
                                template=event_template,
                                segment=segment,
                                match_type=match_type,
                                match_method=match_method,
                                attach_at=attach_at,
                                detach_at=detach_at,
                            )
                            # None means Dispatcharr channel missing - fall through to create new
                            if channel_result is not None:
                                result.merge(channel_result)
                                continue

                        # Check if we should create based on timing
                        decision = self._timing_manager.should_create_channel(
                            event,
                            stream_exists=True,
                        )

                        if not decision.should_act:
                            logger.debug(
                                f"Skipping channel creation for '{stream_name}': {decision.reason}"
                            )
                            result.skipped.append(
                                {
                                    "stream": stream_name,
                                    "event_id": event_id,
                                    "reason": decision.reason,
                                }
                            )
                            continue

                        # Resolve dynamic channel group and profiles for this event
                        event_sport = getattr(event, "sport", None)
                        event_league = getattr(event, "league", None)

                        # Per-league subscription config overrides
                        effective_profile_ids = raw_profile_ids
                        effective_group_id = static_channel_group_id
                        effective_group_mode = channel_group_mode
                        if event_league and event_league in league_configs:
                            lc = league_configs[event_league]
                            if lc.channel_profile_ids is not None:
                                effective_profile_ids = lc.channel_profile_ids
                            if lc.channel_group_id is not None:
                                effective_group_id = lc.channel_group_id
                            if lc.channel_group_mode is not None:
                                effective_group_mode = lc.channel_group_mode

                        resolved_channel_group_id = (
                            self._dynamic_resolver.resolve_channel_group(
                                mode=effective_group_mode,
                                static_group_id=effective_group_id,
                                event_sport=event_sport,
                                event_league=event_league,
                            )
                        )

                        resolved_channel_profile_ids = self._resolve_profiles_for_event(
                            effective_profile_ids, event_sport, event_league
                        )

                        # Create new channel
                        channel_result = self._create_channel(
                            conn=conn,
                            event=event,
                            stream=stream,
                            group_config=group_config,
                            template=event_template,
                            matched_keyword=matched_keyword,
                            channel_group_id=resolved_channel_group_id,
                            channel_profile_ids=resolved_channel_profile_ids,
                            stream_profile_id=stream_profile_id,
                            segment=segment,
                            segment_display=segment_display,
                            segment_start=segment_start,
                            feed_team_id=feed_team_id,
                            feed_team=feed_team,
                            feed_label_style=feed_label_style,
                            match_type=match_type,
                            match_method=match_method,
                            attach_at=attach_at,
                            detach_at=detach_at,
                        )

                        if channel_result.success:
                            logger.info(
                                "[CHANNEL_CREATE] id=%s (#%s) stream='%s' event=%s status=%s",
                                channel_result.dispatcharr_channel_id,
                                channel_result.channel_number,
                                stream_name[:40],
                                event_id,
                                event.status.state if event.status else "N/A",
                            )
                            result.created.append(
                                {
                                    "stream": stream_name,
                                    "event_id": event_id,
                                    "channel_id": channel_result.channel_id,
                                    "dispatcharr_channel_id": channel_result.dispatcharr_channel_id,
                                    "channel_number": channel_result.channel_number,
                                    "tvg_id": channel_result.tvg_id,
                                }
                            )

                            # Log history — a successful create always yields a
                            # local managed-channel id (invariant of _create_channel).
                            assert channel_result.channel_id is not None
                            log_channel_history(
                                conn=conn,
                                managed_channel_id=channel_result.channel_id,
                                change_type="created",
                                change_source="epg_generation",
                                notes=f"Created from stream '{stream_name}'",
                            )
                        else:
                            logger.warning(
                                f"Failed to create channel for '{stream_name}': "
                                f"{channel_result.error}"
                            )
                            result.errors.append(
                                {
                                    "stream": stream_name,
                                    "event_id": event_id,
                                    "error": channel_result.error,
                                }
                            )

                    except Exception as stream_err:
                        event_id = matched.get("event")
                        if event_id is not None and hasattr(event_id, "id"):
                            event_id = event_id.id
                        stream_name = matched.get("stream", {}).get("name", "Unknown")
                        logger.error(
                            "[LIFECYCLE] Error processing stream '%s' for event %s: %s",
                            stream_name,
                            event_id,
                            stream_err,
                        )
                        result.errors.append(
                            {
                                "stream": stream_name,
                                "event": str(event_id),
                                "error": str(stream_err),
                            }
                        )
                        continue

                # Apply all pending profile changes in bulk
                self._apply_pending_profile_changes()

        except Exception as e:
            logger.exception("Error in matched streams setup")
            result.errors.append({"error": str(e)})
            # Still try to apply pending profile changes even on error
            try:
                self._apply_pending_profile_changes()
            except Exception as profile_err:
                logger.debug(
                    "[LIFECYCLE] Failed to apply pending profile changes after error: %s",
                    profile_err,
                )

        # Populate observability counters
        result.dispatcharr_failures += self._dispatcharr_failure_count
        result.stream_drift_fixes += self._stream_drift_fix_count

        # Summary log for generation run visibility
        if self._dispatcharr_failure_count or self._stream_drift_fix_count:
            logger.warning(
                "[LIFECYCLE] Generation: %d Dispatcharr API failure(s), %d stream drift fix(es)",
                self._dispatcharr_failure_count,
                self._stream_drift_fix_count,
            )

        return result

    def _handle_existing_channel(
        self,
        conn: Connection,
        existing: Any,
        stream: dict,
        event: Event,
        effective_mode: str,
        matched_keyword: str | None,
        group_config: dict,
        template: dict | None,
        segment: str | None = None,
        match_type: str = "event",
        match_method: str | None = None,
        attach_at: str | None = None,
        detach_at: str | None = None,
    ) -> StreamProcessResult | None:
        """Handle an existing channel based on duplicate mode.

        Returns:
            StreamProcessResult if channel was handled successfully
            None if Dispatcharr channel is missing and caller should create new
        """
        from teamarr.database.channels import (
            add_stream_to_channel,
            compute_stream_priority_from_rules,
            get_next_stream_priority,
            get_ordered_stream_ids,
            log_channel_history,
            mark_channel_deleted,
            remove_stream_from_channel,
            stream_exists_on_channel,
            update_stream_account_name,
            update_stream_window,
        )

        result = StreamProcessResult()
        stream_name = stream.get("name", "")
        stream_id = stream.get("id")
        # A matched Dispatcharr stream always carries an integer id.
        assert stream_id is not None
        disp_channel = None  # Dispatcharr's view of this channel (for phantom detection)

        # Verify channel exists in Dispatcharr.
        # Only a CONFIRMED 404 means the channel is really gone; a transient blip
        # (timeout, 5xx, auth/network error) must NOT trigger delete + recreate,
        # or we abandon the live channel and create a duplicate (which in gap/
        # strict modes lands far away in the range). On an inconclusive result we
        # leave the channel intact and re-verify next run (DB is source of truth).
        if self._channel_manager and existing.dispatcharr_channel_id:
            with self._dispatcharr_lock:
                disp_channel, confirmed_absent = (
                    self._channel_manager.get_channel_existence(
                        existing.dispatcharr_channel_id
                    )
                )
                if disp_channel is None and confirmed_absent:
                    # Channel confirmed missing from Dispatcharr - mark old record
                    # deleted and return None so the caller creates a new one.
                    logger.warning(
                        f"Channel {existing.dispatcharr_channel_id} missing from "
                        f"Dispatcharr, marking deleted and will create new: {existing.channel_name}"
                    )
                    mark_channel_deleted(
                        conn,
                        existing.id,
                        reason=f"Missing from Dispatcharr (ID {existing.dispatcharr_channel_id})",
                    )
                    log_channel_history(
                        conn=conn,
                        managed_channel_id=existing.id,
                        change_type="deleted",
                        change_source="lifecycle",
                        notes="Channel missing from Dispatcharr, marked for cleanup",
                    )
                    # Return None to signal caller to create new channel
                    return None
                if disp_channel is None:
                    # Inconclusive — could not verify. Keep the channel as-is and
                    # skip phantom-stream purge (disp_channel stays None).
                    logger.warning(
                        "Could not verify channel %s in Dispatcharr (transient error); "
                        "leaving intact, will re-verify next run: %s",
                        existing.dispatcharr_channel_id, existing.channel_name,
                    )

        if effective_mode == "ignore":
            # Skip - don't add stream, but still sync settings
            result.existing.append(
                {
                    "stream": stream_name,
                    "channel_id": existing.dispatcharr_channel_id,
                    "channel_number": existing.channel_number,
                    "action": "ignored",
                }
            )
            # Still sync channel settings even for ignored duplicates
            settings_result = self._sync_channel_settings(
                conn=conn,
                existing=existing,
                stream=stream,
                event=event,
                group_config=group_config,
                template=template,
                segment=segment,
            )
            result.merge(settings_result)
            return result

        if effective_mode == "consolidate":
            # Add stream to existing channel if not already present
            if not stream_exists_on_channel(conn, existing.id, stream_id):
                # Compute priority from ordering rules (or use sequential if no rules)
                m3u_account_name = stream.get("m3u_account_name") or group_config.get(
                    "m3u_account_name"
                )
                source_group_id = group_config.get("id")
                priority = compute_stream_priority_from_rules(
                    conn, stream_name, m3u_account_name, source_group_id
                )
                if priority is None:
                    priority = get_next_stream_priority(conn, existing.id)

                # Add to DB
                add_stream_to_channel(
                    conn=conn,
                    managed_channel_id=existing.id,
                    dispatcharr_stream_id=stream_id,
                    stream_name=stream_name,
                    priority=priority,
                    exception_keyword=matched_keyword,
                    m3u_account_id=stream.get("m3u_account_id"),
                    m3u_account_name=m3u_account_name,
                    source_group_id=source_group_id,
                    match_type=match_type,
                    match_method=match_method,
                    dispatcharr_channel_group=stream.get("dp_channel_group"),
                    attach_at=attach_at,
                    detach_at=detach_at,
                )

                # Sync with Dispatcharr - use ordered stream list to respect rules
                if self._channel_manager:
                    ordered_streams = get_ordered_stream_ids(conn, existing.id)

                    # Purge phantom streams: IDs in our DB that Dispatcharr
                    # no longer knows about (e.g. after M3U re-import).
                    # Sending them causes "Invalid pk" and blocks ALL updates.
                    if disp_channel:
                        valid_ids = set(disp_channel.streams) | {stream_id}
                        phantoms = [s for s in ordered_streams if s not in valid_ids]
                        if phantoms:
                            for pid in phantoms:
                                remove_stream_from_channel(
                                    conn, existing.id, pid,
                                    reason="phantom: not in Dispatcharr",
                                )
                            logger.warning(
                                "[STREAM_AUDIT] purged %d phantom stream(s) from ch='%s' "
                                "(db_id=%d): %s",
                                len(phantoms), existing.channel_name,
                                existing.id, phantoms,
                            )
                            ordered_streams = [s for s in ordered_streams if s not in phantoms]

                    logger.info(
                        "[STREAM_AUDIT] consolidate add: ch='%s' (db_id=%d, d_id=%s) "
                        "added stream_id=%d, db_ordered=%s",
                        existing.channel_name,
                        existing.id,
                        existing.dispatcharr_channel_id,
                        stream_id,
                        ordered_streams,
                    )
                    with self._dispatcharr_lock:
                        api_ok = self._safe_update_channel(
                            existing.dispatcharr_channel_id,
                            {"streams": ordered_streams},
                            "consolidate stream add",
                        )
                    if not api_ok:
                        # Roll back the DB insert so drift is retried next run
                        remove_stream_from_channel(conn, existing.id, stream_id)

                # Log history
                log_channel_history(
                    conn=conn,
                    managed_channel_id=existing.id,
                    change_type="stream_added",
                    change_source="epg_generation",
                    notes=f"Added stream '{stream_name}' (consolidate mode)",
                )

                result.streams_added.append(
                    {
                        "stream": stream_name,
                        "channel_id": existing.dispatcharr_channel_id,
                        "channel_name": existing.channel_name,
                    }
                )
            else:
                # Stream already attached: self-heal the stored M3U account name
                # (#297) — rows attached before per-stream account resolution carry
                # the group's single account name, mislabeling multi-login streams.
                # Guarded on a resolved name: don't null on a transient
                # list-accounts failure.
                resolved_account = stream.get("m3u_account_name")
                if resolved_account:
                    update_stream_account_name(
                        conn,
                        existing.id,
                        stream_id,
                        resolved_account,
                        stream.get("m3u_account_id"),
                    )
                if attach_at is not None and detach_at is not None:
                    # Recompute the EPG time-window from the fresh program slot +
                    # current buffers (183.5 / bead 095) so a buffer-setting change
                    # takes effect on the next run, not only at first attach.
                    # Guarded on a non-None window: don't clobber a full-life/
                    # name-matched stream (None,None) or wipe a window on a
                    # transient EPG miss. Reconciliation re-pushes if membership
                    # changed — no manual Dispatcharr update needed here.
                    update_stream_window(
                        conn, existing.id, stream_id, attach_at, detach_at
                    )

            result.existing.append(
                {
                    "stream": stream_name,
                    "channel_id": existing.dispatcharr_channel_id,
                    "channel_number": existing.channel_number,
                    "action": "consolidated",
                }
            )

        else:  # separate mode - channel found for this stream
            result.existing.append(
                {
                    "stream": stream_name,
                    "channel_id": existing.dispatcharr_channel_id,
                    "channel_number": existing.channel_number,
                    "action": "separate_exists",
                }
            )

        # Sync channel settings
        settings_result = self._sync_channel_settings(
            conn=conn,
            existing=existing,
            stream=stream,
            event=event,
            group_config=group_config,
            template=template,
            segment=segment,
        )
        result.merge(settings_result)

        return result

    def _resolve_profiles_for_event(
        self,
        profile_ids: list[int | str] | None,
        event_sport: str | None,
        event_league: str | None,
    ) -> list[int] | None:
        """Resolve configured channel profile IDs for channel creation.

        None (not configured) must be preserved — _create_channel maps it to
        the [0] all-profiles sentinel. Passing None through the dynamic
        resolver would collapse it to [] (NO profiles), silently creating
        channels without any profile (issue #267).
        """
        if profile_ids is None:
            return None
        return self._dynamic_resolver.resolve_channel_profiles(
            profile_ids=profile_ids,
            event_sport=event_sport,
            event_league=event_league,
        )

    def _create_channel(
        self,
        conn: Connection,
        event: Event,
        stream: dict,
        group_config: dict,
        template: dict | None,
        matched_keyword: str | None,
        channel_group_id: int | None,
        channel_profile_ids: list[int] | None,
        stream_profile_id: int | None = None,
        segment: str | None = None,
        segment_display: str = "",
        segment_start: datetime | None = None,
        feed_team_id: str | None = None,
        feed_team=None,
        feed_label_style: str | None = None,
        match_type: str = "event",
        match_method: str | None = None,
        attach_at: str | None = None,
        detach_at: str | None = None,
    ) -> ChannelCreationResult:
        """Create a new channel in DB and Dispatcharr.

        Args:
            segment: UFC card segment code (e.g., "prelims", "main_card")
            segment_display: Display name for segment (e.g., "Prelims")
            segment_start: Segment-specific start time (for UFC segments)
            feed_team_id: Provider team ID for feed separation (HOME/AWAY channels)
            feed_team: Team object for feed label generation
            feed_label_style: Label style ('team_name', 'short_name', 'home_away')
        """
        from teamarr.database.channels import (
            add_stream_to_channel,
            create_managed_channel,
        )

        event_id = event.id
        event_provider = getattr(event, "provider", "espn")
        stream_name = stream.get("name", "")
        stream_id = stream.get("id")
        # A matched Dispatcharr stream always carries an integer id.
        assert stream_id is not None
        group_id = group_config.get("id")

        # For segments, use segment-aware event_id for DB storage
        effective_event_id = f"{event_id}-{segment}" if segment else event_id

        # Generate tvg_id with segment, exception keyword, and feed-team suffixes.
        # feed_team_id is required to prevent tvg_id collisions across feed-separated
        # channels for the same event (HOME/AWAY/National all need distinct EPG channels).
        tvg_id = generate_event_tvg_id(
            event_id, event_provider, segment, matched_keyword, feed_team_id
        )

        # Generate channel name (segment resolved via {card_segment_display} template variable)
        channel_name = self._generate_channel_name(
            event, template, matched_keyword, segment,
            feed_team=feed_team, feed_label_style=feed_label_style,
        )

        # Get channel number using global mode (AUTO/MANUAL)
        event_league = getattr(event, "league", None)
        channel_number = self._get_next_channel_number(conn, event_league)
        if not channel_number:
            return ChannelCreationResult(
                success=False,
                error="Could not allocate channel number",
            )

        # Calculate delete time
        delete_time = self._timing_manager.calculate_delete_time(event)

        # Resolve logo URL from template (supports template variables including {exception_keyword})
        logo_url = self._resolve_logo_url(
            event, template, matched_keyword, segment, feed_team=feed_team,
        )

        # Dispatcharr profile semantics (as of commit 6b873be):
        #   [] = NO profiles (explicit)
        #   [0] = ALL profiles (sentinel)
        #   [1, 2, ...] = specific profile IDs
        #
        # Logic:
        #   None = not configured → default to [0] (all profiles, backwards compat)
        #   [] = explicitly no profiles → send [] (no profiles)
        #   [1, 2, ...] = specific profiles → send those
        #
        # Persisted to the local DB as-is so the profile drift sync compares
        # against the same value that was pushed to Dispatcharr.
        effective_profile_ids = (
            channel_profile_ids if channel_profile_ids is not None else [0]
        )

        # Create in Dispatcharr
        dispatcharr_channel_id = None
        dispatcharr_uuid = None
        dispatcharr_logo_id = None

        if self._channel_manager:
            with self._dispatcharr_lock:
                # Upload logo if specified
                if logo_url and self._logo_manager:
                    logo_result = self._logo_manager.upload(
                        name=f"{channel_name} Logo",
                        url=logo_url,
                    )
                    if logo_result.success and logo_result.logo:
                        dispatcharr_logo_id = logo_result.logo.get("id")

                logger.debug(
                    f"Channel '{channel_name}' profile assignment: "
                    f"configured={channel_profile_ids}, effective={effective_profile_ids}"
                )
                logger.debug(
                    "[LIFECYCLE] Creating channel '%s' with stream_profile_id=%s",
                    channel_name,
                    stream_profile_id,
                )
                # Window-gate the INITIAL stream membership (bead teamarrv2-uye).
                # An EPG-matched linear stream carries an attach_at/detach_at slot;
                # channel creation is event-anchored (create_threshold) and usually
                # fires hours before the attach window opens. Pushing the stream
                # live now would ignore the "Attach before" buffer — most visibly
                # when this is the channel's ONLY source. Create with no streams
                # when out-of-window; the per-run window sync attaches it once the
                # window opens. Full-life (name-matched) streams have attach_at=None
                # and are always included.
                initial_stream_ids = (
                    [stream_id] if is_stream_in_window(attach_at, detach_at) else []
                )
                if not initial_stream_ids:
                    logger.info(
                        "[EPG_WINDOW] ch='%s' event=%s: sole stream %s out of window "
                        "[%s .. %s] at create — deferring attach until window opens",
                        channel_name,
                        event_id,
                        stream_id,
                        attach_at,
                        detach_at,
                    )
                create_result = self._channel_manager.create_channel(
                    name=channel_name,
                    channel_number=channel_number,
                    stream_ids=initial_stream_ids,
                    tvg_id=tvg_id,
                    channel_group_id=channel_group_id,
                    logo_id=dispatcharr_logo_id,
                    channel_profile_ids=effective_profile_ids,
                    stream_profile_id=stream_profile_id,
                )

                if not create_result.success:
                    return ChannelCreationResult(
                        success=False,
                        error=create_result.error or "Failed to create channel in Dispatcharr",
                    )

                if create_result.channel:
                    dispatcharr_channel_id = create_result.channel.get("id")
                    dispatcharr_uuid = create_result.channel.get("uuid")

        # Create in DB - with rollback protection for Dispatcharr orphans
        try:
            managed_channel_id = create_managed_channel(
                conn=conn,
                event_epg_group_id=group_id,
                event_id=effective_event_id,  # Segment-aware event ID for UFC segments
                event_provider=event_provider,
                tvg_id=tvg_id,
                channel_name=channel_name,
                channel_number=channel_number,
                logo_url=logo_url,
                dispatcharr_channel_id=dispatcharr_channel_id,
                dispatcharr_uuid=dispatcharr_uuid,
                dispatcharr_logo_id=dispatcharr_logo_id,
                channel_group_id=channel_group_id,
                channel_profile_ids=effective_profile_ids,
                primary_stream_id=stream_id,
                exception_keyword=matched_keyword,
                feed_team_id=feed_team_id,
                home_team=event.home_team.name if event.home_team else None,
                away_team=event.away_team.name if event.away_team else None,
                # Use segment-specific start time for UFC segments, otherwise event start
                event_date=(segment_start or event.start_time).isoformat()
                if (segment_start or event.start_time)
                else None,
                event_name=event.name,
                league=event.league,
                sport=event.sport,
                # V1 Parity: Include venue and broadcast
                venue=event.venue.name if event.venue else None,
                broadcast=", ".join(event.broadcasts) if event.broadcasts else None,
                scheduled_delete_at=delete_time.isoformat() if delete_time else None,
                sync_status="in_sync" if dispatcharr_channel_id else "pending",
            )

            # Add stream to managed_channel_streams
            # Use default priority - final ordering happens after all matching complete
            add_stream_to_channel(
                conn=conn,
                managed_channel_id=managed_channel_id,
                dispatcharr_stream_id=stream_id,
                stream_name=stream_name,
                priority=0,
                exception_keyword=matched_keyword,
                m3u_account_id=stream.get("m3u_account_id"),
                # Per-stream account name first (#297): the group-config fallback
                # mislabels multi-login streams with one account for the whole group.
                m3u_account_name=stream.get("m3u_account_name")
                or group_config.get("m3u_account_name"),
                source_group_id=group_id,
                match_type=match_type,
                match_method=match_method,
                dispatcharr_channel_group=stream.get("dp_channel_group"),
                attach_at=attach_at,
                detach_at=detach_at,
            )

            # Commit immediately so next channel number query sees this channel
            conn.commit()

        except Exception as e:
            # DB insert failed - clean up the Dispatcharr channel to prevent orphans
            logger.error("[LIFECYCLE] DB insert failed for channel '%s': %s", channel_name, e)
            if dispatcharr_channel_id and self._channel_manager:
                try:
                    with self._dispatcharr_lock:
                        self._channel_manager.delete_channel(dispatcharr_channel_id)
                    logger.info(
                        f"Cleaned up Dispatcharr channel {dispatcharr_channel_id} after DB failure"
                    )
                except Exception as cleanup_err:
                    logger.warning(
                        "[LIFECYCLE] Failed to cleanup Dispatcharr channel: %s", cleanup_err
                    )

            return ChannelCreationResult(
                success=False,
                error=f"DB insert failed: {e}",
            )

        return ChannelCreationResult(
            success=True,
            channel_id=managed_channel_id,
            dispatcharr_channel_id=dispatcharr_channel_id,
            channel_number=channel_number,
            tvg_id=tvg_id,
        )

    def _get_next_channel_number(
        self,
        conn: Connection,
        event_league: str | None = None,
    ) -> int | None:
        """Get next available channel number.

        Uses global channel mode (AUTO/MANUAL) from settings.
        Passes external Dispatcharr channel numbers to avoid collisions (#146).

        Args:
            conn: Database connection
            event_league: League code for the event (used in MANUAL mode)

        Returns:
            Next available channel number as int, or None if range exhausted
        """
        from teamarr.database.channel_numbers import get_next_channel_number

        next_num = get_next_channel_number(
            conn, league=event_league,
            external_occupied=self._external_occupied,
        )
        if next_num is None:
            logger.warning(
                "[LIFECYCLE] Could not allocate channel (league=%s)", event_league,
            )
            return None
        return next_num
