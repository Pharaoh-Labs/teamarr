"""Database operations for event EPG groups.

Provides CRUD operations for the event_epg_groups table.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from sqlite3 import Connection
from typing import Any

logger = logging.getLogger(__name__)


class _UpdateBuilder:
    """Accumulate UPDATE assignments for partial-update SQL.

    Pattern: each field is either set (value provided) or cleared (clear flag),
    or skipped (None and no clear). Centralizes the boilerplate so update_group
    reads as a list of declarative field bindings rather than 30 if/elif blocks.
    """

    def __init__(self) -> None:
        self._sets: list[str] = []
        self._values: list[Any] = []

    def set_(
        self,
        column: str,
        value: Any,
        *,
        clear: bool = False,
        encoder: Callable[[Any], Any] = lambda v: v,
    ) -> None:
        if value is not None:
            self._sets.append(f"{column} = ?")
            self._values.append(encoder(value))
        elif clear:
            self._sets.append(f"{column} = NULL")

    def set_list_or_clear(self, column: str, value: list | None, *, clear: bool = False) -> None:
        """Set a JSON-encoded list, treating empty list as 'clear to NULL'."""
        if value is not None:
            if value:
                self._sets.append(f"{column} = ?")
                self._values.append(json.dumps(value))
            else:
                self._sets.append(f"{column} = NULL")
        elif clear:
            self._sets.append(f"{column} = NULL")

    def has_changes(self) -> bool:
        return bool(self._sets)

    def build_query(self, table: str, *, where: str = "id = ?") -> str:
        return f"UPDATE {table} SET {', '.join(self._sets)} WHERE {where}"

    def params(self, *where_values: Any) -> list[Any]:
        return [*self._values, *where_values]


@dataclass
class EventEPGGroup:
    """Event EPG group configuration."""

    id: int
    name: str
    display_name: str | None = None  # Optional display name override for UI
    leagues: list[str] = field(default_factory=list)
    soccer_mode: str | None = None  # NULL (non-soccer), 'all', 'teams', 'manual'
    soccer_followed_teams: list[dict] | None = None  # [{provider, team_id, name}] for teams mode
    group_mode: str = "single"  # "single" or "multi" - persisted to preserve user intent
    template_id: int | None = None
    channel_start_number: int | None = None
    stream_timezone: str | None = None  # Timezone for stream datetime parsing
    duplicate_event_handling: str = "consolidate"
    channel_assignment_mode: str = "auto"
    sort_order: int = 0
    total_stream_count: int = 0
    parent_group_id: int | None = None
    m3u_group_id: int | None = None
    m3u_group_name: str | None = None
    m3u_account_id: int | None = None
    m3u_account_name: str | None = None
    # Processing stats
    last_refresh: datetime | None = None
    stream_count: int = 0
    matched_count: int = 0  # Distinct streams matched (coverage)
    match_result_count: int = 0  # Total matched results produced (volume; EPG fans out)
    # Stream filtering (Phase 2)
    stream_include_regex: str | None = None
    stream_include_regex_enabled: bool = False
    stream_exclude_regex: str | None = None
    stream_exclude_regex_enabled: bool = False
    custom_regex_teams: str | None = None
    custom_regex_teams_enabled: bool = False
    custom_regex_date: str | None = None
    custom_regex_date_enabled: bool = False
    custom_regex_month: str | None = None
    custom_regex_month_enabled: bool = False
    custom_regex_day: str | None = None
    custom_regex_day_enabled: bool = False
    custom_regex_time: str | None = None
    custom_regex_time_enabled: bool = False
    custom_regex_league: str | None = None
    custom_regex_league_enabled: bool = False
    # EVENT_CARD specific regex (UFC, Boxing, MMA)
    custom_regex_fighters: str | None = None
    custom_regex_fighters_enabled: bool = False
    custom_regex_event_name: str | None = None
    custom_regex_event_name_enabled: bool = False
    skip_builtin_filter: bool = False
    # Team filtering (canonical team selection, inherited by children)
    include_teams: list[dict] | None = None
    exclude_teams: list[dict] | None = None
    team_filter_mode: str = "include"
    bypass_filter_for_playoffs: bool | None = None  # NULL=use default, True/False=override
    team_streams_enabled: bool = False
    epg_match_enabled: bool = False  # (183.6) opt this group into EPG program-data matching
    # (183.9) system group sourcing candidates from curated Dispatcharr channels
    is_channel_source: bool = False
    # Per-group subscription overrides (NULL = inherit global)
    subscription_leagues: list[str] | None = None
    subscription_soccer_mode: str | None = None
    subscription_soccer_followed_teams: list[dict] | None = None
    # Processing stats by category (FILTERED / FAILED / EXCLUDED)
    filtered_stale: int = 0  # FILTERED: Stream marked as stale in Dispatcharr
    filtered_include_regex: int = 0  # FILTERED: Didn't match include regex
    filtered_exclude_regex: int = 0  # FILTERED: Matched exclude regex
    filtered_not_event: int = 0  # FILTERED: Stream doesn't look like event (placeholder)
    filtered_team: int = 0  # FILTERED: Team not in include/exclude filter
    failed_count: int = 0  # FAILED: Match attempted but couldn't find event
    streams_excluded: int = 0  # EXCLUDED: Matched but excluded (aggregate)
    # EXCLUDED breakdown by reason
    excluded_event_final: int = 0
    excluded_event_past: int = 0
    excluded_before_window: int = 0
    excluded_league_not_included: int = 0
    # Multi-sport enhancements (Phase 3)
    channel_sort_order: str = "time"
    overlap_handling: str = "add_stream"
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _row_to_group(row) -> EventEPGGroup:
    """Convert a database row to EventEPGGroup."""
    leagues = json.loads(row["leagues"]) if row["leagues"] else []

    created_at = None
    if row["created_at"]:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            pass

    updated_at = None
    if row["updated_at"]:
        try:
            updated_at = datetime.fromisoformat(row["updated_at"])
        except (ValueError, TypeError):
            pass

    last_refresh = None
    if row["last_refresh"]:
        try:
            last_refresh = datetime.fromisoformat(row["last_refresh"])
        except (ValueError, TypeError):
            pass

    return EventEPGGroup(
        id=row["id"],
        name=row["name"],
        display_name=row["display_name"] if "display_name" in row.keys() else None,
        leagues=leagues,
        soccer_mode=row["soccer_mode"] if "soccer_mode" in row.keys() else None,
        soccer_followed_teams=json.loads(row["soccer_followed_teams"])
        if "soccer_followed_teams" in row.keys() and row["soccer_followed_teams"]
        else None,
        group_mode=row["group_mode"] if "group_mode" in row.keys() else "single",
        template_id=row["template_id"],
        channel_start_number=row["channel_start_number"],
        stream_timezone=row["stream_timezone"] if "stream_timezone" in row.keys() else None,
        duplicate_event_handling=row["duplicate_event_handling"] or "consolidate",
        channel_assignment_mode=row["channel_assignment_mode"] or "auto",
        sort_order=row["sort_order"] or 0,
        total_stream_count=row["total_stream_count"] or 0,
        parent_group_id=row["parent_group_id"],
        m3u_group_id=row["m3u_group_id"],
        m3u_group_name=row["m3u_group_name"],
        m3u_account_id=row["m3u_account_id"],
        m3u_account_name=row["m3u_account_name"],
        last_refresh=last_refresh,
        stream_count=row["stream_count"] or 0,
        matched_count=row["matched_count"] or 0,
        match_result_count=row["match_result_count"] if "match_result_count" in row.keys() else 0,
        # Stream filtering
        stream_include_regex=row["stream_include_regex"],
        stream_include_regex_enabled=bool(row["stream_include_regex_enabled"]),
        stream_exclude_regex=row["stream_exclude_regex"],
        stream_exclude_regex_enabled=bool(row["stream_exclude_regex_enabled"]),
        custom_regex_teams=row["custom_regex_teams"],
        custom_regex_teams_enabled=bool(row["custom_regex_teams_enabled"]),
        custom_regex_date=row["custom_regex_date"] if "custom_regex_date" in row.keys() else None,
        custom_regex_date_enabled=bool(row["custom_regex_date_enabled"])
        if "custom_regex_date_enabled" in row.keys()
        else False,
        custom_regex_month=(
            row["custom_regex_month"] if "custom_regex_month" in row.keys() else None
        ),
        custom_regex_month_enabled=bool(row["custom_regex_month_enabled"])
        if "custom_regex_month_enabled" in row.keys()
        else False,
        custom_regex_day=row["custom_regex_day"] if "custom_regex_day" in row.keys() else None,
        custom_regex_day_enabled=bool(row["custom_regex_day_enabled"])
        if "custom_regex_day_enabled" in row.keys()
        else False,
        custom_regex_time=row["custom_regex_time"] if "custom_regex_time" in row.keys() else None,
        custom_regex_time_enabled=bool(row["custom_regex_time_enabled"])
        if "custom_regex_time_enabled" in row.keys()
        else False,
        custom_regex_league=row["custom_regex_league"]
        if "custom_regex_league" in row.keys()
        else None,
        custom_regex_league_enabled=bool(row["custom_regex_league_enabled"])
        if "custom_regex_league_enabled" in row.keys()
        else False,
        # EVENT_CARD specific regex
        custom_regex_fighters=row["custom_regex_fighters"]
        if "custom_regex_fighters" in row.keys()
        else None,
        custom_regex_fighters_enabled=bool(row["custom_regex_fighters_enabled"])
        if "custom_regex_fighters_enabled" in row.keys()
        else False,
        custom_regex_event_name=row["custom_regex_event_name"]
        if "custom_regex_event_name" in row.keys()
        else None,
        custom_regex_event_name_enabled=bool(row["custom_regex_event_name_enabled"])
        if "custom_regex_event_name_enabled" in row.keys()
        else False,
        skip_builtin_filter=bool(row["skip_builtin_filter"]),
        # Team filtering
        include_teams=json.loads(row["include_teams"]) if row["include_teams"] else None,
        exclude_teams=json.loads(row["exclude_teams"]) if row["exclude_teams"] else None,
        team_filter_mode=row["team_filter_mode"] if "team_filter_mode" in row.keys() else "include",
        bypass_filter_for_playoffs=(
            bool(row["bypass_filter_for_playoffs"])
            if "bypass_filter_for_playoffs" in row.keys()
            and row["bypass_filter_for_playoffs"] is not None
            else None
        ),
        team_streams_enabled=(
            bool(row["team_streams_enabled"]) if "team_streams_enabled" in row.keys() else False
        ),
        epg_match_enabled=(
            bool(row["epg_match_enabled"]) if "epg_match_enabled" in row.keys() else False
        ),
        is_channel_source=(
            bool(row["is_channel_source"]) if "is_channel_source" in row.keys() else False
        ),
        # Per-group subscription overrides
        subscription_leagues=(
            json.loads(row["subscription_leagues"])
            if "subscription_leagues" in row.keys() and row["subscription_leagues"]
            else None
        ),
        subscription_soccer_mode=(
            row["subscription_soccer_mode"]
            if "subscription_soccer_mode" in row.keys()
            else None
        ),
        subscription_soccer_followed_teams=(
            json.loads(row["subscription_soccer_followed_teams"])
            if "subscription_soccer_followed_teams" in row.keys()
            and row["subscription_soccer_followed_teams"]
            else None
        ),
        # Processing stats by category (FILTERED / FAILED / EXCLUDED)
        filtered_stale=row["filtered_stale"] if "filtered_stale" in row.keys() else 0,
        filtered_include_regex=row["filtered_include_regex"] or 0,
        filtered_exclude_regex=row["filtered_exclude_regex"] or 0,
        filtered_not_event=row["filtered_not_event"] if "filtered_not_event" in row.keys() else 0,
        filtered_team=row["filtered_team"] if "filtered_team" in row.keys() else 0,
        # Handle both old (filtered_no_match) and new (failed_count) column names
        failed_count=(
            row["failed_count"]
            if "failed_count" in row.keys()
            else (row["filtered_no_match"] if "filtered_no_match" in row.keys() else 0)
        )
        or 0,
        streams_excluded=row["streams_excluded"] if "streams_excluded" in row.keys() else 0,
        # EXCLUDED breakdown by reason
        excluded_event_final=row["excluded_event_final"]
        if "excluded_event_final" in row.keys()
        else 0,
        excluded_event_past=row["excluded_event_past"]
        if "excluded_event_past" in row.keys()
        else 0,
        excluded_before_window=row["excluded_before_window"]
        if "excluded_before_window" in row.keys()
        else 0,
        excluded_league_not_included=row["excluded_league_not_included"]
        if "excluded_league_not_included" in row.keys()
        else 0,
        # Multi-sport enhancements
        channel_sort_order=row["channel_sort_order"] or "time",
        overlap_handling=row["overlap_handling"] or "add_stream",
        enabled=bool(row["enabled"]),
        created_at=created_at,
        updated_at=updated_at,
    )


# =============================================================================
# READ OPERATIONS
# =============================================================================


def get_all_groups(
    conn: Connection,
    include_disabled: bool = False,
    exclude_channel_source: bool = False,
) -> list[EventEPGGroup]:
    """Get all event EPG groups.

    Args:
        conn: Database connection
        include_disabled: Include disabled groups
        exclude_channel_source: Omit the system-managed channel-source group (183.9)
            from the result. The UI list uses this so the auto-managed source does
            not appear as a user-editable Event Group; processing leaves it False.

    Returns:
        List of EventEPGGroup objects
    """
    clauses = []
    if not include_disabled:
        clauses.append("enabled = 1")
    if exclude_channel_source:
        clauses.append("COALESCE(is_channel_source, 0) = 0")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cursor = conn.execute(
        f"SELECT * FROM event_epg_groups {where} ORDER BY sort_order, name"
    )

    return [_row_to_group(row) for row in cursor.fetchall()]


def ensure_channel_source_group(conn: Connection, enabled: bool) -> int:
    """Idempotently create/sync the system-managed "Dispatcharr Channels" source group.

    Epic 183.9: when the global ``epg_channel_source_enabled`` setting is on, EPG
    matching also runs over streams curated onto Dispatcharr channels. That source
    is modeled as a real (but hidden) event group so it reuses the full per-group
    pipeline — matching, channel creation, XMLTV, and stats — with no FK hazards.

    The group's ``enabled`` flag mirrors the setting, so disabling the toggle lets
    the normal disabled-group cleanup remove its channels on the next run. Returns
    the group id.
    """
    row = conn.execute(
        "SELECT id FROM event_epg_groups WHERE is_channel_source = 1 LIMIT 1"
    ).fetchone()

    if row:
        group_id = row["id"]
        conn.execute(
            "UPDATE event_epg_groups SET enabled = ?, epg_match_enabled = 1, "
            "skip_builtin_filter = 1, team_streams_enabled = 1 WHERE id = ?",
            (int(enabled), group_id),
        )
        conn.commit()
        return group_id

    group_id = create_group(
        conn,
        name="Dispatcharr Channels",
        display_name="Dispatcharr Channels (EPG source)",
        leagues=[],
        duplicate_event_handling="consolidate",
        epg_match_enabled=True,
        team_streams_enabled=True,
        skip_builtin_filter=True,
        is_channel_source=True,
        enabled=enabled,
    )
    conn.commit()
    return group_id


def get_group(conn: Connection, group_id: int) -> EventEPGGroup | None:
    """Get a single event EPG group by ID.

    Args:
        conn: Database connection
        group_id: Group ID

    Returns:
        EventEPGGroup or None if not found
    """
    cursor = conn.execute("SELECT * FROM event_epg_groups WHERE id = ?", (group_id,))
    row = cursor.fetchone()
    return _row_to_group(row) if row else None


def get_group_by_name(
    conn: Connection, name: str, m3u_account_id: int | None = None
) -> EventEPGGroup | None:
    """Get a single event EPG group by name (optionally scoped to account).

    Args:
        conn: Database connection
        name: Group name
        m3u_account_id: If provided, checks for name within this account only

    Returns:
        EventEPGGroup or None if not found
    """
    if m3u_account_id is not None:
        cursor = conn.execute(
            "SELECT * FROM event_epg_groups WHERE name = ? AND m3u_account_id = ?",
            (name, m3u_account_id),
        )
    else:
        cursor = conn.execute("SELECT * FROM event_epg_groups WHERE name = ?", (name,))
    row = cursor.fetchone()
    return _row_to_group(row) if row else None


def get_groups_for_league(conn: Connection, league: str) -> list[EventEPGGroup]:
    """Get all enabled groups that include a specific league.

    Args:
        conn: Database connection
        league: League code to search for

    Returns:
        List of EventEPGGroup objects that include the league
    """
    cursor = conn.execute(
        "SELECT * FROM event_epg_groups WHERE enabled = 1 ORDER BY sort_order, name"
    )

    groups = []
    for row in cursor.fetchall():
        leagues = json.loads(row["leagues"]) if row["leagues"] else []
        if league in leagues:
            groups.append(_row_to_group(row))

    return groups


def get_enabled_soccer_leagues(conn: Connection) -> list[str]:
    """Get all enabled soccer league codes.

    Used by soccer_mode='all' to dynamically include all soccer leagues.

    Args:
        conn: Database connection

    Returns:
        List of enabled soccer league codes (e.g., ['eng.1', 'esp.1', 'uefa.champions'])
    """
    cursor = conn.execute(
        "SELECT league_code FROM leagues WHERE sport = 'soccer' AND enabled = 1"
    )
    return [row["league_code"] for row in cursor.fetchall()]


# =============================================================================
# CREATE OPERATIONS
# =============================================================================


def create_group(
    conn: Connection,
    name: str,
    leagues: list[str],
    display_name: str | None = None,
    soccer_mode: str | None = None,
    soccer_followed_teams: list[dict] | None = None,
    channel_start_number: int | None = None,
    stream_timezone: str | None = None,
    duplicate_event_handling: str = "consolidate",
    channel_assignment_mode: str = "auto",
    sort_order: int = 0,
    total_stream_count: int = 0,
    m3u_group_id: int | None = None,
    m3u_group_name: str | None = None,
    m3u_account_id: int | None = None,
    m3u_account_name: str | None = None,
    # Stream filtering
    stream_include_regex: str | None = None,
    stream_include_regex_enabled: bool = False,
    stream_exclude_regex: str | None = None,
    stream_exclude_regex_enabled: bool = False,
    custom_regex_teams: str | None = None,
    custom_regex_teams_enabled: bool = False,
    custom_regex_date: str | None = None,
    custom_regex_date_enabled: bool = False,
    custom_regex_month: str | None = None,
    custom_regex_month_enabled: bool = False,
    custom_regex_day: str | None = None,
    custom_regex_day_enabled: bool = False,
    custom_regex_time: str | None = None,
    custom_regex_time_enabled: bool = False,
    custom_regex_league: str | None = None,
    custom_regex_league_enabled: bool = False,
    # EVENT_CARD specific regex
    custom_regex_fighters: str | None = None,
    custom_regex_fighters_enabled: bool = False,
    custom_regex_event_name: str | None = None,
    custom_regex_event_name_enabled: bool = False,
    skip_builtin_filter: bool = False,
    team_streams_enabled: bool = False,
    epg_match_enabled: bool = False,
    is_channel_source: bool = False,
    # Team filtering
    include_teams: list[dict] | None = None,
    exclude_teams: list[dict] | None = None,
    team_filter_mode: str = "include",
    # Multi-sport enhancements (Phase 3)
    channel_sort_order: str = "time",
    overlap_handling: str = "add_stream",
    enabled: bool = True,
    # Per-group subscription overrides (NULL = inherit global)
    subscription_leagues: list[str] | None = None,
    subscription_soccer_mode: str | None = None,
    subscription_soccer_followed_teams: list[dict] | None = None,
) -> int:
    """Create a new event EPG group.

    Args:
        conn: Database connection
        name: Unique group name
        leagues: List of league codes to scan
        channel_start_number: Starting channel number (for MANUAL mode)
        duplicate_event_handling: How to handle duplicate events
        channel_assignment_mode: 'auto' or 'manual'
        sort_order: Ordering for AUTO channel allocation
        total_stream_count: Expected streams for range reservation
        m3u_group_id: M3U group ID to scan
        m3u_group_name: M3U group name
        m3u_account_id: M3U account ID
        m3u_account_name: M3U account name for display
        enabled: Whether group is enabled

    Returns:
        New group ID
    """
    # Auto-calculate sort_order for AUTO mode groups
    if channel_assignment_mode == "auto" and sort_order == 0:
        max_order = conn.execute(
            """SELECT COALESCE(MAX(sort_order), -1) + 1
               FROM event_epg_groups
               WHERE channel_assignment_mode = 'auto'"""
        ).fetchone()[0]
        sort_order = max_order

    cursor = conn.execute(
        """INSERT INTO event_epg_groups (
            name, display_name, leagues, soccer_mode, soccer_followed_teams,
            group_mode, channel_start_number,
            stream_timezone, duplicate_event_handling,
            channel_assignment_mode, sort_order, total_stream_count,
            m3u_group_id, m3u_group_name, m3u_account_id, m3u_account_name,
            stream_include_regex, stream_include_regex_enabled,
            stream_exclude_regex, stream_exclude_regex_enabled,
            custom_regex_teams, custom_regex_teams_enabled,
            custom_regex_date, custom_regex_date_enabled,
            custom_regex_month, custom_regex_month_enabled,
            custom_regex_day, custom_regex_day_enabled,
            custom_regex_time, custom_regex_time_enabled,
            custom_regex_league, custom_regex_league_enabled,
            custom_regex_fighters, custom_regex_fighters_enabled,
            custom_regex_event_name, custom_regex_event_name_enabled,
            skip_builtin_filter, team_streams_enabled, epg_match_enabled, is_channel_source,
            include_teams, exclude_teams, team_filter_mode,
            channel_sort_order, overlap_handling, enabled,
            subscription_leagues, subscription_soccer_mode, subscription_soccer_followed_teams
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",  # noqa: E501
        (
            name,
            display_name,
            json.dumps(leagues),
            soccer_mode,
            json.dumps(soccer_followed_teams) if soccer_followed_teams else None,
            "multi",  # Hardcoded — hierarchy removed in v58
            channel_start_number,
            stream_timezone,
            duplicate_event_handling,
            channel_assignment_mode,
            sort_order,
            total_stream_count,
            m3u_group_id,
            m3u_group_name,
            m3u_account_id,
            m3u_account_name,
            stream_include_regex,
            int(stream_include_regex_enabled),
            stream_exclude_regex,
            int(stream_exclude_regex_enabled),
            custom_regex_teams,
            int(custom_regex_teams_enabled),
            custom_regex_date,
            int(custom_regex_date_enabled),
            custom_regex_month,
            int(custom_regex_month_enabled),
            custom_regex_day,
            int(custom_regex_day_enabled),
            custom_regex_time,
            int(custom_regex_time_enabled),
            custom_regex_league,
            int(custom_regex_league_enabled),
            custom_regex_fighters,
            int(custom_regex_fighters_enabled),
            custom_regex_event_name,
            int(custom_regex_event_name_enabled),
            int(skip_builtin_filter),
            int(team_streams_enabled),
            int(epg_match_enabled),
            int(is_channel_source),
            json.dumps(include_teams) if include_teams else None,
            json.dumps(exclude_teams) if exclude_teams else None,
            team_filter_mode,
            channel_sort_order,
            overlap_handling,
            int(enabled),
            json.dumps(subscription_leagues) if subscription_leagues else None,
            subscription_soccer_mode,
            json.dumps(subscription_soccer_followed_teams)
            if subscription_soccer_followed_teams else None,
        ),
    )
    group_id = cursor.lastrowid
    logger.info("[CREATED] Event group id=%d name=%s", group_id, name)
    return group_id


# =============================================================================
# UPDATE OPERATIONS
# =============================================================================


def update_group(
    conn: Connection,
    group_id: int,
    name: str | None = None,
    display_name: str | None = None,
    leagues: list[str] | None = None,
    soccer_mode: str | None = None,
    soccer_followed_teams: list[dict] | None = None,
    channel_start_number: int | None = None,
    stream_timezone: str | None = None,
    duplicate_event_handling: str | None = None,
    channel_assignment_mode: str | None = None,
    sort_order: int | None = None,
    total_stream_count: int | None = None,
    m3u_group_id: int | None = None,
    m3u_group_name: str | None = None,
    m3u_account_id: int | None = None,
    m3u_account_name: str | None = None,
    # Stream filtering
    stream_include_regex: str | None = None,
    stream_include_regex_enabled: bool | None = None,
    stream_exclude_regex: str | None = None,
    stream_exclude_regex_enabled: bool | None = None,
    custom_regex_teams: str | None = None,
    custom_regex_teams_enabled: bool | None = None,
    custom_regex_date: str | None = None,
    custom_regex_date_enabled: bool | None = None,
    custom_regex_month: str | None = None,
    custom_regex_month_enabled: bool | None = None,
    custom_regex_day: str | None = None,
    custom_regex_day_enabled: bool | None = None,
    custom_regex_time: str | None = None,
    custom_regex_time_enabled: bool | None = None,
    custom_regex_league: str | None = None,
    custom_regex_league_enabled: bool | None = None,
    # EVENT_CARD specific regex
    custom_regex_fighters: str | None = None,
    custom_regex_fighters_enabled: bool | None = None,
    custom_regex_event_name: str | None = None,
    custom_regex_event_name_enabled: bool | None = None,
    skip_builtin_filter: bool | None = None,
    team_streams_enabled: bool | None = None,
    epg_match_enabled: bool | None = None,
    # Team filtering
    include_teams: list[dict] | None = None,
    exclude_teams: list[dict] | None = None,
    team_filter_mode: str | None = None,
    bypass_filter_for_playoffs: bool | None = None,
    # Multi-sport enhancements (Phase 3)
    channel_sort_order: str | None = None,
    overlap_handling: str | None = None,
    enabled: bool | None = None,
    # Clear flags
    clear_display_name: bool = False,
    clear_channel_start_number: bool = False,
    clear_stream_timezone: bool = False,
    clear_m3u_group_id: bool = False,
    clear_m3u_group_name: bool = False,
    clear_m3u_account_id: bool = False,
    clear_m3u_account_name: bool = False,
    clear_stream_include_regex: bool = False,
    clear_stream_exclude_regex: bool = False,
    clear_custom_regex_teams: bool = False,
    clear_custom_regex_date: bool = False,
    clear_custom_regex_month: bool = False,
    clear_custom_regex_day: bool = False,
    clear_custom_regex_time: bool = False,
    clear_custom_regex_league: bool = False,
    clear_custom_regex_fighters: bool = False,
    clear_custom_regex_event_name: bool = False,
    clear_include_teams: bool = False,
    clear_exclude_teams: bool = False,
    clear_bypass_filter_for_playoffs: bool = False,
    clear_soccer_mode: bool = False,
    clear_soccer_followed_teams: bool = False,
    # Per-group subscription overrides (NULL = inherit global)
    subscription_leagues: list[str] | None = None,
    subscription_soccer_mode: str | None = None,
    subscription_soccer_followed_teams: list[dict] | None = None,
    clear_subscription_leagues: bool = False,
    clear_subscription_soccer_mode: bool = False,
    clear_subscription_soccer_followed_teams: bool = False,
) -> bool:
    """Update an event EPG group.

    Only updates fields that are explicitly provided (not None).
    Use clear_* flags to explicitly set fields to NULL.

    Args:
        conn: Database connection
        group_id: Group ID to update
        ... (field parameters)
        clear_*: Set corresponding field to NULL

    Returns:
        True if updated
    """
    builder = _UpdateBuilder()

    # Identity / basics
    builder.set_("name", name)
    builder.set_("display_name", display_name, clear=clear_display_name)
    builder.set_("leagues", leagues, encoder=json.dumps)
    builder.set_("soccer_mode", soccer_mode, clear=clear_soccer_mode)
    builder.set_(
        "soccer_followed_teams",
        soccer_followed_teams,
        clear=clear_soccer_followed_teams,
        encoder=json.dumps,
    )
    builder.set_("channel_start_number", channel_start_number, clear=clear_channel_start_number)
    builder.set_("stream_timezone", stream_timezone, clear=clear_stream_timezone)
    builder.set_("duplicate_event_handling", duplicate_event_handling)
    builder.set_("channel_assignment_mode", channel_assignment_mode)
    builder.set_("sort_order", sort_order)
    builder.set_("total_stream_count", total_stream_count)

    # M3U binding
    builder.set_("m3u_group_id", m3u_group_id, clear=clear_m3u_group_id)
    builder.set_("m3u_group_name", m3u_group_name, clear=clear_m3u_group_name)
    builder.set_("m3u_account_id", m3u_account_id, clear=clear_m3u_account_id)
    builder.set_("m3u_account_name", m3u_account_name, clear=clear_m3u_account_name)

    # Stream filtering
    builder.set_("stream_include_regex", stream_include_regex, clear=clear_stream_include_regex)
    builder.set_("stream_include_regex_enabled", stream_include_regex_enabled, encoder=int)
    builder.set_("stream_exclude_regex", stream_exclude_regex, clear=clear_stream_exclude_regex)
    builder.set_("stream_exclude_regex_enabled", stream_exclude_regex_enabled, encoder=int)
    builder.set_("custom_regex_teams", custom_regex_teams, clear=clear_custom_regex_teams)
    builder.set_("custom_regex_teams_enabled", custom_regex_teams_enabled, encoder=int)
    builder.set_("custom_regex_date", custom_regex_date, clear=clear_custom_regex_date)
    builder.set_("custom_regex_date_enabled", custom_regex_date_enabled, encoder=int)
    builder.set_("custom_regex_month", custom_regex_month, clear=clear_custom_regex_month)
    builder.set_("custom_regex_month_enabled", custom_regex_month_enabled, encoder=int)
    builder.set_("custom_regex_day", custom_regex_day, clear=clear_custom_regex_day)
    builder.set_("custom_regex_day_enabled", custom_regex_day_enabled, encoder=int)
    builder.set_("custom_regex_time", custom_regex_time, clear=clear_custom_regex_time)
    builder.set_("custom_regex_time_enabled", custom_regex_time_enabled, encoder=int)
    builder.set_("custom_regex_league", custom_regex_league, clear=clear_custom_regex_league)
    builder.set_("custom_regex_league_enabled", custom_regex_league_enabled, encoder=int)
    builder.set_("custom_regex_fighters", custom_regex_fighters, clear=clear_custom_regex_fighters)
    builder.set_("custom_regex_fighters_enabled", custom_regex_fighters_enabled, encoder=int)
    builder.set_(
        "custom_regex_event_name", custom_regex_event_name, clear=clear_custom_regex_event_name
    )
    builder.set_("custom_regex_event_name_enabled", custom_regex_event_name_enabled, encoder=int)
    builder.set_("skip_builtin_filter", skip_builtin_filter, encoder=int)
    builder.set_("team_streams_enabled", team_streams_enabled, encoder=int)
    builder.set_("epg_match_enabled", epg_match_enabled, encoder=int)

    # Team filtering — empty list semantics: empty list also means "clear".
    builder.set_list_or_clear("include_teams", include_teams, clear=clear_include_teams)
    builder.set_list_or_clear("exclude_teams", exclude_teams, clear=clear_exclude_teams)
    builder.set_("team_filter_mode", team_filter_mode)
    builder.set_(
        "bypass_filter_for_playoffs",
        bypass_filter_for_playoffs,
        clear=clear_bypass_filter_for_playoffs,
        encoder=int,
    )

    # Multi-sport enhancements (Phase 3)
    builder.set_("channel_sort_order", channel_sort_order)
    builder.set_("overlap_handling", overlap_handling)
    builder.set_("enabled", enabled, encoder=int)

    # Per-group subscription overrides
    builder.set_(
        "subscription_leagues",
        subscription_leagues,
        clear=clear_subscription_leagues,
        encoder=json.dumps,
    )
    builder.set_(
        "subscription_soccer_mode",
        subscription_soccer_mode,
        clear=clear_subscription_soccer_mode,
    )
    builder.set_(
        "subscription_soccer_followed_teams",
        subscription_soccer_followed_teams,
        clear=clear_subscription_soccer_followed_teams,
        encoder=json.dumps,
    )

    if not builder.has_changes():
        return False

    cursor = conn.execute(builder.build_query("event_epg_groups"), builder.params(group_id))
    if cursor.rowcount > 0:
        logger.info("[UPDATED] Event group id=%d", group_id)
        return True
    return False


def set_group_enabled(conn: Connection, group_id: int, enabled: bool) -> bool:
    """Set group enabled status.

    Args:
        conn: Database connection
        group_id: Group ID
        enabled: New enabled status

    Returns:
        True if updated
    """
    cursor = conn.execute(
        "UPDATE event_epg_groups SET enabled = ? WHERE id = ?", (int(enabled), group_id)
    )
    if cursor.rowcount > 0:
        logger.info("[UPDATED] Event group id=%d enabled=%s", group_id, enabled)
        return True
    return False


def update_group_stats(
    conn: Connection,
    group_id: int,
    stream_count: int,
    matched_count: int,
    match_result_count: int = 0,
    filtered_stale: int = 0,
    filtered_include_regex: int = 0,
    filtered_exclude_regex: int = 0,
    filtered_not_event: int = 0,
    filtered_team: int = 0,
    failed_count: int = 0,
    streams_excluded: int = 0,
    total_stream_count: int | None = None,
    # EXCLUDED breakdown
    excluded_event_final: int = 0,
    excluded_event_past: int = 0,
    excluded_before_window: int = 0,
    excluded_league_not_included: int = 0,
) -> bool:
    """Update processing stats for a group after EPG generation.

    Stats are organized into three categories:
    - FILTERED: Pre-match filtering (stale, regex, not_event, team)
    - FAILED: Match attempted but couldn't find event
    - EXCLUDED: Matched but excluded (timing/config)

    Args:
        conn: Database connection
        group_id: Group ID
        stream_count: Number of streams after filtering (eligible for matching)
        matched_count: Distinct streams matched to ≥1 event (coverage numerator)
        match_result_count: Total matched results produced (volume; EPG fans out)
        filtered_stale: FILTERED - Stream marked as stale in Dispatcharr
        filtered_include_regex: FILTERED - Didn't match include regex
        filtered_exclude_regex: FILTERED - Matched exclude regex
        filtered_not_event: FILTERED - Stream doesn't look like event
        filtered_team: FILTERED - Team not in include/exclude list
        failed_count: FAILED - Match attempted but couldn't find event
        streams_excluded: EXCLUDED - Matched but excluded (aggregate)
        total_stream_count: Total streams fetched (before filtering)
        excluded_event_final: EXCLUDED - Event status is final
        excluded_event_past: EXCLUDED - Event already ended
        excluded_before_window: EXCLUDED - Too early to create channel
        excluded_league_not_included: EXCLUDED - League not in group

    Returns:
        True if updated
    """
    if total_stream_count is not None:
        cursor = conn.execute(
            """UPDATE event_epg_groups
               SET last_refresh = datetime('now'),
                   stream_count = ?,
                   matched_count = ?,
                   match_result_count = ?,
                   filtered_stale = ?,
                   filtered_include_regex = ?,
                   filtered_exclude_regex = ?,
                   filtered_not_event = ?,
                   filtered_team = ?,
                   failed_count = ?,
                   streams_excluded = ?,
                   excluded_event_final = ?,
                   excluded_event_past = ?,
                   excluded_before_window = ?,
                   excluded_league_not_included = ?,
                   total_stream_count = ?
               WHERE id = ?""",
            (
                stream_count,
                matched_count,
                match_result_count,
                filtered_stale,
                filtered_include_regex,
                filtered_exclude_regex,
                filtered_not_event,
                filtered_team,
                failed_count,
                streams_excluded,
                excluded_event_final,
                excluded_event_past,
                excluded_before_window,
                excluded_league_not_included,
                total_stream_count,
                group_id,
            ),
        )
    else:
        cursor = conn.execute(
            """UPDATE event_epg_groups
               SET last_refresh = datetime('now'),
                   stream_count = ?,
                   matched_count = ?,
                   match_result_count = ?,
                   filtered_stale = ?,
                   filtered_include_regex = ?,
                   filtered_exclude_regex = ?,
                   filtered_not_event = ?,
                   filtered_team = ?,
                   failed_count = ?,
                   streams_excluded = ?,
                   excluded_event_final = ?,
                   excluded_event_past = ?,
                   excluded_before_window = ?,
                   excluded_league_not_included = ?
               WHERE id = ?""",
            (
                stream_count,
                matched_count,
                match_result_count,
                filtered_stale,
                filtered_include_regex,
                filtered_exclude_regex,
                filtered_not_event,
                filtered_team,
                failed_count,
                streams_excluded,
                excluded_event_final,
                excluded_event_past,
                excluded_before_window,
                excluded_league_not_included,
                group_id,
            ),
        )
    return cursor.rowcount > 0


# =============================================================================
# STALE SOURCE TRACKING (lylt)
# =============================================================================


def mark_group_source_seen(conn: Connection, group_id: int) -> None:
    """Mark a group's M3U source as present (found in Dispatcharr this run).

    Refreshes source_last_seen and clears the stale flag.
    """
    conn.execute(
        """
        UPDATE event_epg_groups
        SET source_last_seen = datetime('now'), source_missing = 0
        WHERE id = ?
        """,
        (group_id,),
    )


def mark_group_source_missing(conn: Connection, group_id: int) -> None:
    """Mark a group's M3U source as missing (no longer exists in Dispatcharr)."""
    conn.execute(
        "UPDATE event_epg_groups SET source_missing = 1 WHERE id = ?",
        (group_id,),
    )


def get_stale_groups(conn: Connection) -> list[dict]:
    """Return enabled groups whose M3U source channel-group is gone (stale).

    See the stale-source detection note in schema.sql. Excludes the
    system channel-source group.
    """
    rows = conn.execute(
        """
        SELECT id, name, display_name, m3u_group_id, m3u_group_name,
               m3u_account_name, source_last_seen, total_stream_count
        FROM event_epg_groups
        WHERE enabled = 1 AND source_missing = 1 AND COALESCE(is_channel_source, 0) = 0
        ORDER BY name
        """
    ).fetchall()
    return [dict(row) for row in rows]


# =============================================================================
# DELETE OPERATIONS
# =============================================================================


def delete_group(conn: Connection, group_id: int) -> bool:
    """Delete an event EPG group.

    Note: This will cascade delete all managed_channels for this group.

    Args:
        conn: Database connection
        group_id: Group ID to delete

    Returns:
        True if deleted
    """
    cursor = conn.execute("DELETE FROM event_epg_groups WHERE id = ?", (group_id,))
    if cursor.rowcount > 0:
        logger.info("[DELETED] Event group id=%d", group_id)
        return True
    return False


# =============================================================================
# STATS / HELPERS
# =============================================================================


def reorder_groups(conn: Connection, items: list[tuple[int, int]]) -> int:
    """Reorder groups by updating sort_order.

    Args:
        conn: Database connection
        items: List of (sort_order, group_id) tuples

    Returns:
        Number of groups updated
    """
    updated = 0
    for sort_order, group_id in items:
        conn.execute(
            "UPDATE event_epg_groups SET sort_order = ? WHERE id = ?",
            (sort_order, group_id),
        )
        updated += 1
    conn.commit()
    return updated


def get_existing_group_ids(conn: Connection, group_ids: list[int]) -> set[int]:
    """Check which group IDs exist in the database.

    Args:
        conn: Database connection
        group_ids: List of group IDs to check

    Returns:
        Set of IDs that exist
    """
    if not group_ids:
        return set()
    placeholders = ",".join("?" * len(group_ids))
    rows = conn.execute(
        f"SELECT id FROM event_epg_groups WHERE id IN ({placeholders})",
        group_ids,
    ).fetchall()
    return {row["id"] for row in rows}


def get_group_channel_count(conn: Connection, group_id: int) -> int:
    """Get count of managed channels for a group.

    Args:
        conn: Database connection
        group_id: Group ID

    Returns:
        Number of managed channels (active, not deleted)
    """
    cursor = conn.execute(
        """SELECT COUNT(*) as count FROM managed_channels
           WHERE event_epg_group_id = ? AND deleted_at IS NULL""",
        (group_id,),
    )
    row = cursor.fetchone()
    return row["count"] if row else 0


def get_group_stats(conn: Connection, group_id: int) -> dict:
    """Get statistics for a group.

    Args:
        conn: Database connection
        group_id: Group ID

    Returns:
        Dict with channel counts and status breakdown
    """
    cursor = conn.execute(
        """SELECT
            COUNT(*) as total,
            SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) as active,
            SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) as deleted,
            SUM(CASE WHEN sync_status = 'pending' AND deleted_at IS NULL
                THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN sync_status = 'created' AND deleted_at IS NULL
                THEN 1 ELSE 0 END) as created,
            SUM(CASE WHEN sync_status = 'in_sync' AND deleted_at IS NULL
                THEN 1 ELSE 0 END) as in_sync,
            SUM(CASE WHEN sync_status = 'error' AND deleted_at IS NULL
                THEN 1 ELSE 0 END) as errors
        FROM managed_channels
        WHERE event_epg_group_id = ?""",
        (group_id,),
    )
    row = cursor.fetchone()

    if not row:
        return {"total": 0, "active": 0, "deleted": 0, "by_status": {}}

    return {
        "total": row["total"] or 0,
        "active": row["active"] or 0,
        "deleted": row["deleted"] or 0,
        "by_status": {
            "pending": row["pending"] or 0,
            "created": row["created"] or 0,
            "in_sync": row["in_sync"] or 0,
            "errors": row["errors"] or 0,
        },
    }


def get_all_group_stats(conn: Connection) -> dict[int, dict]:
    """Get statistics for all groups.

    Args:
        conn: Database connection

    Returns:
        Dict mapping group_id to stats dict
    """
    cursor = conn.execute(
        """SELECT
            event_epg_group_id,
            COUNT(*) as total,
            SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) as active
        FROM managed_channels
        GROUP BY event_epg_group_id"""
    )

    stats = {}
    for row in cursor.fetchall():
        stats[row["event_epg_group_id"]] = {
            "total": row["total"] or 0,
            "active": row["active"] or 0,
        }

    return stats


# =============================================================================
# XMLTV CONTENT OPERATIONS
# =============================================================================


def get_group_xmltv(conn: Connection, group_id: int) -> str | None:
    """Get stored XMLTV content for a group.

    Args:
        conn: Database connection
        group_id: Group ID

    Returns:
        XMLTV content string or None if not found
    """
    cursor = conn.execute(
        "SELECT xmltv_content FROM event_epg_xmltv WHERE group_id = ?",
        (group_id,),
    )
    row = cursor.fetchone()
    return row["xmltv_content"] if row else None


def get_group_xmltv_with_metadata(
    conn: Connection, group_id: int
) -> tuple[str, str] | None:
    """Get stored XMLTV content and metadata for a group.

    Args:
        conn: Database connection
        group_id: Group ID

    Returns:
        Tuple of (xmltv_content, updated_at) or None if not found
    """
    row = conn.execute(
        "SELECT xmltv_content, updated_at FROM event_epg_xmltv WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    if not row:
        return None
    return (row["xmltv_content"], row["updated_at"] or "")


def get_all_group_xmltv(conn: Connection, group_ids: list[int] | None = None) -> list[str]:
    """Get stored XMLTV content for multiple groups.

    Args:
        conn: Database connection
        group_ids: Optional list of group IDs (None = all active groups)

    Returns:
        List of XMLTV content strings (non-empty only)
    """
    if group_ids:
        placeholders = ",".join("?" * len(group_ids))
        cursor = conn.execute(
            f"""SELECT xmltv_content FROM event_epg_xmltv
                WHERE group_id IN ({placeholders})
                AND xmltv_content IS NOT NULL AND xmltv_content != ''""",
            group_ids,
        )
    else:
        # Get XMLTV for all enabled groups
        cursor = conn.execute(
            """SELECT x.xmltv_content FROM event_epg_xmltv x
               JOIN event_epg_groups g ON x.group_id = g.id
               WHERE g.enabled = 1
               AND x.xmltv_content IS NOT NULL AND x.xmltv_content != ''"""
        )

    return [row["xmltv_content"] for row in cursor.fetchall()]


def store_group_xmltv(conn: Connection, group_id: int, xmltv_content: str) -> None:
    """Store XMLTV content for a group.

    Args:
        conn: Database connection
        group_id: Group ID
        xmltv_content: XMLTV content string
    """
    conn.execute(
        """INSERT INTO event_epg_xmltv (group_id, xmltv_content, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(group_id) DO UPDATE SET
               xmltv_content = excluded.xmltv_content,
               updated_at = datetime('now')""",
        (group_id, xmltv_content),
    )
    conn.commit()
    logger.debug("[STORED] XMLTV for group id=%d size=%d", group_id, len(xmltv_content))


def delete_group_xmltv(conn: Connection, group_id: int) -> bool:
    """Delete stored XMLTV content for a group.

    Args:
        conn: Database connection
        group_id: Group ID

    Returns:
        True if deleted
    """
    cursor = conn.execute("DELETE FROM event_epg_xmltv WHERE group_id = ?", (group_id,))
    conn.commit()
    if cursor.rowcount > 0:
        logger.debug("[DELETED] XMLTV for group id=%d", group_id)
        return True
    return False


