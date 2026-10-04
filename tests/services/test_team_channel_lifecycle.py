"""Game-days lifecycle for managed team channels (#904).

``game_days`` keeps the ownership row (and so the number) for every opted-in
team, but the Dispatcharr channel only while a game sits inside the
event-channel lifecycle window. Every read that could tear a channel down is
exercised in its failure mode: no schedule service, a provider exception, a
team whose guide errored this run — each keeps the current state (#826).
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from teamarr.database.managed_team_channels import get_managed_team_channel
from teamarr.services.team_channel_manager import TeamChannelManager
from tests.services.test_team_channel_manager import (
    FakeChannels,
    RemoteChannel,
    _factory,
    _ok,
)


@dataclass
class Game:
    id: str
    start_time: datetime
    name: str = "Blue vs Red"
    short_name: str = "BLU @ RED"
    sport: str = "basketball"
    league: str = "nba"
    status: SimpleNamespace | None = None


class FakeSports:
    def __init__(self, games=(), *, raises=False):
        self.games = list(games)
        self.raises = raises
        self.calls = []

    def get_team_schedule(self, team_id, league, days_ahead=14):
        self.calls.append((team_id, league, days_ahead))
        if self.raises:
            raise RuntimeError("provider down")
        return list(self.games)


class Timing:
    """A stand-in for ChannelLifecycleManager: window = [start-1h, start+3h]."""

    pre_buffer_minutes = 60
    post_buffer_minutes = 60

    def should_create_channel(self, event, **_):
        return SimpleNamespace(
            should_act=datetime.now(UTC) >= event.start_time - timedelta(hours=1)
        )

    def should_delete_channel(self, event, **_):
        return SimpleNamespace(
            should_act=datetime.now(UTC) >= event.start_time + timedelta(hours=3)
        )

    def get_event_end_time(self, event):
        return event.start_time + timedelta(hours=2)


@pytest.fixture
def conn():
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.executescript(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY, active INTEGER, managed_channel_enabled INTEGER,
            managed_channel_number INTEGER, channel_id TEXT, team_name TEXT,
            primary_league TEXT, template_id INTEGER, provider_team_id TEXT,
            leagues TEXT, managed_channel_lifecycle TEXT
        );
        CREATE TABLE leagues (league_code TEXT PRIMARY KEY, league_alias TEXT, display_name TEXT);
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER NOT NULL, sync_status TEXT NOT NULL,
            sync_message TEXT, last_verified_at TEXT, updated_at TEXT
        );
        CREATE TABLE subscription_league_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT, league_code TEXT UNIQUE, channel_profile_ids TEXT,
            channel_group_id INTEGER, channel_group_mode TEXT, matchup_order TEXT
        );
        CREATE TABLE channel_sort_priorities (
            id INTEGER PRIMARY KEY, sport TEXT, league_code TEXT, sort_priority INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE channel_priority_teams (
            id INTEGER PRIMARY KEY, provider TEXT, provider_team_id TEXT, team_name TEXT,
            league TEXT, sport TEXT, scope TEXT
        );
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY, epg_stream_pre_buffer_minutes INTEGER,
            epg_stream_post_buffer_minutes INTEGER
        );
        INSERT INTO settings VALUES (1, 60, 30);
        CREATE TABLE managed_team_channel_streams (
            id INTEGER PRIMARY KEY, team_id INTEGER, dispatcharr_stream_id INTEGER,
            event_id TEXT, event_provider TEXT, source_group_id INTEGER,
            stream_name TEXT, m3u_account_name TEXT, match_method TEXT,
            match_type TEXT DEFAULT 'event', feed_team_id TEXT, feed_side TEXT,
            dispatcharr_channel_group TEXT, dispatcharr_source_channel_id INTEGER,
            priority INTEGER DEFAULT 999,
            event_start TEXT, attach_at TEXT, detach_at TEXT, removed_at TEXT,
            created_at TEXT, updated_at TEXT
        );
        """
    )
    yield database
    database.close()


@pytest.fixture
def settings(monkeypatch):
    import teamarr.services.team_channel_manager as module

    monkeypatch.setattr(module, "get_channel_stability_settings", lambda _: {"mode": "compact"})
    monkeypatch.setattr(
        module,
        "get_managed_team_channel_settings",
        lambda _: SimpleNamespace(
            range_start=9000, range_end=9005, priority_ids=[], lifecycle="game_days"
        ),
    )
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


def _team(conn, team_id=1, *, active=1, number=None, lifecycle=None, name="Blue"):
    conn.execute(
        "INSERT INTO teams VALUES (?, ?, 1, ?, ?, ?, 'nba', NULL, '10', '[\"nba\"]', ?)",
        (team_id, active, number, f"team-{name.lower()}", name, lifecycle),
    )


def _owned(conn, team_id=1, channel_id=50, number=9000):
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (?, ?, 'u50', ?, 'ready', NULL, NULL, NULL)",
        (team_id, channel_id, number),
    )
    return RemoteChannel(
        id=channel_id, uuid="u50", name="Blue", channel_number=str(number), tvg_id="team-blue"
    )


def _in_window():
    return [Game("g1", datetime.now(UTC) + timedelta(minutes=30))]


def _next_week():
    return [Game("g2", datetime.now(UTC) + timedelta(days=7))]


def _manager(conn, channels, sports, **kw):
    return TeamChannelManager(_factory(conn), channels, sports_service=sports, **kw)


# --- activation -------------------------------------------------------------


def test_game_in_window_creates_the_channel(conn, settings):
    _team(conn)
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(_in_window())).sync()

    assert result == _ok(created=1)
    assert channels.created[0]["tvg_id"] == "team-blue"
    assert get_managed_team_channel(conn, 1).sync_status == "ready"


def test_no_game_in_window_reserves_number_without_a_channel(conn, settings):
    _team(conn)
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(_next_week())).sync()

    assert result == _ok(idle=1)
    assert channels.created == []
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.sync_status == "idle"
    assert mapping.dispatcharr_channel_id is None
    assert mapping.channel_number == 9000
    assert "next" in (mapping.sync_message or "")


def test_window_closing_hibernates_the_owned_channel(conn, settings):
    _team(conn)
    remote = _owned(conn)
    channels = FakeChannels([remote])

    result = _manager(conn, channels, FakeSports(_next_week())).sync()

    assert result == _ok(idle=1, hibernated=1)
    assert channels.deleted == [50]
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.sync_status == "idle"
    assert mapping.dispatcharr_channel_id is None
    assert mapping.dispatcharr_uuid is None
    assert mapping.channel_number == 9000


def test_waking_recreates_with_the_reserved_number(conn, settings):
    _team(conn, team_id=1, name="Blue")
    _team(conn, team_id=2, name="Red")
    # Blue is dormant on 9000; Red is active on 9001.
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, NULL, NULL, 9000, 'idle', 'x', NULL, NULL)"
    )
    red = RemoteChannel(id=51, uuid="u51", name="Red", channel_number="9001", tvg_id="team-red")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (2, 51, 'u51', 9001, 'ready', NULL, NULL, NULL)"
    )
    channels = FakeChannels([red])

    result = _manager(conn, channels, FakeSports(_in_window())).sync()

    assert result["created"] == 1
    assert channels.created[0]["channel_number"] == 9000
    assert channels.created[0]["tvg_id"] == "team-blue"


def test_dormant_number_is_not_handed_to_another_team(conn, settings):
    _team(conn, team_id=1, name="Blue")  # sorts first, dormant
    _team(conn, team_id=2, name="Red")  # active
    sports = FakeSports()
    sports.get_team_schedule = lambda team_id, league, days_ahead=14: (
        _in_window() if league == "nba" and sports.calls.append(1) is None and len(sports.calls) > 1
        else _next_week()
    )
    channels = FakeChannels()

    result = _manager(conn, channels, sports).sync()

    assert result["idle"] == 1 and result["created"] == 1
    assert get_managed_team_channel(conn, 1).channel_number == 9000
    assert channels.created[0]["channel_number"] == 9001


# --- overrides and persistence ----------------------------------------------


def test_per_team_persistent_override_ignores_schedule(conn, settings):
    _team(conn, lifecycle="persistent")
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(_next_week())).sync()

    assert result == _ok(created=1)


def test_per_team_game_days_override_under_global_persistent(conn, settings, monkeypatch):
    import teamarr.services.team_channel_manager as module

    monkeypatch.setattr(
        module,
        "get_managed_team_channel_settings",
        lambda _: SimpleNamespace(
            range_start=9000, range_end=9005, priority_ids=[], lifecycle="persistent"
        ),
    )
    _team(conn, lifecycle="game_days")
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(_next_week())).sync()

    assert result == _ok(idle=1)


def test_inactive_team_goes_dormant(conn, settings):
    _team(conn, active=0)
    remote = _owned(conn)
    channels = FakeChannels([remote])
    sports = FakeSports(_in_window())

    result = _manager(conn, channels, sports).sync()

    assert result == _ok(idle=1, hibernated=1)
    assert sports.calls == []


# --- evidence rules (#826) --------------------------------------------------


def test_provider_error_keeps_the_channel(conn, settings):
    _team(conn)
    remote = _owned(conn)
    channels = FakeChannels([remote])

    result = _manager(conn, channels, FakeSports(raises=True)).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []


def test_provider_error_does_not_create_either(conn, settings):
    """No channel yet + unreadable schedule: stay dormant, but reserve the
    number and say why, so the Teams page shows the state."""
    _team(conn)
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports(raises=True)).sync()

    assert result == _ok(idle=1)
    assert channels.created == []
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.dispatcharr_channel_id is None
    assert mapping.sync_message == "Schedule unavailable for nba"


def test_team_whose_guide_errored_keeps_state(conn, settings):
    _team(conn)
    remote = _owned(conn)
    channels = FakeChannels([remote])

    result = _manager(
        conn, channels, FakeSports(_next_week()), unverified_team_ids={1}
    ).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []


def test_no_sports_service_keeps_state(conn, settings):
    """Without a schedule service the verdict is unknown: an owned channel
    stays, a missing one is not created."""
    _team(conn, team_id=1, name="Blue")
    _team(conn, team_id=2, name="Red")
    red = RemoteChannel(id=51, uuid="u51", name="Red", channel_number="9001", tvg_id="team-red")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (2, 51, 'u51', 9001, 'ready', NULL, NULL, NULL)"
    )
    channels = FakeChannels([red])

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result == _ok(synced=1, idle=1)
    assert channels.created == []
    assert channels.deleted == []


def test_attached_stream_keeps_channel_through_schedule_gap(conn, settings):
    _team(conn)
    remote = _owned(conn)
    now = datetime.now(UTC)
    fmt = "%Y-%m-%d %H:%M:%S"
    conn.execute(
        "INSERT INTO managed_team_channel_streams (team_id, dispatcharr_stream_id, event_id,"
        " event_provider, source_group_id, priority, attach_at, detach_at) VALUES"
        " (1, 700, 'g9', 'espn', 3, 1, ?, ?)",
        ((now - timedelta(hours=1)).strftime(fmt), (now + timedelta(hours=1)).strftime(fmt)),
    )
    channels = FakeChannels([remote])

    result = _manager(conn, channels, FakeSports([])).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []


def test_uuid_mismatch_blocks_hibernate(conn, settings):
    _team(conn)
    remote = _owned(conn)
    remote.uuid = "someone-else"
    channels = FakeChannels([remote])

    result = _manager(conn, channels, FakeSports(_next_week())).sync()

    assert result["conflicts"] == 1
    assert channels.deleted == []


def test_remote_delete_failure_is_reported_not_forgotten(conn, settings):
    _team(conn)
    remote = _owned(conn)
    channels = FakeChannels([remote])
    channels.delete_channel = lambda cid: SimpleNamespace(success=False, error="nope")

    result = _manager(conn, channels, FakeSports(_next_week())).sync()

    assert result["errors"] == 1
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.dispatcharr_channel_id == 50
    assert mapping.sync_status == "error"


def test_toggle_off_removes_a_dormant_row(conn, settings):
    _team(conn)
    conn.execute("UPDATE teams SET managed_channel_enabled = 0 WHERE id = 1")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, NULL, NULL, 9000, 'idle', 'x', NULL, NULL)"
    )
    channels = FakeChannels()

    result = _manager(conn, channels, FakeSports()).sync()

    assert result["deleted"] == 1
    assert get_managed_team_channel(conn, 1) is None


# --- settings and team API ----------------------------------------------------


def test_lifecycle_setting_and_team_override_round_trip(monkeypatch, db_path):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    client = TestClient(app)

    assert client.get("/api/v1/settings/managed-team-channels").json()["lifecycle"] == "persistent"
    resp = client.put("/api/v1/settings/managed-team-channels", json={"lifecycle": "game_days"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle"] == "game_days"
    assert client.get("/api/v1/settings/managed-team-channels").json()["lifecycle"] == "game_days"
    bad = client.put("/api/v1/settings/managed-team-channels", json={"lifecycle": "bogus"})
    assert bad.status_code == 422

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
        },
    )
    assert team.status_code in (200, 201), team.text
    team_id = team.json()["id"]
    assert team.json()["managed_channel_lifecycle"] is None

    resp = client.patch(f"/api/v1/teams/{team_id}", json={"managed_channel_lifecycle": "game_days"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["managed_channel_lifecycle"] == "game_days"
    bad = client.patch(f"/api/v1/teams/{team_id}", json={"managed_channel_lifecycle": "x"})
    assert bad.status_code == 422
    resp = client.patch(f"/api/v1/teams/{team_id}", json={"managed_channel_lifecycle": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["managed_channel_lifecycle"] is None
