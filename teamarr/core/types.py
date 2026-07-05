"""Core data types for Teamarr v2.

All data structures are dataclasses with attribute access.
Provider-scoped IDs: every entity carries its `id` and `provider`.
"""

from dataclasses import dataclass, field
from datetime import datetime

# --- Canonical season_type values ---
# Every provider normalizes its native season-type representation (ESPN
# integers/slugs, MLB StatsAPI gameType codes, etc.) to one of these strings
# before populating Event.season_type. Consumers and template variables
# compare against these constants — never against provider-native values.
SEASON_PRESEASON = "preseason"
SEASON_REGULAR = "regular"
SEASON_POSTSEASON = "postseason"
SEASON_OFFSEASON = "offseason"


@dataclass(frozen=True)
class Venue:
    """Event location."""

    name: str
    city: str | None = None
    state: str | None = None
    country: str | None = None


@dataclass(frozen=True)
class Team:
    """Team identity."""

    id: str
    provider: str
    name: str
    short_name: str
    abbreviation: str
    league: str
    sport: str  # e.g., "football", "basketball", "soccer"
    logo_url: str | None = None
    color: str | None = None
    # Combat sports: fighter record (e.g., "8-1-0" for W-L-D)
    record_summary: str | None = None


@dataclass(frozen=True)
class EventStatus:
    """Current state of an event."""

    state: str  # "scheduled" | "live" | "final" | "postponed" | "cancelled"
    detail: str | None = None
    period: int | None = None
    clock: str | None = None


@dataclass(frozen=True)
class Bout:
    """A single bout/fight on a combat sports card.

    Used for UFC, Boxing, and other combat sports events to track
    all matchups on the card, not just the headline bout.
    """

    fighter1: str  # First fighter name
    fighter2: str  # Second fighter name
    segment: str  # "early_prelims", "prelims", "main_card"
    order: int  # Position on card (0 = opener, higher = later)


@dataclass(frozen=True)
class RacingResult:
    """A single driver's result/grid slot for a racing session.

    Used for motorsports (F1, NASCAR, IndyCar, MotoGP, etc.) where each
    session (practice, qualifying, race) has its own ordered list of
    competitors.
    """

    driver_name: str
    team_name: str | None = None  # Constructor/team name
    position: int | None = None  # Finishing position (None if not yet run)
    grid_position: int | None = None  # Starting position for this session
    points: float | None = None  # Championship points earned
    fastest_lap: bool = False
    status: str | None = None  # "Finished", "DNF", "DNS", "+1 Lap", etc.


@dataclass(frozen=True)
class RacingSession:
    """A single session within a racing event (race weekend).

    Examples: Practice 1/2/3, Qualifying, Sprint, Race.
    """

    code: str  # "fp1", "fp2", "fp3", "qualifying", "sprint", "race"
    name: str  # "Practice 1", "Qualifying", "Race"
    start_time: datetime
    results: list["RacingResult"] = field(default_factory=list)


@dataclass
class Event:
    """A single sporting event (game/match)."""

    id: str
    provider: str
    name: str
    short_name: str
    start_time: datetime
    home_team: Team
    away_team: Team
    status: EventStatus
    league: str
    sport: str  # e.g., "football", "basketball", "soccer"

    home_score: int | None = None
    away_score: int | None = None
    venue: Venue | None = None
    broadcasts: list[str] = field(default_factory=list)
    season_year: int | None = None
    season_type: str | None = None

    # Betting odds (from scoreboard API, usually same-day only)
    odds_data: dict | None = None

    # Editorial/context copy from the provider — EPG-friendly form, dateline dash
    # stripped (empty when absent). All three come free from the scoreboard
    # payload — no per-event call. See
    # docs/reference/architecture/gracenote-template-design.md.
    game_recap: str = ""  # scoreboard headlines[type=Recap].shortLinkText (clean headline)
    game_event_note: str = ""  # notes[0].headline, e.g. "NBA Finals - Game 5"
    soccer_match_note: str = ""  # altGameNote, e.g. "FIFA World Cup, Group J"
    # Per-event tier — from the summary endpoint (overlaid by refresh_event_status,
    # which already fetches it, so zero extra calls).
    game_preview: str = ""  # summary article[type=Preview].description (pregame)
    series_summary: str = ""  # summary seasonseries[0].summary, e.g. "Series tied 1-1"

    # MMA-specific: when main card begins (prelims start at start_time)
    main_card_start: datetime | None = None

    # MMA-specific: exact segment times from ESPN bout-level data
    # Keys: "early_prelims", "prelims", "main_card"
    # Values: datetime of segment start
    segment_times: dict[str, datetime] = field(default_factory=dict)

    # MMA-specific: all bouts on the card (ordered by position)
    bouts: list["Bout"] = field(default_factory=list)

    # MMA-specific: fight result data (headline bout)
    # Method: 'ko', 'tko', 'submission', 'decision_unanimous', 'decision_split', 'decision_majority'
    fight_result_method: str | None = None
    finish_round: int | None = None  # Round fight ended (1-5)
    finish_time: str | None = None  # Time in round (e.g., "3:48")
    weight_class: str | None = None  # e.g., "Bantamweight", "Lightweight"
    # Judge scores for decisions (list of total scores per judge)
    fighter1_scores: list[int] | None = None  # home_team/fighter1 scores
    fighter2_scores: list[int] | None = None  # away_team/fighter2 scores

    # Racing-specific: circuit/track name (e.g., "Circuit de Monaco")
    circuit_name: str | None = None

    # Racing-specific: all sessions for the race weekend (Practice,
    # Qualifying, Race, etc.), ordered by start_time
    sessions: list["RacingSession"] = field(default_factory=list)

    # Racing-specific: scheduled lap count and distance (miles)
    race_laps: int | None = None
    race_distance_miles: float | None = None

    # Racing-specific: per-stage lap counts [stage1, stage2, stage3, ...]
    # Cumulative stage end laps: cumsum(stage_laps)
    stage_laps: list[int] = field(default_factory=list)

    # Tennis-specific: one Event per match; players ride home_team/away_team.
    # The tournament is context, not the event (ESPN: 1 scoreboard event =
    # 1 tournament, matches under groupings[].competitions[]).
    tournament_name: str | None = None  # e.g., "Wimbledon"
    round_name: str | None = None  # e.g., "Round 4", "Qualifying 1st Round"
    court: str | None = None  # e.g., "Centre Court", "No. 1 Court"
    draw_type: str | None = None  # e.g., "Men's Singles", "Mixed Doubles"


@dataclass(frozen=True)
class TeamStats:
    """Team statistics for template variables.

    Record fields store formatted strings like "10-2" or "8-3-1".
    Numeric fields store parsed values for calculations.
    """

    # Overall record
    record: str  # "10-2" or "8-3-1" (W-L or W-L-T)
    wins: int = 0
    losses: int = 0
    ties: int = 0

    # Home/away splits
    home_record: str | None = None
    away_record: str | None = None

    # Streak info
    streak: str | None = None  # "W3" or "L2" format
    streak_count: int = 0  # positive = wins, negative = losses

    # Rankings and standings
    rank: int | None = None  # College sports ranking (1-25, None if unranked)
    playoff_seed: int | None = None
    games_back: float | None = None

    # Conference/division
    conference: str | None = None  # Full name
    conference_abbrev: str | None = None
    division: str | None = None

    # Scoring stats
    ppg: float | None = None  # Points per game
    papg: float | None = None  # Points allowed per game

    # Racing-specific: championship standings
    championship_points: float | None = None
    championship_position: int | None = None
    constructor_name: str | None = None
    constructor_points: float | None = None


@dataclass
class Programme:
    """An XMLTV programme entry."""

    channel_id: str
    title: str
    start: datetime
    stop: datetime
    description: str | None = None
    subtitle: str | None = None
    icon: str | None = None
    episode_num: str | None = None
    # Filler type: 'pregame', 'postgame', 'idle', or None for actual events
    filler_type: str | None = None
    # Categories for XMLTV output (e.g., ["Sports", "Football", "NFL"])
    categories: list[str] = field(default_factory=list)
    # XMLTV flags: new, live, date
    xmltv_flags: dict = field(default_factory=dict)
    # XMLTV video: enabled, quality (HDTV/SDTV), aspect (16:9/4:3)
    xmltv_video: dict = field(default_factory=dict)


@dataclass
class TemplateConfig:
    """Template configuration for EPG generation.

    Used by TeamEPGGenerator for formatting main game programmes.
    All fields are required - templates MUST be loaded from the database.
    There are no hardcoded defaults to prevent silent fallback behavior.
    """

    title_format: str
    description_format: str
    subtitle_format: str
    program_art_url: str | None = None
    conditional_descriptions: list[dict] = field(default_factory=list)

    # V1 Parity: Duration override support
    game_duration_mode: str = "sport"  # 'sport', 'default', 'custom'
    game_duration_override: float | None = None

    # XMLTV metadata (no hardcoded defaults - schema.sql provides them)
    xmltv_flags: dict = field(default_factory=dict)
    xmltv_video: dict = field(default_factory=dict)
    xmltv_categories: list[str] = field(default_factory=list)
