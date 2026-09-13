"""Managed channel list route tests."""

import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

from teamarr.api.routes import channels


@contextmanager
def _connection(conn):
    yield conn


def test_managed_channel_list_appends_owned_enabled_team_channels(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY, active INTEGER, managed_channel_enabled INTEGER,
            channel_id TEXT, team_name TEXT, team_logo_url TEXT, channel_logo_url TEXT,
            primary_league TEXT, sport TEXT
        );
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER, sync_status TEXT,
            created_at TEXT, updated_at TEXT
        );
        INSERT INTO teams VALUES (7, 1, 1, 'team-blue', 'Blue', NULL, NULL, 'nba', 'basketball');
        INSERT INTO teams VALUES
            (8, 0, 1, 'team-disabled', 'Disabled', NULL, NULL, 'nba', 'basketball');
        INSERT INTO managed_team_channels VALUES
            (7, 90, 'team-uuid', 9000, 'ready', '2026-01-01', '2026-01-02');
        INSERT INTO managed_team_channels VALUES
            (8, 91, 'disabled-uuid', 9001, 'ready', '2026-01-01', '2026-01-02');
        """
    )
    monkeypatch.setattr(channels, "get_db", lambda: _connection(conn))
    event_channel = SimpleNamespace(
        id=-7,
        event_epg_group_id=None,
        event_id="event-1",
        event_provider="espn",
        tvg_id="teamarr-event-1",
        channel_name="Event channel",
        channel_number=100,
        logo_url=None,
        dispatcharr_channel_id=10,
        dispatcharr_uuid="event-uuid",
        home_team=None,
        home_team_abbrev=None,
        away_team=None,
        away_team_abbrev=None,
        event_date=None,
        event_name="Event",
        league="nba",
        sport="basketball",
        scheduled_delete_at=None,
        sync_status="ready",
        created_at=None,
        updated_at=None,
        deleted_at=None,
    )
    monkeypatch.setattr(
        channels, "get_all_managed_channels", lambda *_args, **_kwargs: [event_channel]
    )

    response = channels.list_managed_channels(
        group_id=None, sport=None, league=None, include_deleted=False
    )

    assert response.total == 2
    channel = response.channels[1]
    assert channel.id == -8
    assert channel.channel_type == "team"
    assert channel.team_id == 7
    assert channel.tvg_id == "team-blue"
    assert channel.dispatcharr_channel_id == 90
