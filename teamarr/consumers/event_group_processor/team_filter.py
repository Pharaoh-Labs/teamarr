"""Team include/exclude filtering for event-group processing."""

import logging
from sqlite3 import Connection
from typing import TYPE_CHECKING, Any

from teamarr.consumers.channel_lifecycle import create_lifecycle_service
from teamarr.core import SEASON_POSTSEASON, Event
from teamarr.database.groups import EventEPGGroup

logger = logging.getLogger(__name__)


class TeamFiltering:
    """Applies team include/exclude filters and cleans up filtered channels.

    Mixin for EventGroupProcessor — relies on the coordinator's
    ``_db_factory``, ``_dispatcharr_client`` and ``_service`` attributes.
    """

    if TYPE_CHECKING:
        # Provided by the EventGroupProcessor coordinator / sibling mixins.
        # Declared for type-checkers only — no runtime effect.
        _db_factory: Any
        _dispatcharr_client: Any
        _service: Any

    def _filter_by_teams(
        self,
        matched_streams: list[dict],
        group: EventEPGGroup,
        conn,
    ) -> tuple[list[dict], int]:
        """Filter matched streams by team include/exclude configuration.

        Uses canonical team selection (provider, team_id) for unambiguous matching.

        When bypass_filter_for_playoffs is enabled, playoff games (season_type='postseason')
        bypass the team filter entirely.

        Args:
            matched_streams: List of {'stream': ..., 'event': ...} dicts
            group: The event group being processed
            conn: Database connection for parent lookup

        Returns:
            Tuple of (filtered_streams, filtered_count)
        """
        # Get effective team filter (from group or parent)
        include_teams, exclude_teams, mode, bypass_playoffs = self._get_effective_team_filter(
            group, conn
        )

        # No filter configured
        if not include_teams and not exclude_teams:
            return matched_streams, 0

        filter_list = include_teams if include_teams else exclude_teams
        # The empty-filter guard above guarantees one of the two lists is truthy,
        # so filter_list is always a non-None list here.
        assert filter_list is not None
        filtered = []
        filtered_count = 0
        playoff_bypass_count = 0

        # Extract leagues that have teams in the filter
        # Only filter events from leagues with explicit selections
        filter_leagues = {f.get("league") for f in filter_list if f.get("league")}

        for match in matched_streams:
            event = match.get("event")
            if not event:
                # No event - can't filter by team, keep it
                filtered.append(match)
                continue

            # Bypass filter for playoff games if setting is enabled
            if bypass_playoffs and event.season_type == SEASON_POSTSEASON:
                filtered.append(match)
                playoff_bypass_count += 1
                continue

            # Get event's league
            event_league = event.league if event else None

            # If no teams from this league are in the filter, pass through unfiltered
            if event_league and event_league not in filter_leagues:
                filtered.append(match)
                continue

            # Check if either team matches filter
            home_match = self._team_matches_filter(event.home_team, filter_list)
            away_match = self._team_matches_filter(event.away_team, filter_list)
            team_in_filter = home_match or away_match

            if mode == "include":
                # Include mode: keep if team IS in list
                if team_in_filter:
                    filtered.append(match)
                else:
                    filtered_count += 1
                    logger.debug(
                        f"Team filter excluded: {event.name} - "
                        f"neither {event.home_team.name if event.home_team else 'N/A'} "
                        f"nor {event.away_team.name if event.away_team else 'N/A'} in include list"
                    )
            else:
                # Exclude mode: keep if team is NOT in list
                if not team_in_filter:
                    filtered.append(match)
                else:
                    filtered_count += 1
                    logger.debug(f"Team filter excluded: {event.name} - team in exclude list")

        if playoff_bypass_count > 0:
            logger.info(
                "Playoff bypass: %d playoff game(s) included despite team filter",
                playoff_bypass_count,
            )

        if filtered_count > 0:
            logger.info(
                "[EVENT_EPG] Team filter: %d streams excluded, %d remaining",
                filtered_count,
                len(filtered),
            )

        return filtered, filtered_count

    def _get_effective_team_filter(
        self,
        group: EventEPGGroup,
        conn,
    ) -> tuple[list[dict] | None, list[dict] | None, str, bool]:
        """Get team filter with settings fallback.

        Priority chain:
        1. Master toggle off (settings.enabled=False) → no filtering, no playoff bypass
        2. Group's own filter (if configured)
        3. Global settings default (if configured)
        4. No filtering (default)

        Returns:
            Tuple of (include_teams, exclude_teams, mode, bypass_filter_for_playoffs)
        """
        from teamarr.database.settings import get_team_filter_settings

        settings = get_team_filter_settings(conn)

        # Master toggle: when disabled, skip filtering entirely (group filters
        # included). Playoff bypass is moot when nothing is being filtered.
        if not settings.enabled:
            return None, None, "include", False

        # Determine bypass_filter_for_playoffs (group override -> global default)
        bypass_playoffs = group.bypass_filter_for_playoffs
        if bypass_playoffs is None:
            bypass_playoffs = settings.bypass_filter_for_playoffs

        # If group has its own filter, use it
        if group.include_teams or group.exclude_teams:
            return (
                group.include_teams,
                group.exclude_teams,
                group.team_filter_mode,
                bypass_playoffs,
            )

        # Fall back to global settings default
        if settings.include_teams or settings.exclude_teams:
            return (
                settings.include_teams,
                settings.exclude_teams,
                settings.mode,
                bypass_playoffs,
            )

        return None, None, "include", bypass_playoffs

    def _team_matches_filter(
        self,
        team,
        filter_teams: list[dict],
    ) -> bool:
        """Check if a team matches any entry in the filter list.

        Matches on provider + team_id. League is optional (some teams
        play in multiple leagues).

        Args:
            team: Team object from event
            filter_teams: List of filter entries with provider, team_id, league

        Returns:
            True if team matches any filter entry
        """
        if not team or not filter_teams:
            return False

        for f in filter_teams:
            if f.get("provider") == team.provider and f.get("team_id") == team.id:
                # League check is optional
                filter_league = f.get("league")
                if filter_league:
                    if filter_league == team.league:
                        return True
                else:
                    return True
        return False

    def _cleanup_team_filtered_channels(
        self,
        group: EventEPGGroup,
        conn: Connection,
        all_matched_events: dict[str, Event],
        passed_event_ids: set[str],
    ) -> int:
        """Delete existing channels that don't pass team filter.

        When teams are added to exclude list (or removed from include list),
        existing channels for those teams should be deleted.

        This handles both include and exclude modes:
        - Include mode: channels for teams NOT in include list are deleted
        - Exclude mode: channels for teams IN exclude list are deleted

        Works for both global and per-group team filters.

        Args:
            group: The event group
            conn: Database connection
            all_matched_events: Dict of event_id -> Event for all matched events
                               (before team filtering was applied)
            passed_event_ids: Set of event IDs that passed the team filter

        Returns:
            Number of channels deleted
        """
        from teamarr.database.channels import get_managed_channels_for_group

        # Get effective team filter (group -> parent -> global)
        include_teams, exclude_teams, mode, _bypass = self._get_effective_team_filter(group, conn)

        if not include_teams and not exclude_teams:
            return 0  # No filter configured

        # Get all existing channels for this group
        channels = get_managed_channels_for_group(conn, group.id)

        deleted_count = 0
        for channel in channels:
            event_id = channel.event_id

            # Only process channels whose events were matched in this run
            # (meaning the event is for today's date and we have the team info)
            if event_id not in all_matched_events:
                continue

            # If the event passed the filter, keep the channel
            if event_id in passed_event_ids:
                continue

            # Event was matched but didn't pass filter - delete the channel
            success = self._delete_channel_for_team_filter(conn, channel, reason="team_filter")
            if success:
                deleted_count += 1
                logger.info(
                    "[EVENT_EPG] Deleted channel '%s' (event_id=%s) - team excluded by filter",
                    channel.channel_name,
                    event_id,
                )

        return deleted_count

    def _delete_channel_for_team_filter(
        self,
        conn: Connection,
        channel,
        reason: str,
    ) -> bool:
        """Delete a managed channel due to team filter.

        Args:
            conn: Database connection
            channel: ManagedChannel to delete
            reason: Deletion reason

        Returns:
            True if deleted successfully
        """
        from teamarr.database.channels import (
            log_channel_history,
            mark_channel_deleted,
        )

        try:
            # Soft delete in our database
            mark_channel_deleted(conn, channel.id, reason=reason)

            # Log the history
            log_channel_history(
                conn=conn,
                managed_channel_id=channel.id,
                change_type="deleted",
                change_source="team_filter",
                notes=f"Channel deleted: {reason}",
            )

            # Delete from Dispatcharr if connected
            if self._dispatcharr_client and channel.dispatcharr_channel_id:
                try:
                    lifecycle_service = create_lifecycle_service(
                        self._db_factory,
                        self._service,
                        self._dispatcharr_client,
                    )
                    if lifecycle_service._channel_manager:
                        lifecycle_service._channel_manager.delete_channel(
                            channel.dispatcharr_channel_id
                        )
                except Exception as e:
                    logger.warning(
                        "[EVENT_EPG] Failed to delete channel %d from Dispatcharr: %s",
                        channel.dispatcharr_channel_id,
                        e,
                    )

            return True
        except Exception as e:
            logger.error(
                "[EVENT_EPG] Failed to delete channel %d for team filter: %s",
                channel.id,
                e,
            )
            return False
