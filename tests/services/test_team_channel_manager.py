"""Focused ownership and numbering tests for persistent Team EPG channels."""

import sqlite3
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from teamarr.database.managed_team_channels import get_managed_team_channel
from teamarr.services.team_channel_manager import TeamChannelManager


@dataclass
class RemoteChannel:
    id: int
    uuid: str
    name: str
    channel_number: str
    tvg_id: str | None = None
    streams: tuple[int, ...] = ()
    channel_group_id: int | None = None
    channel_profile_ids: tuple[int, ...] | None = None
    stream_profile_id: int | None = None
    logo_id: int | None = None


class FakeChannels:
    def __init__(self, channels=()):
        self.channels = {channel.id: channel for channel in channels}
        self.created = []
        self.updated = []
        self.deleted = []
        self.epg_assignments = []

    def get_channels(self):
        return list(self.channels.values())

    def create_channel(self, **kwargs):
        self.created.append(kwargs)
        channel = RemoteChannel(
            id=99,
            uuid="created",
            name=kwargs["name"],
            channel_number=str(kwargs["channel_number"]),
            tvg_id=kwargs["tvg_id"],
        )
        self.channels[channel.id] = channel
        return SimpleNamespace(success=True, channel={"id": 99, "uuid": "created"}, error=None)

    def update_channel(self, channel_id, changes):
        self.updated.append((channel_id, changes))
        return SimpleNamespace(success=True, error=None)

    def delete_channel(self, channel_id):
        self.deleted.append(channel_id)
        return SimpleNamespace(success=True)

    def build_epg_lookup(self, _epg_source_id):
        return {"team-blue": {"id": 42}}

    def set_channel_epg(self, channel_id, epg_id):
        self.epg_assignments.append((channel_id, epg_id))


@pytest.fixture
def conn():
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.executescript(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY, active INTEGER, managed_channel_enabled INTEGER,
            managed_channel_number INTEGER, channel_id TEXT, team_name TEXT,
            primary_league TEXT
        );
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER NOT NULL, sync_status TEXT NOT NULL,
            sync_message TEXT, last_verified_at TEXT, updated_at TEXT
        );
        CREATE TABLE subscription_league_config (
            league_code TEXT PRIMARY KEY, channel_profile_ids TEXT,
            channel_group_id INTEGER, channel_group_mode TEXT, matchup_order TEXT
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
            dispatcharr_channel_group TEXT, priority INTEGER DEFAULT 999,
            attach_at TEXT, detach_at TEXT, removed_at TEXT,
            created_at TEXT, updated_at TEXT,
            UNIQUE(team_id, dispatcharr_stream_id, event_id, event_provider,
                   source_group_id, attach_at)
        );
        """
    )
    yield database
    database.close()


def _factory(conn):
    class Context:
        def __enter__(self):
            return conn

        def __exit__(self, *_):
            conn.commit()

    return Context


@pytest.fixture
def settings(monkeypatch):
    import teamarr.services.team_channel_manager as module

    monkeypatch.setattr(
        module,
        "get_managed_team_channel_settings",
        lambda _: SimpleNamespace(range_start=9000, range_end=9002, priority_ids=[]),
    )
    monkeypatch.setattr(
        module,
        "get_dispatcharr_settings",
        lambda _: SimpleNamespace(
            default_channel_group_id=7,
            default_channel_profile_ids=[3],
            default_stream_profile_id=4,
        ),
    )


def test_creates_owned_streamless_channel_with_requested_number(conn, settings):
    conn.execute(
        "INSERT INTO teams VALUES (1, 1, 1, 9100, 'team-blue', 'Blue', 'nba')"
    )
    channels = FakeChannels()

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result == {"created": 1, "synced": 0, "deleted": 0, "conflicts": 0, "errors": 0}
    assert channels.created == [
        {
            "name": "Blue", "channel_number": 9100, "stream_ids": [], "tvg_id": "team-blue",
            "channel_group_id": 7, "channel_profile_ids": [3], "stream_profile_id": 4,
        }
    ]
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.dispatcharr_channel_id == 99
    assert mapping.channel_number == 9100


def test_manual_tvg_id_conflict_is_not_adopted(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba')")
    manual = RemoteChannel(8, "manual", "Manual", "9000", tvg_id="team-blue")
    channels = FakeChannels([manual])

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result["conflicts"] == 1
    assert not channels.created
    assert get_managed_team_channel(conn, 1) is None


def test_rejects_an_occupied_exact_number(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, 9000, 'team-blue', 'Blue', 'nba')")
    channels = FakeChannels([RemoteChannel(8, "external", "External", "9000")])

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result["errors"] == 1
    assert not channels.created


def test_existing_mapping_preserves_streams_and_is_removed_when_disabled(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba')")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )
    owned = RemoteChannel(
        10,
        "owned",
        "Old",
        "9000",
        tvg_id="team-blue",
        streams=(1,),
        channel_group_id=7,
        channel_profile_ids=(3,),
        stream_profile_id=4,
    )
    channels = FakeChannels([owned])
    manager = TeamChannelManager(_factory(conn), channels)

    result = manager.sync()
    assert result["synced"] == 1
    assert channels.updated == [(10, {"name": "Blue"})]

    conn.execute("UPDATE teams SET managed_channel_enabled = 0 WHERE id = 1")
    result = manager.sync()
    assert result["deleted"] == 1
    assert channels.deleted == [10]
    assert get_managed_team_channel(conn, 1) is None


def test_associates_only_owned_channels_after_refresh(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba')")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )
    channels = FakeChannels()

    result = TeamChannelManager(_factory(conn), channels, object()).associate_epg(12)

    assert result == {"associated": 1, "not_found": 0, "errors": 0}
    assert channels.epg_assignments == [(10, 42)]


def test_stream_memberships_attach_only_to_matching_owned_team(monkeypatch):
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.executescript(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY, active INTEGER, managed_channel_enabled INTEGER,
            provider TEXT, provider_team_id TEXT, team_name TEXT
        );
        INSERT INTO teams VALUES (1, 1, 1, 'espn', 'home', 'Home');
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER, sync_status TEXT,
            sync_message TEXT, last_verified_at TEXT
        );
        INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL);
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
            dispatcharr_channel_group TEXT, priority INTEGER DEFAULT 999,
            attach_at TEXT, detach_at TEXT, removed_at TEXT,
            created_at TEXT, updated_at TEXT,
            UNIQUE(team_id, dispatcharr_stream_id, event_id, event_provider,
                   source_group_id, attach_at)
        );
        """
    )
    channels = FakeChannels()
    manager = TeamChannelManager(_factory(database), channels)
    monkeypatch.setattr(
        "teamarr.services.stream_ordering.get_stream_ordering_service",
        lambda *_: SimpleNamespace(compute_priority=lambda stream: stream.priority),
    )
    event = SimpleNamespace(
        id="game-1",
        provider="espn",
        home_team=SimpleNamespace(id="home"),
        away_team=SimpleNamespace(id="away"),
    )

    result = manager.sync_stream_memberships(
        [{"event": event, "stream": {"id": 55}, "source_group_id": 7, "match_method": "epg"}]
    )

    assert result == {"memberships": 1, "channels": 1, "errors": 0}
    assert channels.updated == [(10, {"streams": [55]})]
    database.close()


def test_stream_ordering_uses_team_scope_and_excludes_closed_windows(monkeypatch):
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.executescript(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY, active INTEGER, managed_channel_enabled INTEGER,
            provider TEXT, provider_team_id TEXT, team_name TEXT, sport TEXT,
            primary_league TEXT
        );
        INSERT INTO teams VALUES (1, 1, 1, 'espn', 'home', 'Home', 'basketball', 'nba');
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER, sync_status TEXT,
            sync_message TEXT, last_verified_at TEXT
        );
        INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL);
        CREATE TABLE managed_team_channel_streams (
            id INTEGER PRIMARY KEY, team_id INTEGER, dispatcharr_stream_id INTEGER,
            event_id TEXT, event_provider TEXT, source_group_id INTEGER,
            stream_name TEXT, m3u_account_name TEXT, match_method TEXT,
            match_type TEXT, feed_team_id TEXT, feed_side TEXT,
            dispatcharr_channel_group TEXT, priority INTEGER, attach_at TEXT,
            detach_at TEXT, removed_at TEXT, created_at TEXT, updated_at TEXT
        );
        INSERT INTO managed_team_channel_streams VALUES
            (1, 1, 55, 'game-1', 'espn', 7, 'Secondary', NULL, 'epg',
             'event', 'home', 'home', NULL, 999, NULL, NULL, NULL, NULL, NULL),
            (2, 1, 56, 'game-1', 'espn', 7, 'Primary', NULL, 'epg',
             'event', 'home', 'home', NULL, 999, NULL, NULL, NULL, NULL, NULL),
            (3, 1, 57, 'game-2', 'espn', 7, 'Closed', NULL, 'epg',
             'event', 'home', 'home', NULL, 999, '2000-01-01 00:00:00',
             '2000-01-01 01:00:00', NULL, NULL, NULL);
        """
    )
    seen = []

    def priority(stream):
        seen.append(stream.stream_name)
        return 1 if stream.stream_name == "Primary" else 2

    monkeypatch.setattr(
        "teamarr.services.stream_ordering.get_stream_ordering_service",
        lambda conn, sport, league: (
            seen.append((sport, league)) or SimpleNamespace(compute_priority=priority)
        ),
    )
    channels = FakeChannels([RemoteChannel(10, "owned", "Home", "9000", streams=(55, 56, 57))])

    result = TeamChannelManager(_factory(database), channels).sync_stream_ordering()

    assert ("basketball", "nba") in seen
    assert result == {"channels": 1, "streams": 3, "errors": 0}
    assert channels.updated == [(10, {"streams": [56, 55]})]
    database.close()
