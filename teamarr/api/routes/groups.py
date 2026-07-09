"""Event EPG groups management endpoints.

Provides REST API for:
- CRUD operations on event EPG groups
- Group statistics and channel counts
- M3U group discovery from Dispatcharr
"""

import logging

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from teamarr.consumers.stream_match_cache import (
    StreamMatchCache,
    clear_all_match_data,
    clear_group_match_data,
)
from teamarr.database import get_db
from teamarr.database.groups import (
    delete_group,
    delete_group_xmltv,
    get_all_group_stats,
    get_all_group_xmltv,
    get_all_groups,
    get_group,
    get_group_by_name,
    get_group_channel_count,
    get_group_xmltv_with_metadata,
    get_stale_groups,
    reorder_groups,
    set_group_enabled,
    update_group,
)
from teamarr.database.settings import get_display_settings
from teamarr.dispatcharr import get_dispatcharr_connection, get_factory
from teamarr.services import create_group_service
from teamarr.services.stream_filter import (
    UNSUPPORTED_SPORTS,
    detect_sport_hint,
    is_event_stream,
    is_placeholder,
)
from teamarr.utilities.sorting import natural_sort_key
from teamarr.utilities.xmltv import merge_xmltv_content

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class TeamFilterEntry(BaseModel):
    """A team reference for include/exclude filtering.

    Uses canonical team selection from team_cache for unambiguous identification.
    """

    provider: str  # e.g., "espn", "tsdb"
    team_id: str  # provider_team_id from team_cache
    league: str  # e.g., "nfl", "nba"
    name: str | None = None  # For display only, not used in matching


class SoccerFollowedTeam(BaseModel):
    """A soccer team to follow for teams mode.

    Leagues are auto-discovered from team_cache at processing time.
    """

    provider: str = "espn"  # e.g., "espn", "tsdb"
    team_id: str  # provider_team_id from team_cache
    name: str | None = None  # For display only


class GroupCreate(BaseModel):
    """Create event EPG group request."""

    name: str = Field(..., min_length=1, max_length=100)
    display_name: str | None = Field(None, max_length=100)  # Optional display name override
    # Deprecated: leagues/soccer/mode/parent now managed via sports subscription
    # Accepted for backward compat but ignored
    leagues: list[str] = Field(default_factory=list)
    soccer_mode: str | None = None
    soccer_followed_teams: list[SoccerFollowedTeam] | None = None
    channel_start_number: int | None = Field(None, ge=1)
    stream_timezone: str | None = None  # Timezone for stream datetime parsing
    duplicate_event_handling: str = "consolidate"
    channel_assignment_mode: str = "auto"
    sort_order: int = 0
    total_stream_count: int = 0
    m3u_group_id: int | None = None
    m3u_group_name: str | None = None
    m3u_account_id: int | None = None
    m3u_account_name: str | None = None
    # Stream filtering
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
    name_match_enabled: bool = True
    team_streams_enabled: bool = False
    epg_match_enabled: bool = False
    # Team filtering (canonical team selection)
    include_teams: list[TeamFilterEntry] | None = None
    exclude_teams: list[TeamFilterEntry] | None = None
    team_filter_mode: str = "include"  # "include" (whitelist) or "exclude" (blacklist)
    channel_sort_order: str = "time"
    overlap_handling: str = "add_stream"
    enabled: bool = True
    # Per-group subscription overrides (NULL = inherit global)
    subscription_leagues: list[str] | None = None
    subscription_soccer_mode: str | None = None
    subscription_soccer_followed_teams: list[SoccerFollowedTeam] | None = None


class GroupUpdate(BaseModel):
    """Update event EPG group request."""

    name: str | None = Field(None, min_length=1, max_length=100)
    display_name: str | None = Field(None, max_length=100)  # Optional display name override
    leagues: list[str] | None = None
    soccer_mode: str | None = None  # 'all', 'teams', 'manual', or None (non-soccer)
    soccer_followed_teams: list[SoccerFollowedTeam] | None = None  # Teams to follow
    channel_start_number: int | None = None
    stream_timezone: str | None = None  # Timezone for stream datetime parsing
    duplicate_event_handling: str | None = None
    channel_assignment_mode: str | None = None
    sort_order: int | None = None
    total_stream_count: int | None = None
    m3u_group_id: int | None = None
    m3u_group_name: str | None = None
    m3u_account_id: int | None = None
    m3u_account_name: str | None = None
    # Stream filtering
    stream_include_regex: str | None = None
    stream_include_regex_enabled: bool | None = None
    stream_exclude_regex: str | None = None
    stream_exclude_regex_enabled: bool | None = None
    custom_regex_teams: str | None = None
    custom_regex_teams_enabled: bool | None = None
    custom_regex_date: str | None = None
    custom_regex_date_enabled: bool | None = None
    custom_regex_month: str | None = None
    custom_regex_month_enabled: bool | None = None
    custom_regex_day: str | None = None
    custom_regex_day_enabled: bool | None = None
    custom_regex_time: str | None = None
    custom_regex_time_enabled: bool | None = None
    custom_regex_league: str | None = None
    custom_regex_league_enabled: bool | None = None
    # EVENT_CARD specific regex (UFC, Boxing, MMA)
    custom_regex_fighters: str | None = None
    custom_regex_fighters_enabled: bool | None = None
    custom_regex_event_name: str | None = None
    custom_regex_event_name_enabled: bool | None = None
    skip_builtin_filter: bool | None = None
    name_match_enabled: bool | None = None
    team_streams_enabled: bool | None = None
    epg_match_enabled: bool | None = None
    # Team filtering (canonical team selection)
    include_teams: list[TeamFilterEntry] | None = None
    exclude_teams: list[TeamFilterEntry] | None = None
    team_filter_mode: str | None = None  # "include" (whitelist) or "exclude" (blacklist)
    channel_sort_order: str | None = None
    overlap_handling: str | None = None
    enabled: bool | None = None
    # Per-group subscription overrides (NULL = inherit global)
    subscription_leagues: list[str] | None = None
    subscription_soccer_mode: str | None = None
    subscription_soccer_followed_teams: list[SoccerFollowedTeam] | None = None

    # Clear flags for nullable fields
    clear_display_name: bool = False
    clear_channel_start_number: bool = False
    clear_stream_timezone: bool = False
    clear_m3u_group_id: bool = False
    clear_m3u_group_name: bool = False
    clear_m3u_account_id: bool = False
    clear_m3u_account_name: bool = False
    clear_stream_include_regex: bool = False
    clear_stream_exclude_regex: bool = False
    clear_custom_regex_teams: bool = False
    clear_custom_regex_date: bool = False
    clear_custom_regex_month: bool = False
    clear_custom_regex_day: bool = False
    clear_custom_regex_time: bool = False
    clear_custom_regex_league: bool = False
    clear_custom_regex_fighters: bool = False
    clear_custom_regex_event_name: bool = False
    clear_include_teams: bool = False
    clear_exclude_teams: bool = False
    clear_soccer_mode: bool = False
    clear_soccer_followed_teams: bool = False
    clear_subscription_leagues: bool = False
    clear_subscription_soccer_mode: bool = False
    clear_subscription_soccer_followed_teams: bool = False


class GroupResponse(BaseModel):
    """Event EPG group response."""

    id: int
    name: str
    display_name: str | None = None  # Optional display name override for UI
    # Deprecated: managed via subscription. Kept for backward compat.
    leagues: list[str] = Field(default_factory=list)
    soccer_mode: str | None = None
    soccer_followed_teams: list[SoccerFollowedTeam] | None = None
    channel_start_number: int | None = None
    stream_timezone: str | None = None  # Timezone for stream datetime parsing
    duplicate_event_handling: str = "consolidate"
    channel_assignment_mode: str = "auto"
    sort_order: int = 0
    total_stream_count: int = 0
    m3u_group_id: int | None = None
    m3u_group_name: str | None = None
    m3u_account_id: int | None = None
    m3u_account_name: str | None = None
    # Stream filtering
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
    name_match_enabled: bool = True
    team_streams_enabled: bool = False
    epg_match_enabled: bool = False
    # Team filtering (canonical team selection, inherited by children)
    include_teams: list[TeamFilterEntry] | None = None
    exclude_teams: list[TeamFilterEntry] | None = None
    team_filter_mode: str = "include"  # "include" (whitelist) or "exclude" (blacklist)
    # Processing stats
    last_refresh: str | None = None
    stream_count: int = 0
    matched_count: int = 0  # Distinct streams matched (coverage)
    match_result_count: int = 0  # Total matched results produced (volume; EPG fans out)
    # Processing stats by category (FILTERED / FAILED / EXCLUDED)
    filtered_stale: int = 0  # FILTERED: Stream marked as stale in Dispatcharr
    filtered_include_regex: int = 0  # FILTERED: Didn't match include regex
    filtered_exclude_regex: int = 0  # FILTERED: Matched exclude regex
    filtered_not_event: int = 0  # FILTERED: Stream doesn't look like event
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
    # Per-group subscription overrides (NULL = inherit global)
    subscription_leagues: list[str] | None = None
    subscription_soccer_mode: str | None = None
    subscription_soccer_followed_teams: list[SoccerFollowedTeam] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    channel_count: int | None = None


class GroupListResponse(BaseModel):
    """List of event EPG groups."""

    groups: list[GroupResponse]
    total: int


class GroupStatsResponse(BaseModel):
    """Group statistics."""

    group_id: int
    total: int = 0
    active: int = 0
    deleted: int = 0
    by_status: dict = {}


class M3UGroupResponse(BaseModel):
    """M3U group from Dispatcharr."""

    id: int
    name: str
    stream_count: int | None = None


class M3UGroupListResponse(BaseModel):
    """List of M3U groups."""

    groups: list[M3UGroupResponse]
    total: int


class BulkGroupItem(BaseModel):
    """Single group to create in bulk import."""

    m3u_group_id: int
    m3u_group_name: str
    m3u_account_id: int
    m3u_account_name: str


class BulkGroupSettings(BaseModel):
    """Shared settings for bulk group creation."""

    # Deprecated: accepted for backward compat but ignored
    leagues: list[str] = Field(default_factory=list)
    soccer_mode: str | None = None
    soccer_followed_teams: list[SoccerFollowedTeam] | None = None
    stream_timezone: str | None = None  # Timezone for stream datetime parsing
    duplicate_event_handling: str = "consolidate"
    channel_sort_order: str = "time"
    overlap_handling: str = "add_stream"
    enabled: bool = True
    name_match_enabled: bool = True
    team_streams_enabled: bool = False
    epg_match_enabled: bool = False


class BulkGroupCreateRequest(BaseModel):
    """Bulk create event EPG groups request."""

    groups: list[BulkGroupItem] = Field(..., min_length=1)
    settings: BulkGroupSettings


class BulkGroupCreateResult(BaseModel):
    """Result of a single group creation in bulk."""

    m3u_group_id: int
    m3u_account_id: int
    group_id: int | None = None
    name: str
    success: bool
    error: str | None = None


class BulkGroupCreateResponse(BaseModel):
    """Response from bulk group creation."""

    created: list[BulkGroupCreateResult]
    total_requested: int
    total_created: int
    total_failed: int


class BulkGroupUpdateRequest(BaseModel):
    """Bulk update event EPG groups request.

    Only provided (non-None) fields will be updated.
    Use clear_* flags to explicitly set fields to NULL.
    """

    group_ids: list[int] = Field(..., min_length=1)

    # Updateable fields (all optional - only provided fields are applied)
    leagues: list[str] | None = None
    soccer_mode: str | None = None  # 'all', 'teams', 'manual', or None (non-soccer)
    soccer_followed_teams: list[SoccerFollowedTeam] | None = None  # Teams to follow
    stream_timezone: str | None = None  # Timezone for stream datetime parsing
    duplicate_event_handling: str | None = None
    channel_sort_order: str | None = None
    overlap_handling: str | None = None
    enabled: bool | None = None
    name_match_enabled: bool | None = None
    team_streams_enabled: bool | None = None
    epg_match_enabled: bool | None = None

    # Team filtering
    include_teams: list[TeamFilterEntry] | None = None
    exclude_teams: list[TeamFilterEntry] | None = None
    team_filter_mode: str | None = None  # 'include' or 'exclude'
    bypass_filter_for_playoffs: bool | None = None

    # Clear flags to explicitly set fields to NULL
    clear_stream_timezone: bool = False
    clear_soccer_mode: bool = False
    clear_soccer_followed_teams: bool = False
    clear_include_teams: bool = False
    clear_exclude_teams: bool = False
    clear_bypass_filter_for_playoffs: bool = False
    # Per-group subscription overrides
    subscription_leagues: list[str] | None = None
    subscription_soccer_mode: str | None = None
    subscription_soccer_followed_teams: list[SoccerFollowedTeam] | None = None
    clear_subscription_leagues: bool = False
    clear_subscription_soccer_mode: bool = False
    clear_subscription_soccer_followed_teams: bool = False


class ClearCacheRequest(BaseModel):
    """Request to clear stream match cache for multiple groups."""

    group_ids: list[int] = Field(..., min_length=1)


class ClearCacheGroupResult(BaseModel):
    """Result of clearing cache for a single group."""

    group_id: int
    cleared: int


class ClearCacheResponse(BaseModel):
    """Response from clearing stream match cache."""

    success: bool
    group_id: int | None = None  # For single group
    group_name: str | None = None  # For single group
    entries_cleared: int | None = None  # For single group
    total_cleared: int | None = None  # For bulk
    by_group: list[ClearCacheGroupResult] | None = None  # For bulk


class BulkGroupUpdateResult(BaseModel):
    """Result of a single group update in bulk."""

    group_id: int
    name: str
    success: bool
    error: str | None = None


class BulkGroupUpdateResponse(BaseModel):
    """Response from bulk group update."""

    results: list[BulkGroupUpdateResult]
    total_requested: int
    total_updated: int
    total_failed: int


class GroupOrderItem(BaseModel):
    """A single group reorder entry."""

    group_id: int
    sort_order: int


class ReorderGroupsRequest(BaseModel):
    """Request to reorder groups."""

    groups: list[GroupOrderItem]


class ReorderGroupsResponse(BaseModel):
    """Response from reorder groups."""

    success: bool
    updated_count: int
    message: str


# =============================================================================
# VALIDATION
# =============================================================================

VALID_DUPLICATE_HANDLING = {"consolidate", "separate", "ignore"}
VALID_ASSIGNMENT_MODE = {"auto", "manual"}
VALID_CHANNEL_SORT_ORDER = {"time", "sport_time", "league_time"}
VALID_OVERLAP_HANDLING = {"add_stream", "add_only", "create_all", "skip"}


def _effective_flag(patch: bool | None, current: bool) -> bool:
    """Resolve a partial-update boolean: the patch value if given, else current."""
    return current if patch is None else patch


def require_matching_type(name: bool, team: bool, epg: bool) -> None:
    """Reject a source with no matching type enabled (epic ahow).

    Every source must run at least one of Stream Name / Team / EPG matching,
    otherwise it would process streams and match nothing.
    """
    if not (name or team or epg):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "At least one matching type must be enabled "
                "(Stream Name, Team, or EPG)."
            ),
        )


def validate_group_fields(
    duplicate_event_handling: str | None = None,
    channel_assignment_mode: str | None = None,
    channel_sort_order: str | None = None,
    overlap_handling: str | None = None,
):
    """Validate group field values."""
    if duplicate_event_handling and duplicate_event_handling not in VALID_DUPLICATE_HANDLING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid duplicate_event_handling. Valid: {VALID_DUPLICATE_HANDLING}",
        )
    if channel_assignment_mode and channel_assignment_mode not in VALID_ASSIGNMENT_MODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid channel_assignment_mode. Valid: {VALID_ASSIGNMENT_MODE}",
        )
    if channel_sort_order and channel_sort_order not in VALID_CHANNEL_SORT_ORDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid channel_sort_order. Valid: {VALID_CHANNEL_SORT_ORDER}",
        )
    if overlap_handling and overlap_handling not in VALID_OVERLAP_HANDLING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid overlap_handling. Valid: {VALID_OVERLAP_HANDLING}",
        )


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("", response_model=GroupListResponse)
def list_groups(
    include_disabled: bool = Query(False, description="Include disabled groups"),
    include_stats: bool = Query(False, description="Include channel counts"),
):
    """List all event EPG groups."""

    with get_db() as conn:
        # Hide the system-managed channel-source group (183.9) — it is controlled
        # via Settings → EPG, not edited as a normal Event Group.
        groups = get_all_groups(
            conn, include_disabled=include_disabled, exclude_channel_source=True
        )

        stats = {}
        if include_stats:
            stats = get_all_group_stats(conn)

    # Fetch fresh M3U account names from Dispatcharr
    m3u_account_names: dict[int, str] = {}
    account_ids = {g.m3u_account_id for g in groups if g.m3u_account_id}
    if account_ids:
        try:
            dispatcharr = get_dispatcharr_connection(get_db)
            if dispatcharr:
                accounts = dispatcharr.m3u.list_accounts()
                m3u_account_names = {a.id: a.name for a in accounts}
        except Exception:
            pass  # Fall back to stored names if Dispatcharr unavailable

    def get_account_name(g):
        """Get fresh M3U account name, falling back to stored name."""
        if g.m3u_account_id and g.m3u_account_id in m3u_account_names:
            return m3u_account_names[g.m3u_account_id]
        return g.m3u_account_name

    return GroupListResponse(
        groups=[
            GroupResponse(
                id=g.id,
                name=g.name,
                display_name=g.display_name,
                leagues=g.leagues,
                soccer_mode=g.soccer_mode,
                soccer_followed_teams=[SoccerFollowedTeam(**t) for t in g.soccer_followed_teams]
                if g.soccer_followed_teams
                else None,
                channel_start_number=g.channel_start_number,
                duplicate_event_handling=g.duplicate_event_handling,
                channel_assignment_mode=g.channel_assignment_mode,
                sort_order=g.sort_order,
                total_stream_count=g.total_stream_count,
                m3u_group_id=g.m3u_group_id,
                m3u_group_name=g.m3u_group_name,
                m3u_account_id=g.m3u_account_id,
                m3u_account_name=get_account_name(g),
                stream_include_regex=g.stream_include_regex,
                stream_include_regex_enabled=g.stream_include_regex_enabled,
                stream_exclude_regex=g.stream_exclude_regex,
                stream_exclude_regex_enabled=g.stream_exclude_regex_enabled,
                custom_regex_teams=g.custom_regex_teams,
                custom_regex_teams_enabled=g.custom_regex_teams_enabled,
                custom_regex_date=g.custom_regex_date,
                custom_regex_date_enabled=g.custom_regex_date_enabled,
                custom_regex_month=g.custom_regex_month,
                custom_regex_month_enabled=g.custom_regex_month_enabled,
                custom_regex_day=g.custom_regex_day,
                custom_regex_day_enabled=g.custom_regex_day_enabled,
                custom_regex_time=g.custom_regex_time,
                custom_regex_time_enabled=g.custom_regex_time_enabled,
                custom_regex_league=g.custom_regex_league,
                custom_regex_league_enabled=g.custom_regex_league_enabled,
                custom_regex_fighters=g.custom_regex_fighters,
                custom_regex_fighters_enabled=g.custom_regex_fighters_enabled,
                custom_regex_event_name=g.custom_regex_event_name,
                custom_regex_event_name_enabled=g.custom_regex_event_name_enabled,
                skip_builtin_filter=g.skip_builtin_filter,
                name_match_enabled=g.name_match_enabled,
                team_streams_enabled=g.team_streams_enabled,
                epg_match_enabled=g.epg_match_enabled,
                include_teams=[TeamFilterEntry(**t) for t in g.include_teams]
                if g.include_teams
                else None,
                exclude_teams=[TeamFilterEntry(**t) for t in g.exclude_teams]
                if g.exclude_teams
                else None,
                team_filter_mode=g.team_filter_mode,
                last_refresh=g.last_refresh.isoformat() if g.last_refresh else None,
                stream_count=g.stream_count,
                matched_count=g.matched_count,
                match_result_count=g.match_result_count,
                filtered_stale=g.filtered_stale,
                filtered_include_regex=g.filtered_include_regex,
                filtered_exclude_regex=g.filtered_exclude_regex,
                filtered_not_event=g.filtered_not_event,
                filtered_team=g.filtered_team,
                failed_count=g.failed_count,
                streams_excluded=g.streams_excluded,
                excluded_event_final=g.excluded_event_final,
                excluded_event_past=g.excluded_event_past,
                excluded_before_window=g.excluded_before_window,
                excluded_league_not_included=g.excluded_league_not_included,
                channel_sort_order=g.channel_sort_order,
                overlap_handling=g.overlap_handling,
                enabled=g.enabled,
                subscription_leagues=g.subscription_leagues,
                subscription_soccer_mode=g.subscription_soccer_mode,
                subscription_soccer_followed_teams=(
                    [SoccerFollowedTeam(**t) for t in g.subscription_soccer_followed_teams]
                )
                if g.subscription_soccer_followed_teams
                else None,
                created_at=g.created_at.isoformat() if g.created_at else None,
                updated_at=g.updated_at.isoformat() if g.updated_at else None,
                channel_count=stats.get(g.id, {}).get("active"),
            )
            for g in groups
        ],
        total=len(groups),
    )


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
def create_group(request: GroupCreate):
    """Create a new event EPG group."""
    from teamarr.database.groups import (
        create_group,
        get_group,
        get_group_by_name,
    )

    require_matching_type(
        request.name_match_enabled,
        request.team_streams_enabled,
        request.epg_match_enabled,
    )

    # Deprecated per-group channel fields accepted but ignored (v59)
    # validate_group_fields skipped for deprecated fields

    with get_db() as conn:
        # Check for duplicate name within same M3U account
        existing = get_group_by_name(conn, request.name, request.m3u_account_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Group with name '{request.name}' already exists for this M3U account",
            )

        group_id = create_group(
            conn,
            name=request.name,
            leagues=request.leagues,
            display_name=request.display_name,
            soccer_mode=request.soccer_mode,
            soccer_followed_teams=[t.model_dump() for t in request.soccer_followed_teams]
            if request.soccer_followed_teams
            else None,
            channel_start_number=None,  # Deprecated — global mode in v59
            stream_timezone=request.stream_timezone,
            duplicate_event_handling="consolidate",  # Deprecated — global mode in v59
            channel_assignment_mode="auto",  # Deprecated — global mode in v59
            sort_order=request.sort_order,
            total_stream_count=request.total_stream_count,
            m3u_group_id=request.m3u_group_id,
            m3u_group_name=request.m3u_group_name,
            m3u_account_id=request.m3u_account_id,
            m3u_account_name=request.m3u_account_name,
            stream_include_regex=request.stream_include_regex,
            stream_include_regex_enabled=request.stream_include_regex_enabled,
            stream_exclude_regex=request.stream_exclude_regex,
            stream_exclude_regex_enabled=request.stream_exclude_regex_enabled,
            custom_regex_teams=request.custom_regex_teams,
            custom_regex_teams_enabled=request.custom_regex_teams_enabled,
            custom_regex_date=request.custom_regex_date,
            custom_regex_date_enabled=request.custom_regex_date_enabled,
            custom_regex_month=request.custom_regex_month,
            custom_regex_month_enabled=request.custom_regex_month_enabled,
            custom_regex_day=request.custom_regex_day,
            custom_regex_day_enabled=request.custom_regex_day_enabled,
            custom_regex_time=request.custom_regex_time,
            custom_regex_time_enabled=request.custom_regex_time_enabled,
            custom_regex_league=request.custom_regex_league,
            custom_regex_league_enabled=request.custom_regex_league_enabled,
            custom_regex_fighters=request.custom_regex_fighters,
            custom_regex_fighters_enabled=request.custom_regex_fighters_enabled,
            custom_regex_event_name=request.custom_regex_event_name,
            custom_regex_event_name_enabled=request.custom_regex_event_name_enabled,
            skip_builtin_filter=request.skip_builtin_filter,
            name_match_enabled=request.name_match_enabled,
            team_streams_enabled=request.team_streams_enabled,
            epg_match_enabled=request.epg_match_enabled,
            include_teams=[t.model_dump() for t in request.include_teams]
            if request.include_teams is not None
            else None,
            exclude_teams=[t.model_dump() for t in request.exclude_teams]
            if request.exclude_teams is not None
            else None,
            team_filter_mode=request.team_filter_mode,
            channel_sort_order="time",  # Deprecated — global ordering in v59
            overlap_handling="add_stream",  # Deprecated — global consolidation in v59
            enabled=request.enabled,
            subscription_leagues=request.subscription_leagues,
            subscription_soccer_mode=request.subscription_soccer_mode,
            subscription_soccer_followed_teams=(
                [t.model_dump() for t in request.subscription_soccer_followed_teams]
            )
            if request.subscription_soccer_followed_teams
            else None,
        )

        group = get_group(conn, group_id)
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Group {group_id} could not be loaded after creation",
            )

    logger.info("[CREATED] Event group id=%d name=%s", group_id, request.name)

    return GroupResponse(
        id=group.id,
        name=group.name,
        display_name=group.display_name,
        leagues=group.leagues,
        soccer_mode=group.soccer_mode,
        soccer_followed_teams=[SoccerFollowedTeam(**t) for t in group.soccer_followed_teams]
        if group.soccer_followed_teams
        else None,
        channel_start_number=group.channel_start_number,
        stream_timezone=group.stream_timezone,
        duplicate_event_handling=group.duplicate_event_handling,
        channel_assignment_mode=group.channel_assignment_mode,
        sort_order=group.sort_order,
        total_stream_count=group.total_stream_count,
        m3u_group_id=group.m3u_group_id,
        m3u_group_name=group.m3u_group_name,
        m3u_account_id=group.m3u_account_id,
        m3u_account_name=group.m3u_account_name,
        stream_include_regex=group.stream_include_regex,
        stream_include_regex_enabled=group.stream_include_regex_enabled,
        stream_exclude_regex=group.stream_exclude_regex,
        stream_exclude_regex_enabled=group.stream_exclude_regex_enabled,
        custom_regex_teams=group.custom_regex_teams,
        custom_regex_teams_enabled=group.custom_regex_teams_enabled,
        custom_regex_date=group.custom_regex_date,
        custom_regex_date_enabled=group.custom_regex_date_enabled,
        custom_regex_month=group.custom_regex_month,
        custom_regex_month_enabled=group.custom_regex_month_enabled,
        custom_regex_day=group.custom_regex_day,
        custom_regex_day_enabled=group.custom_regex_day_enabled,
        custom_regex_time=group.custom_regex_time,
        custom_regex_time_enabled=group.custom_regex_time_enabled,
        custom_regex_league=group.custom_regex_league,
        custom_regex_league_enabled=group.custom_regex_league_enabled,
        custom_regex_fighters=group.custom_regex_fighters,
        custom_regex_fighters_enabled=group.custom_regex_fighters_enabled,
        custom_regex_event_name=group.custom_regex_event_name,
        custom_regex_event_name_enabled=group.custom_regex_event_name_enabled,
        skip_builtin_filter=group.skip_builtin_filter,
        name_match_enabled=group.name_match_enabled,
        team_streams_enabled=group.team_streams_enabled,
        epg_match_enabled=group.epg_match_enabled,
        include_teams=[TeamFilterEntry(**t) for t in group.include_teams]
        if group.include_teams
        else None,
        exclude_teams=[TeamFilterEntry(**t) for t in group.exclude_teams]
        if group.exclude_teams
        else None,
        team_filter_mode=group.team_filter_mode,
        last_refresh=group.last_refresh.isoformat() if group.last_refresh else None,
        stream_count=group.stream_count,
        matched_count=group.matched_count,
        filtered_stale=group.filtered_stale,
        filtered_include_regex=group.filtered_include_regex,
        filtered_exclude_regex=group.filtered_exclude_regex,
        filtered_not_event=group.filtered_not_event,
        filtered_team=group.filtered_team,
        failed_count=group.failed_count,
        streams_excluded=group.streams_excluded,
        excluded_event_final=group.excluded_event_final,
        excluded_event_past=group.excluded_event_past,
        excluded_before_window=group.excluded_before_window,
        excluded_league_not_included=group.excluded_league_not_included,
        channel_sort_order=group.channel_sort_order,
        overlap_handling=group.overlap_handling,
        enabled=group.enabled,
        subscription_leagues=group.subscription_leagues,
        subscription_soccer_mode=group.subscription_soccer_mode,
        subscription_soccer_followed_teams=(
            [SoccerFollowedTeam(**t) for t in group.subscription_soccer_followed_teams]
        )
        if group.subscription_soccer_followed_teams
        else None,
        created_at=group.created_at.isoformat() if group.created_at else None,
        updated_at=group.updated_at.isoformat() if group.updated_at else None,
    )


@router.post("/bulk", response_model=BulkGroupCreateResponse, status_code=status.HTTP_201_CREATED)
def create_groups_bulk(request: BulkGroupCreateRequest):
    """Bulk create event EPG groups with shared settings.

    All groups will be created with the same mode, leagues, and settings.
    Useful for importing multiple groups from the same M3U account.
    """
    from teamarr.database.groups import create_group, get_group_by_name

    # Validate settings
    validate_group_fields(
        duplicate_event_handling=request.settings.duplicate_event_handling,
        channel_sort_order=request.settings.channel_sort_order,
        overlap_handling=request.settings.overlap_handling,
    )
    require_matching_type(
        request.settings.name_match_enabled,
        request.settings.team_streams_enabled,
        request.settings.epg_match_enabled,
    )

    results: list[BulkGroupCreateResult] = []
    total_created = 0
    total_failed = 0

    with get_db() as conn:
        for item in request.groups:
            try:
                # Check for duplicate name within same M3U account
                existing = get_group_by_name(conn, item.m3u_group_name, item.m3u_account_id)
                if existing:
                    results.append(
                        BulkGroupCreateResult(
                            m3u_group_id=item.m3u_group_id,
                            m3u_account_id=item.m3u_account_id,
                            name=item.m3u_group_name,
                            success=False,
                            error="Group already exists for this M3U account",
                        )
                    )
                    total_failed += 1
                    continue

                group_id = create_group(
                    conn,
                    name=item.m3u_group_name,
                    leagues=request.settings.leagues,
                    soccer_mode=request.settings.soccer_mode,
                    soccer_followed_teams=(
                        [t.model_dump() for t in request.settings.soccer_followed_teams]
                        if request.settings.soccer_followed_teams
                        else None
                    ),
                    stream_timezone=request.settings.stream_timezone,
                    duplicate_event_handling=request.settings.duplicate_event_handling,
                    channel_sort_order=request.settings.channel_sort_order,
                    overlap_handling=request.settings.overlap_handling,
                    m3u_group_id=item.m3u_group_id,
                    m3u_group_name=item.m3u_group_name,
                    m3u_account_id=item.m3u_account_id,
                    m3u_account_name=item.m3u_account_name,
                    enabled=request.settings.enabled,
                    name_match_enabled=request.settings.name_match_enabled,
                    team_streams_enabled=request.settings.team_streams_enabled,
                    epg_match_enabled=request.settings.epg_match_enabled,
                )

                results.append(
                    BulkGroupCreateResult(
                        m3u_group_id=item.m3u_group_id,
                        m3u_account_id=item.m3u_account_id,
                        group_id=group_id,
                        name=item.m3u_group_name,
                        success=True,
                    )
                )
                total_created += 1

            except Exception as e:
                results.append(
                    BulkGroupCreateResult(
                        m3u_group_id=item.m3u_group_id,
                        m3u_account_id=item.m3u_account_id,
                        name=item.m3u_group_name,
                        success=False,
                        error=str(e),
                    )
                )
                total_failed += 1

    logger.info("[BULK_IMPORT] Event groups: %d created, %d failed", total_created, total_failed)

    return BulkGroupCreateResponse(
        created=results,
        total_requested=len(request.groups),
        total_created=total_created,
        total_failed=total_failed,
    )


@router.put("/bulk", response_model=BulkGroupUpdateResponse)
def update_groups_bulk(request: BulkGroupUpdateRequest):
    """Bulk update event EPG groups with shared settings.

    Only provided (non-None) fields will be updated across all selected groups.
    Use clear_* flags to explicitly set fields to NULL.
    """

    # Validate fields
    validate_group_fields(
        channel_sort_order=request.channel_sort_order,
        overlap_handling=request.overlap_handling,
    )

    results: list[BulkGroupUpdateResult] = []
    total_updated = 0
    total_failed = 0

    with get_db() as conn:
        for group_id in request.group_ids:
            try:
                # Verify group exists
                group = get_group(conn, group_id)
                if not group:
                    results.append(
                        BulkGroupUpdateResult(
                            group_id=group_id,
                            name=f"Group {group_id}",
                            success=False,
                            error="Group not found",
                        )
                    )
                    total_failed += 1
                    continue

                # Reject (per-group) if the update would leave no matching type.
                if not (
                    _effective_flag(request.name_match_enabled, group.name_match_enabled)
                    or _effective_flag(request.team_streams_enabled, group.team_streams_enabled)
                    or _effective_flag(request.epg_match_enabled, group.epg_match_enabled)
                ):
                    results.append(
                        BulkGroupUpdateResult(
                            group_id=group_id,
                            name=group.name,
                            success=False,
                            error=(
                                "At least one matching type must be enabled "
                                "(Stream Name, Team, or EPG)."
                            ),
                        )
                    )
                    total_failed += 1
                    continue

                # Update the group with provided fields
                update_group(
                    conn,
                    group_id,
                    leagues=request.leagues,
                    soccer_mode=request.soccer_mode,
                    soccer_followed_teams=[t.model_dump() for t in request.soccer_followed_teams]
                    if request.soccer_followed_teams
                    else None,
                    stream_timezone=request.stream_timezone,
                    duplicate_event_handling=request.duplicate_event_handling,
                    channel_sort_order=request.channel_sort_order,
                    overlap_handling=request.overlap_handling,
                    enabled=request.enabled,
                    name_match_enabled=request.name_match_enabled,
                    team_streams_enabled=request.team_streams_enabled,
                    epg_match_enabled=request.epg_match_enabled,
                    clear_stream_timezone=request.clear_stream_timezone,
                    clear_soccer_mode=request.clear_soccer_mode,
                    clear_soccer_followed_teams=request.clear_soccer_followed_teams,
                    # Team filtering
                    include_teams=[t.model_dump() for t in request.include_teams]
                    if request.include_teams
                    else None,
                    exclude_teams=[t.model_dump() for t in request.exclude_teams]
                    if request.exclude_teams
                    else None,
                    team_filter_mode=request.team_filter_mode,
                    bypass_filter_for_playoffs=request.bypass_filter_for_playoffs,
                    clear_include_teams=request.clear_include_teams,
                    clear_exclude_teams=request.clear_exclude_teams,
                    clear_bypass_filter_for_playoffs=request.clear_bypass_filter_for_playoffs,
                    # Per-group subscription overrides
                    subscription_leagues=request.subscription_leagues,
                    subscription_soccer_mode=request.subscription_soccer_mode,
                    subscription_soccer_followed_teams=(
                [t.model_dump() for t in request.subscription_soccer_followed_teams]
            )
                    if request.subscription_soccer_followed_teams
                    else None,
                    clear_subscription_leagues=request.clear_subscription_leagues,
                    clear_subscription_soccer_mode=request.clear_subscription_soccer_mode,
                    clear_subscription_soccer_followed_teams=request.clear_subscription_soccer_followed_teams,
                )

                results.append(
                    BulkGroupUpdateResult(
                        group_id=group_id,
                        name=group.name,
                        success=True,
                    )
                )
                total_updated += 1

            except Exception as e:
                logger.exception("[BULK_UPDATE] Failed to update group %d: %s", group_id, e)
                results.append(
                    BulkGroupUpdateResult(
                        group_id=group_id,
                        name=f"Group {group_id}",
                        success=False,
                        error=str(e),
                    )
                )
                total_failed += 1

    logger.info("[BULK_UPDATE] Event groups: %d updated, %d failed", total_updated, total_failed)

    return BulkGroupUpdateResponse(
        results=results,
        total_requested=len(request.group_ids),
        total_updated=total_updated,
        total_failed=total_failed,
    )


@router.post("/reorder", response_model=ReorderGroupsResponse)
def reorder_groups_endpoint(request: ReorderGroupsRequest):
    """Reorder event groups by updating sort_order values."""

    if not request.groups:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No groups provided for reordering",
        )

    with get_db() as conn:
        items = [(g.sort_order, g.group_id) for g in request.groups]
        updated = reorder_groups(conn, items)

    return ReorderGroupsResponse(
        success=True,
        updated_count=updated,
        message=f"Reordered {updated} groups",
    )


class MatchCacheStatsResponse(BaseModel):
    """Response for stream match cache statistics."""

    total_entries: int


@router.get("/cache/stats", response_model=MatchCacheStatsResponse)
def get_match_cache_stats():
    """Get stream match cache statistics."""

    cache = StreamMatchCache(get_db)
    return MatchCacheStatsResponse(total_entries=cache.get_size())


@router.get("/stale")
def list_stale_groups() -> list[dict]:
    """List enabled groups whose Dispatcharr M3U source channel-group is gone (stale).

    Populated by the post-generation stale-source detection (lylt.1). Delete a
    stale group via the standard DELETE /groups/{id} endpoint.
    """

    with get_db() as conn:
        return get_stale_groups(conn)


@router.get("/{group_id}", response_model=GroupResponse)
def get_group_by_id(group_id: int):
    """Get a single event EPG group."""

    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

        channel_count = get_group_channel_count(conn, group_id)

    # Fetch fresh M3U account name from Dispatcharr
    m3u_account_name = group.m3u_account_name
    if group.m3u_account_id:
        try:
            dispatcharr = get_dispatcharr_connection(get_db)
            if dispatcharr:
                accounts = dispatcharr.m3u.list_accounts()
                for a in accounts:
                    if a.id == group.m3u_account_id:
                        m3u_account_name = a.name
                        break
        except Exception:
            pass  # Fall back to stored name if Dispatcharr unavailable

    return GroupResponse(
        id=group.id,
        name=group.name,
        display_name=group.display_name,
        leagues=group.leagues,
        soccer_mode=group.soccer_mode,
        soccer_followed_teams=[SoccerFollowedTeam(**t) for t in group.soccer_followed_teams]
        if group.soccer_followed_teams
        else None,
        channel_start_number=group.channel_start_number,
        stream_timezone=group.stream_timezone,
        duplicate_event_handling=group.duplicate_event_handling,
        channel_assignment_mode=group.channel_assignment_mode,
        sort_order=group.sort_order,
        total_stream_count=group.total_stream_count,
        m3u_group_id=group.m3u_group_id,
        m3u_group_name=group.m3u_group_name,
        m3u_account_id=group.m3u_account_id,
        m3u_account_name=m3u_account_name,
        stream_include_regex=group.stream_include_regex,
        stream_include_regex_enabled=group.stream_include_regex_enabled,
        stream_exclude_regex=group.stream_exclude_regex,
        stream_exclude_regex_enabled=group.stream_exclude_regex_enabled,
        custom_regex_teams=group.custom_regex_teams,
        custom_regex_teams_enabled=group.custom_regex_teams_enabled,
        custom_regex_date=group.custom_regex_date,
        custom_regex_date_enabled=group.custom_regex_date_enabled,
        custom_regex_month=group.custom_regex_month,
        custom_regex_month_enabled=group.custom_regex_month_enabled,
        custom_regex_day=group.custom_regex_day,
        custom_regex_day_enabled=group.custom_regex_day_enabled,
        custom_regex_time=group.custom_regex_time,
        custom_regex_time_enabled=group.custom_regex_time_enabled,
        custom_regex_league=group.custom_regex_league,
        custom_regex_league_enabled=group.custom_regex_league_enabled,
        custom_regex_fighters=group.custom_regex_fighters,
        custom_regex_fighters_enabled=group.custom_regex_fighters_enabled,
        custom_regex_event_name=group.custom_regex_event_name,
        custom_regex_event_name_enabled=group.custom_regex_event_name_enabled,
        skip_builtin_filter=group.skip_builtin_filter,
        name_match_enabled=group.name_match_enabled,
        team_streams_enabled=group.team_streams_enabled,
        epg_match_enabled=group.epg_match_enabled,
        include_teams=[TeamFilterEntry(**t) for t in group.include_teams]
        if group.include_teams
        else None,
        exclude_teams=[TeamFilterEntry(**t) for t in group.exclude_teams]
        if group.exclude_teams
        else None,
        team_filter_mode=group.team_filter_mode,
        last_refresh=group.last_refresh.isoformat() if group.last_refresh else None,
        stream_count=group.stream_count,
        matched_count=group.matched_count,
        filtered_stale=group.filtered_stale,
        filtered_include_regex=group.filtered_include_regex,
        filtered_exclude_regex=group.filtered_exclude_regex,
        filtered_not_event=group.filtered_not_event,
        filtered_team=group.filtered_team,
        failed_count=group.failed_count,
        streams_excluded=group.streams_excluded,
        excluded_event_final=group.excluded_event_final,
        excluded_event_past=group.excluded_event_past,
        excluded_before_window=group.excluded_before_window,
        excluded_league_not_included=group.excluded_league_not_included,
        channel_sort_order=group.channel_sort_order,
        overlap_handling=group.overlap_handling,
        enabled=group.enabled,
        subscription_leagues=group.subscription_leagues,
        subscription_soccer_mode=group.subscription_soccer_mode,
        subscription_soccer_followed_teams=(
            [SoccerFollowedTeam(**t) for t in group.subscription_soccer_followed_teams]
        )
        if group.subscription_soccer_followed_teams
        else None,
        created_at=group.created_at.isoformat() if group.created_at else None,
        updated_at=group.updated_at.isoformat() if group.updated_at else None,
        channel_count=channel_count,
    )


@router.put("/{group_id}", response_model=GroupResponse)
def update_group_by_id(group_id: int, request: GroupUpdate):
    """Update an event EPG group."""

    # Deprecated per-group channel fields accepted but ignored (v59)

    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

        # Validate the post-update matching types (patch overrides current value).
        require_matching_type(
            _effective_flag(request.name_match_enabled, group.name_match_enabled),
            _effective_flag(request.team_streams_enabled, group.team_streams_enabled),
            _effective_flag(request.epg_match_enabled, group.epg_match_enabled),
        )

        # Check for duplicate name if changing (within same M3U account)
        # Determine the target account_id (could be changing)
        target_account_id = (
            None
            if request.clear_m3u_account_id
            else request.m3u_account_id
            if request.m3u_account_id is not None
            else group.m3u_account_id
        )
        target_name = request.name if request.name else group.name
        if target_name != group.name or target_account_id != group.m3u_account_id:
            existing = get_group_by_name(conn, target_name, target_account_id)
            if existing and existing.id != group_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Group with name '{target_name}' already exists for this M3U account",
                )

        try:
            update_group(
                conn,
                group_id,
                name=request.name,
                display_name=request.display_name,
                leagues=request.leagues,
                soccer_mode=request.soccer_mode,
                soccer_followed_teams=[t.model_dump() for t in request.soccer_followed_teams]
                if request.soccer_followed_teams
                else None,
                channel_start_number=request.channel_start_number,
                stream_timezone=request.stream_timezone,
                duplicate_event_handling=None,  # Deprecated — global consolidation in v59
                channel_assignment_mode=None,  # Deprecated — global mode in v59
                sort_order=request.sort_order,
                total_stream_count=request.total_stream_count,
                m3u_group_id=request.m3u_group_id,
                m3u_group_name=request.m3u_group_name,
                m3u_account_id=request.m3u_account_id,
                m3u_account_name=request.m3u_account_name,
                stream_include_regex=request.stream_include_regex,
                stream_include_regex_enabled=request.stream_include_regex_enabled,
                stream_exclude_regex=request.stream_exclude_regex,
                stream_exclude_regex_enabled=request.stream_exclude_regex_enabled,
                custom_regex_teams=request.custom_regex_teams,
                custom_regex_teams_enabled=request.custom_regex_teams_enabled,
                custom_regex_date=request.custom_regex_date,
                custom_regex_date_enabled=request.custom_regex_date_enabled,
                custom_regex_month=request.custom_regex_month,
                custom_regex_month_enabled=request.custom_regex_month_enabled,
                custom_regex_day=request.custom_regex_day,
                custom_regex_day_enabled=request.custom_regex_day_enabled,
                custom_regex_time=request.custom_regex_time,
                custom_regex_time_enabled=request.custom_regex_time_enabled,
                custom_regex_league=request.custom_regex_league,
                custom_regex_league_enabled=request.custom_regex_league_enabled,
                custom_regex_fighters=request.custom_regex_fighters,
                custom_regex_fighters_enabled=request.custom_regex_fighters_enabled,
                custom_regex_event_name=request.custom_regex_event_name,
                custom_regex_event_name_enabled=request.custom_regex_event_name_enabled,
                skip_builtin_filter=request.skip_builtin_filter,
                name_match_enabled=request.name_match_enabled,
                team_streams_enabled=request.team_streams_enabled,
                epg_match_enabled=request.epg_match_enabled,
                include_teams=[t.model_dump() for t in request.include_teams]
                if request.include_teams is not None
                else None,
                exclude_teams=[t.model_dump() for t in request.exclude_teams]
                if request.exclude_teams is not None
                else None,
                team_filter_mode=request.team_filter_mode,
                channel_sort_order=None,  # Deprecated — global ordering in v59
                overlap_handling=None,  # Deprecated — global consolidation in v59
                enabled=request.enabled,
                clear_display_name=request.clear_display_name,
                clear_channel_start_number=request.clear_channel_start_number,
                clear_stream_timezone=request.clear_stream_timezone,
                clear_m3u_group_id=request.clear_m3u_group_id,
                clear_m3u_group_name=request.clear_m3u_group_name,
                clear_m3u_account_id=request.clear_m3u_account_id,
                clear_m3u_account_name=request.clear_m3u_account_name,
                clear_stream_include_regex=request.clear_stream_include_regex,
                clear_stream_exclude_regex=request.clear_stream_exclude_regex,
                clear_custom_regex_teams=request.clear_custom_regex_teams,
                clear_custom_regex_date=request.clear_custom_regex_date,
                clear_custom_regex_month=request.clear_custom_regex_month,
                clear_custom_regex_day=request.clear_custom_regex_day,
                clear_custom_regex_time=request.clear_custom_regex_time,
                clear_custom_regex_league=request.clear_custom_regex_league,
                clear_custom_regex_fighters=request.clear_custom_regex_fighters,
                clear_custom_regex_event_name=request.clear_custom_regex_event_name,
                clear_include_teams=request.clear_include_teams,
                clear_exclude_teams=request.clear_exclude_teams,
                clear_soccer_mode=request.clear_soccer_mode,
                clear_soccer_followed_teams=request.clear_soccer_followed_teams,
                subscription_leagues=request.subscription_leagues,
                subscription_soccer_mode=request.subscription_soccer_mode,
                subscription_soccer_followed_teams=(
                [t.model_dump() for t in request.subscription_soccer_followed_teams]
            )
                if request.subscription_soccer_followed_teams
                else None,
                clear_subscription_leagues=request.clear_subscription_leagues,
                clear_subscription_soccer_mode=request.clear_subscription_soccer_mode,
                clear_subscription_soccer_followed_teams=request.clear_subscription_soccer_followed_teams,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from None

        # Clean up XMLTV content when group is disabled
        if request.enabled is False:

            delete_group_xmltv(conn, group_id)

        group = get_group(conn, group_id)
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Group {group_id} could not be loaded after update",
            )
        channel_count = get_group_channel_count(conn, group_id)

    logger.info("[UPDATED] Event group id=%d", group_id)

    return GroupResponse(
        id=group.id,
        name=group.name,
        display_name=group.display_name,
        leagues=group.leagues,
        soccer_mode=group.soccer_mode,
        soccer_followed_teams=[SoccerFollowedTeam(**t) for t in group.soccer_followed_teams]
        if group.soccer_followed_teams
        else None,
        channel_start_number=group.channel_start_number,
        stream_timezone=group.stream_timezone,
        duplicate_event_handling=group.duplicate_event_handling,
        channel_assignment_mode=group.channel_assignment_mode,
        sort_order=group.sort_order,
        total_stream_count=group.total_stream_count,
        m3u_group_id=group.m3u_group_id,
        m3u_group_name=group.m3u_group_name,
        m3u_account_id=group.m3u_account_id,
        m3u_account_name=group.m3u_account_name,
        stream_include_regex=group.stream_include_regex,
        stream_include_regex_enabled=group.stream_include_regex_enabled,
        stream_exclude_regex=group.stream_exclude_regex,
        stream_exclude_regex_enabled=group.stream_exclude_regex_enabled,
        custom_regex_teams=group.custom_regex_teams,
        custom_regex_teams_enabled=group.custom_regex_teams_enabled,
        custom_regex_date=group.custom_regex_date,
        custom_regex_date_enabled=group.custom_regex_date_enabled,
        custom_regex_month=group.custom_regex_month,
        custom_regex_month_enabled=group.custom_regex_month_enabled,
        custom_regex_day=group.custom_regex_day,
        custom_regex_day_enabled=group.custom_regex_day_enabled,
        custom_regex_time=group.custom_regex_time,
        custom_regex_time_enabled=group.custom_regex_time_enabled,
        custom_regex_league=group.custom_regex_league,
        custom_regex_league_enabled=group.custom_regex_league_enabled,
        custom_regex_fighters=group.custom_regex_fighters,
        custom_regex_fighters_enabled=group.custom_regex_fighters_enabled,
        custom_regex_event_name=group.custom_regex_event_name,
        custom_regex_event_name_enabled=group.custom_regex_event_name_enabled,
        skip_builtin_filter=group.skip_builtin_filter,
        name_match_enabled=group.name_match_enabled,
        team_streams_enabled=group.team_streams_enabled,
        epg_match_enabled=group.epg_match_enabled,
        include_teams=[TeamFilterEntry(**t) for t in group.include_teams]
        if group.include_teams
        else None,
        exclude_teams=[TeamFilterEntry(**t) for t in group.exclude_teams]
        if group.exclude_teams
        else None,
        team_filter_mode=group.team_filter_mode,
        last_refresh=group.last_refresh.isoformat() if group.last_refresh else None,
        stream_count=group.stream_count,
        matched_count=group.matched_count,
        filtered_stale=group.filtered_stale,
        filtered_include_regex=group.filtered_include_regex,
        filtered_exclude_regex=group.filtered_exclude_regex,
        filtered_not_event=group.filtered_not_event,
        filtered_team=group.filtered_team,
        failed_count=group.failed_count,
        streams_excluded=group.streams_excluded,
        excluded_event_final=group.excluded_event_final,
        excluded_event_past=group.excluded_event_past,
        excluded_before_window=group.excluded_before_window,
        excluded_league_not_included=group.excluded_league_not_included,
        channel_sort_order=group.channel_sort_order,
        overlap_handling=group.overlap_handling,
        enabled=group.enabled,
        subscription_leagues=group.subscription_leagues,
        subscription_soccer_mode=group.subscription_soccer_mode,
        subscription_soccer_followed_teams=(
            [SoccerFollowedTeam(**t) for t in group.subscription_soccer_followed_teams]
        )
        if group.subscription_soccer_followed_teams
        else None,
        created_at=group.created_at.isoformat() if group.created_at else None,
        updated_at=group.updated_at.isoformat() if group.updated_at else None,
        channel_count=channel_count,
    )


@router.delete("/{group_id}")
def delete_group_by_id(group_id: int) -> dict:
    """Delete an event EPG group.

    Warning: This will cascade delete all managed channels for this group.
    """

    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

        channel_count = get_group_channel_count(conn, group_id)
        delete_group(conn, group_id)

    logger.info(
        "[DELETED] Event group id=%d name=%s channels=%d", group_id, group.name, channel_count
    )

    return {
        "success": True,
        "message": f"Deleted group '{group.name}'",
        "channels_deleted": channel_count,
    }


@router.get("/{group_id}/stats", response_model=GroupStatsResponse)
def get_group_stats(group_id: int):
    """Get statistics for an event EPG group."""
    from teamarr.database.groups import get_group, get_group_stats

    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

        stats = get_group_stats(conn, group_id)

    return GroupStatsResponse(
        group_id=group_id,
        **stats,
    )


@router.post("/{group_id}/enable")
def enable_group(group_id: int) -> dict:
    """Enable an event EPG group."""

    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

        set_group_enabled(conn, group_id, True)

    return {"success": True, "message": f"Group '{group.name}' enabled"}


@router.post("/{group_id}/disable")
def disable_group(group_id: int) -> dict:
    """Disable an event EPG group."""

    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

        set_group_enabled(conn, group_id, False)

    return {"success": True, "message": f"Group '{group.name}' disabled"}


@router.post("/{group_id}/cache/clear", response_model=ClearCacheResponse)
def clear_group_match_cache(group_id: int):
    """Clear stream match cache for a specific event group.

    Forces re-matching on next EPG generation run. Useful when matching
    algorithm changes or cached matches are incorrect.
    """

    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

    entries_cleared, stats_cleared = clear_group_match_data(get_db, group_id)

    logger.info(
        "[CACHE_CLEAR] group_id=%d name=%s entries=%d stats_cleared=%d",
        group_id, group.name, entries_cleared, stats_cleared,
    )

    return ClearCacheResponse(
        success=True,
        group_id=group_id,
        group_name=group.name,
        entries_cleared=entries_cleared,
    )


@router.post("/cache/clear", response_model=ClearCacheResponse)
def clear_groups_match_cache(request: ClearCacheRequest):
    """Clear stream match cache for multiple event groups.

    Forces re-matching on next EPG generation run for all specified groups.
    """

    results: list[ClearCacheGroupResult] = []
    total_cleared = 0
    total_stats_cleared = 0

    with get_db() as conn:
        valid_group_ids = [
            group_id for group_id in request.group_ids if get_group(conn, group_id)
        ]

    for group_id in valid_group_ids:
        cleared, stats_cleared = clear_group_match_data(get_db, group_id)
        results.append(ClearCacheGroupResult(group_id=group_id, cleared=cleared))
        total_cleared += cleared
        total_stats_cleared += stats_cleared

    logger.info(
        "[CACHE_CLEAR_BULK] groups=%d total_cleared=%d total_stats_cleared=%d",
        len(results), total_cleared, total_stats_cleared,
    )

    return ClearCacheResponse(
        success=True,
        total_cleared=total_cleared,
        by_group=results,
    )


@router.post("/cache/clear-all", response_model=ClearCacheResponse)
def clear_all_match_cache():
    """Clear entire stream match cache for all groups.

    Forces re-matching on next EPG generation run for every group.
    """

    cleared, stats_cleared = clear_all_match_data(get_db)

    logger.info("[CACHE_CLEAR_ALL] Cleared %d entries stats_cleared=%d", cleared, stats_cleared)

    return ClearCacheResponse(
        success=True,
        total_cleared=cleared,
    )


# =============================================================================
# M3U GROUP DISCOVERY
# =============================================================================


@router.get("/m3u/groups", response_model=M3UGroupListResponse)
def list_m3u_groups():
    """List available M3U groups from Dispatcharr.

    Returns groups that can be used as stream sources for event EPG groups.
    """

    conn = get_dispatcharr_connection(get_db)
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr not configured or not connected",
        )

    try:
        groups = conn.m3u.list_groups()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch M3U groups: {e}",
        ) from e

    return M3UGroupListResponse(
        groups=[
            M3UGroupResponse(
                id=g.id,
                name=g.name,
                stream_count=getattr(g, "stream_count", None),
            )
            for g in groups
        ],
        total=len(groups),
    )


@router.get("/dispatcharr/channel-groups")
def list_dispatcharr_channel_groups() -> dict:
    """List available channel groups from Dispatcharr.

    Returns channel groups that can be assigned to event EPG groups.
    """

    conn = get_dispatcharr_connection(get_db)
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr not configured or not connected",
        )

    try:
        groups = conn.m3u.list_groups()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch channel groups: {e}",
        ) from e

    return {
        "groups": [{"id": g.id, "name": g.name} for g in groups],
        "total": len(groups),
    }


# =============================================================================
# GROUP PROCESSING
# =============================================================================


class PreviewStreamModel(BaseModel):
    """Individual stream preview result."""

    stream_id: int
    stream_name: str
    matched: bool
    event_id: str | None = None
    event_name: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    league: str | None = None
    start_time: str | None = None
    from_cache: bool = False
    exclusion_reason: str | None = None


class PreviewGroupResponse(BaseModel):
    """Response from previewing stream matches for a group."""

    group_id: int
    group_name: str
    total_streams: int
    filtered_count: int
    matched_count: int
    unmatched_count: int
    filtered_stale: int = 0
    filtered_not_event: int = 0
    filtered_include_regex: int = 0
    filtered_exclude_regex: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    streams: list[PreviewStreamModel]
    errors: list[str]


@router.get("/{group_id}/preview", response_model=PreviewGroupResponse)
def preview_group(group_id: int):
    """Preview stream matching for a group without creating channels.

    Fetches streams from Dispatcharr, filters them, matches them to events,
    but does NOT create channels or generate EPG.
    """
    from datetime import date


    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

    # Get Dispatcharr connection (has m3u manager)
    factory = get_factory(get_db)
    conn = factory.get_connection() if factory else None

    # Preview the group
    group_service = create_group_service(get_db, conn)
    result = group_service.preview_group(group_id, date.today())

    return PreviewGroupResponse(
        group_id=result.group_id,
        group_name=result.group_name,
        total_streams=result.total_streams,
        filtered_count=result.filtered_count,
        matched_count=result.matched_count,
        unmatched_count=result.unmatched_count,
        filtered_stale=result.filtered_stale,
        filtered_not_event=result.filtered_not_event,
        filtered_include_regex=result.filtered_include_regex,
        filtered_exclude_regex=result.filtered_exclude_regex,
        cache_hits=result.cache_hits,
        cache_misses=result.cache_misses,
        streams=[
            PreviewStreamModel(
                stream_id=s.stream_id,
                stream_name=s.stream_name,
                matched=s.matched,
                event_id=s.event_id,
                event_name=s.event_name,
                home_team=s.home_team,
                away_team=s.away_team,
                league=s.league,
                start_time=s.start_time,
                from_cache=s.from_cache,
                exclusion_reason=s.exclusion_reason,
            )
            for s in result.streams
        ],
        errors=result.errors,
    )


class RawStreamModel(BaseModel):
    """Stream info for regex testing with builtin filter status."""

    stream_id: int
    stream_name: str
    # Builtin filter results (None if passes, string describing why filtered)
    builtin_filtered: str | None = None


class RawStreamsResponse(BaseModel):
    """Response for raw streams endpoint."""

    group_id: int
    group_name: str
    total: int
    streams: list[RawStreamModel]


@router.get("/{group_id}/streams/raw", response_model=RawStreamsResponse)
def get_raw_streams(group_id: int):
    """Get raw stream names for a group without filtering or matching.

    Returns minimal stream data (id + name) for regex testing in the UI.
    Fetches directly from Dispatcharr without running the matching pipeline.
    """

    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

    factory = get_factory(get_db)
    if not factory:
        return RawStreamsResponse(
            group_id=group_id,
            group_name=group.name,
            total=0,
            streams=[],
        )

    conn = factory.get_connection()
    if not conn or not conn.m3u:
        return RawStreamsResponse(
            group_id=group_id,
            group_name=group.name,
            total=0,
            streams=[],
        )

    raw = conn.m3u.list_streams(
        group_id=group.m3u_group_id,
        account_id=group.m3u_account_id,
    )


    def get_builtin_filter_reason(name: str) -> str | None:
        """Check all builtin filters and return reason if filtered."""
        if is_placeholder(name):
            return "placeholder"
        sport = detect_sport_hint(name)
        if sport:
            hints = [sport] if isinstance(sport, str) else sport
            for s in hints:
                if s in UNSUPPORTED_SPORTS:
                    return f"unsupported_sport:{s}"
        if not is_event_stream(name):
            return "not_event"
        return None

    streams = sorted(
        (
            RawStreamModel(
                stream_id=s.id,
                stream_name=s.name,
                builtin_filtered=get_builtin_filter_reason(s.name),
            )
            for s in raw
        ),
        key=lambda s: natural_sort_key(s.stream_name),
    )

    return RawStreamsResponse(
        group_id=group_id,
        group_name=group.name,
        total=len(streams),
        streams=streams,
    )


# =============================================================================
# GROUP XMLTV ENDPOINTS
# =============================================================================


@router.get("/{group_id}/xmltv")
def get_group_xmltv(group_id: int) -> Response:
    """Get the stored XMLTV for an event group.

    This endpoint serves the XMLTV content that was generated when
    the group was last processed. Dispatcharr can be configured to
    fetch from this URL.

    Returns 404 if the group hasn't been processed yet.
    """

    with get_db() as conn:
        group = get_group(conn, group_id)
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Group {group_id} not found",
            )

        result = get_group_xmltv_with_metadata(conn, group_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No XMLTV generated for group '{group.name}'. Process the group first.",
            )

    xmltv_content, updated_at = result
    return Response(
        content=xmltv_content,
        media_type="application/xml",
        headers={
            "Content-Disposition": f"inline; filename=teamarr-group-{group_id}.xml",
            "X-Generated-At": updated_at,
        },
    )


@router.get("/xmltv/combined")
def get_combined_xmltv() -> Response:
    """Get combined XMLTV from all enabled event groups.

    Merges XMLTV content from all groups that have been processed.
    This is useful for having a single EPG source in Dispatcharr.
    """

    with get_db() as conn:
        xmltv_contents = get_all_group_xmltv(conn)

        if not xmltv_contents:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No XMLTV generated for any groups. Process groups first.",
            )

        display_settings = get_display_settings(conn)

    combined = merge_xmltv_content(
        xmltv_contents,
        generator_name=display_settings.xmltv_generator_name,
        generator_url=display_settings.xmltv_generator_url,
    )

    return Response(
        content=combined,
        media_type="application/xml",
        headers={"Content-Disposition": "inline; filename=teamarr-events.xml"},
    )
