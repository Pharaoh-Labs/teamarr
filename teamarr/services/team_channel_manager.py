"""Lifecycle management for persistent, streamless Team EPG channels."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from teamarr.database.channel_numbers import get_channel_stability_settings
from teamarr.database.managed_team_channel_streams import (
    active_stream_ids,
    reconcile_team_streams,
)
from teamarr.database.managed_team_channels import (
    delete_managed_team_channel,
    get_managed_team_channel,
    list_disabled_managed_team_channels,
    list_enabled_managed_teams,
    upsert_managed_team_channel,
)
from teamarr.database.settings import (
    get_dispatcharr_settings,
    get_epg_settings,
    get_managed_team_channel_settings,
)
from teamarr.utilities.art_url import apply_art_base_url, is_relative_art_path
from teamarr.utilities.tz import now_utc, to_db_utc, to_utc

logger = logging.getLogger(__name__)

# Dispatcharr's "every profile" sentinel (creator.py). A None setting means the
# user never narrowed profiles, which the event path also sends as [0].
_ALL_PROFILES = [0]


class TeamChannelManager:
    """Create and maintain Teamarr-owned channels for Team EPG output.

    Ownership is deliberately determined only by ``managed_team_channels``.
    A matching ``tvg_id`` on an unmapped Dispatcharr channel is a user-owned
    channel and remains untouched.

    Every Dispatcharr read that feeds a destructive decision (create because a
    channel is "missing", drop a mapping because a channel is "gone") must be
    able to say "I could not read" as distinct from "there is nothing". A
    failed list fetch returns ``None`` from ``_remote_channels`` and the sync
    is skipped for the run; a mapped channel missing from a successful list is
    re-verified with an uncached lookup before anything is recreated (#826).
    """

    def __init__(
        self,
        db_factory: Any,
        channel_manager: Any | None,
        epg_manager: Any | None = None,
        logo_manager: Any | None = None,
        dynamic_resolver: Any | None = None,
    ):
        self._db_factory = db_factory
        self._channels = channel_manager
        self._epg = epg_manager
        self._logos = logo_manager
        self._resolver = dynamic_resolver
        self._warned_unresolved_profiles = False

    # ------------------------------------------------------------------
    # Dispatcharr reads that must distinguish failure from emptiness
    # ------------------------------------------------------------------

    def _remote_channels(self) -> dict[int, Any] | None:
        """All Dispatcharr channels keyed by id, or None when the read failed."""
        if self._channels is None:
            return None
        fetch = getattr(self._channels, "fetch_channels", None)
        try:
            channels = fetch() if fetch is not None else self._channels.get_channels()
        except Exception as exc:  # noqa: BLE001 - a read failure must not abort the run
            logger.warning("[TEAM_CHANNEL] Could not read Dispatcharr channels: %s", exc)
            return None
        if channels is None:
            logger.warning(
                "[TEAM_CHANNEL] Dispatcharr channel list unavailable — skipping team channel sync"
            )
            return None
        return {channel.id: channel for channel in channels}

    def _existence(self, channel_id: int) -> tuple[Any | None, bool]:
        """(channel, confirmed_absent) for one id, bypassing the list cache."""
        probe = getattr(self._channels, "get_channel_existence", None)
        if probe is None:
            return None, False
        try:
            return probe(channel_id, use_cache=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TEAM_CHANNEL] Could not verify channel %s: %s", channel_id, exc)
            return None, False

    # ------------------------------------------------------------------
    # Channel ownership
    # ------------------------------------------------------------------

    def sync(self, relayout: bool = False) -> dict[str, Any]:
        """Create or update enabled team channels and remove disabled ones.

        Automatic numbers follow the event channels' Number Stability setting:
        Compact re-sorts every run; Gapped/Strict hold a channel's number and
        re-sort only when the daily re-layout or a manual re-grid fires, which
        the caller reports as ``relayout`` (the event pass computes it once).
        """
        result: dict[str, Any] = {
            "created": 0, "synced": 0, "deleted": 0, "conflicts": 0, "errors": 0,
            "unavailable": False,
        }
        if not self._channels:
            return result

        remote_channels = self._remote_channels()
        if remote_channels is None:
            result["unavailable"] = True
            return result
        remote_by_tvg = {
            channel.tvg_id: channel for channel in remote_channels.values() if channel.tvg_id
        }
        occupied = {
            self._number(channel.channel_number)
            for channel in remote_channels.values()
            if self._number(channel.channel_number) is not None
        }

        with self._db_factory() as conn:
            self._delete_disabled(conn, result)
            settings = get_managed_team_channel_settings(conn)
            dispatcharr = get_dispatcharr_settings(conn)
            teams = list_enabled_managed_teams(conn)
            from teamarr.database.priority_teams import get_priority_team_match_keys
            from teamarr.database.sort_priorities import get_all_sort_priorities

            managed_priorities = {
                team_id: index for index, team_id in enumerate(settings.priority_ids)
            }
            sort_priorities = get_all_sort_priorities(conn)
            sport_order = {
                priority.sport.lower(): priority.sort_priority
                for priority in sort_priorities
                if priority.league_code is None
            }
            league_order = {
                (priority.sport.lower(), priority.league_code.lower()): priority.sort_priority
                for priority in sort_priorities
                if priority.league_code is not None
            }
            priority_teams = get_priority_team_match_keys(conn)

            def team_sort_key(team):
                sport = (team.get("sport") or "").lower()
                league = (team.get("primary_league") or "").lower()
                priority_scope = priority_teams.get((sport, team["team_name"].lower()))
                return (
                    managed_priorities.get(team["id"], len(managed_priorities)),
                    0 if priority_scope == "all" else 1,
                    sport_order.get(sport, 9999),
                    0 if priority_scope in {"all", "sport"} else 1,
                    league_order.get((sport, league), 9999),
                    0 if priority_scope else 1,
                    team["team_name"],
                )

            teams.sort(key=team_sort_key)
            reflow = relayout or self._stability_mode(conn) == "compact"
            if reflow:
                # Every automatic channel floats back into sort order: release
                # their current numbers so the walk below can hand them out
                # again from the top of the lane.
                for team in teams:
                    if team.get("managed_channel_number") is not None:
                        continue
                    mapped_id = team.get("dispatcharr_channel_id")
                    remote = remote_channels.get(mapped_id) if mapped_id else None
                    number = self._number(remote.channel_number) if remote else None
                    if number is not None:
                        occupied.discard(number)
            for team in teams:
                mapping_id = team.get("dispatcharr_channel_id")
                remote = remote_channels.get(mapping_id) if mapping_id else None
                if mapping_id and remote is None:
                    # Missing from the list is not proof it is gone: the list
                    # may be stale. Only an HTTP 404 lets the mapping be replaced.
                    remote, confirmed_absent = self._existence(mapping_id)
                    if remote is not None:
                        remote_channels[mapping_id] = remote
                    elif not confirmed_absent:
                        self._record_error(
                            conn, team, "Could not verify the mapped Dispatcharr channel"
                        )
                        result["errors"] += 1
                        continue
                if (
                    remote is not None
                    and team.get("dispatcharr_uuid")
                    and getattr(remote, "uuid", None) != team["dispatcharr_uuid"]
                ):
                    self._record_error(
                        conn,
                        team,
                        "Mapped Dispatcharr channel UUID no longer matches Teamarr ownership",
                        sync_status="conflict",
                    )
                    result["conflicts"] += 1
                    continue

                own_number = self._number(remote.channel_number) if remote else None
                # Holding: a channel's own number never blocks itself. Reflow
                # already released every floating number above, and one that
                # has since been handed to an earlier team must stay taken.
                team_occupied = (
                    occupied
                    if reflow and team.get("managed_channel_number") is None
                    else occupied - ({own_number} if own_number is not None else set())
                )
                channel_number, allocation_error = self._allocate_number(
                    team.get("managed_channel_number"),
                    None if reflow else own_number,
                    None if reflow else team.get("allocated_channel_number"),
                    team_occupied,
                    settings,
                    conn,
                    team,
                )
                if channel_number is None:
                    self._record_error(
                        conn, team, allocation_error or "No free managed team channel number"
                    )
                    result["errors"] += 1
                    continue

                if remote is None:
                    # Never adopt a channel merely because its XMLTV identifier matches.
                    if remote_by_tvg.get(team["channel_id"]):
                        self._record_error(
                            conn,
                            team,
                            "A Dispatcharr channel already uses this tvg_id and is not "
                            "Teamarr-managed. Delete or re-point it, then generate again.",
                            sync_status="conflict",
                        )
                        result["conflicts"] += 1
                        continue
                    create_data = {
                        "name": self._channel_name(conn, team),
                        "channel_number": channel_number,
                        "stream_ids": [],
                        "tvg_id": team["channel_id"],
                        "channel_group_id": self._channel_group(dispatcharr),
                        "channel_profile_ids": self._channel_profiles(dispatcharr, team),
                        "stream_profile_id": dispatcharr.default_stream_profile_id,
                    }
                    logo_id = self._logo_id(conn, team)
                    if logo_id is not None:
                        create_data["logo_id"] = logo_id
                    create_result = self._channels.create_channel(**create_data)
                    if not create_result.success or not create_result.channel:
                        self._record_error(
                            conn, team, create_result.error or "Dispatcharr create failed"
                        )
                        result["errors"] += 1
                        continue
                    created = create_result.channel
                    remote_by_tvg[team["channel_id"]] = created
                    occupied.add(channel_number)
                    upsert_managed_team_channel(
                        conn,
                        team_id=team["id"],
                        dispatcharr_channel_id=created["id"],
                        dispatcharr_uuid=created.get("uuid"),
                        channel_number=channel_number,
                        sync_status="ready",
                    )
                    # Dispatcharr does not consistently persist logo_id from a
                    # channel-create payload, so enforce the template logo once
                    # the newly-created channel has a stable ID.
                    if logo_id is not None:
                        logo_result = self._channels.update_channel(
                            created["id"], {"logo_id": logo_id}
                        )
                        if not logo_result.success:
                            self._record_error(
                                conn,
                                {**team, "dispatcharr_channel_id": created["id"]},
                                logo_result.error or "Dispatcharr logo update failed",
                            )
                            result["errors"] += 1
                    result["created"] += 1
                    continue

                changes = self._changes(remote, team, channel_number, dispatcharr, conn)
                if changes:
                    update_result = self._channels.update_channel(remote.id, changes)
                    if not update_result.success:
                        self._record_error(
                            conn, team, update_result.error or "Dispatcharr update failed"
                        )
                        result["errors"] += 1
                        continue
                occupied.add(channel_number)
                upsert_managed_team_channel(
                    conn,
                    team_id=team["id"],
                    dispatcharr_channel_id=remote.id,
                    # The stored UUID is the ownership proof; it is written once
                    # at create (or backfilled for a pre-UUID row) and never
                    # replaced from a remote read.
                    dispatcharr_uuid=team.get("dispatcharr_uuid") or remote.uuid,
                    channel_number=channel_number,
                    sync_status="ready",
                )
                result["synced"] += 1
        return result

    def associate_epg(self, epg_source_id: int) -> dict[str, int]:
        """Link refreshed Team EPG data to only locally-owned team channels."""
        result = {"associated": 0, "not_found": 0, "errors": 0}
        if not self._channels or not self._epg:
            return result
        with self._db_factory() as conn:
            teams = [
                team for team in list_enabled_managed_teams(conn)
                if team.get("dispatcharr_channel_id")
            ]
        if not teams:
            return result
        lookup = self._channels.build_epg_lookup(epg_source_id)
        for team in teams:
            epg_data = lookup.get(team["channel_id"])
            if not epg_data or not epg_data.get("id"):
                result["not_found"] += 1
                continue
            try:
                outcome = self._channels.set_channel_epg(
                    team["dispatcharr_channel_id"], epg_data["id"]
                )
            except Exception:
                logger.exception(
                    "[TEAM_CHANNEL] EPG association failed for %s", team["team_name"]
                )
                result["errors"] += 1
                continue
            if outcome is not None and not getattr(outcome, "success", True):
                logger.warning(
                    "[TEAM_CHANNEL] EPG association rejected for %s: %s",
                    team["team_name"],
                    getattr(outcome, "error", None),
                )
                result["errors"] += 1
                continue
            result["associated"] += 1
        return result

    def remove_team_channel(self, team_id: int) -> tuple[bool, str | None]:
        """Delete one proven-owned remote channel before removing its mapping."""
        with self._db_factory() as conn:
            mapping = get_managed_team_channel(conn, team_id)
            if not mapping:
                return True, None
            if mapping.dispatcharr_channel_id is None:
                # An error/conflict record with no channel behind it.
                delete_managed_team_channel(conn, team_id)
                return True, None
            if not self._channels:
                return False, "Dispatcharr connection not available"
            remote, confirmed_absent = self._existence(mapping.dispatcharr_channel_id)
            if remote is None:
                if not confirmed_absent:
                    return False, "Could not verify the Dispatcharr channel; try again later"
                delete_managed_team_channel(conn, team_id)
                return True, None
            if mapping.dispatcharr_uuid and remote.uuid != mapping.dispatcharr_uuid:
                message = "Mapped Dispatcharr channel UUID no longer matches Teamarr ownership"
                self._record_error(
                    conn,
                    {
                        "id": team_id,
                        "dispatcharr_channel_id": remote.id,
                        "dispatcharr_uuid": mapping.dispatcharr_uuid,
                        "allocated_channel_number": mapping.channel_number,
                    },
                    message,
                    sync_status="conflict",
                )
                return False, message
            deleted = self._channels.delete_channel(remote.id)
            if not deleted.success:
                return False, deleted.error or "Dispatcharr delete failed"
            delete_managed_team_channel(conn, team_id)
            return True, None

    # ------------------------------------------------------------------
    # Stream memberships
    # ------------------------------------------------------------------

    def sync_stream_memberships(
        self,
        matched_streams: list[dict],
        completed_group_ids: set[int] | None = None,
    ) -> dict[str, int]:
        """Persist this run's matched event streams as team channel memberships.

        ``completed_group_ids`` are the event groups whose matching finished
        this run. Only their rows (plus rows from groups that no longer exist
        or are disabled) are reconciled; a group that errored or returned
        early says nothing about its streams, so its memberships stand (#826).
        ``None`` means every group completed (single-caller convenience).

        Every membership carries a window. EPG-matched linear streams keep the
        programme slot; name-matched streams get the game itself, widened by
        the lifecycle buffers, so a finished game releases its streams and the
        soonest game wins the channel rather than the lowest event id.
        """
        result = {"memberships": 0, "channels": 0, "errors": 0}
        if not self._channels:
            return result
        # Import lazily: consumers.__init__ imports generation, which imports services.
        from teamarr.consumers.lifecycle.feed_side import resolve_feed_side
        from teamarr.consumers.lifecycle.timing import compute_stream_window

        with self._db_factory() as conn:
            teams = list_enabled_managed_teams(conn)
            recipients: dict[tuple[str, str], list[tuple[dict, set[str]]]] = {}
            for team in teams:
                if not team.get("dispatcharr_channel_id") or not team.get("active", 1):
                    continue
                key = (team.get("provider") or "espn", str(team.get("provider_team_id", "")))
                recipients.setdefault(key, []).append((team, self._team_leagues(team)))
            timing = self._timing_manager(conn)
            buffers = conn.execute(
                "SELECT epg_stream_pre_buffer_minutes, epg_stream_post_buffer_minutes "
                "FROM settings WHERE id = 1"
            ).fetchone()
            pre_buffer = buffers["epg_stream_pre_buffer_minutes"] if buffers else 60
            post_buffer = buffers["epg_stream_post_buffer_minutes"] if buffers else 60
            memberships = []
            for matched in matched_streams:
                event = matched.get("event")
                stream = matched.get("stream") or {}
                if not event or stream.get("id") is None:
                    continue
                status = getattr(getattr(event, "status", None), "state", None)
                if status in {"final", "cancelled", "postponed"}:
                    continue
                if timing is not None and timing.categorize_event_timing(event) is not None:
                    continue
                provider = str(getattr(event, "provider", None) or "")
                league = getattr(event, "league", None)
                sides = (getattr(event, "home_team", None), getattr(event, "away_team", None))
                attach_at, detach_at = compute_stream_window(
                    matched.get("epg_program_start"),
                    matched.get("epg_program_end"),
                    pre_buffer,
                    post_buffer,
                )
                event_start = self._event_start(event)
                if attach_at is None:
                    attach_at, detach_at = self._event_window(event, timing)
                stream_feed_team = matched.get("stream_feed_team")
                stream_feed_team_id = (
                    str(stream_feed_team.id) if stream_feed_team is not None else None
                )
                if stream_feed_team_id is None:
                    side_hint = matched.get("matched_side")
                    if side_hint == "home" and sides[0] is not None:
                        stream_feed_team_id = str(sides[0].id)
                    elif side_hint == "away" and sides[1] is not None:
                        stream_feed_team_id = str(sides[1].id)
                feed_side = resolve_feed_side(
                    event,
                    feed_hint=matched.get("feed_hint"),
                    matched_side=matched.get("matched_side"),
                    feed_team_id=stream_feed_team_id,
                )
                if stream_feed_team_id is None and feed_side in {"home", "away"}:
                    # A resolved side names the broadcast's team, so team_feed
                    # rules can read it as a lookup (#527/#533).
                    feed_team = sides[0] if feed_side == "home" else sides[1]
                    if feed_team is not None:
                        stream_feed_team_id = str(feed_team.id)
                for side in sides:
                    if side is None:
                        continue
                    for team, leagues in recipients.get((provider, str(side.id)), []):
                        if league not in leagues:
                            continue
                        memberships.append(
                            {
                                "team_id": team["id"],
                                "dispatcharr_stream_id": stream["id"],
                                "event_id": str(event.id),
                                "event_provider": provider,
                                "source_group_id": matched["source_group_id"],
                                "match_method": matched.get("match_method"),
                                "match_type": matched.get("match_type", "event"),
                                "stream_name": stream.get("name"),
                                "m3u_account_name": stream.get("m3u_account_name"),
                                "feed_team_id": stream_feed_team_id,
                                "feed_side": feed_side,
                                "dispatcharr_channel_group": stream.get("dp_channel_group"),
                                "event_start": event_start,
                                "attach_at": attach_at,
                                "detach_at": detach_at,
                            }
                        )
            reconcile_groups = self._reconcile_groups(conn, completed_group_ids)
            active_team_ids = {team["id"] for entries in recipients.values() for team, _ in entries}
            reconcile_team_streams(
                conn, memberships, reconcile_groups, active_team_ids=active_team_ids
            )
            result["memberships"] = len(memberships)
        return result

    @staticmethod
    def _team_leagues(team: dict) -> set[str]:
        leagues = team.get("leagues")
        if isinstance(leagues, str):
            try:
                leagues = json.loads(leagues)
            except (TypeError, ValueError):
                leagues = []
        allowed = {lg for lg in (leagues or []) if lg}
        if team.get("primary_league"):
            allowed.add(team["primary_league"])
        return allowed

    @staticmethod
    def _timing_manager(conn):
        """The event lifecycle's timing rules, so team channels attach the same games."""
        try:
            from dataclasses import asdict

            from teamarr.consumers.lifecycle import get_lifecycle_settings
            from teamarr.consumers.lifecycle.timing import ChannelLifecycleManager
            from teamarr.database.settings import get_all_settings

            lifecycle = get_lifecycle_settings(conn)
            all_settings = get_all_settings(conn)
            return ChannelLifecycleManager(
                create_timing=lifecycle["create_timing"],
                delete_timing=lifecycle["delete_timing"],
                pre_buffer_minutes=lifecycle["pre_buffer_minutes"],
                post_buffer_minutes=lifecycle["post_buffer_minutes"],
                default_duration_hours=all_settings.durations.default,
                sport_durations=asdict(all_settings.durations),
                include_final_events=False,
            )
        except Exception as exc:  # noqa: BLE001 - tests use a bare schema
            logger.debug("[TEAM_CHANNEL] Lifecycle timing unavailable: %s", exc)
            return None

    @staticmethod
    def _event_start(event) -> str | None:
        start = getattr(event, "start_time", None)
        if start is None:
            return None
        try:
            return to_db_utc(to_utc(start))
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _event_window(event, timing) -> tuple[str | None, str | None]:
        """Game start/end widened by the lifecycle buffers, as SQLite UTC strings."""
        start = getattr(event, "start_time", None)
        if start is None:
            return None, None
        try:
            start_utc = to_utc(start)
            if timing is not None:
                end_utc = to_utc(timing.get_event_end_time(event))
                pre = timedelta(minutes=timing.pre_buffer_minutes)
                post = timedelta(minutes=timing.post_buffer_minutes)
            else:
                end_utc = start_utc + timedelta(hours=3)
                pre = post = timedelta(minutes=60)
            return to_db_utc(start_utc - pre), to_db_utc(end_utc + post)
        except Exception:  # noqa: BLE001
            return None, None

    @staticmethod
    def _reconcile_groups(conn, completed_group_ids: set[int] | None) -> set[int] | None:
        """Groups whose memberships may be reconciled this run."""
        if completed_group_ids is None:
            return None
        groups = set(completed_group_ids)
        try:
            enabled = {
                row[0]
                for row in conn.execute("SELECT id FROM event_epg_groups WHERE enabled = 1")
            }
            present = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT source_group_id FROM managed_team_channel_streams "
                    "WHERE removed_at IS NULL"
                )
            }
            groups |= present - enabled
        except Exception as exc:  # noqa: BLE001 - tests use a bare schema
            logger.debug("[TEAM_CHANNEL] Could not read group state: %s", exc)
        return groups

    # ------------------------------------------------------------------
    # Stream ordering
    # ------------------------------------------------------------------

    def sync_stream_ordering(self) -> dict[str, int]:
        """Apply scoped ordering and active windows to durable team channels.

        Opens its own connection and issues its own PATCHes; the caller must
        not hold a database connection across this call (#735, #826).
        """
        result = {"channels": 0, "streams": 0, "errors": 0}
        if not self._channels:
            return result

        from teamarr.database.channels.types import ManagedChannelStream
        from teamarr.services.stream_ordering import get_stream_ordering_service

        remote_channels = self._remote_channels()
        if remote_channels is None:
            return result
        remote_order = {
            channel_id: list(channel.streams or ())
            for channel_id, channel in remote_channels.items()
        }
        pushes: list[tuple[dict, list[int]]] = []
        with self._db_factory() as conn:
            teams = list_enabled_managed_teams(conn)
            for team in teams:
                channel_id = team.get("dispatcharr_channel_id")
                if not channel_id:
                    continue
                rows = conn.execute(
                    "SELECT * FROM managed_team_channel_streams "
                    "WHERE team_id = ? AND removed_at IS NULL",
                    (team["id"],),
                ).fetchall()
                service = get_stream_ordering_service(
                    conn, team.get("sport"), team.get("primary_league")
                )
                for row in rows:
                    stream = ManagedChannelStream(
                        id=row["id"], managed_channel_id=0,
                        dispatcharr_stream_id=row["dispatcharr_stream_id"],
                        stream_name=row["stream_name"],
                        m3u_account_name=row["m3u_account_name"],
                        source_group_id=row["source_group_id"],
                        match_type=row["match_type"], match_method=row["match_method"],
                        feed_team_id=row["feed_team_id"], feed_side=row["feed_side"],
                        dispatcharr_channel_group=row["dispatcharr_channel_group"],
                        priority=row["priority"],
                    )
                    priority = service.compute_priority(stream)
                    if priority != stream.priority:
                        conn.execute(
                            "UPDATE managed_team_channel_streams SET priority = ?, "
                            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (priority, stream.id),
                        )
                        result["streams"] += 1

                ordered = active_stream_ids(conn, team["id"], now_utc())
                if channel_id not in remote_order or ordered == remote_order[channel_id]:
                    continue
                pushes.append((team, ordered))

        # Network only, after the connection is closed.
        for team, ordered in pushes:
            try:
                sync_result = self._channels.update_channel(
                    team["dispatcharr_channel_id"], {"streams": ordered}
                )
                if not sync_result.success:
                    raise RuntimeError(sync_result.error or "Dispatcharr update failed")
                result["channels"] += 1
            except Exception:
                logger.exception(
                    "[TEAM_CHANNEL] Stream order sync failed for %s", team["team_name"]
                )
                result["errors"] += 1
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _delete_disabled(self, conn, result) -> None:
        for mapping in list_disabled_managed_team_channels(conn):
            deleted, _ = self.remove_team_channel(mapping["team_id"])
            if deleted:
                result["deleted"] += 1
            else:
                result["errors"] += 1

    @staticmethod
    def _stability_mode(conn) -> str:
        try:
            return get_channel_stability_settings(conn)["mode"]
        except Exception:  # noqa: BLE001 - tests use a bare schema
            return "compact"

    @staticmethod
    def _number(value: Any) -> int | None:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _allocate_number(
        self, requested, own, allocated, occupied, settings, conn, team
    ) -> tuple[int | None, str | None]:
        """An exact override wins; a held number (sticky modes) is kept; else first free."""
        requested = self._number(requested)
        if requested is not None:
            if requested < 1:
                return None, f"Requested channel number {requested} is not valid"
            if requested in occupied:
                return None, f"Requested channel number {requested} is already occupied"
            return requested, None
        for held in (self._number(own), self._number(allocated)):
            if held is not None and held not in occupied:
                return held, None
        from teamarr.database.numbering_exceptions import Lane, LaneResolver

        lane = LaneResolver.load(
            conn, Lane(id=None, start=settings.range_start, end=settings.range_end)
        ).resolve(team.get("sport"), team.get("primary_league"), team.get("team_name"))
        number = lane.start
        while lane.end is None or number <= lane.end:
            if number not in occupied:
                return number, None
            number += 1
        return None, None

    @staticmethod
    def _channel_group(dispatcharr):
        """Return the managed-team-only group, never an event-channel default."""
        return dispatcharr.managed_team_channel_group_id

    def _channel_profiles(self, dispatcharr, team) -> list[int]:
        """Managed-team profiles as Dispatcharr ids; None means every profile."""
        configured = dispatcharr.managed_team_channel_profile_ids
        if configured is None:
            return list(_ALL_PROFILES)
        resolved: list[int] = []
        patterns: list[str] = []
        for item in configured:
            if isinstance(item, int):
                resolved.append(item)
            elif isinstance(item, str) and item.isdigit():
                resolved.append(int(item))
            elif isinstance(item, str) and "{" in item:
                patterns.append(item)
        if patterns:
            if self._resolver is not None:
                try:
                    resolved.extend(
                        self._resolver.resolve_channel_profiles(
                            patterns, team.get("sport"), team.get("primary_league")
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[TEAM_CHANNEL] Profile pattern resolution failed: %s", exc)
            elif not self._warned_unresolved_profiles:
                self._warned_unresolved_profiles = True
                logger.warning(
                    "[TEAM_CHANNEL] Managed team profile patterns %s cannot be resolved "
                    "without Dispatcharr; ignoring them",
                    patterns,
                )
        if not resolved and configured:
            # Every configured entry was unusable: visible everywhere beats a
            # channel silently attached to no profile (creator.py, #565).
            return list(_ALL_PROFILES)
        return resolved

    def _changes(self, remote, team, number, dispatcharr, conn) -> dict:
        desired: dict[str, Any] = {
            "name": self._channel_name(conn, team),
            "channel_number": number,
            "tvg_id": team["channel_id"],
        }
        # Output defaults are enforced only when configured; None means the
        # user has not narrowed them and whatever Dispatcharr has stands.
        group_id = self._channel_group(dispatcharr)
        if group_id is not None:
            desired["channel_group_id"] = group_id
        if dispatcharr.default_stream_profile_id is not None:
            desired["stream_profile_id"] = dispatcharr.default_stream_profile_id
        profiles = self._channel_profiles(dispatcharr, team)
        remote_profiles = getattr(remote, "channel_profile_ids", None)
        if profiles != _ALL_PROFILES and remote_profiles is not None:
            if sorted(profiles) != sorted(remote_profiles):
                desired["channel_profile_ids"] = profiles
        logo_id = self._logo_id(conn, team)
        if logo_id is not None:
            desired["logo_id"] = logo_id
        current = {
            "name": remote.name,
            "channel_number": self._number(remote.channel_number),
            "tvg_id": remote.tvg_id,
            "channel_group_id": remote.channel_group_id,
            "stream_profile_id": remote.stream_profile_id,
            "logo_id": remote.logo_id,
        }
        return {
            key: value
            for key, value in desired.items()
            if key == "channel_profile_ids" or current.get(key) != value
        }

    @staticmethod
    def _template_context(conn, team) -> dict:
        from teamarr.database.leagues import get_league_display

        return {
            "league": get_league_display(conn, team["primary_league"]),
            "league_id": team["primary_league"],
            "league_code": team["primary_league"],
            "team_name": team["team_name"],
        }

    def _logo_id(self, conn, team) -> int | None:
        if not self._logos or not team.get("template_id"):
            return None
        from teamarr.database.templates import get_template
        from teamarr.templates.resolver import TemplateResolver

        template = get_template(conn, team["template_id"])
        url = template.team_channel_logo_url if template else None
        if not url:
            return None
        art_base_url = get_epg_settings(conn).art_base_url
        url = TemplateResolver(art_base_url).resolve_with_map(
            url, self._template_context(conn, team)
        )
        url = apply_art_base_url(url, art_base_url)
        if is_relative_art_path(url):
            # A game-thumbs path with no base URL is not a fetchable logo.
            return None
        uploaded = self._logos.upload(name=f'{team["team_name"]} Logo', url=url)
        return uploaded.logo.get("id") if uploaded.success and uploaded.logo else None

    @classmethod
    def _channel_name(cls, conn, team) -> str:
        if not team.get("template_id"):
            return team["team_name"]
        from teamarr.database.templates import get_template
        from teamarr.templates.resolver import TemplateResolver

        template = get_template(conn, team["template_id"])
        if not template or not template.team_channel_name:
            return team["team_name"]
        return TemplateResolver(get_epg_settings(conn).art_base_url).resolve_with_map(
            template.team_channel_name, cls._template_context(conn, team)
        )

    @staticmethod
    def _record_error(conn, team, message: str, sync_status: str = "error") -> None:
        """Persist the failure so the Teams page can show it, channel or not."""
        upsert_managed_team_channel(
            conn,
            team_id=team["id"],
            dispatcharr_channel_id=team.get("dispatcharr_channel_id"),
            dispatcharr_uuid=team.get("dispatcharr_uuid"),
            channel_number=(
                team.get("allocated_channel_number") or team.get("managed_channel_number") or 0
            ),
            sync_status=sync_status,
            sync_message=message,
        )
