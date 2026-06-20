"""Shared lightweight fakes for the test suite.

Each fake is the field-union of the per-file variants it replaced (iua3.5) —
a minimal duck-typed stand-in for the real dataclass/model, NOT a mirror of
the full schema. Add fields as tests need them; keep every field defaulted so
call sites stay keyword-only and construction stays cheap.

Single-use fakes (FakeDispatcharrChannel, FakeTemplate, FakeMappingSource,
...) stay local to their test file.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime


class FakeCache:
    """Minimal in-memory stand-in for the shared PersistentTTLCache.

    Stores values forever (TTLs are recorded in ``set_calls`` but not
    enforced) — within-one-run cache semantics, which is what service-layer
    tests exercise.
    """

    def __init__(self):
        self.data = {}
        self.set_calls = []

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value
        self.set_calls.append((key, value, ttl))

    def delete(self, key):
        self.data.pop(key, None)

    @contextmanager
    def lock_key(self, key):
        """No-op single-flight lock — get_events/get_event enter this before a
        provider fetch; the real PersistentTTLCache serializes concurrent
        misses, but tests run single-threaded so a bare yield suffices."""
        yield


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


# ---------------------------------------------------------------------------
# Matcher/processor factories (iua3.5 step 6)
#
# Prefer the REAL constructor wherever __init__ tolerates None deps (so a
# signature refactor is caught at test time). Only EventGroupProcessor keeps
# an object.__new__ bypass — its __init__ needs a live DB and service — and it
# lives here so a refactor breaks one factory, not N test files.
# ---------------------------------------------------------------------------


def make_team_matcher(service=None, cache=None, *, db_factory=None, days_ahead=3):
    """Real TeamMatcher via its constructor (db_factory=None → empty alias caches)."""
    from teamarr.consumers.matching.team_matcher import TeamMatcher

    return TeamMatcher(service, cache, db_factory=db_factory, days_ahead=days_ahead)


def make_stream_matcher(
    *,
    leagues=(),
    league_event_types=None,
    league_sports=None,
    team_streams_enabled=True,
    epg_index=None,
    user_tz=None,
):
    """Real StreamMatcher constructed with no service/DB.

    generation/days_ahead are pinned so __init__ never touches db_factory;
    league metadata (normally loaded from the DB during match_all) is set
    directly from the given dicts.
    """
    from zoneinfo import ZoneInfo

    from teamarr.consumers.matching.matcher import StreamMatcher

    m = StreamMatcher(
        service=None,
        db_factory=None,
        group_id=1,
        search_leagues=list(leagues),
        user_tz=user_tz or ZoneInfo("UTC"),
        generation=1,
        days_ahead=3,
        team_streams_enabled=team_streams_enabled,
        epg_index=epg_index,
    )
    m._league_event_types = dict(league_event_types or {})
    m._league_sports = dict(league_sports or {})
    return m


def make_bare_processor(**attrs):
    """EventGroupProcessor without running __init__ (which needs a live DB and
    service). Set only the attributes the test actually touches."""
    from teamarr.consumers.event_group_processor import EventGroupProcessor

    proc = object.__new__(EventGroupProcessor)
    for k, v in attrs.items():
        setattr(proc, k, v)
    return proc
