"""Ownership, numbering and membership tests for persistent Team EPG channels.

Every Dispatcharr read that feeds a destructive decision is exercised in its
failure mode here (#826): a list that cannot be read, a mapped channel missing
from a stale list, a delete without a connection, a source group that did not
report this run.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from teamarr.database.managed_team_channel_streams import (
    active_stream_ids,
    get_assigned_team_streams,
    reconcile_team_streams,
)
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
    """A Dispatcharr channel manager whose reads can be made to fail."""

    def __init__(self, channels=(), *, list_fails=False, absent_ids=(), probe_fails=False):
        self.channels = {channel.id: channel for channel in channels}
        self.list_fails = list_fails
        self.absent_ids = set(absent_ids)
        self.probe_fails = probe_fails
        self.created = []
        self.updated = []
        self.deleted = []
        self.epg_assignments = []
        self.epg_result = SimpleNamespace(success=True, error=None)
        self.probes = []

    def fetch_channels(self):
        if self.list_fails:
            return None
        return list(self.channels.values())

    def get_channels(self):
        return self.fetch_channels() or []

    def get_channel_existence(self, channel_id, use_cache=True):
        self.probes.append(channel_id)
        if self.probe_fails:
            return None, False
        channel = self.channels.get(channel_id)
        if channel is not None:
            return channel, False
        return None, channel_id in self.absent_ids

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
        self.channels.pop(channel_id, None)
        return SimpleNamespace(success=True, error=None)

    def build_epg_lookup(self, _epg_source_id):
        return {"team-blue": {"id": 42}}

    def set_channel_epg(self, channel_id, epg_id):
        self.epg_assignments.append((channel_id, epg_id))
        return self.epg_result


_MEMBERSHIP_TABLE = """
    CREATE TABLE managed_team_channel_streams (
        id INTEGER PRIMARY KEY, team_id INTEGER, dispatcharr_stream_id INTEGER,
        event_id TEXT, event_provider TEXT, source_group_id INTEGER,
        stream_name TEXT, m3u_account_name TEXT, match_method TEXT,
        match_type TEXT DEFAULT 'event', feed_team_id TEXT, feed_side TEXT,
        dispatcharr_channel_group TEXT, priority INTEGER DEFAULT 999,
        event_start TEXT, attach_at TEXT, detach_at TEXT, removed_at TEXT,
        created_at TEXT, updated_at TEXT,
        UNIQUE(team_id, dispatcharr_stream_id, event_id, event_provider,
               source_group_id, attach_at)
    );
"""


@pytest.fixture
def conn():
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.executescript(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY, active INTEGER, managed_channel_enabled INTEGER,
            managed_channel_number INTEGER, channel_id TEXT, team_name TEXT,
            primary_league TEXT, template_id INTEGER
        );
        CREATE TABLE leagues (league_code TEXT PRIMARY KEY, league_alias TEXT, display_name TEXT);
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER NOT NULL, sync_status TEXT NOT NULL,
            sync_message TEXT, last_verified_at TEXT, updated_at TEXT
        );
        CREATE TABLE subscription_league_config (
            league_code TEXT PRIMARY KEY, channel_profile_ids TEXT,
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
        """
        + _MEMBERSHIP_TABLE
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

    # Compact is the event channels' default; the sticky tests override it.
    monkeypatch.setattr(
        module, "get_channel_stability_settings", lambda _: {"mode": "compact"}
    )
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
            managed_team_channel_group_id=None,
            managed_team_channel_profile_ids=None,
        ),
    )


def _ok(**overrides):
    base = {"created": 0, "synced": 0, "deleted": 0, "conflicts": 0, "errors": 0,
            "unavailable": False}
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# Ownership sync
# ---------------------------------------------------------------------------


def test_creates_owned_streamless_channel_with_requested_number(conn, settings):
    conn.execute(
        "INSERT INTO teams VALUES (1, 1, 1, 9100, 'team-blue', 'Blue', 'nba', NULL)"
    )
    channels = FakeChannels()

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result == _ok(created=1)
    assert channels.created == [
        {
            "name": "Blue", "channel_number": 9100, "stream_ids": [], "tvg_id": "team-blue",
            "channel_group_id": None, "channel_profile_ids": [0], "stream_profile_id": 4,
        }
    ]
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.dispatcharr_channel_id == 99
    assert mapping.channel_number == 9100


def test_creation_uses_managed_output_and_uploads_resolved_template_logo(
    conn, settings, monkeypatch
):
    conn.execute(
        "INSERT INTO teams VALUES (1, 1, 1, 9100, 'team-blue', 'Blue', 'nba', 5)"
    )
    conn.execute("INSERT INTO leagues VALUES ('nba', NULL, 'National Basketball Association')")
    channels = FakeChannels()
    uploaded = []

    class Logos:
        def upload(self, **kwargs):
            uploaded.append(kwargs)
            return SimpleNamespace(success=True, logo={"id": 42})

    import teamarr.database.templates as templates

    monkeypatch.setattr(
        templates,
        "get_template",
        lambda *_: SimpleNamespace(
            team_channel_name="{league} | {team_name}",
            team_channel_logo_url="https://logos.example/{league_code}/{team_name}.png",
        ),
    )
    monkeypatch.setattr(
        "teamarr.services.team_channel_manager.get_epg_settings",
        lambda _: SimpleNamespace(art_base_url=""),
    )

    TeamChannelManager(_factory(conn), channels, logo_manager=Logos()).sync()

    assert channels.created[0]["name"] == "National Basketball Association | Blue"
    assert channels.created[0]["logo_id"] == 42
    assert channels.updated == [(99, {"logo_id": 42})]
    assert uploaded == [{
        "name": "Blue Logo",
        "url": "https://logos.example/nba/Blue.png",
    }]


def test_relative_template_logo_without_art_base_is_not_uploaded(conn, settings, monkeypatch):
    """A game-thumbs path with no base URL is not a fetchable logo (#826)."""
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, 9100, 'team-blue', 'Blue', 'nba', 5)")
    channels = FakeChannels()
    uploaded = []

    class Logos:
        def upload(self, **kwargs):
            uploaded.append(kwargs)
            return SimpleNamespace(success=True, logo={"id": 42})

    import teamarr.database.templates as templates

    monkeypatch.setattr(
        templates,
        "get_template",
        lambda *_: SimpleNamespace(
            team_channel_name=None,
            team_channel_logo_url="{league_id}/{team_name|pascal}/logo.png?style=1",
        ),
    )
    monkeypatch.setattr(
        "teamarr.services.team_channel_manager.get_epg_settings",
        lambda _: SimpleNamespace(art_base_url=""),
    )

    TeamChannelManager(_factory(conn), channels, logo_manager=Logos()).sync()

    assert uploaded == []
    assert "logo_id" not in channels.created[0]
    assert channels.updated == []


def test_manual_tvg_id_conflict_is_not_adopted_and_is_reported(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    manual = RemoteChannel(8, "manual", "Manual", "9000", tvg_id="team-blue")
    channels = FakeChannels([manual])

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result["conflicts"] == 1
    assert not channels.created
    # The conflict is persisted so the Teams page can show it (#826) — with no
    # channel id, because nothing was adopted.
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.dispatcharr_channel_id is None
    assert mapping.sync_status == "conflict"
    assert "tvg_id" in mapping.sync_message


def test_rejects_an_occupied_exact_number_and_reports_it(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, 9000, 'team-blue', 'Blue', 'nba', NULL)")
    channels = FakeChannels([RemoteChannel(8, "external", "External", "9000")])

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result["errors"] == 1
    assert not channels.created
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.sync_status == "error"
    assert "9000" in mapping.sync_message


def test_existing_mapping_preserves_streams_and_is_removed_when_unmanaged(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )
    owned = RemoteChannel(
        10, "owned", "Old", "9000", tvg_id="team-blue", streams=(1,), stream_profile_id=4,
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


def test_deactivating_a_team_keeps_its_channel(conn, settings):
    """The channel is persistent: only the managed toggle releases it (#826)."""
    conn.execute("INSERT INTO teams VALUES (1, 0, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )
    channels = FakeChannels([
        RemoteChannel(10, "owned", "Blue", "9000", tvg_id="team-blue", stream_profile_id=4)
    ])

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result == _ok(synced=1)
    assert channels.deleted == []
    assert get_managed_team_channel(conn, 1).dispatcharr_channel_id == 10


def test_unreadable_channel_list_skips_the_sync_instead_of_recreating(conn, settings):
    """A failed fetch must never look like an empty Dispatcharr (#826)."""
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )
    channels = FakeChannels(list_fails=True)

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result == _ok(unavailable=True)
    assert channels.created == []
    assert get_managed_team_channel(conn, 1).dispatcharr_channel_id == 10


def test_mapped_channel_missing_from_list_is_verified_before_recreation(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )

    # Inconclusive probe (timeout/5xx): keep the mapping, report, do nothing.
    channels = FakeChannels(probe_fails=True)
    result = TeamChannelManager(_factory(conn), channels).sync()
    assert result["errors"] == 1
    assert channels.created == []
    assert channels.probes == [10]
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.dispatcharr_channel_id == 10
    assert mapping.sync_status == "error"

    # Confirmed 404: the channel is really gone, so it is recreated.
    channels = FakeChannels(absent_ids=[10])
    result = TeamChannelManager(_factory(conn), channels).sync()
    assert result["created"] == 1
    assert get_managed_team_channel(conn, 1).dispatcharr_channel_id == 99


def test_uuid_mismatch_blocks_every_mutation(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )
    foreign = RemoteChannel(10, "someone-elses", "Theirs", "9000", tvg_id="x", stream_profile_id=4)
    channels = FakeChannels([foreign])

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result["conflicts"] == 1
    assert channels.updated == []
    mapping = get_managed_team_channel(conn, 1)
    assert mapping.dispatcharr_uuid == "owned"  # never overwritten from the remote read
    assert mapping.sync_status == "conflict"


def _two_out_of_order_teams(conn):
    """Alpha (basketball) holds 9000, Zulu (hockey) 9001; hockey sorts first."""
    conn.execute("ALTER TABLE teams ADD COLUMN sport TEXT")
    conn.execute(
        "INSERT INTO teams (id, active, managed_channel_enabled, channel_id, team_name, "
        "primary_league, sport) VALUES (1, 1, 1, 'alpha', 'Alpha', 'nhl', 'basketball')"
    )
    conn.execute(
        "INSERT INTO teams (id, active, managed_channel_enabled, channel_id, team_name, "
        "primary_league, sport) VALUES (2, 1, 1, 'zulu', 'Zulu', 'nhl', 'hockey')"
    )
    conn.execute(
        "INSERT INTO channel_sort_priorities (id, sport, league_code, sort_priority) "
        "VALUES (1, 'hockey', NULL, 0)"
    )
    conn.execute(
        "INSERT INTO channel_sort_priorities (id, sport, league_code, sort_priority) "
        "VALUES (2, 'basketball', NULL, 1)"
    )
    conn.execute(
        "INSERT INTO managed_team_channels VALUES "
        "(1, 10, 'alpha-uuid', 9000, 'ready', NULL, NULL, NULL)"
    )
    conn.execute(
        "INSERT INTO managed_team_channels VALUES "
        "(2, 11, 'zulu-uuid', 9001, 'ready', NULL, NULL, NULL)"
    )
    return FakeChannels([
        RemoteChannel(10, "alpha-uuid", "Alpha", "9000", tvg_id="alpha", stream_profile_id=4),
        RemoteChannel(11, "zulu-uuid", "Zulu", "9001", tvg_id="zulu", stream_profile_id=4),
    ])


def test_compact_mode_reflows_automatic_channels_every_run(conn, settings):
    """Compact is what event channels do by default: re-sort every run."""
    channels = _two_out_of_order_teams(conn)

    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result["synced"] == 2
    assert channels.updated == [
        (11, {"channel_number": 9000}),
        (10, {"channel_number": 9001}),
    ]


def test_sticky_modes_hold_numbers_until_a_relayout(conn, settings, monkeypatch):
    """Gapped/Strict: a channel keeps its number; the daily re-layout re-sorts (#826)."""
    import teamarr.services.team_channel_manager as module

    monkeypatch.setattr(module, "get_channel_stability_settings", lambda _: {"mode": "gap"})
    channels = _two_out_of_order_teams(conn)

    result = TeamChannelManager(_factory(conn), channels).sync()
    assert result["synced"] == 2
    assert channels.updated == []
    assert get_managed_team_channel(conn, 1).channel_number == 9000
    assert get_managed_team_channel(conn, 2).channel_number == 9001

    result = TeamChannelManager(_factory(conn), channels).sync(relayout=True)
    assert result["synced"] == 2
    assert channels.updated == [
        (11, {"channel_number": 9000}),
        (10, {"channel_number": 9001}),
    ]


def test_new_channels_are_numbered_in_priority_order_into_free_slots(conn, settings):
    conn.execute("ALTER TABLE teams ADD COLUMN sport TEXT")
    conn.execute(
        "INSERT INTO teams (id, active, managed_channel_enabled, channel_id, team_name, "
        "primary_league, sport) VALUES (1, 1, 1, 'alpha', 'Alpha', 'nhl', 'basketball')"
    )
    conn.execute(
        "INSERT INTO teams (id, active, managed_channel_enabled, channel_id, team_name, "
        "primary_league, sport) VALUES (2, 1, 1, 'zulu', 'Zulu', 'nhl', 'hockey')"
    )
    conn.execute(
        "INSERT INTO channel_sort_priorities (id, sport, league_code, sort_priority) "
        "VALUES (1, 'hockey', NULL, 0)"
    )
    channels = FakeChannels([RemoteChannel(5, "ext", "External", "9000")])

    class Sequential(FakeChannels):
        next_id = 20

        def create_channel(self, **kwargs):
            self.created.append(kwargs)
            self.next_id += 1
            channel = RemoteChannel(
                self.next_id, f"u{self.next_id}", kwargs["name"],
                str(kwargs["channel_number"]), tvg_id=kwargs["tvg_id"],
            )
            self.channels[channel.id] = channel
            return SimpleNamespace(
                success=True, channel={"id": channel.id, "uuid": channel.uuid}, error=None
            )

    channels = Sequential([RemoteChannel(5, "ext", "External", "9000")])
    result = TeamChannelManager(_factory(conn), channels).sync()

    assert result["created"] == 2
    # Hockey sorts first and takes the first free number above the external 9000.
    assert [(c["name"], c["channel_number"]) for c in channels.created] == [
        ("Zulu", 9001), ("Alpha", 9002),
    ]


def test_configured_profiles_are_compared_as_sets_and_all_profiles_is_never_pushed(
    conn, settings, monkeypatch
):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )
    remote = RemoteChannel(
        10, "owned", "Blue", "9000", tvg_id="team-blue", stream_profile_id=4,
        channel_profile_ids=(2, 1),
    )
    channels = FakeChannels([remote])

    # Default (None = all profiles): Dispatcharr's concrete list is left alone.
    TeamChannelManager(_factory(conn), channels).sync()
    assert channels.updated == []

    # A narrowed selection in a different order is the same selection.
    import teamarr.services.team_channel_manager as module

    monkeypatch.setattr(
        module,
        "get_dispatcharr_settings",
        lambda _: SimpleNamespace(
            default_stream_profile_id=4, managed_team_channel_group_id=None,
            managed_team_channel_profile_ids=[1, "2"],
        ),
    )
    TeamChannelManager(_factory(conn), channels).sync()
    assert channels.updated == []

    monkeypatch.setattr(
        module,
        "get_dispatcharr_settings",
        lambda _: SimpleNamespace(
            default_stream_profile_id=4, managed_team_channel_group_id=None,
            managed_team_channel_profile_ids=[3],
        ),
    )
    TeamChannelManager(_factory(conn), channels).sync()
    assert channels.updated == [(10, {"channel_profile_ids": [3]})]


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def test_remove_without_mapping_needs_no_dispatcharr(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 0, NULL, 'team-blue', 'Blue', 'nba', NULL)")

    assert TeamChannelManager(_factory(conn), None).remove_team_channel(1) == (True, None)


def test_remove_with_mapping_refuses_without_dispatcharr(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )

    ok, error = TeamChannelManager(_factory(conn), None).remove_team_channel(1)

    assert not ok and "Dispatcharr" in error
    assert get_managed_team_channel(conn, 1) is not None


def test_remove_verifies_absence_before_dropping_the_mapping(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )

    manager = TeamChannelManager(_factory(conn), FakeChannels(probe_fails=True))
    ok, error = manager.remove_team_channel(1)
    assert not ok and "verify" in error
    assert get_managed_team_channel(conn, 1) is not None

    manager = TeamChannelManager(_factory(conn), FakeChannels(absent_ids=[10]))
    ok, error = manager.remove_team_channel(1)
    assert ok
    assert get_managed_team_channel(conn, 1) is None


# ---------------------------------------------------------------------------
# EPG association
# ---------------------------------------------------------------------------


def test_associates_only_owned_channels_and_counts_rejections(conn, settings):
    conn.execute("INSERT INTO teams VALUES (1, 1, 1, NULL, 'team-blue', 'Blue', 'nba', NULL)")
    conn.execute(
        "INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL, NULL)"
    )
    channels = FakeChannels()

    result = TeamChannelManager(_factory(conn), channels, object()).associate_epg(12)
    assert result == {"associated": 1, "not_found": 0, "errors": 0}
    assert channels.epg_assignments == [(10, 42)]

    channels.epg_result = SimpleNamespace(success=False, error="boom")
    result = TeamChannelManager(_factory(conn), channels, object()).associate_epg(12)
    assert result == {"associated": 0, "not_found": 0, "errors": 1}


# ---------------------------------------------------------------------------
# Stream memberships
# ---------------------------------------------------------------------------


def _membership_db(*teams):
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.executescript(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY, active INTEGER, managed_channel_enabled INTEGER,
            provider TEXT, provider_team_id TEXT, team_name TEXT, primary_league TEXT,
            leagues TEXT, sport TEXT
        );
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER, sync_status TEXT,
            sync_message TEXT, last_verified_at TEXT
        );
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY, epg_stream_pre_buffer_minutes INTEGER,
            epg_stream_post_buffer_minutes INTEGER
        );
        INSERT INTO settings VALUES (1, 60, 30);
        CREATE TABLE event_epg_groups (id INTEGER PRIMARY KEY, enabled INTEGER);
        INSERT INTO event_epg_groups VALUES (7, 1), (8, 1);
        """
        + _MEMBERSHIP_TABLE
    )
    for team_id, provider_team_id, name, primary, leagues in teams:
        database.execute(
            "INSERT INTO teams VALUES (?, 1, 1, 'espn', ?, ?, ?, ?, 'hockey')",
            (team_id, provider_team_id, name, primary, leagues),
        )
        database.execute(
            "INSERT INTO managed_team_channels VALUES (?, ?, 'owned', 9000, 'ready', NULL, NULL)",
            (team_id, 10 + team_id),
        )
    return database


def _event(event_id, home, away, league="nhl", start=None, state="scheduled"):
    return SimpleNamespace(
        id=event_id,
        provider="espn",
        league=league,
        sport="hockey",
        start_time=start or datetime.now(UTC) + timedelta(hours=1),
        status=SimpleNamespace(state=state),
        home_team=SimpleNamespace(id=home),
        away_team=SimpleNamespace(id=away),
        sessions=None,
    )


def _rows(database):
    return [
        dict(row)
        for row in database.execute(
            "SELECT * FROM managed_team_channel_streams ORDER BY id"
        )
    ]


def test_stream_memberships_attach_only_to_matching_owned_team():
    database = _membership_db((1, "home", "Home", "nhl", '["nhl"]'))
    manager = TeamChannelManager(_factory(database), FakeChannels())

    result = manager.sync_stream_memberships(
        [{"event": _event("game-1", "home", "away"), "stream": {"id": 55},
          "source_group_id": 7, "match_method": "epg", "matched_side": "home"}]
    )

    assert result == {"memberships": 1, "channels": 0, "errors": 0}
    rows = _rows(database)
    assert [(r["team_id"], r["dispatcharr_stream_id"]) for r in rows] == [(1, 55)]
    # Name-matched streams get the game's own window, never open-ended (#826).
    assert rows[0]["attach_at"] and rows[0]["detach_at"] and rows[0]["event_start"]
    database.close()


def test_stream_memberships_do_not_cross_leagues_with_same_provider_team_id():
    database = _membership_db((1, "21", "Toronto Maple Leafs", "nhl", '["nhl"]'))
    manager = TeamChannelManager(_factory(database), FakeChannels())

    result = manager.sync_stream_memberships(
        [{"event": _event("game-1", "21", "22", league="nfl"), "stream": {"id": 55},
          "source_group_id": 7, "match_method": "epg"}]
    )

    assert result["memberships"] == 0
    database.close()


def test_stream_memberships_cover_every_league_the_team_plays_in():
    """An MLS side in Leagues Cup, an EPL side in the UCL (#826)."""
    database = _membership_db((1, "9", "Inter Miami", "usa.1", '["usa.1", "concacaf.leagues.cup"]'))
    manager = TeamChannelManager(_factory(database), FakeChannels())

    result = manager.sync_stream_memberships(
        [{"event": _event("cup-1", "9", "3", league="concacaf.leagues.cup"),
          "stream": {"id": 55}, "source_group_id": 7, "match_method": "fuzzy"}]
    )

    assert result["memberships"] == 1
    database.close()


def test_final_and_cancelled_games_never_attach():
    database = _membership_db((1, "home", "Home", "nhl", '["nhl"]'))
    manager = TeamChannelManager(_factory(database), FakeChannels())

    result = manager.sync_stream_memberships(
        [
            {"event": _event("done", "home", "away", state="final"), "stream": {"id": 55},
             "source_group_id": 7},
            {"event": _event("off", "home", "away", state="cancelled"), "stream": {"id": 56},
             "source_group_id": 7},
        ]
    )

    assert result["memberships"] == 0
    database.close()


def test_feed_side_comes_from_the_stream_not_the_recipient_team():
    database = _membership_db(
        (1, "home", "Home", "nhl", '["nhl"]'), (2, "away", "Away", "nhl", '["nhl"]')
    )
    manager = TeamChannelManager(_factory(database), FakeChannels())
    event = _event("game-1", "home", "away")

    manager.sync_stream_memberships(
        [
            # The away broadcast, attached to BOTH teams' channels.
            {"event": event, "stream": {"id": 55}, "source_group_id": 7,
             "feed_hint": "away", "matched_side": None},
            # A national feed: no side is known.
            {"event": event, "stream": {"id": 56}, "source_group_id": 7},
        ]
    )

    rows = {(r["team_id"], r["dispatcharr_stream_id"]): r for r in _rows(database)}
    assert rows[(1, 55)]["feed_side"] == "away"
    assert rows[(2, 55)]["feed_side"] == "away"
    assert rows[(1, 55)]["feed_team_id"] == "away"
    assert rows[(1, 56)]["feed_side"] is None
    database.close()


def test_group_that_did_not_report_keeps_its_memberships():
    """A transient source failure must not clear a live game (#826)."""
    database = _membership_db((1, "home", "Home", "nhl", '["nhl"]'))
    manager = TeamChannelManager(_factory(database), FakeChannels())
    event = _event("game-1", "home", "away")
    manager.sync_stream_memberships(
        [
            {"event": event, "stream": {"id": 55}, "source_group_id": 7},
            {"event": event, "stream": {"id": 66}, "source_group_id": 8},
        ],
        completed_group_ids={7, 8},
    )

    # Group 8 errored this run: group 7 reports nothing, group 8 is silent.
    manager.sync_stream_memberships([], completed_group_ids={7})

    live = {
        r["dispatcharr_stream_id"]
        for r in _rows(database)
        if r["removed_at"] is None
    }
    assert live == {66}
    database.close()


def test_disabled_group_memberships_are_released_even_when_silent():
    database = _membership_db((1, "home", "Home", "nhl", '["nhl"]'))
    manager = TeamChannelManager(_factory(database), FakeChannels())
    manager.sync_stream_memberships(
        [{"event": _event("game-1", "home", "away"), "stream": {"id": 66},
          "source_group_id": 8}],
        completed_group_ids={7, 8},
    )
    database.execute("UPDATE event_epg_groups SET enabled = 0 WHERE id = 8")

    manager.sync_stream_memberships([], completed_group_ids={7})

    assert all(r["removed_at"] for r in _rows(database))
    database.close()


def test_reconcile_purges_long_removed_rows():
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.executescript(_MEMBERSHIP_TABLE)
    database.execute(
        "INSERT INTO managed_team_channel_streams (team_id, dispatcharr_stream_id, event_id, "
        "event_provider, source_group_id, attach_at, removed_at) "
        "VALUES (1, 1, 'old', 'espn', 7, '', datetime('now', '-30 days'))"
    )
    database.execute(
        "INSERT INTO managed_team_channel_streams (team_id, dispatcharr_stream_id, event_id, "
        "event_provider, source_group_id, attach_at, removed_at) "
        "VALUES (1, 2, 'recent', 'espn', 7, '', datetime('now', '-1 days'))"
    )

    reconcile_team_streams(database, [], set())

    assert [r["event_id"] for r in _rows(database)] == ["recent"]
    database.close()


# ---------------------------------------------------------------------------
# Selection and ordering
# ---------------------------------------------------------------------------


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
        """
        + _MEMBERSHIP_TABLE
        + """
        INSERT INTO managed_team_channel_streams
            (id, team_id, dispatcharr_stream_id, event_id, event_provider, source_group_id,
             stream_name, match_method, match_type, feed_team_id, feed_side, priority,
             attach_at, detach_at)
        VALUES
            (1, 1, 55, 'game-1', 'espn', 7, 'Secondary', 'epg', 'event', 'home', 'home', 999,
             '', NULL),
            (2, 1, 56, 'game-1', 'espn', 7, 'Primary', 'epg', 'event', 'home', 'home', 999,
             '', NULL),
            (3, 1, 57, 'game-2', 'espn', 7, 'Closed', 'epg', 'event', 'home', 'home', 999,
             '2000-01-01 00:00:00', '2000-01-01 01:00:00');
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


def test_stream_ordering_skips_when_dispatcharr_cannot_be_read():
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.executescript(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY, active INTEGER, managed_channel_enabled INTEGER,
            team_name TEXT, sport TEXT, primary_league TEXT
        );
        INSERT INTO teams VALUES (1, 1, 1, 'Home', 'basketball', 'nba');
        CREATE TABLE managed_team_channels (
            team_id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER,
            dispatcharr_uuid TEXT, channel_number INTEGER, sync_status TEXT,
            sync_message TEXT, last_verified_at TEXT
        );
        INSERT INTO managed_team_channels VALUES (1, 10, 'owned', 9000, 'ready', NULL, NULL);
        """
        + _MEMBERSHIP_TABLE
    )
    channels = FakeChannels(list_fails=True)

    result = TeamChannelManager(_factory(database), channels).sync_stream_ordering()

    assert result == {"channels": 0, "streams": 0, "errors": 0}
    assert channels.updated == []
    database.close()


def _selection_db(rows):
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.executescript(_MEMBERSHIP_TABLE)
    database.executemany(
        "INSERT INTO managed_team_channel_streams (id, team_id, dispatcharr_stream_id, "
        "event_id, event_provider, source_group_id, priority, event_start, attach_at, "
        "detach_at) VALUES (?, 1, ?, ?, 'espn', 7, ?, ?, ?, ?)",
        rows,
    )
    return database


def test_soonest_active_game_wins_the_channel():
    """Not the lowest event id: yesterday's final must not beat tonight's game (#826)."""
    database = _selection_db([
        # Yesterday's game, lower id, window already closed.
        (1, 55, '401000', 1, '2026-01-01 00:00:00', '2025-12-31 23:00:00', '2026-01-01 04:00:00'),
        # Tonight's game, window open.
        (2, 56, '401999', 1, '2026-01-02 00:00:00', '2026-01-01 23:00:00', '2026-01-02 04:00:00'),
        # Next week's game, higher id but window not open yet.
        (3, 57, '401001', 1, '2026-01-09 00:00:00', '2026-01-08 23:00:00', '2026-01-09 04:00:00'),
    ])

    assert active_stream_ids(database, 1, datetime(2026, 1, 2, 0, 30, tzinfo=UTC)) == [56]
    database.close()


def test_overlapping_windows_pick_the_earlier_start():
    database = _selection_db([
        (1, 55, 'game-1', 2, '2026-01-01 12:00:00', '2026-01-01 11:00:00', '2026-01-01 15:30:00'),
        (2, 56, 'game-1', 1, '2026-01-01 12:00:00', '2026-01-01 11:00:00', '2026-01-01 15:30:00'),
        (3, 57, 'game-2', 1, '2026-01-01 13:30:00', '2026-01-01 12:30:00', '2026-01-01 17:00:00'),
    ])

    assert active_stream_ids(database, 1, datetime(2026, 1, 1, 13, tzinfo=UTC)) == [56, 55]
    database.close()


def test_assigned_streams_deduplicate_active_event_memberships():
    database = _selection_db([
        # The same stream twice for one game (two EPG programme slots): one row.
        (1, 55, 'game-1', 2, '2026-01-01 12:00:00', '2026-01-01 11:00:00', '2026-01-01 13:30:00'),
        (2, 55, 'game-1', 1, '2026-01-01 12:00:00', '2026-01-01 10:00:00', '2026-01-01 13:30:00'),
        (3, 56, 'game-1', 3, '2026-01-01 12:00:00', '2026-01-01 11:00:00', '2026-01-01 13:30:00'),
        (4, 57, 'game-2', 1, '2026-01-01 13:30:00', '2026-01-01 12:30:00', '2026-01-01 16:00:00'),
    ])

    streams = get_assigned_team_streams(database, 1, datetime(2026, 1, 1, 13, tzinfo=UTC))

    assert [stream["dispatcharr_stream_id"] for stream in streams] == [55, 56]
    database.close()
