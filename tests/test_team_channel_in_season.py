"""In-season lifecycle for managed team channels (#1206).

``in_season`` is the game-days arrangement (#904) with a wider rule: the
Dispatcharr channel exists while the team has a game inside the Team EPG
schedule look-ahead, and is removed when it has none. The ownership row, and
so the reserved number, is kept either way. Every read that could tear a
channel down is exercised in its failure mode, as for game days (#826).
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from teamarr.database.managed_team_channels import get_managed_team_channel
from teamarr.services.team_channel_manager import TeamChannelManager
from tests.services import test_team_channel_lifecycle as game_days
from tests.services.test_team_channel_lifecycle import (
    FakeSports,
    Game,
    Timing,
    _manager,
    _owned,
    _team,
)
from tests.services.test_team_channel_manager import FakeChannels, _factory, _ok

# The bare schema the game-days tests run on (no settings columns, so the
# look-ahead reads as its default of 30 days).
conn = game_days.conn

LOOK_AHEAD_DAYS = 30


def _global(monkeypatch, lifecycle):
    import teamarr.services.team_channel_manager as module

    monkeypatch.setattr(
        module,
        "get_managed_team_channel_settings",
        lambda _: SimpleNamespace(
            range_start=9000, range_end=9005, priority_ids=[], lifecycle=lifecycle
        ),
    )


@pytest.fixture
def settings(monkeypatch):
    import teamarr.services.team_channel_manager as module

    monkeypatch.setattr(module, "get_channel_stability_settings", lambda _: {"mode": "compact"})
    _global(monkeypatch, "in_season")
    monkeypatch.setattr(
        module,
        "get_dispatcharr_settings",
        lambda _: SimpleNamespace(
            default_channel_group_id=7,
            default_channel_profile_ids=[3],
            default_stream_profile_id=4,
            managed_team_channel_group_id=None,
            managed_team_channel_profile_ids=None,
        ),
    )
    monkeypatch.setattr(TeamChannelManager, "_timing_manager", staticmethod(lambda _: Timing()))


def _in(**delta):
    return [Game("g1", datetime.now(UTC) + timedelta(**delta))]


def _attach_stream(conn):
    now = datetime.now(UTC)
    fmt = "%Y-%m-%d %H:%M:%S"
    conn.execute(
        "INSERT INTO managed_team_channel_streams (team_id, dispatcharr_stream_id, event_id,"
        " event_provider, source_group_id, priority, attach_at, detach_at) VALUES"
        " (1, 700, 'g9', 'espn', 3, 1, ?, ?)",
        ((now - timedelta(hours=1)).strftime(fmt), (now + timedelta(hours=1)).strftime(fmt)),
    )


# --- the rule ---------------------------------------------------------------


def test_lifecycle_for_knows_three_values_and_the_team_wins():
    resolve = TeamChannelManager._lifecycle_for

    def glob(value):
        return SimpleNamespace(lifecycle=value)

    assert resolve({}, glob("in_season")) == "in_season"
    assert resolve({}, glob("game_days")) == "game_days"
    assert resolve({}, glob("persistent")) == "persistent"
    assert resolve({"managed_channel_lifecycle": "in_season"}, glob("persistent")) == "in_season"
    assert resolve({"managed_channel_lifecycle": "persistent"}, glob("in_season")) == "persistent"
    assert resolve({"managed_channel_lifecycle": "game_days"}, glob("in_season")) == "game_days"
    assert resolve({"managed_channel_lifecycle": "junk"}, glob("in_season")) == "persistent"
    assert resolve({}, glob("junk")) == "persistent"
    assert resolve({}, glob(None)) == "persistent"


def test_upcoming_game_creates_the_channel(conn, settings):
    _team(conn)
    channels = FakeChannels()
    sports = FakeSports(_in(days=10))

    result = _manager(conn, channels, sports).sync()

    assert result == _ok(created=1)
    assert channels.created[0]["tvg_id"] == "team-blue"
    assert channels.created[0]["channel_number"] == 9000
    assert get_managed_team_channel(conn, 1).sync_status == "ready"
    assert sports.calls == [("10", "nba", LOOK_AHEAD_DAYS)]


def test_upcoming_game_keeps_an_owned_channel(conn, settings):
    _team(conn)
    channels = FakeChannels([_owned(conn)])

    result = _manager(conn, channels, FakeSports(_in(days=10))).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []


def test_game_in_its_window_is_wanted(conn, settings):
    """Started an hour ago: no longer upcoming, still inside create/delete."""
    _team(conn)
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(_in(hours=-1))).sync()

    assert result == _ok(created=1)


def test_empty_schedule_reserves_the_number_without_a_channel(conn, settings):
    _team(conn)
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports([])).sync()

    assert result == _ok(idle=1)
    assert channels.created == []
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.sync_status == "idle"
    assert mapping.dispatcharr_channel_id is None
    assert mapping.channel_number == 9000
    assert mapping.sync_message == f"Off-season: no game in the next {LOOK_AHEAD_DAYS} days"


def test_empty_schedule_removes_the_owned_channel_and_keeps_the_row(conn, settings):
    _team(conn)
    channels = FakeChannels([_owned(conn)])

    result = _manager(conn, channels, FakeSports([])).sync()

    assert result == _ok(idle=1, hibernated=1)
    assert channels.deleted == [50]
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.sync_status == "idle"
    assert mapping.dispatcharr_channel_id is None
    assert mapping.dispatcharr_uuid is None
    assert mapping.channel_number == 9000


def test_only_past_games_is_off_season(conn, settings):
    _team(conn)
    channels = FakeChannels([_owned(conn)])
    past = [
        Game("p1", datetime.now(UTC) - timedelta(days=40)),
        Game("p2", datetime.now(UTC) - timedelta(days=2)),
    ]

    result = _manager(conn, channels, FakeSports(past)).sync()

    assert result == _ok(idle=1, hibernated=1)
    assert channels.deleted == [50]
    assert get_managed_team_channel(conn, 1).sync_message.startswith("Off-season")


def test_game_past_the_look_ahead_is_off_season(conn, settings):
    """A provider may list the whole season; only the look-ahead counts."""
    _team(conn)
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(_in(days=LOOK_AHEAD_DAYS + 15))).sync()

    assert result == _ok(idle=1)
    message = get_managed_team_channel(conn, 1).sync_message
    assert message.startswith("Off-season") and "next" in message


def test_returning_channel_takes_its_reserved_number(conn, settings):
    _team(conn)
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, NULL, NULL, 9003, 'idle', 'x', NULL, NULL)"
    )
    conn.execute("UPDATE teams SET managed_channel_number = 9003 WHERE id = 1")
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(_in(days=10))).sync()

    assert result == _ok(created=1)
    assert channels.created[0]["channel_number"] == 9003
    assert channels.created[0]["tvg_id"] == "team-blue"


def test_inactive_team_goes_dormant(conn, settings):
    _team(conn, active=0)
    channels = FakeChannels([_owned(conn)])
    sports = FakeSports(_in(days=10))

    result = _manager(conn, channels, sports).sync()

    assert result == _ok(idle=1, hibernated=1)
    assert sports.calls == []


# --- overrides ----------------------------------------------------------------


def test_team_in_season_beats_global_persistent(conn, settings, monkeypatch):
    _global(monkeypatch, "persistent")
    _team(conn, lifecycle="in_season")
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports([])).sync()

    assert result == _ok(idle=1)
    assert channels.created == []


def test_team_persistent_beats_global_in_season(conn, settings):
    _team(conn, lifecycle="persistent")
    channels = FakeChannels()
    sports = FakeSports([])

    result = _manager(conn, channels, sports).sync()

    assert result == _ok(created=1)
    assert sports.calls == []


def test_team_game_days_under_global_in_season_keeps_the_game_days_rule(conn, settings):
    """A game ten days out is in season, and not a game day."""
    _team(conn, lifecycle="game_days")
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(_in(days=10))).sync()

    assert result == _ok(idle=1)
    assert "next" in get_managed_team_channel(conn, 1).sync_message


# --- evidence rules (#826) ----------------------------------------------------


def test_provider_error_keeps_the_channel(conn, settings):
    _team(conn)
    channels = FakeChannels([_owned(conn)])

    result = _manager(conn, channels, FakeSports(raises=True)).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []


def test_provider_error_does_not_create_either(conn, settings):
    _team(conn)
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(raises=True)).sync()

    assert result == _ok(idle=1)
    assert channels.created == []
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.dispatcharr_channel_id is None
    assert mapping.channel_number == 9000
    assert mapping.sync_message == "Schedule unavailable for nba"


def test_team_whose_guide_errored_keeps_state(conn, settings):
    _team(conn)
    channels = FakeChannels([_owned(conn)])
    sports = FakeSports([])

    result = _manager(conn, channels, sports, unverified_team_ids={1}).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []
    assert sports.calls == []


def test_team_whose_guide_errored_is_not_created(conn, settings):
    _team(conn)
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(_in(days=10)), unverified_team_ids={1}).sync()

    assert result == _ok(idle=1)
    assert channels.created == []


def test_no_sports_service_keeps_state(conn, settings):
    _team(conn)
    channels = FakeChannels([_owned(conn)])

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []


def test_team_without_provider_id_keeps_state(conn, settings):
    _team(conn)
    conn.execute("UPDATE teams SET provider_team_id = NULL WHERE id = 1")
    channels = FakeChannels([_owned(conn)])

    result = _manager(conn, channels, FakeSports([])).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []


def test_attached_stream_keeps_channel_through_an_empty_schedule(conn, settings):
    _team(conn)
    remote = _owned(conn)
    _attach_stream(conn)
    channels = FakeChannels([remote])

    result = _manager(conn, channels, FakeSports([])).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []


@pytest.mark.parametrize(
    ("lifecycle", "kwargs", "expected"),
    [
        ("in_season", {"days": 10}, True),
        ("game_days", {"days": 10}, False),
        ("in_season", {"minutes": 30}, True),
        ("game_days", {"minutes": 30}, True),
        ("in_season", {"days": -3}, False),
        ("game_days", {"days": -3}, False),
    ],
)
def test_the_two_schedule_modes_differ_only_on_an_upcoming_game(
    conn, settings, lifecycle, kwargs, expected
):
    _team(conn)
    manager = _manager(conn, FakeChannels(), FakeSports(_in(**kwargs)))
    team = dict(conn.execute("SELECT * FROM teams WHERE id = 1").fetchone())

    wanted, note = manager._lifecycle_verdict(conn, team, Timing(), lifecycle)

    assert wanted is expected
    assert note


# --- settings and team API ----------------------------------------------------


def test_in_season_setting_and_team_override_round_trip(monkeypatch, db_path):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    client = TestClient(app)

    resp = client.put("/api/v1/settings/managed-team-channels", json={"lifecycle": "in_season"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle"] == "in_season"
    assert client.get("/api/v1/settings/managed-team-channels").json()["lifecycle"] == "in_season"
    for junk in ("in-season", "season", ""):
        bad = client.put("/api/v1/settings/managed-team-channels", json={"lifecycle": junk})
        assert bad.status_code == 422, junk
    assert client.get("/api/v1/settings/managed-team-channels").json()["lifecycle"] == "in_season"

    team = client.post(
        "/api/v1/teams",
        json={
            "provider": "espn",
            "provider_team_id": "8",
            "primary_league": "nfl",
            "leagues": ["nfl"],
            "sport": "football",
            "team_name": "Detroit Lions",
            "channel_id": "det.lions",
            "managed_channel_enabled": True,
            "managed_channel_lifecycle": "in_season",
        },
    )
    assert team.status_code in (200, 201), team.text
    team_id = team.json()["id"]
    assert team.json()["managed_channel_lifecycle"] == "in_season"

    resp = client.patch(f"/api/v1/teams/{team_id}", json={"managed_channel_lifecycle": "game_days"})
    assert resp.json()["managed_channel_lifecycle"] == "game_days"
    resp = client.patch(f"/api/v1/teams/{team_id}", json={"managed_channel_lifecycle": "in_season"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["managed_channel_lifecycle"] == "in_season"
    bad = client.patch(f"/api/v1/teams/{team_id}", json={"managed_channel_lifecycle": "in-season"})
    assert bad.status_code == 422
