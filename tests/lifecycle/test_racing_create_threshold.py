"""Create threshold must anchor to the session's own start time (#550).

Racing anchors `event.start_time` to the weekend's FIRST broadcastable
session (e.g. Friday practice), so once practice entered the pre-buffer
window `should_create_channel` approved every session channel — the race-day
channel appeared up to ~35h early with a 1440-minute pre-buffer.

The delete side is already session-aware (`get_event_end_time`); these tests
pin the create side's mirror: each session channel's threshold derives from
its own `segment_start`, and callers passing no segment keep the old
event-anchored behavior.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.lifecycle.timing import ChannelLifecycleManager
from teamarr.core import Event, EventStatus, RacingSession, Team

# NASCAR-style weekend: practice Friday evening, race Sunday afternoon.
PRACTICE_START = datetime(2026, 8, 21, 22, 0, tzinfo=UTC)  # Fri
QUALIFYING_START = datetime(2026, 8, 22, 21, 0, tzinfo=UTC)  # Sat
RACE_START = datetime(2026, 8, 23, 18, 30, tzinfo=UTC)  # Sun


def _race_weekend() -> Event:
    team = Team(
        id="5620_1",
        provider="espn",
        name="Field",
        short_name="Field",
        abbreviation="FLD",
        league="nascar-cup",
        sport="racing",
    )
    return Event(
        id="5620",
        provider="espn",
        name="Iowa Corn 350",
        short_name="Iowa Corn 350",
        start_time=PRACTICE_START,  # provider anchors to first session
        home_team=team,
        away_team=team,
        status=EventStatus(state="scheduled"),
        league="nascar-cup",
        sport="racing",
        sessions=[
            RacingSession(code="practice", name="Practice", start_time=PRACTICE_START),
            RacingSession(code="qualifying", name="Qualifying", start_time=QUALIFYING_START),
            RacingSession(code="race", name="Race", start_time=RACE_START),
        ],
    )


@pytest.fixture(autouse=True)
def _utc_user(monkeypatch):
    monkeypatch.setattr("teamarr.utilities.tz.get_user_timezone", lambda: ZoneInfo("UTC"))


def _freeze_now(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr("teamarr.consumers.lifecycle.timing.now_user", lambda: now)


def test_race_channel_waits_for_its_own_session_before_event(monkeypatch):
    """1440-min pre-buffer + Friday practice must not create Sunday's race channel."""
    manager = ChannelLifecycleManager(create_timing="before_event", pre_buffer_minutes=1440)
    event = _race_weekend()
    # Practice is inside its window; the race is still ~44h out.
    _freeze_now(monkeypatch, datetime(2026, 8, 21, 22, 30, tzinfo=UTC))

    assert manager.should_create_channel(event, segment_start=PRACTICE_START).should_act
    assert not manager.should_create_channel(event, segment_start=RACE_START).should_act


def test_race_channel_created_once_race_enters_window(monkeypatch):
    manager = ChannelLifecycleManager(create_timing="before_event", pre_buffer_minutes=1440)
    event = _race_weekend()
    _freeze_now(monkeypatch, datetime(2026, 8, 22, 19, 0, tzinfo=UTC))  # Sat, <24h to race

    assert manager.should_create_channel(event, segment_start=RACE_START).should_act


def test_same_day_anchors_to_session_day(monkeypatch):
    """same_day mode: race channel appears at midnight of RACE day, not practice day."""
    manager = ChannelLifecycleManager(create_timing="same_day")
    event = _race_weekend()
    _freeze_now(monkeypatch, datetime(2026, 8, 21, 23, 0, tzinfo=UTC))  # Friday

    assert manager.should_create_channel(event, segment_start=PRACTICE_START).should_act
    assert not manager.should_create_channel(event, segment_start=RACE_START).should_act

    _freeze_now(monkeypatch, datetime(2026, 8, 23, 0, 1, tzinfo=UTC))  # Sunday 00:01
    assert manager.should_create_channel(event, segment_start=RACE_START).should_act


def test_no_segment_keeps_event_anchored_behavior(monkeypatch):
    """Non-segmented callers are unchanged: threshold from event.start_time."""
    manager = ChannelLifecycleManager(create_timing="before_event", pre_buffer_minutes=60)
    event = _race_weekend()
    _freeze_now(monkeypatch, datetime(2026, 8, 21, 21, 30, tzinfo=UTC))

    assert manager.should_create_channel(event).should_act
