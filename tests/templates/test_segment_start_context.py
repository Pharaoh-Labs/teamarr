"""A segment channel's template context is anchored to its own segment (#1148).

A race weekend is one Event whose `sessions[]` each get a channel, and
`event.start_time` is the weekend's first session. The guide path swapped
the session start into the event before resolving, but the channel-name
path (creation and the sync rename) passed only the segment code, so
`{game_time}` / `{game_day_short}` in a session channel's name printed
Practice 1's time on every channel. The context builder now does the swap
for every reader — name, logo URL, conditions, guide — from the event's own
session (or ESPN's MMA `segment_times`), so the two paths cannot disagree.
"""

from datetime import UTC, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.lifecycle.naming import ChannelNaming
from teamarr.core.types import Event, EventStatus, RacingSession, Team
from teamarr.database.templates import EventTemplateConfig
from teamarr.services import league_mappings as lm
from teamarr.services.sports_data import SportsDataService
from teamarr.templates.context_builder import ContextBuilder, segment_start_time
from teamarr.templates.resolver import TemplateResolver

FP1_START = datetime(2026, 10, 23, 17, 30, tzinfo=UTC)  # Fri 13:30 EDT
FP2_START = datetime(2026, 10, 23, 21, 0, tzinfo=UTC)  # Fri 17:00 EDT
QUALI_START = datetime(2026, 10, 24, 21, 0, tzinfo=UTC)  # Sat 17:00 EDT
RACE_START = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)  # Sun 16:00 EDT


def _field() -> Team:
    return Team(
        id="1",
        provider="espn",
        name="Field",
        short_name="Field",
        abbreviation="FLD",
        league="f1",
        sport="racing",
    )


def _weekend() -> Event:
    return Event(
        id="600057446",
        provider="espn",
        name="United States Grand Prix",
        short_name="US GP",
        start_time=FP1_START,  # provider anchors to the first session
        home_team=_field(),
        away_team=_field(),
        status=EventStatus(state="scheduled"),
        league="f1",
        sport="racing",
        sessions=[
            RacingSession(code="fp1", name="Practice 1", start_time=FP1_START),
            RacingSession(code="fp2", name="Practice 2", start_time=FP2_START),
            RacingSession(code="qualifying", name="Qualifying", start_time=QUALI_START),
            RacingSession(code="race", name="Race", start_time=RACE_START),
        ],
    )


def _card() -> Event:
    team = Team(
        id="f1",
        provider="espn",
        name="Fighter A",
        short_name="A",
        abbreviation="A",
        league="ufc",
        sport="mma",
    )
    return Event(
        id="401",
        provider="espn",
        name="UFC 335",
        short_name="UFC 335",
        start_time=datetime(2026, 11, 7, 22, 0, tzinfo=UTC),
        home_team=team,
        away_team=team,
        status=EventStatus(state="scheduled"),
        league="ufc",
        sport="mma",
        segment_times={
            "prelims": datetime(2026, 11, 7, 22, 0, tzinfo=UTC),
            "main_card": datetime(2026, 11, 8, 2, 0, tzinfo=UTC),
        },
    )


@pytest.fixture(autouse=True)
def real_league_service(db_factory):
    # The resolver builds every variable, `{league}` included, so the mapping
    # service must exist even for a template that never names it.
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


@pytest.fixture(autouse=True)
def _eastern_user(monkeypatch):
    monkeypatch.setattr(
        "teamarr.utilities.tz.get_user_timezone", lambda: ZoneInfo("America/New_York")
    )


@pytest.fixture
def naming():
    service = SportsDataService(providers=[])
    with (
        patch.object(service, "enrich_event_preview", side_effect=lambda e: e),
        patch.object(service, "get_team_stats", return_value=None),
    ):
        n = ChannelNaming()
        n._context_builder = ContextBuilder(service)
        n._resolver = TemplateResolver("")
        yield n


TEMPLATE = EventTemplateConfig(
    channel_name_format="F1 | {session_name} · {game_day_short} {game_time}",
    event_channel_logo_url="art/{game_date_short}/{session_type}.png",
)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("fp1", "F1 | Practice 1 · Fri 1:30 PM EDT"),
        ("fp2", "F1 | Practice 2 · Fri 5:00 PM EDT"),
        ("qualifying", "F1 | Qualifying · Sat 5:00 PM EDT"),
        ("race", "F1 | Race · Sun 4:00 PM EDT"),
    ],
)
def test_session_channel_name_reads_its_own_session_time(naming, code, expected):
    # The reporter's template: every session channel used to read Practice 1's
    # day and time while the guide showed each session's own.
    assert naming._generate_channel_name(_weekend(), TEMPLATE, None, segment=code) == expected


def test_logo_url_reads_the_session_date(naming):
    assert naming._resolve_logo_url(_weekend(), TEMPLATE, segment="race") == ("art/Oct 25/race.png")


def test_sync_rename_resolves_like_creation(naming):
    # The sync path passes only the segment code (no segment_start), so the
    # anchor must come from the event itself or existing channels flap.
    event = _weekend()
    assert naming._generate_channel_name(
        event, TEMPLATE, None, segment="race"
    ) == naming._generate_channel_name(event, TEMPLATE, None, segment="race")
    assert "Sun 4:00 PM" in naming._generate_channel_name(event, TEMPLATE, None, segment="race")


def test_no_segment_keeps_the_event_start(naming):
    assert naming._generate_channel_name(_weekend(), TEMPLATE, None) == "F1 | · Fri 1:30 PM EDT"


def test_unknown_segment_keeps_the_event_start():
    event = _weekend()
    assert segment_start_time(event, "prelims") is None
    assert segment_start_time(event, None) is None


def test_repeated_session_code_anchors_to_the_earliest_running():
    # Three `race` runnings share one channel (same rule as lifecycle timing).
    event = _weekend()
    later = RacingSession(code="race", name="Race 2", start_time=RACE_START.replace(hour=23))
    event.sessions.append(later)
    assert segment_start_time(event, "race") == RACE_START


def test_mma_card_segment_reads_espn_segment_time(naming):
    template = EventTemplateConfig(channel_name_format="{card_segment_display} {game_time}")
    assert naming._generate_channel_name(_card(), template, None, segment="main_card") == (
        "Main Card 9:00 PM EST"
    )
    assert naming._generate_channel_name(_card(), template, None, segment="prelims") == (
        "Prelims 5:00 PM EST"
    )
