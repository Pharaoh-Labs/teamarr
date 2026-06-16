"""Settings Pydantic models.

All request/response models for settings endpoints.
"""

from typing import Any

from pydantic import BaseModel, Field, field_serializer, field_validator

# Sentinel value for masked secrets in API responses.
# Update handlers should treat this as "unchanged" (skip update).
MASKED_SECRET = "********"


def unmask_or_skip(value: str | None) -> str | None:
    """Convert masked secret back to None so DB update skips the field."""
    return None if value == MASKED_SECRET else value


def _validate_profile_ids(v: Any) -> list[str | int] | None:
    """Validate channel_profile_ids accepts mixed int/str types.

    Pydantic v2 union validation can fail on mixed types when the first
    element is an int (it infers list[int] and rejects subsequent strings).
    This validator explicitly handles the mixed case.
    """
    if v is None:
        return None
    if not isinstance(v, list):
        return v
    result: list[str | int] = []
    for item in v:
        if isinstance(item, int):
            result.append(item)
        elif isinstance(item, str):
            # Keep wildcards as strings, convert numeric strings to int
            if item in ("{sport}", "{league}"):
                result.append(item)
            elif item.isdigit():
                result.append(int(item))
            else:
                result.append(item)
        else:
            # Let Pydantic handle invalid types
            result.append(item)
    return result


# =============================================================================
# DISPATCHARR SETTINGS
# =============================================================================


class DispatcharrSettingsModel(BaseModel):
    """Dispatcharr integration settings."""

    enabled: bool = False
    url: str | None = None
    username: str | None = None
    password: str | None = None

    @field_serializer("password")
    @classmethod
    def _mask_password(cls, v: str | None) -> str | None:
        return MASKED_SECRET if v else None
    epg_id: int | None = None
    # None = all profiles, [] = no profiles, [1,2,...] = specific profiles
    # Supports int IDs and string wildcards like "{sport}", "{league}"
    default_channel_profile_ids: list[str | int] | None = None
    # Default stream profile for event channels (overrideable per-group)
    default_stream_profile_id: int | None = None
    # Default channel group for event channels (overrideable per-league)
    default_channel_group_id: int | None = None
    # Channel group mode: 'static', 'sport', 'league', or custom pattern
    default_channel_group_mode: str | None = None
    # Clean up ALL unused logos in Dispatcharr after generation
    cleanup_unused_logos: bool = False

    @field_validator("default_channel_profile_ids", mode="before")
    @classmethod
    def validate_profile_ids(cls, v: Any) -> list[str | int] | None:
        return _validate_profile_ids(v)


class DispatcharrSettingsUpdate(BaseModel):
    """Update model for Dispatcharr settings (all fields optional)."""

    enabled: bool | None = None
    url: str | None = None
    username: str | None = None
    password: str | None = None
    epg_id: int | None = None
    default_channel_profile_ids: list[str | int] | None = None
    default_stream_profile_id: int | None = None
    default_channel_group_id: int | None = None
    default_channel_group_mode: str | None = None
    cleanup_unused_logos: bool | None = None

    @field_validator("default_channel_profile_ids", mode="before")
    @classmethod
    def validate_profile_ids(cls, v: Any) -> list[str | int] | None:
        return _validate_profile_ids(v)


class ConnectionTestRequest(BaseModel):
    """Request to test Dispatcharr connection."""

    url: str | None = Field(None, description="Override URL (uses saved if not provided)")
    username: str | None = Field(None, description="Override username")
    password: str | None = Field(None, description="Override password")


class ConnectionTestResponse(BaseModel):
    """Response from connection test."""

    success: bool
    url: str | None = None
    username: str | None = None
    version: str | None = None
    account_count: int | None = None
    group_count: int | None = None
    channel_count: int | None = None
    error: str | None = None


# =============================================================================
# LIFECYCLE SETTINGS
# =============================================================================


class LifecycleSettingsModel(BaseModel):
    """Channel lifecycle settings."""

    channel_create_timing: str = "same_day"
    channel_delete_timing: str = "same_day"
    channel_pre_buffer_minutes: int = 60
    channel_post_buffer_minutes: int = 60
    channel_range_start: int = 101
    channel_range_end: int | None = None


# =============================================================================
# RECONCILIATION SETTINGS
# =============================================================================


class ReconciliationSettingsModel(BaseModel):
    """Reconciliation settings."""

    reconcile_on_epg_generation: bool = True
    reconcile_on_startup: bool = True
    auto_fix_orphan_teamarr: bool = True
    auto_fix_orphan_dispatcharr: bool = True
    auto_fix_duplicates: bool = False
    default_duplicate_event_handling: str = "consolidate"
    channel_history_retention_days: int = 90


# =============================================================================
# SCHEDULER SETTINGS
# =============================================================================


class SchedulerSettingsModel(BaseModel):
    """Scheduler settings."""

    enabled: bool = True
    interval_minutes: int = 15
    # Scheduled channel reset (for Jellyfin logo cache issues)
    channel_reset_enabled: bool = False
    channel_reset_cron: str | None = None


class SchedulerSettingsUpdate(BaseModel):
    """Update model for scheduler settings (all fields optional)."""

    enabled: bool | None = None
    interval_minutes: int | None = None
    channel_reset_enabled: bool | None = None
    channel_reset_cron: str | None = None


class SchedulerStatusResponse(BaseModel):
    """Scheduler status response."""

    running: bool
    cron_expression: str | None = None
    last_run: str | None = None
    next_run: str | None = None


# =============================================================================
# EPG SETTINGS
# =============================================================================


class EPGSettingsModel(BaseModel):
    """EPG generation settings."""

    team_schedule_days_ahead: int = 30
    event_match_days_ahead: int = 3
    epg_output_days_ahead: int = 14
    epg_lookback_hours: int = 6
    epg_timezone: str = "America/New_York"
    epg_output_path: str = "./data/teamarr.xml"
    include_final_events: bool = False
    midnight_crossover_mode: str = "postgame"
    cron_expression: str = "0 * * * *"
    epg_xtream_fallback_enabled: bool = False
    epg_xtream_cache_hours: int = 24
    epg_channel_source_enabled: bool = False
    epg_channel_source_groups: list[int] = []
    epg_stream_pre_buffer_minutes: int = 60
    epg_stream_post_buffer_minutes: int = 60
    art_base_url: str = ""


# =============================================================================
# DURATION SETTINGS
# =============================================================================

# Dynamic dict - sports are defined in teamarr/database/settings/types.py DurationSettings
# No need to duplicate field definitions here
DurationSettingsModel = dict[str, float]


# =============================================================================
# DISPLAY SETTINGS
# =============================================================================


class DisplaySettingsModel(BaseModel):
    """Display and formatting settings."""

    time_format: str = "12h"
    show_timezone: bool = True
    channel_id_format: str = "{team_name_pascal}.{league_id}"
    xmltv_generator_name: str = "Teamarr"
    xmltv_generator_url: str = "https://github.com/Pharaoh-Labs/teamarr"
    tsdb_api_key: str | None = None  # Optional TheSportsDB premium API key

    @field_serializer("tsdb_api_key")
    @classmethod
    def _mask_tsdb_key(cls, v: str | None) -> str | None:
        return MASKED_SECRET if v else None


class TSDBKeyValidationRequest(BaseModel):
    """Request to validate a TSDB API key."""

    api_key: str = Field(..., description="TSDB API key to validate")


class TSDBKeyValidationResponse(BaseModel):
    """Response from TSDB API key validation."""

    valid: bool
    is_premium: bool = False
    message: str


# =============================================================================
# TEAM FILTER SETTINGS
# =============================================================================


class TeamFilterSettingsModel(BaseModel):
    """Default team filtering settings for event groups."""

    enabled: bool = True  # Master toggle - when False, filtering is skipped
    include_teams: list[dict] | None = None
    exclude_teams: list[dict] | None = None
    mode: str = "include"
    bypass_filter_for_playoffs: bool = False  # Include all playoff games


class TeamFilterSettingsUpdate(BaseModel):
    """Update model for team filter settings."""

    enabled: bool | None = None
    include_teams: list[dict] | None = None
    exclude_teams: list[dict] | None = None
    mode: str | None = None
    clear_include_teams: bool = False
    clear_exclude_teams: bool = False
    bypass_filter_for_playoffs: bool | None = None


# =============================================================================
# CHANNEL NUMBERING SETTINGS
# =============================================================================


class ChannelNumberingSettingsModel(BaseModel):
    """Global channel numbering and consolidation settings."""

    global_channel_mode: str = "auto"  # 'auto', 'manual'
    league_channel_starts: dict = {}  # {"nfl": 1001, "nba": 2001}
    global_consolidation_mode: str = "consolidate"  # 'consolidate', 'separate'


class ChannelNumberingSettingsUpdate(BaseModel):
    """Update model for channel numbering settings (all fields optional)."""

    global_channel_mode: str | None = None
    league_channel_starts: dict | None = None
    global_consolidation_mode: str | None = None


# =============================================================================
# STREAM ORDERING SETTINGS
# =============================================================================


class StreamOrderingRuleModel(BaseModel):
    """A single stream ordering rule."""

    type: str = Field(..., description="Rule type: 'm3u', 'group', or 'regex'")
    value: str = Field(..., description="M3U account name, group name, or regex pattern")
    priority: int = Field(..., ge=1, le=99, description="Priority (1-99, lower = higher)")


class StreamOrderingSettingsModel(BaseModel):
    """Stream ordering rules for prioritizing streams within channels."""

    rules: list[StreamOrderingRuleModel] = Field(
        default_factory=list, description="List of ordering rules, evaluated by priority"
    )


class StreamOrderingSettingsUpdate(BaseModel):
    """Update model for stream ordering settings (full replacement)."""

    rules: list[StreamOrderingRuleModel] = Field(
        ..., description="Complete list of rules (replaces existing)"
    )


# =============================================================================
# UPDATE CHECK SETTINGS
# =============================================================================


class UpdateCheckSettingsModel(BaseModel):
    """Update check and notification settings."""

    enabled: bool = True  # Master toggle for update checking
    notify_stable: bool = True  # Notify about stable releases
    notify_dev: bool = True  # Notify about dev builds (if running dev)
    github_owner: str = "Pharaoh-Labs"  # Repository owner (for forks)
    github_repo: str = "teamarr"  # Repository name (for forks)
    dev_branch: str = "dev"  # Branch to check for dev builds
    auto_detect_branch: bool = True  # Auto-detect branch from version string


class UpdateCheckSettingsUpdate(BaseModel):
    """Update model for update check settings (all fields optional)."""

    enabled: bool | None = None
    notify_stable: bool | None = None
    notify_dev: bool | None = None
    github_owner: str | None = None
    github_repo: str | None = None
    dev_branch: str | None = None
    auto_detect_branch: bool | None = None


class UpdateInfoModel(BaseModel):
    """Information about available updates."""

    current_version: str
    latest_version: str | None
    update_available: bool
    checked_at: str  # ISO timestamp
    build_type: str  # "stable", "dev", or "unknown"
    download_url: str | None = None
    latest_stable: str | None = None
    latest_dev: str | None = None
    latest_date: str | None = None  # ISO timestamp of when latest version was released


# =============================================================================
# FEED SEPARATION SETTINGS
# =============================================================================


class FeedSeparationSettingsModel(BaseModel):
    """Feed separation settings for HOME/AWAY stream detection."""

    enabled: bool = False  # Master toggle
    home_terms: list[str] = ["HOME"]  # Terms that indicate home feed
    away_terms: list[str] = ["AWAY"]  # Terms that indicate away feed
    detect_team_names: bool = True  # Also detect team names as feed indicators
    label_style: str = "team_name"  # 'team_name', 'short_name', 'home_away'


class FeedSeparationSettingsUpdate(BaseModel):
    """Update model for feed separation settings (all fields optional)."""

    enabled: bool | None = None
    home_terms: list[str] | None = None
    away_terms: list[str] | None = None
    detect_team_names: bool | None = None
    label_style: str | None = None


# =============================================================================
# EMBY SETTINGS
# =============================================================================


class EmbySettingsModel(BaseModel):
    """Emby integration settings."""

    enabled: bool = False
    url: str | None = None
    username: str | None = None
    password: str | None = None
    api_key: str | None = None

    @field_serializer("password")
    @classmethod
    def _mask_password(cls, v: str | None) -> str | None:
        return MASKED_SECRET if v else None

    @field_serializer("api_key")
    @classmethod
    def _mask_api_key(cls, v: str | None) -> str | None:
        return MASKED_SECRET if v else None


class EmbySettingsUpdate(BaseModel):
    """Update model for Emby settings (all fields optional)."""

    enabled: bool | None = None
    url: str | None = None
    username: str | None = None
    password: str | None = None
    api_key: str | None = None


class EmbyConnectionTestRequest(BaseModel):
    """Request to test Emby connection."""

    url: str | None = Field(
        None, description="Override URL (uses saved if not provided)"
    )
    username: str | None = Field(None, description="Override username")
    password: str | None = Field(None, description="Override password")
    api_key: str | None = Field(None, description="Override API key")


class EmbyConnectionTestResponse(BaseModel):
    """Response from Emby connection test."""

    success: bool
    server_name: str | None = None
    server_version: str | None = None
    error: str | None = None


# =============================================================================
# JELLYFIN SETTINGS
# =============================================================================


class JellyfinSettingsModel(BaseModel):
    """Jellyfin integration settings."""

    enabled: bool = False
    url: str | None = None
    username: str | None = None
    password: str | None = None
    api_key: str | None = None

    @field_serializer("password")
    @classmethod
    def _mask_password(cls, v: str | None) -> str | None:
        return MASKED_SECRET if v else None

    @field_serializer("api_key")
    @classmethod
    def _mask_api_key(cls, v: str | None) -> str | None:
        return MASKED_SECRET if v else None


class JellyfinSettingsUpdate(BaseModel):
    """Update model for Jellyfin settings (all fields optional)."""

    enabled: bool | None = None
    url: str | None = None
    username: str | None = None
    password: str | None = None
    api_key: str | None = None


class JellyfinConnectionTestRequest(BaseModel):
    """Request to test Jellyfin connection."""

    url: str | None = Field(
        None, description="Override URL (uses saved if not provided)"
    )
    username: str | None = Field(None, description="Override username")
    password: str | None = Field(None, description="Override password")
    api_key: str | None = Field(None, description="Override API key")


class JellyfinConnectionTestResponse(BaseModel):
    """Response from Jellyfin connection test."""

    success: bool
    server_name: str | None = None
    server_version: str | None = None
    error: str | None = None


# =============================================================================
# CHANNELS DVR SETTINGS
# =============================================================================


class ChannelsDVRSettingsModel(BaseModel):
    """Channels DVR integration settings."""

    enabled: bool = False
    url: str | None = None
    source_name: str | None = None
    lineup_id: str | None = None


class ChannelsDVRSettingsUpdate(BaseModel):
    """Update model for Channels DVR settings (all fields optional)."""

    enabled: bool | None = None
    url: str | None = None
    source_name: str | None = None
    lineup_id: str | None = None


class ChannelsDVRConnectionTestRequest(BaseModel):
    """Request to test Channels DVR connection."""

    url: str | None = Field(
        None, description="Override URL (uses saved if not provided)"
    )
    source_name: str | None = Field(None, description="Override source name")


class ChannelsDVRConnectionTestResponse(BaseModel):
    """Response from Channels DVR connection test."""

    success: bool
    server_version: str | None = None
    source_name: str | None = None
    error: str | None = None


class ChannelsDVRSourcesResponse(BaseModel):
    """List of M3U sources discovered on the Channels DVR server."""

    success: bool
    sources: list[str] = []
    error: str | None = None


class ChannelsDVRLineup(BaseModel):
    """An XMLTV lineup configured on the Channels DVR server."""

    id: str
    name: str


class ChannelsDVRLineupsResponse(BaseModel):
    """List of XMLTV lineups discovered on the Channels DVR server."""

    success: bool
    lineups: list[ChannelsDVRLineup] = []
    error: str | None = None


# =============================================================================
# ALL SETTINGS
# =============================================================================


class AllSettingsModel(BaseModel):
    """Complete application settings."""

    dispatcharr: DispatcharrSettingsModel
    lifecycle: LifecycleSettingsModel
    reconciliation: ReconciliationSettingsModel
    scheduler: SchedulerSettingsModel
    epg: EPGSettingsModel
    durations: DurationSettingsModel
    display: DisplaySettingsModel
    team_filter: TeamFilterSettingsModel | None = None
    channel_numbering: ChannelNumberingSettingsModel | None = None
    stream_ordering: StreamOrderingSettingsModel | None = None
    update_check: UpdateCheckSettingsModel | None = None
    feed_separation: FeedSeparationSettingsModel | None = None
    emby: EmbySettingsModel = EmbySettingsModel()
    jellyfin: JellyfinSettingsModel = JellyfinSettingsModel()
    channelsdvr: ChannelsDVRSettingsModel = ChannelsDVRSettingsModel()
    epg_generation_counter: int = 0
    schema_version: int = 44

    # UI timezone info (read-only, from environment or fallback to epg_timezone)
    ui_timezone: str = "America/New_York"
    ui_timezone_source: str = "epg"  # "env" if from UI_TIMEZONE env var, "epg" if fallback
