"""Core data types for Teamarr v2.

All data structures are dataclasses with attribute access.
Provider-scoped IDs: every entity carries its `id` and `provider`.
"""

from dataclasses import dataclass, field
from datetime import datetime


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
    logo_url: str | None = None
    color: str | None = None


@dataclass(frozen=True)
class EventStatus:
    """Current state of an event."""

    state: str  # "scheduled" | "live" | "final" | "postponed" | "cancelled"
    detail: str | None = None
    period: int | None = None
    clock: str | None = None


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

    home_score: int | None = None
    away_score: int | None = None
    venue: Venue | None = None
    broadcasts: list[str] = field(default_factory=list)
    season_year: int | None = None
    season_type: str | None = None


@dataclass(frozen=True)
class TeamStats:
    """Team statistics for template variables."""

    record: str
    home_record: str | None = None
    away_record: str | None = None
    streak: str | None = None
    rank: int | None = None
    conference: str | None = None
    division: str | None = None


@dataclass
class Programme:
    """An XMLTV programme entry."""

    channel_id: str
    title: str
    start: datetime
    stop: datetime
    description: str | None = None
    category: str | None = None
    icon: str | None = None
    episode_num: str | None = None
