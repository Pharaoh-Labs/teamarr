"""Delete time must anchor to the session's own end, not the weekend's last one.

A race weekend is one Event with `sessions[]`; each session gets its own
channel (event_id `<id>-<segment>`). `get_event_end_time` always returned the
LAST session's end, so every session channel of the weekend was scheduled for
deletion after Sunday's race instead of after its own session. These tests pin
the delete-side mirror of the create-side fix (#550): each channel's delete
time derives from its own session, and callers passing no segment (or a
segment that is not a racing session, e.g. a UFC "prelims") are unchanged.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.lifecycle.timing import ChannelLifecycleManager
from teamarr.core import Event, EventStatus, RacingSession, Team
from teamarr.database.templates import EventTemplateConfig
from tests.fakes import FakeManagedChannel

# Sprint weekend on three days. Durations: 1h sessions, 3h race.
SPRINT_QUALI_START = datetime(2026, 8, 21, 15, 30, tzinfo=UTC)  # Fri
SPRINT_START = datetime(2026, 8, 22, 11, 0, tzinfo=UTC)  # Sat
QUALIFYING_START = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)  # Sat
RACE_START = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)  # Sun

POST_BUFFER = timedelta(minutes=30)

SESSION_STARTS = {
    "sprint_qualifying": SPRINT_QUALI_START,
    "sprint": SPRINT_START,
    "qualifying": QUALIFYING_START,
    "race": RACE_START,
}
SESSION_HOURS = {"sprint_qualifying": 1.0, "sprint": 1.0, "qualifying": 1.0, "race": 3.0}


def _sprint_weekend() -> Event:
    team = Team(
        id="1",
        provider="espn",
        name="Field",
        short_name="Field",
        abbreviation="FLD",
        league="f1",
        sport="racing",
    )
    return Event(
        id="9001",
        provider="espn",
        name="Grand Prix",
        short_name="GP",
        start_time=SPRINT_QUALI_START,  # provider anchors to first session
        home_team=team,
        away_team=team,
        status=EventStatus(state="scheduled"),
        league="f1",
        sport="racing",
        sessions=[
            RacingSession(
                code="sprint_qualifying", name="Sprint Qualifying", start_time=SPRINT_QUALI_START
            ),
            RacingSession(code="sprint", name="Sprint", start_time=SPRINT_START),
            RacingSession(code="qualifying", name="Qualifying", start_time=QUALIFYING_START),
            RacingSession(code="race", name="Race", start_time=RACE_START),
        ],
    )


def _manager(**kwargs) -> ChannelLifecycleManager:
    return ChannelLifecycleManager(
        delete_timing="after_event",
        post_buffer_minutes=30,
        default_duration_hours=3.0,
        sport_durations={"racing": 3.0},
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _utc_user(monkeypatch):
    monkeypatch.setattr("teamarr.utilities.tz.get_user_timezone", lambda: ZoneInfo("UTC"))


def _freeze_now(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr("teamarr.consumers.lifecycle.timing.now_user", lambda: now)


@pytest.mark.parametrize("code", list(SESSION_STARTS))
def test_each_session_deletes_after_its_own_end(code):
    expected_end = SESSION_STARTS[code] + timedelta(hours=SESSION_HOURS[code])

    manager = _manager()
    event = _sprint_weekend()

    assert manager.get_event_end_time(event, segment=code) == expected_end
    assert manager.calculate_delete_time(event, segment=code) == expected_end + POST_BUFFER


def test_race_channel_unchanged():
    manager = _manager()
    event = _sprint_weekend()

    assert manager.calculate_delete_time(event) == manager.calculate_delete_time(
        event, segment="race"
    )


def test_no_segment_keeps_last_session_behavior():
    manager = _manager()
    event = _sprint_weekend()

    assert manager.get_event_end_time(event) == RACE_START + timedelta(hours=3.0)
    assert manager.calculate_delete_time(event) == RACE_START + timedelta(hours=3.0) + POST_BUFFER


@pytest.mark.parametrize("segment", ["fp1", "prelims", "main_card", ""])
def test_unknown_segment_falls_back_to_last_session(segment):
    """A code with no matching session (including a UFC card segment) is a no-op."""
    manager = _manager()
    event = _sprint_weekend()

    assert manager.get_event_end_time(event, segment=segment) == manager.get_event_end_time(event)
    assert manager.calculate_delete_time(event, segment=segment) == manager.calculate_delete_time(
        event
    )


def test_mma_segment_on_sessionless_event_is_unchanged():
    """UFC/MMA events have no sessions; their segment keeps the event-level path."""
    manager = _manager()
    event = _sprint_weekend()
    object.__setattr__(event, "sessions", [])
    object.__setattr__(event, "sport", "mma")

    assert manager.get_event_end_time(event, segment="prelims") == manager.get_event_end_time(
        event
    )


def test_duration_override_applies_to_race_only():
    manager = _manager()
    event = _sprint_weekend()

    assert manager.get_event_end_time(event, 11.0, segment="race") == RACE_START + timedelta(
        hours=11.0
    )
    # A custom duration describes the race, not the sprint.
    assert manager.get_event_end_time(event, 11.0, segment="sprint") == SPRINT_START + timedelta(
        hours=1.0
    )
    assert manager.calculate_delete_time(event, 11.0, segment="qualifying") == (
        QUALIFYING_START + timedelta(hours=1.0) + POST_BUFFER
    )


def _same_day_manager() -> ChannelLifecycleManager:
    return ChannelLifecycleManager(
        delete_timing="same_day",
        post_buffer_minutes=60,
        default_duration_hours=3.0,
        sport_durations={"racing": 3.0},
    )


def test_same_day_delete_uses_session_day():
    """same_day: the sprint channel is reaped at 23:59 Saturday, not Sunday."""
    manager = _same_day_manager()
    event = _sprint_weekend()

    assert manager.calculate_delete_time(event, segment="sprint") == datetime(
        2026, 8, 22, 23, 59, 59, 999999, tzinfo=UTC
    )
    assert manager.calculate_delete_time(event, segment="race") == datetime(
        2026, 8, 23, 23, 59, 59, 999999, tzinfo=UTC
    )


def test_same_day_midnight_crossing_is_judged_within_the_session():
    """The crosses-midnight test pairs the session's start with its own end."""
    manager = _same_day_manager()
    event = _sprint_weekend()
    late = datetime(2026, 8, 22, 23, 30, tzinfo=UTC)  # 1h session ends Sunday 00:30
    object.__setattr__(
        event, "sessions", [*event.sessions, RacingSession(code="fp3", name="FP3", start_time=late)]
    )

    assert manager.calculate_delete_time(event, segment="fp3") == (
        late + timedelta(hours=1.0) + timedelta(minutes=60)
    )


def _duplicate_race_event() -> Event:
    """NASCAR-style weekend where one code runs three times (one shared channel)."""
    event = _sprint_weekend()
    first = datetime(2026, 8, 22, 3, 0, tzinfo=UTC)
    second = datetime(2026, 8, 23, 5, 0, tzinfo=UTC)
    object.__setattr__(
        event,
        "sessions",
        [
            RacingSession(code="race", name="Race", start_time=first),
            RacingSession(code="race", name="Race", start_time=second),
            RacingSession(code="race", name="Race", start_time=RACE_START),
        ],
    )
    return event


def test_duplicate_session_codes_use_the_latest(monkeypatch):
    manager = _manager(create_timing="same_day", include_final_events=True)
    event = _duplicate_race_event()

    assert manager.get_event_end_time(event, segment="race") == RACE_START + timedelta(hours=3.0)
    # Between the first and last runnings the shared channel is still live.
    _freeze_now(monkeypatch, datetime(2026, 8, 22, 10, 0, tzinfo=UTC))
    assert manager.categorize_event_timing(event, segment="race") is None
    _freeze_now(monkeypatch, datetime(2026, 8, 23, 9, 0, tzinfo=UTC))
    assert manager.categorize_event_timing(event, segment="race") is None


def test_categorize_treats_finished_sprint_as_past_while_race_upcoming(monkeypatch):
    from teamarr.consumers.matching.result import ExcludedReason

    manager = _manager(create_timing="same_day", include_final_events=True)
    event = _sprint_weekend()
    # Saturday evening: sprint (ended 12:00 + 30m buffer) is over, race is tomorrow.
    _freeze_now(monkeypatch, datetime(2026, 8, 22, 20, 0, tzinfo=UTC))

    assert manager.categorize_event_timing(event, segment="sprint") is ExcludedReason.EVENT_PAST
    assert manager.categorize_event_timing(event, segment="race") is None
    assert manager.categorize_event_timing(event) is None


def _service(db_factory):
    from teamarr.consumers.lifecycle.service import ChannelLifecycleService

    service = ChannelLifecycleService(
        db_factory=db_factory,
        sports_service=MagicMock(),
        channel_manager=MagicMock(),
        logo_manager=MagicMock(),
        epg_manager=MagicMock(),
    )
    service._timing_manager = _manager()
    return service


def test_creator_stores_session_delete_time(db_factory):
    from teamarr.dispatcharr.types import OperationResult

    service = _service(db_factory)
    service._channel_manager.create_channel.return_value = OperationResult(
        success=True, channel={"id": 100, "uuid": "uuid-100"}
    )
    expected_end = SPRINT_START + timedelta(hours=1.0)

    with (
        patch.object(service, "_generate_channel_name", return_value="Sprint"),
        patch.object(service, "_get_next_channel_number", return_value="5001"),
        patch.object(service, "_resolve_logo_url", return_value=None),
        patch("teamarr.database.channels.create_managed_channel", return_value=1) as create_db,
        patch("teamarr.database.channels.add_stream_to_channel"),
    ):
        result = service._create_channel(
            conn=MagicMock(),
            event=_sprint_weekend(),
            stream={"id": 456, "name": "Sprint"},
            group_config={"id": 1},
            template=None,
            matched_keyword=None,
            channel_group_id=10,
            channel_profile_ids=None,
            segment="sprint",
            segment_start=SPRINT_START,
        )

    assert result.success
    stored = create_db.call_args.kwargs
    assert stored["event_end_estimate"] == expected_end.isoformat()
    assert stored["scheduled_delete_at"] == (expected_end + POST_BUFFER).isoformat()


def _sync(service, db_conn, existing, segment="sprint"):
    with (
        patch.object(service, "_generate_channel_name", return_value="n"),
        patch.object(service, "_sync_channel_profiles"),
        patch.object(service, "_sync_channel_logo"),
        patch.object(service, "_sync_stream_profile"),
        patch("teamarr.database.channels.log_channel_history"),
        patch("teamarr.database.channels.update_managed_channel") as update,
    ):
        service._sync_channel_settings(
            conn=db_conn,
            existing=existing,
            stream={"id": 1},
            event=_sprint_weekend(),
            group_config={},
            template=EventTemplateConfig(game_duration_mode="sport"),
            segment=segment,
        )
    written = {}
    for call in update.call_args_list:
        written.update(call.args[2])
    return written


def test_syncer_keeps_session_delete_time(db_factory, db_conn):
    service = _service(db_factory)
    expected_end = SPRINT_START + timedelta(hours=1.0)
    # What the creator stored for the sprint channel.
    existing = FakeManagedChannel()
    existing.event_end_estimate = expected_end.isoformat()
    existing.scheduled_delete_at = (expected_end + POST_BUFFER).isoformat()

    written = _sync(service, db_conn, existing)

    # Already correct, so the sync must not rewrite it to the race's end.
    assert "event_end_estimate" not in written
    assert "scheduled_delete_at" not in written


def test_syncer_rewrites_stale_weekend_level_value(db_factory, db_conn):
    """Channels created before the fix hold the race's end; the sync repairs them."""
    service = _service(db_factory)
    race_end = RACE_START + timedelta(hours=3.0)
    existing = FakeManagedChannel()
    existing.event_end_estimate = race_end.isoformat()
    existing.scheduled_delete_at = (race_end + POST_BUFFER).isoformat()
    sprint_end = SPRINT_START + timedelta(hours=1.0)

    written = _sync(service, db_conn, existing)

    assert written["event_end_estimate"] == sprint_end.isoformat()
    assert written["scheduled_delete_at"] == (sprint_end + POST_BUFFER).isoformat()


@pytest.mark.parametrize("delete_timing", ["same_day", "after_event"])
def test_cleanup_recalc_agrees_with_creator_value(monkeypatch, tmp_path, delete_timing):
    """cleanup rebuilds the delete time from the stored row; it must not flap."""
    from teamarr.consumers.lifecycle.cleanup import ChannelCleanup
    from teamarr.database.connection import get_db, init_db

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    manager = ChannelLifecycleManager(
        delete_timing=delete_timing,
        post_buffer_minutes=60,
        default_duration_hours=3.0,
        sport_durations={"racing": 3.0},
    )
    event = _sprint_weekend()
    end = manager.get_event_end_time(event, segment="sprint")
    delete = manager.calculate_delete_time(event, segment="sprint")

    with get_db() as conn:
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (999993, 'g', '[\"f1\"]')"
        )
        conn.execute(
            """INSERT INTO managed_channels
               (id, event_id, event_provider, tvg_id, event_epg_group_id, channel_name,
                event_date, event_end_estimate, scheduled_delete_at, sport, league)
               VALUES (1, '9001-sprint', 'espn', 'tvg-1', 999993, 'Sprint', ?, ?, ?,
                       'racing', 'f1')""",
            (SPRINT_START.isoformat(), end.isoformat(), delete.isoformat()),
        )
        conn.commit()

    cleanup = ChannelCleanup.__new__(ChannelCleanup)
    cleanup._db_factory = get_db
    cleanup._timing_manager = manager
    with get_db() as conn:
        assert cleanup._recalculate_deletion_times(conn) == 0


def _truck_event() -> Event:
    """Three `race` runnings across days that share one channel (NASCAR Truck)."""
    event = _sprint_weekend()
    runs = [
        datetime(2026, 5, 22, 23, 0, tzinfo=UTC),
        datetime(2026, 5, 24, 1, 0, tzinfo=UTC),
        datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
    ]
    object.__setattr__(event, "start_time", runs[0])
    object.__setattr__(
        event, "sessions", [RacingSession(code="race", name="Race", start_time=t) for t in runs]
    )
    return event


@pytest.mark.parametrize("delete_timing", ["same_day", "after_event"])
def test_repeated_code_across_days_is_stable_under_cleanup(monkeypatch, tmp_path, delete_timing):
    """Shared channel: first running's start to last running's end, no flapping."""
    from teamarr.consumers.lifecycle.cleanup import ChannelCleanup
    from teamarr.database.connection import get_db, init_db

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    manager = ChannelLifecycleManager(
        delete_timing=delete_timing,
        post_buffer_minutes=60,
        default_duration_hours=3.0,
        sport_durations={"racing": 3.0},
    )
    event = _truck_event()
    end = manager.get_event_end_time(event, segment="race")
    delete = manager.calculate_delete_time(event, segment="race")

    assert delete == datetime(2026, 5, 24, 18, 0, tzinfo=UTC)

    with get_db() as conn:
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (999994, 'g', '[\"f1\"]')"
        )
        conn.execute(
            """INSERT INTO managed_channels
               (id, event_id, event_provider, tvg_id, event_epg_group_id, channel_name,
                event_date, event_end_estimate, scheduled_delete_at, sport, league)
               VALUES (1, '9001-race', 'espn', 'tvg-1', 999994, 'Race', ?, ?, ?,
                       'racing', 'f1')""",
            (event.start_time.isoformat(), end.isoformat(), delete.isoformat()),
        )
        conn.commit()

    cleanup = ChannelCleanup.__new__(ChannelCleanup)
    cleanup._db_factory = get_db
    cleanup._timing_manager = manager
    with get_db() as conn:
        assert cleanup._recalculate_deletion_times(conn) == 0
