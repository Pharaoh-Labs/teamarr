"""Channel settings sync path — keeps existing channels aligned with config.

Re-resolves every channel property (name, number, group, streams, tvg_id,
delete time, profiles, logo, stream profile) against current templates and
settings, pushing drift fixes to Dispatcharr closed-loop (DB only persists
what Dispatcharr confirmed). Also owns post-refresh EPG association.
"""

import json
import logging
from sqlite3 import Connection
from typing import Any

from teamarr.core import Event

from ._host import _LifecycleHost
from .types import StreamProcessResult, generate_event_tvg_id

logger = logging.getLogger(__name__)


class ChannelSyncer(_LifecycleHost):
    """Syncs existing channels' settings and EPG links to Dispatcharr.

    Mixin for ChannelLifecycleService — relies on the coordinator's managers,
    lock, timing manager, dynamic resolver and helper methods.
    """

    def _sync_channel_settings(
        self,
        conn: Connection,
        existing: Any,
        stream: dict,
        event: Event,
        group_config: dict,
        template: dict | None,
        segment: str | None = None,
    ) -> StreamProcessResult:
        """Sync channel settings from group/template to Dispatcharr.

        V1 Parity: Syncs all 9 channel properties:
        | Source              | Dispatcharr Field    | Handling                    |
        |---------------------|---------------------|-----------------------------|
        | template            | name                | Template variable resolution|
        | managed_channels    | channel_number      | DB is source of truth       |
        | league_config/group | channel_group_id    | Per-league → group → global |
        | current_stream      | streams             | M3U ID lookup               |
        | league_config/group | channel_profile_ids | Per-league → group → global |
        | template            | logo_id             | Upload/update if different  |
        | event_id            | tvg_id              | Ensures EPG matching        |
        | settings (global)   | stream_profile_id   | Always global default       |
        """
        from teamarr.database.channels import (
            log_channel_history,
            update_managed_channel,
        )

        result = StreamProcessResult()

        if not self._channel_manager:
            return result

        try:
            with self._dispatcharr_lock:
                current_channel = self._channel_manager.get_channel(existing.dispatcharr_channel_id)
                if not current_channel:
                    return result

            update_data = {}
            db_updates = {}
            changes_made = []

            # 1. Check channel name (template resolution) - V1 parity
            matched_keyword = getattr(existing, "exception_keyword", None)

            # Resolve feed team for name generation (from stored feed_team_id)
            sync_feed_team = None
            sync_feed_label_style = None
            stored_feed_team_id = getattr(existing, "feed_team_id", None)
            if stored_feed_team_id and event:
                from teamarr.database.settings import get_feed_separation_settings

                with self._db_factory() as settings_conn:
                    fs = get_feed_separation_settings(settings_conn)
                    if fs.enabled:
                        sync_feed_label_style = fs.label_style
                        if (event.home_team
                                and event.home_team.id == stored_feed_team_id):
                            sync_feed_team = event.home_team
                        elif (event.away_team
                                and event.away_team.id == stored_feed_team_id):
                            sync_feed_team = event.away_team

            expected_name = self._generate_channel_name(
                event, template, matched_keyword, segment,
                feed_team=sync_feed_team,
                feed_label_style=sync_feed_label_style,
            )
            if expected_name != current_channel.name:
                update_data["name"] = expected_name
                db_updates["channel_name"] = expected_name
                changes_made.append(f"name: {current_channel.name} → {expected_name}")

            # 2. Check channel number - Teamarr DB is source of truth
            # Handle channel numbers that may be floats as strings (e.g., "8121.0")
            expected_number = (
                int(float(existing.channel_number)) if existing.channel_number else None
            )
            current_number = (
                int(float(current_channel.channel_number))
                if current_channel.channel_number
                else None
            )
            if expected_number and expected_number != current_number:
                update_data["channel_number"] = expected_number
                changes_made.append(f"number: {current_number} → {expected_number}")

            # 3. Check channel_group_id (supports dynamic sport/league resolution)
            # Use global defaults from settings, then per-league overrides
            from teamarr.database.settings import get_dispatcharr_settings as _get_ds

            _ds = _get_ds(conn)
            channel_group_mode = _ds.default_channel_group_mode or "static"
            static_group_id = _ds.default_channel_group_id
            event_sport = getattr(event, "sport", None)
            event_league = getattr(event, "league", None)

            # Per-league subscription config overrides
            effective_group_mode = channel_group_mode
            effective_group_id = static_group_id
            if event_league and hasattr(self, "_league_configs"):
                lc = self._league_configs.get(event_league)
                if lc:
                    if lc.channel_group_id is not None:
                        effective_group_id = lc.channel_group_id
                    if lc.channel_group_mode is not None:
                        effective_group_mode = lc.channel_group_mode

            # Resolve dynamic group ID (creates group in Dispatcharr if needed)
            new_group_id = self._dynamic_resolver.resolve_channel_group(
                mode=effective_group_mode,
                static_group_id=effective_group_id,
                event_sport=event_sport,
                event_league=event_league,
            )

            old_group_id = current_channel.channel_group_id
            if new_group_id != old_group_id:
                update_data["channel_group_id"] = new_group_id
                changes_made.append(f"channel_group_id: {old_group_id} → {new_group_id}")

            # 4. Check streams (M3U ID sync) - V1 parity
            stream_id = stream.get("id") if stream else None
            if stream_id:
                # streams is already tuple[int, ...] of stream IDs
                ch_streams = current_channel.streams
                current_stream_ids = list(ch_streams) if ch_streams else []
                if stream_id not in current_stream_ids:
                    # Stream drift — Dispatcharr is missing a stream the DB expects.
                    # The fix is Dispatcharr-side (push the stream back via update_data);
                    # DB stream membership lives in managed_channel_streams (written by
                    # add_stream_to_channel during matching), NOT a column on
                    # managed_channels. A V1-parity leftover used to write
                    # db_updates["dispatcharr_stream_id"] here, but that column only
                    # exists on managed_channel_streams — it raised "no such column" on
                    # every drift fix and aborted the sync (bead 91l).
                    new_streams = current_stream_ids + [stream_id]
                    update_data["streams"] = new_streams
                    changes_made.append(f"streams: added {stream_id}")
                    self._stream_drift_fix_count += 1
                    logger.info(
                        "[STREAM_AUDIT] sync_settings drift fix: ch='%s' (d_id=%s) "
                        "stream_id=%d not in cached_streams=%s → setting to %s",
                        existing.channel_name,
                        existing.dispatcharr_channel_id,
                        stream_id,
                        current_stream_ids,
                        new_streams,
                    )

            # Note: Stream ordering is applied as a final step after all matching
            # See generation.py Step 3b - this ensures all streams from all groups
            # are considered together when computing final order

            # 5. Check tvg_id (regenerate with keyword + feed_team_id to migrate
            # old-format tvg_ids; feed_team_id keeps feed-separated channels distinct)
            event_id = event.id
            event_provider = getattr(event, "provider", "espn")
            stored_feed_team_id_for_tvg = getattr(existing, "feed_team_id", None)
            expected_tvg_id = generate_event_tvg_id(
                event_id, event_provider, segment, matched_keyword,
                stored_feed_team_id_for_tvg,
            )
            if expected_tvg_id != existing.tvg_id:
                db_updates["tvg_id"] = expected_tvg_id
            if expected_tvg_id != current_channel.tvg_id:
                update_data["tvg_id"] = expected_tvg_id
                changes_made.append(f"tvg_id: {current_channel.tvg_id} → {expected_tvg_id}")

            # 6b. Recalculate scheduled_delete_at based on current settings
            expected_delete_time = self._timing_manager.calculate_delete_time(event)
            if expected_delete_time:
                expected_delete_str = expected_delete_time.isoformat()
                stored_delete_str = getattr(existing, "scheduled_delete_at", None)
                # Compare as strings (both should be ISO format)
                if stored_delete_str:
                    stored_delete_str = str(stored_delete_str)
                if expected_delete_str != stored_delete_str:
                    db_updates["scheduled_delete_at"] = expected_delete_str
                    changes_made.append("scheduled_delete_at updated")

            # Apply Dispatcharr updates (closed-loop: only persist DB on success)
            if update_data:
                with self._dispatcharr_lock:
                    api_ok = self._safe_update_channel(
                        existing.dispatcharr_channel_id,
                        update_data,
                        "bulk settings sync",
                    )
                if not api_ok:
                    # Don't persist DB changes — drift will be re-detected next run
                    db_updates = {}

            # Apply DB updates
            if db_updates:
                update_managed_channel(conn, existing.id, db_updates)

            # 7. Sync channel_profile_ids (compares against Dispatcharr actual state)
            self._sync_channel_profiles(
                conn, existing, event_sport, event_league, changes_made,
                current_channel=current_channel,
            )

            # 8. Sync logo
            self._sync_channel_logo(
                conn, existing, event, template, matched_keyword, segment, changes_made,
                feed_team=sync_feed_team,
            )

            # 9. Sync stream_profile_id
            self._sync_stream_profile(
                conn, existing, current_channel, changes_made
            )

            # Log changes if any
            if changes_made:
                result.settings_updated.append(
                    {
                        "channel_id": existing.dispatcharr_channel_id,
                        "channel_name": existing.channel_name,
                        "changes": changes_made,
                    }
                )

                # Log to history
                log_channel_history(
                    conn=conn,
                    managed_channel_id=existing.id,
                    change_type="synced",
                    change_source="epg_generation",
                    notes=f"Settings synced: {', '.join(changes_made)}",
                )

        except Exception as e:
            logger.warning(
                "[LIFECYCLE] Error syncing settings for channel %s: %s",
                existing.channel_name,
                e,
                exc_info=True,
            )

        return result

    def _sync_channel_profiles(
        self,
        conn: Connection,
        existing: Any,
        event_sport: str | None,
        event_league: str | None,
        changes_made: list[str],
        current_channel: Any = None,
    ) -> None:
        """Sync channel_profile_ids (supports dynamic {sport}/{league} resolution).

        Self-healing: compares against Dispatcharr's actual profile state
        (via current_channel) rather than only the local DB.  If Dispatcharr
        drifted from what the DB says, the correct profiles are pushed.

        Dispatcharr profile semantics:
          [] = NO profiles, [0] = ALL profiles (sentinel), [1,2,...] = specific IDs
        """
        from teamarr.database.channels import update_managed_channel
        from teamarr.database.settings import get_dispatcharr_settings

        dispatcharr_settings = get_dispatcharr_settings(conn)
        raw_group_profiles = dispatcharr_settings.default_channel_profile_ids

        # Per-league subscription config override for profiles
        if event_league and hasattr(self, "_league_configs"):
            lc = self._league_configs.get(event_league)
            if lc and lc.channel_profile_ids is not None:
                raw_group_profiles = lc.channel_profile_ids

        stored_profile_ids = self._parse_profile_ids(
            getattr(existing, "channel_profile_ids", None)
        )

        # Resolve dynamic profile IDs (expands "{sport}" and "{league}" wildcards)
        if raw_group_profiles is not None:
            resolved_profile_ids = self._dynamic_resolver.resolve_channel_profiles(
                profile_ids=raw_group_profiles,
                event_sport=event_sport,
                event_league=event_league,
            )
            effective_profile_ids = resolved_profile_ids if resolved_profile_ids else []
        else:
            effective_profile_ids = [0]

        # Self-healing: also compare against Dispatcharr's actual state.
        # If the Dispatcharr API returned channel_profile_ids, use that as truth
        # instead of relying only on our DB (which may be stale/desynced).
        dispatcharr_profile_ids = None
        if current_channel and current_channel.channel_profile_ids is not None:
            dispatcharr_profile_ids = list(current_channel.channel_profile_ids)

        logger.debug(
            f"Channel '{existing.channel_name}' profile sync: "
            f"raw={raw_group_profiles}, resolved={effective_profile_ids}, "
            f"stored={stored_profile_ids}, dispatcharr={dispatcharr_profile_ids}"
        )

        # Detect drift: check both DB and Dispatcharr state
        db_in_sync = effective_profile_ids == stored_profile_ids
        dispatcharr_in_sync = (
            dispatcharr_profile_ids is None  # API didn't include field — can't check
            or sorted(effective_profile_ids) == sorted(dispatcharr_profile_ids)
        )

        if db_in_sync and dispatcharr_in_sync:
            return

        if not dispatcharr_in_sync and db_in_sync:
            logger.warning(
                "[LIFECYCLE] Profile drift detected for '%s': "
                "DB=%s but Dispatcharr=%s, pushing correct profiles %s",
                existing.channel_name,
                stored_profile_ids,
                dispatcharr_profile_ids,
                effective_profile_ids,
            )
            self._stream_drift_fix_count += 1

        logger.info(
            f"Channel '{existing.channel_name}' profiles changed: "
            f"{stored_profile_ids} → {effective_profile_ids}"
        )
        is_sentinel = effective_profile_ids in ([0], [])

        if is_sentinel:
            with self._dispatcharr_lock:
                api_ok = self._safe_update_channel(
                    existing.dispatcharr_channel_id,
                    {"channel_profile_ids": effective_profile_ids},
                    "profile sentinel update",
                )
            if not api_ok:
                return  # Don't persist DB — drift retried next run
            if effective_profile_ids == [0]:
                changes_made.append("profiles: all profiles")
            else:
                changes_made.append("profiles: no profiles")
        else:
            profiles_to_add = set(effective_profile_ids) - set(stored_profile_ids)
            profiles_to_remove = set(stored_profile_ids) - set(effective_profile_ids)

            channel_id = existing.dispatcharr_channel_id
            for profile_id in profiles_to_remove:
                self._collect_profile_change(profile_id, channel_id, "remove")
                changes_made.append(f"queued remove from profile {profile_id}")

            for profile_id in profiles_to_add:
                self._collect_profile_change(profile_id, channel_id, "add")
                changes_made.append(f"queued add to profile {profile_id}")

        update_managed_channel(
            conn, existing.id, {"channel_profile_ids": json.dumps(effective_profile_ids)}
        )

    def _sync_channel_logo(
        self,
        conn: Connection,
        existing: Any,
        event: Event,
        template: dict | None,
        matched_keyword: str | None,
        segment: str | None,
        changes_made: list[str],
        feed_team=None,
    ) -> None:
        """Sync logo — handles both updates and removals."""
        from teamarr.database.channels import update_managed_channel

        logo_url = self._resolve_logo_url(
            event, template, matched_keyword, segment, feed_team=feed_team,
        )
        current_logo_id = getattr(existing, "dispatcharr_logo_id", None)
        stored_logo_url = getattr(existing, "logo_url", None)

        if logo_url and self._logo_manager:
            needs_logo_update = logo_url != stored_logo_url or not current_logo_id
            if needs_logo_update:
                reason = "URL changed" if logo_url != stored_logo_url else "missing logo_id"
                logger.debug(
                    "[LIFECYCLE] Logo sync for '%s': %s (stored=%s, new=%s, logo_id=%s)",
                    existing.channel_name,
                    reason,
                    stored_logo_url,
                    logo_url,
                    current_logo_id,
                )
                with self._dispatcharr_lock:
                    logo_result = self._logo_manager.upload(
                        name=f"{existing.channel_name} Logo",
                        url=logo_url,
                    )
                    if logo_result.success and logo_result.logo:
                        new_logo_id = logo_result.logo.get("id")
                        api_ok = self._safe_update_channel(
                            existing.dispatcharr_channel_id,
                            {"logo_id": new_logo_id},
                            "logo assignment",
                        )
                        if api_ok:
                            update_managed_channel(
                                conn,
                                existing.id,
                                {"logo_url": logo_url, "dispatcharr_logo_id": new_logo_id},
                            )
                            changes_made.append("logo updated")

        elif stored_logo_url and self._logo_manager:
            with self._dispatcharr_lock:
                api_ok = self._safe_update_channel(
                    existing.dispatcharr_channel_id,
                    {"logo_id": None},
                    "logo removal",
                )
            if api_ok:
                update_managed_channel(
                    conn,
                    existing.id,
                    {"logo_url": None, "dispatcharr_logo_id": None},
                )
                changes_made.append("logo removed")

    def _sync_stream_profile(
        self,
        conn: Connection,
        existing: Any,
        current_channel: Any,
        changes_made: list[str],
    ) -> None:
        """Sync stream_profile_id (always global default)."""
        from teamarr.database.settings import get_dispatcharr_settings

        dispatcharr_settings = get_dispatcharr_settings(conn)
        expected_stream_profile = dispatcharr_settings.default_stream_profile_id

        current_stream_profile = current_channel.stream_profile_id
        if expected_stream_profile != current_stream_profile:
            with self._dispatcharr_lock:
                api_ok = self._safe_update_channel(
                    existing.dispatcharr_channel_id,
                    {"stream_profile_id": expected_stream_profile},
                    "stream profile assign",
                )
            if api_ok:
                logger.debug(
                    "[LIFECYCLE] Stream profile PATCH for '%s': %s → %s",
                    existing.channel_name,
                    current_stream_profile,
                    expected_stream_profile,
                )
                changes_made.append(
                    f"stream_profile: {current_stream_profile} → {expected_stream_profile}"
                )

    def associate_epg_with_channels(self, epg_source_id: int | None = None) -> dict:
        """Associate EPG data with managed channels after EPG refresh.

        Looks up EPGData by tvg_id and calls set_channel_epg to link them.

        Args:
            epg_source_id: Optional EPG source ID (uses default from settings if not provided)

        Returns:
            Dict with success/error counts
        """
        from teamarr.database.channels import get_all_managed_channels

        if not self._channel_manager or not self._epg_manager:
            return {"error": "Dispatcharr not configured"}

        result = {"associated": 0, "not_found": 0, "errors": 0}

        with self._db_factory() as conn:
            # Get all active managed channels
            channels = get_all_managed_channels(conn, include_deleted=False)

            if not channels:
                return result

            # Build EPG data lookup from Dispatcharr (via ChannelManager)
            epg_lookup = self._channel_manager.build_epg_lookup(epg_source_id)

            for channel in channels:
                if not channel.dispatcharr_channel_id or not channel.tvg_id:
                    continue

                # Look up EPG data by tvg_id
                epg_data = epg_lookup.get(channel.tvg_id)

                if not epg_data:
                    result["not_found"] += 1
                    continue

                # Associate EPG with channel
                epg_data_id = epg_data.get("id")
                if not epg_data_id:
                    result["not_found"] += 1
                    continue

                try:
                    with self._dispatcharr_lock:
                        self._channel_manager.set_channel_epg(
                            channel.dispatcharr_channel_id,
                            epg_data_id,
                        )
                    result["associated"] += 1
                except Exception as e:
                    logger.debug(
                        "[LIFECYCLE] Failed to associate EPG for channel %s: %s",
                        channel.channel_name,
                        e,
                    )
                    result["errors"] += 1

        if result["associated"]:
            logger.info("[LIFECYCLE] Associated EPG data with %d channels", result["associated"])

        return result
