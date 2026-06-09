"""Pydantic models for API requests and responses."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Teams
# =============================================================================


class TeamCreate(BaseModel):
    """Request body for creating a team."""

    provider: str = "espn"
    provider_team_id: str
    primary_league: str  # Main league for schedule lookups
    leagues: list[str] = []  # All leagues (includes primary)
    sport: str
    team_name: str
    team_abbrev: str | None = None
    team_logo_url: str | None = None
    team_color: str | None = None
    channel_id: str
    channel_logo_url: str | None = None
    template_id: int | None = None
    active: bool = True


class TeamUpdate(BaseModel):
    """Request body for updating a team."""

    team_name: str | None = None
    team_abbrev: str | None = None
    team_logo_url: str | None = None
    team_color: str | None = None
    channel_id: str | None = None
    channel_logo_url: str | None = None
    template_id: int | None = None
    active: bool | None = None
    primary_league: str | None = None
    leagues: list[str] | None = None


class TeamResponse(BaseModel):
    """Response body for a team."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    provider_team_id: str
    primary_league: str
    leagues: list[str]
    sport: str
    team_name: str
    team_abbrev: str | None
    team_logo_url: str | None
    team_color: str | None
    channel_id: str
    channel_logo_url: str | None
    template_id: int | None
    active: bool
    created_at: datetime
    updated_at: datetime


class TeamChannelStatusTeam(BaseModel):
    """Team fields included in the channel status response."""

    id: int
    provider: str
    provider_team_id: str
    primary_league: str
    leagues: list[str]
    sport: str
    team_name: str
    team_abbrev: str | None = None
    channel_id: str
    active: bool


class TeamChannelStatusDispatcharrChannel(BaseModel):
    """Dispatcharr channel mapping for a Teamarr team channel."""

    found: bool
    id: int | None = None
    uuid: str | None = None
    name: str | None = None
    channel_number: str | None = None
    tvg_id: str | None = None
    stream_count: int = 0
    streams: list[int] = Field(default_factory=list)
    error: str | None = None


class TeamChannelStatusProgramme(BaseModel):
    """Next live programme window for a Teamarr team channel."""

    found: bool
    start: datetime | None = None
    stop: datetime | None = None
    title: str | None = None
    sub_title: str | None = None
    is_live: bool = False
    source: str = "team_epg_xmltv"


class TeamChannelStatusResponse(BaseModel):
    """Combined status for a static Teamarr team channel."""

    team: TeamChannelStatusTeam
    dispatcharr_channel: TeamChannelStatusDispatcharrChannel
    next_live_window: TeamChannelStatusProgramme
    status: str
    missing: list[str] = Field(default_factory=list)
    xmltv_updated_at: datetime | None = None


# =============================================================================
# Templates
# =============================================================================


class PregamePeriod(BaseModel):
    """A pregame filler period."""

    start_hours_before: float
    end_hours_before: float
    title: str | None = ""
    description: str | None = ""


class PostgamePeriod(BaseModel):
    """A postgame filler period."""

    start_hours_after: float
    end_hours_after: float
    title: str | None = ""
    description: str | None = ""


class FillerFallback(BaseModel):
    """Fallback content for filler."""

    title: str | None = ""
    subtitle: str | None = None
    description: str | None = ""
    art_url: str | None = None


class ConditionalContent(BaseModel):
    """Conditional content settings based on game status (final/not final).

    Used for postgame and idle filler to show different content based on
    whether the relevant game (last game for postgame/idle) is final.
    """

    enabled: bool = False
    title_final: str | None = None
    title_not_final: str | None = None
    subtitle_final: str | None = None
    subtitle_not_final: str | None = None
    description_final: str | None = None
    description_not_final: str | None = None


class IdleOffseasonContent(BaseModel):
    """Offseason content settings (no game in 30-day lookahead).

    Each field (title, subtitle, description) can be independently enabled
    to override the default idle content when there's no upcoming game.
    """

    title_enabled: bool = False
    title: str | None = None
    subtitle_enabled: bool = False
    subtitle: str | None = None
    description_enabled: bool = False
    description: str | None = "No upcoming {team_name} games scheduled."


class ConditionalDescriptionEntry(BaseModel):
    """A conditional description entry."""

    condition: str | None = None  # None for default descriptions (priority=100)
    condition_value: str | None = None
    template: str
    priority: int = 50
    label: str | None = None  # Optional label for default descriptions


class TemplateCreate(BaseModel):
    """Request body for creating a template."""

    name: str
    template_type: str = "team"
    sport: str | None = None
    league: str | None = None

    # Programme formatting
    title_format: str = "{team_name} {sport}"
    subtitle_template: str | None = "{venue_full}"
    description_template: str | None = "{matchup} | {venue_full}"
    program_art_url: str | None = None

    # Game duration
    game_duration_mode: str = "sport"
    game_duration_override: float | None = None

    # XMLTV metadata
    xmltv_flags: dict | None = None
    xmltv_video: dict | None = None
    xmltv_categories: list[str] | None = None
    xmltv_filler_categories: list[str] | None = None

    # Filler: Pregame
    pregame_enabled: bool = True
    pregame_periods: list[PregamePeriod] | None = None
    pregame_fallback: FillerFallback | None = None

    # Filler: Postgame
    postgame_enabled: bool = True
    postgame_periods: list[PostgamePeriod] | None = None
    postgame_fallback: FillerFallback | None = None
    postgame_conditional: ConditionalContent | None = None

    # Filler: Idle
    idle_enabled: bool = True
    idle_content: FillerFallback | None = None
    idle_conditional: ConditionalContent | None = None
    idle_offseason: IdleOffseasonContent | None = None

    # Conditional descriptions
    conditional_descriptions: list[ConditionalDescriptionEntry] | None = None

    # Event template specific
    event_channel_name: str | None = None
    event_channel_logo_url: str | None = None


class TemplateUpdate(BaseModel):
    """Request body for updating a template."""

    name: str | None = None
    sport: str | None = None
    league: str | None = None
    title_format: str | None = None
    subtitle_template: str | None = None
    description_template: str | None = None
    program_art_url: str | None = None
    game_duration_mode: str | None = None
    game_duration_override: float | None = None

    # XMLTV metadata
    xmltv_flags: dict | None = None
    xmltv_video: dict | None = None
    xmltv_categories: list[str] | None = None
    xmltv_filler_categories: list[str] | None = None

    # Filler toggles
    pregame_enabled: bool | None = None
    pregame_fallback: FillerFallback | None = None
    postgame_enabled: bool | None = None
    postgame_fallback: FillerFallback | None = None
    postgame_conditional: ConditionalContent | None = None
    idle_enabled: bool | None = None
    idle_content: FillerFallback | None = None
    idle_conditional: ConditionalContent | None = None
    idle_offseason: IdleOffseasonContent | None = None

    # Conditional descriptions
    conditional_descriptions: list[ConditionalDescriptionEntry] | None = None

    # Event template specific
    event_channel_name: str | None = None
    event_channel_logo_url: str | None = None


class TemplateResponse(BaseModel):
    """Response body for a template."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    template_type: str
    sport: str | None
    league: str | None
    title_format: str | None
    subtitle_template: str | None
    program_art_url: str | None
    game_duration_mode: str | None
    game_duration_override: float | None
    pregame_enabled: bool | None
    postgame_enabled: bool | None
    idle_enabled: bool | None
    created_at: datetime
    updated_at: datetime
    # Usage counts from list query
    team_count: int | None = None
    global_assignments: list[dict] | None = None


class TemplateFullResponse(TemplateResponse):
    """Full template response including JSON fields."""

    xmltv_flags: dict | None = None
    xmltv_video: dict | None = None
    xmltv_categories: list[str] | None = None
    xmltv_filler_categories: list[str] | None = None
    pregame_periods: list[dict] | None = None
    pregame_fallback: dict | None = None
    postgame_periods: list[dict] | None = None
    postgame_fallback: dict | None = None
    postgame_conditional: dict | None = None
    idle_content: dict | None = None
    idle_conditional: dict | None = None
    idle_offseason: dict | None = None
    conditional_descriptions: list[dict] | None = None
    event_channel_name: str | None = None
    event_channel_logo_url: str | None = None


# =============================================================================
# EPG
# =============================================================================


class EPGGenerateRequest(BaseModel):
    """Request body for team-based EPG generation."""

    team_ids: list[int] | None = None  # None = all active teams
    days_ahead: int | None = None  # None = use settings default


class MatchStats(BaseModel):
    """Match statistics from stream matching."""

    streams_fetched: int = 0
    streams_filtered: int = 0  # Excluded before matching (not event-like)
    streams_eligible: int = 0  # Available for matching (fetched - filtered)
    streams_matched: int = 0
    streams_unmatched: int = 0
    streams_cached: int = 0
    match_rate: float = 0.0  # matched / eligible * 100


class EPGGenerateResponse(BaseModel):
    """Response body for EPG generation."""

    programmes_count: int
    teams_processed: int
    events_processed: int = 0
    duration_seconds: float
    run_id: int | None = None
    match_stats: MatchStats | None = None


# =============================================================================
# Match Correction Models (Phase 7)
# =============================================================================


class MatchCorrectionRequest(BaseModel):
    """Request to correct a stream match."""

    group_id: int = Field(..., description="Event group ID where stream is located")
    stream_id: int = Field(..., description="Stream ID being corrected")
    stream_name: str = Field(..., description="Stream name for verification")
    correct_event_id: str | None = Field(None, description="Correct event ID (None = no event)")
    correct_league: str | None = Field(None, description="Correct league code")
    notes: str | None = Field(None, description="Optional notes about the correction")


class MatchCorrectionResponse(BaseModel):
    """Response after applying a match correction."""

    success: bool
    fingerprint: str
    message: str
    previous_event_id: str | None = None
    new_event_id: str | None = None


class EventSearchResult(BaseModel):
    """Event search result for correction UI."""

    event_id: str
    event_name: str
    league: str
    league_name: str | None = None
    start_time: str
    home_team: str | None = None
    away_team: str | None = None
    status: str | None = None


class GameDataCacheStats(BaseModel):
    """Game data cache statistics."""

    total_entries: int
    active_entries: int
    expired_entries: int
    hits: int
    misses: int
    hit_rate: float
    pending_writes: int
    pending_deletes: int


class GameDataCacheClearResponse(BaseModel):
    """Response after clearing game data cache."""

    success: bool
    entries_cleared: int
    message: str
