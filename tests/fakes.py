"""Shared lightweight fakes for the test suite.

Each fake is the field-union of the per-file variants it replaced (iua3.5) —
a minimal duck-typed stand-in for the real dataclass/model, NOT a mirror of
the full schema. Add fields as tests need them; keep every field defaulted so
call sites stay keyword-only and construction stays cheap.

Single-use fakes (FakeDispatcharrChannel, FakeTemplate, FakeMappingSource,
...) stay local to their test file.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FakeTeam:
    """Minimal Team stand-in."""

    id: str = "1"
    name: str = "Team A"
    abbreviation: str = "TA"


@dataclass
class FakeStatus:
    """Minimal EventStatus stand-in."""

    state: str = "pre"


@dataclass
class FakeEvent:
    """Minimal Event stand-in.

    Defaults are deliberately bland (nfl, no teams/status); tests that need a
    populated event pass explicit values or use a local wrapper.
    """

    id: str = "123"
    name: str = "Team A vs Team B"
    short_name: str = "A vs B"
    sport: str = "football"
    league: str = "nfl"
    provider: str = "espn"
    start_time: datetime | None = None
    home_team: FakeTeam | None = None
    away_team: FakeTeam | None = None
    venue: str | None = None
    broadcasts: list = field(default_factory=list)
    status: FakeStatus | None = None


def make_event(**overrides) -> FakeEvent:
    """A populated FakeEvent (teams, status, start_time set) with overrides."""
    defaults: dict = {
        "start_time": datetime(2026, 3, 1, 20, 0, tzinfo=UTC),
        "home_team": FakeTeam(),
        "away_team": FakeTeam(id="2", name="Team B", abbreviation="TB"),
        "status": FakeStatus(),
    }
    defaults.update(overrides)
    return FakeEvent(**defaults)


@dataclass
class FakeGroup:
    """Minimal EventEPGGroup stand-in."""

    id: int = 1
    name: str = "G"
    enabled: bool = True
    is_channel_source: bool = False
    # Subscription-scope overrides
    subscription_leagues: list[str] | None = None
    subscription_soccer_mode: str | None = None
    subscription_soccer_followed_teams: list[dict] | None = None
    # Team filter
    include_teams: list[dict] | None = None
    exclude_teams: list[dict] | None = None
    team_filter_mode: str = "include"
    bypass_filter_for_playoffs: bool | None = None


@dataclass
class FakeChannel:
    """Minimal managed-channel row stand-in (id + the fields cleanup logic reads)."""

    id: int
    dispatcharr_channel_id: int = 100
    channel_number: int = 1
    channel_name: str = "Ch"
    league: str | None = None
    event_epg_group_id: int | None = 1


@dataclass
class FakeManagedChannel:
    """Lightweight stand-in for ManagedChannel from the DB."""

    id: int = 1
    dispatcharr_channel_id: int = 100
    dispatcharr_uuid: str = "uuid-100"
    channel_name: str = "Test Channel"
    channel_number: str = "5001"
    tvg_id: str = "teamarr-event-123"
    event_id: str = "123"
    event_epg_group_id: int = 1
    channel_group_id: int = 10
    channel_profile_ids: str = "[0]"
    exception_keyword: str | None = None
    dispatcharr_logo_id: int | None = None
    logo_url: str | None = None
    scheduled_delete_at: str | None = None
    sport: str = "football"
    league: str = "nfl"
    event_date: str | None = None
    primary_stream_id: int | None = None


@dataclass
class FakeStream:
    """Minimal Dispatcharr stream stand-in."""

    dispatcharr_stream_id: int
    source_group_id: int | None


@dataclass
class FakeSubscription:
    """Minimal SportsSubscription stand-in."""

    leagues: list[str] = field(default_factory=lambda: ["nhl", "nba"])
    soccer_mode: str | None = None
    soccer_followed_teams: list[dict] | None = None
