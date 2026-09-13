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
            primary_league TEXT, sport TEXT, template_id INTEGER
        );
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER, sync_status TEXT,
            created_at TEXT, updated_at TEXT
        );
        INSERT INTO teams VALUES
            (7, 1, 1, 'team-blue', 'Blue', 'team-logo', 'deprecated-logo', 'nba',
             'basketball', NULL);
        INSERT INTO teams VALUES
            (8, 0, 1, 'team-disabled', 'Disabled', NULL, NULL, 'nba', 'basketball', NULL);
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
    assert channel.logo_url == "team-logo"


def test_managed_team_channel_streams_include_current_epg_event(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY, active INTEGER, managed_channel_enabled INTEGER,
            channel_id TEXT, team_name TEXT, team_logo_url TEXT, channel_logo_url TEXT,
            primary_league TEXT, sport TEXT, template_id INTEGER
        );
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER, sync_status TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE managed_team_channel_streams (
            id INTEGER PRIMARY KEY, team_id INTEGER, dispatcharr_stream_id INTEGER,
            event_id TEXT, event_provider TEXT, source_group_id INTEGER, stream_name TEXT,
            m3u_account_name TEXT, match_method TEXT, match_type TEXT, feed_side TEXT,
            priority INTEGER, removed_at TEXT
        );
        CREATE TABLE team_epg_xmltv (team_id INTEGER, xmltv_content TEXT, updated_at TEXT);
        INSERT INTO teams VALUES
            (7, 1, 1, 'team-blue', 'Blue', NULL, NULL, 'nba', 'basketball', NULL);
        INSERT INTO managed_team_channels VALUES
            (7, 90, 'team-uuid', 9000, 'ready', '2026-01-01', '2026-01-02');
        INSERT INTO managed_team_channel_streams VALUES
            (1, 7, 44, 'game-1', 'espn', 3, 'Blue at Red', 'Sports', 'epg', 'event',
             'away', 1, NULL);
        INSERT INTO team_epg_xmltv VALUES (
            7,
            '<tv><programme channel="team-blue" start="20260913090000 +0000" '
            || 'stop="20260913110000 +0000"><title>Blue at Red</title>'
            || '<category>Sports</category><live/></programme></tv>',
            '2026-09-13'
        );
        """
    )
    monkeypatch.setattr(channels, "get_db", lambda: _connection(conn))
    monkeypatch.setattr(channels, "get_group_names_by_ids", lambda *_args: {3: "Sports"})
    monkeypatch.setattr(
        channels,
        "find_current_live_window",
        lambda *_args: {
            "title": "Blue at Red", "sub_title": "Regular season",
            "start": "2026-09-13T09:00:00+00:00", "stop": "2026-09-13T11:00:00+00:00",
        },
    )

    response = channels.get_managed_channel_streams(-7)

    assert response.current_event is not None
    assert response.current_event.title == "Blue at Red"
    assert response.streams[0].dispatcharr_stream_id == 44
    assert response.streams[0].source_group == "Sports"
