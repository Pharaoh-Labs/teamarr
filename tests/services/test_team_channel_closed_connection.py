"""Team channel paths must not use a database connection after it is closed (#938).

Two objects were handed a connection inside a ``with db_factory() as conn``
block and used after it:

- the group resolver built for managed team channels (#935) loads its names
  lazily, so every per-league group override failed with "Cannot operate on a
  closed database" and fell back to the global group;
- the stream-ordering service in ``sync_stream_ordering`` (#890) was built on
  one connection and scored on a second, so ``team_feed`` rules were skipped.

The existing tests use one connection that never closes, which is why neither
was caught. These use connections that really close.
"""

import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from teamarr.consumers.generation_pipeline.phases import preparation
from teamarr.consumers.lifecycle.dynamic_resolver import DynamicResolver
from teamarr.dispatcharr.factory import DispatcharrConnection
from teamarr.services.team_channel_manager import TeamChannelManager
from tests.services.test_team_channel_manager import (
    _MEMBERSHIP_TABLE,
    FakeChannels,
    RemoteChannel,
)


def _closing_factory(path):
    """A db_factory whose connections are closed when the block exits."""

    @contextmanager
    def factory():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    return factory


@pytest.fixture
def names_db(tmp_path):
    path = tmp_path / "names.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE sports (sport_code TEXT, display_name TEXT);
        INSERT INTO sports VALUES ('football', 'Football');
        CREATE TABLE leagues (league_code TEXT, display_name TEXT, league_alias TEXT, sport TEXT);
        INSERT INTO leagues VALUES ('nfl', 'National Football League', 'NFL', 'football');
        CREATE TABLE league_cache (league_slug TEXT, league_name TEXT);
        INSERT INTO league_cache VALUES ('esp.3', 'Primera Federación');
        """
    )
    conn.commit()
    conn.close()
    return path


class TestResolverOwnsItsConnection:
    def _resolver(self, factory, conn=None):
        resolver = DynamicResolver()
        resolver.initialize(factory, conn)
        resolver._get_dispatcharr = lambda: None  # no network in a unit test
        return resolver

    def test_names_load_without_a_caller_connection(self, names_db):
        resolver = self._resolver(_closing_factory(names_db))

        assert resolver.get_league_alias("nfl") == "NFL"
        assert resolver.get_sport_display_name("football") == "Football"
        assert resolver.get_league_display_name("esp.3") == "Primera Federación"

    def test_the_reported_shape_fails_and_the_fix_does_not(self, names_db):
        """What #935 did: initialize inside a with-block, resolve after it."""
        factory = _closing_factory(names_db)
        with factory() as conn:
            handed_a_connection = self._resolver(factory, conn)
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            handed_a_connection.get_league_alias("nfl")

        assert self._resolver(factory).get_league_alias("nfl") == "NFL"

    def test_a_caller_held_connection_is_still_used(self, names_db):
        """The lifecycle path keeps its connection open; that is unchanged."""
        opened = []
        base = _closing_factory(names_db)

        @contextmanager
        def counting():
            opened.append(1)
            with base() as conn:
                yield conn

        with base() as conn:
            resolver = self._resolver(counting, conn)
            assert resolver.get_league_alias("nfl") == "NFL"
        assert opened == []


def test_prepare_stage_resolver_works_after_the_stage_returns(names_db, monkeypatch):
    factory = _closing_factory(names_db)
    client = DispatcharrConnection.__new__(DispatcharrConnection)
    client.channels = client.epg = client.logos = None
    context = SimpleNamespace(
        dispatcharr_client=client,
        db_factory=factory,
        sports_service=object(),
        team_result=None,
        result=SimpleNamespace(teams_processed=0),
        report=lambda *a, **k: None,
    )
    captured = {}

    def manager(*args, **kwargs):
        captured.update(kwargs)
        return "manager"

    monkeypatch.setattr(preparation, "TeamChannelManager", manager)
    preparation.stage_prepare_team_channels(context)

    resolver = captured["dynamic_resolver"]
    resolver._get_dispatcharr = lambda: None
    assert resolver.get_league_alias("nfl") == "NFL"


def test_ordering_service_scores_on_the_live_connection(tmp_path, monkeypatch):
    path = tmp_path / "team.db"
    conn = sqlite3.connect(path)
    conn.executescript(
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
             stream_name, match_method, match_type, feed_team_id, feed_side, priority, attach_at)
        VALUES
            (1, 1, 55, 'game-1', 'espn', 7, 'Secondary', 'epg', 'event', 'home', 'home', 999, ''),
            (2, 1, 56, 'game-1', 'espn', 7, 'Primary', 'epg', 'event', 'home', 'home', 999, '');
        """
    )
    conn.commit()
    conn.close()

    class Service:
        """Reads the database while scoring, as a team_feed rule does."""

        def __init__(self, conn):
            self.conn = conn

        def compute_priority(self, stream):
            self.conn.execute("SELECT team_name FROM teams WHERE active = 1").fetchall()
            return 1 if stream.stream_name == "Primary" else 2

    monkeypatch.setattr(
        "teamarr.services.stream_ordering.get_stream_ordering_service",
        lambda conn, sport, league: Service(conn),
    )
    channels = FakeChannels([RemoteChannel(10, "owned", "Home", "9000", streams=(55, 56))])

    result = TeamChannelManager(_closing_factory(path), channels).sync_stream_ordering()

    assert result == {"channels": 1, "streams": 2, "errors": 0}
    assert channels.updated == [(10, {"streams": [56, 55]})]
