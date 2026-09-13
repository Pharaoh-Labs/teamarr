"""Lifecycle management for persistent, streamless Team EPG channels."""

from __future__ import annotations

import logging
from typing import Any

from teamarr.database.managed_team_channel_streams import (
    active_stream_ids,
    reconcile_team_streams,
)
from teamarr.database.managed_team_channels import (
    delete_managed_team_channel,
    list_disabled_managed_team_channels,
    list_enabled_managed_teams,
    upsert_managed_team_channel,
)
from teamarr.database.settings import (
    get_dispatcharr_settings,
    get_epg_settings,
    get_managed_team_channel_settings,
)
from teamarr.database.subscription import get_league_config
from teamarr.utilities.art_url import apply_art_base_url

logger = logging.getLogger(__name__)


class TeamChannelManager:
    """Create and maintain Teamarr-owned channels for Team EPG output.

    Ownership is deliberately determined only by ``managed_team_channels``.
    A matching ``tvg_id`` on an unmapped Dispatcharr channel is a user-owned
    channel and remains untouched.
    """

    def __init__(
        self,
        db_factory: Any,
        channel_manager: Any | None,
        epg_manager: Any | None = None,
        logo_manager: Any | None = None,
    ):
        self._db_factory = db_factory
        self._channels = channel_manager
        self._epg = epg_manager
        self._logos = logo_manager

    def sync(self) -> dict[str, int]:
        """Create or update enabled team channels and remove disabled ones."""
        result = {"created": 0, "synced": 0, "deleted": 0, "conflicts": 0, "errors": 0}
        if not self._channels:
            return result

        remote_channels = {channel.id: channel for channel in self._channels.get_channels()}
        remote_by_tvg = {
            channel.tvg_id: channel for channel in remote_channels.values() if channel.tvg_id
        }
        occupied = {
            self._number(channel.channel_number)
            for channel in remote_channels.values()
            if self._number(channel.channel_number) is not None
        }

        with self._db_factory() as conn:
            self._delete_disabled(conn, remote_channels, result)
            settings = get_managed_team_channel_settings(conn)
            dispatcharr = get_dispatcharr_settings(conn)
            teams = list_enabled_managed_teams(conn)
            priorities = {team_id: index for index, team_id in enumerate(settings.priority_ids)}
            teams.sort(
                key=lambda team: (
                    priorities.get(team["id"], len(priorities)),
                    team["team_name"],
                )
            )
            for team in teams:
                mapping_id = team["dispatcharr_channel_id"]
                remote = remote_channels.get(mapping_id) if mapping_id else None
                requested = team.get("managed_channel_number")
                team_occupied = occupied.copy()
                if remote:
                    remote_number = self._number(remote.channel_number)
                    if remote_number is not None:
                        team_occupied.discard(remote_number)
                channel_number, allocation_error = self._allocate_number(
                    requested,
                    team.get("allocated_channel_number"),
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
                            "Dispatcharr channel with this tvg_id is not Teamarr-managed",
                        )
                        result["conflicts"] += 1
                        continue
                    create_data = {
                        "name": team["team_name"],
                        "channel_number": channel_number,
                        "stream_ids": [],
                        "tvg_id": team["channel_id"],
                        "channel_group_id": self._channel_group(dispatcharr, conn, team),
                        "channel_profile_ids": self._channel_profiles(dispatcharr, conn, team),
                        "stream_profile_id": dispatcharr.default_stream_profile_id,
                    }
                    logo_id = self._logo_id(conn, team)
                    if logo_id is not None:
                        create_data["logo_id"] = logo_id
                    create_result = self._channels.create_channel(
                        **create_data,
                    )
                    if not create_result.success or not create_result.channel:
                        self._record_error(
                            conn, team, create_result.error or "Dispatcharr create failed"
                        )
                        result["errors"] += 1
                        continue
                    remote = create_result.channel
                    remote_channels[remote["id"]] = remote
                    remote_by_tvg[team["channel_id"]] = remote
                    occupied.add(channel_number)
                    upsert_managed_team_channel(
                        conn,
                        team_id=team["id"],
                        dispatcharr_channel_id=remote["id"],
                        dispatcharr_uuid=remote.get("uuid"),
                        channel_number=channel_number,
                        sync_status="ready",
                    )
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
                    dispatcharr_uuid=remote.uuid,
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
        lookup = self._channels.build_epg_lookup(epg_source_id)
        with self._db_factory() as conn:
            for team in list_enabled_managed_teams(conn):
                channel_id = team.get("dispatcharr_channel_id")
                epg_data = lookup.get(team["channel_id"])
                if not channel_id or not epg_data or not epg_data.get("id"):
                    result["not_found"] += 1
                    continue
                try:
                    self._channels.set_channel_epg(channel_id, epg_data["id"])
                    result["associated"] += 1
                except Exception:
                    logger.exception(
                        "[TEAM_CHANNEL] EPG association failed for %s", team["team_name"]
                    )
                    result["errors"] += 1
        return result

    def sync_stream_memberships(self, matched_streams: list[dict]) -> dict[str, int]:
        """Persist matched event streams and synchronize active remote memberships."""
        result = {"memberships": 0, "channels": 0, "errors": 0}
        if not self._channels:
            return result
        # Import lazily: consumers.__init__ imports generation, which imports services.
        from teamarr.consumers.lifecycle.timing import compute_stream_window

        with self._db_factory() as conn:
            teams = list_enabled_managed_teams(conn)
            recipients = {
                (team.get("provider", "espn"), str(team.get("provider_team_id", ""))): team
                for team in teams
                if team.get("dispatcharr_channel_id")
            }
            buffers = conn.execute(
                "SELECT epg_stream_pre_buffer_minutes, epg_stream_post_buffer_minutes "
                "FROM settings WHERE id = 1"
            ).fetchone()
            pre_buffer = buffers["epg_stream_pre_buffer_minutes"] if buffers else 60
            post_buffer = buffers["epg_stream_post_buffer_minutes"] if buffers else 30
            memberships = []
            for matched in matched_streams:
                event = matched.get("event")
                stream = matched.get("stream") or {}
                if not event or stream.get("id") is None:
                    continue
                provider = getattr(event, "provider", None)
                sides = (getattr(event, "home_team", None), getattr(event, "away_team", None))
                attach_at, detach_at = compute_stream_window(
                    matched.get("epg_program_start"),
                    matched.get("epg_program_end"),
                    pre_buffer,
                    post_buffer,
                )
                for side in sides:
                    team = recipients.get((provider, str(getattr(side, "id", ""))))
                    if team:
                        memberships.append(
                            {
                                "team_id": team["id"],
                                "dispatcharr_stream_id": stream["id"],
                                "event_id": str(event.id),
                                "event_provider": provider,
                                "source_group_id": matched["source_group_id"],
                                "match_method": matched.get("match_method"),
                                "attach_at": attach_at,
                                "detach_at": detach_at,
                            }
                        )
            reconcile_team_streams(conn, memberships)
            result["memberships"] = len(memberships)
            for team in teams:
                channel_id = team.get("dispatcharr_channel_id")
                if not channel_id:
                    continue
                try:
                    self._channels.update_channel(channel_id, {
                        "streams": active_stream_ids(conn, team["id"])
                    })
                    result["channels"] += 1
                except Exception:
                    logger.exception("[TEAM_CHANNEL] Stream sync failed for %s", team["team_name"])
                    result["errors"] += 1
        return result

    def _delete_disabled(self, conn, remote_channels, result) -> None:
        for mapping in list_disabled_managed_team_channels(conn):
            remote = remote_channels.get(mapping["dispatcharr_channel_id"])
            if remote:
                deleted = self._channels.delete_channel(remote.id)
                if not deleted.success:
                    result["errors"] += 1
                    continue
            delete_managed_team_channel(conn, mapping["team_id"])
            result["deleted"] += 1

    @staticmethod
    def _number(value: Any) -> int | None:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _allocate_number(
        self, requested, allocated, occupied, settings, conn, team
    ) -> tuple[int | None, str | None]:
        requested = self._number(requested)
        allocated = self._number(allocated)
        if requested is not None:
            if requested in occupied:
                return None, f"Requested channel number {requested} is already occupied"
            return requested, None
        if allocated is not None and allocated not in occupied:
            return allocated, None
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
    def _channel_group(dispatcharr, conn, team):
        league = get_league_config(conn, team["primary_league"])
        if league and league.channel_group_id is not None:
            return league.channel_group_id
        return dispatcharr.default_channel_group_id

    @staticmethod
    def _channel_profiles(dispatcharr, conn, team):
        league = get_league_config(conn, team["primary_league"])
        profiles = league.channel_profile_ids if league else None
        return profiles if profiles is not None else dispatcharr.default_channel_profile_ids

    def _changes(self, remote, team, number, dispatcharr, conn) -> dict:
        desired = {
            "name": team["team_name"],
            "channel_number": number,
            "tvg_id": team["channel_id"],
            "channel_group_id": self._channel_group(dispatcharr, conn, team),
            "channel_profile_ids": self._channel_profiles(dispatcharr, conn, team),
            "stream_profile_id": dispatcharr.default_stream_profile_id,
        }
        logo_id = self._logo_id(conn, team)
        if logo_id is not None:
            desired["logo_id"] = logo_id
        current = {
            "name": remote.name,
            "channel_number": self._number(remote.channel_number),
            "tvg_id": remote.tvg_id,
            "channel_group_id": remote.channel_group_id,
            "channel_profile_ids": (
                list(remote.channel_profile_ids)
                if remote.channel_profile_ids is not None
                else None
            ),
            "stream_profile_id": remote.stream_profile_id,
            "logo_id": remote.logo_id,
        }
        return {key: value for key, value in desired.items() if current[key] != value}

    def _logo_id(self, conn, team) -> int | None:
        if not self._logos or not team.get("template_id"):
            return None
        from teamarr.database.templates import get_template
        from teamarr.templates.resolver import TemplateResolver

        template = get_template(conn, team["template_id"])
        url = template.team_channel_logo_url if template else None
        if not url:
            return None
        url = TemplateResolver(get_epg_settings(conn).art_base_url).resolve_with_map(
            url,
            {"league_id": team["primary_league"], "team_name": team["team_name"]},
        )
        uploaded = self._logos.upload(
            name=f'{team["team_name"]} Logo',
            url=apply_art_base_url(url, get_epg_settings(conn).art_base_url),
        )
        return uploaded.logo.get("id") if uploaded.success and uploaded.logo else None

    @staticmethod
    def _record_error(conn, team, message: str) -> None:
        # Until Dispatcharr accepts a create, there is no Teamarr ownership record.
        if not team.get("dispatcharr_channel_id"):
            return
        upsert_managed_team_channel(
            conn,
            team_id=team["id"],
            dispatcharr_channel_id=team.get("dispatcharr_channel_id"),
            dispatcharr_uuid=team.get("dispatcharr_uuid"),
            channel_number=(
                team.get("allocated_channel_number") or team.get("managed_channel_number") or 0
            ),
            sync_status="error",
            sync_message=message,
        )
