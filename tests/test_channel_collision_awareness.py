"""Tests for channel number collision awareness (epic wq8, GitHub #146).

Teamarr must skip channel numbers already occupied by non-Teamarr channels
in Dispatcharr to prevent EPG data bleeding between channels.

Updated for v59: global channel mode (auto/manual) replaces per-group settings.
"""

import sqlite3

import pytest


@pytest.fixture
def conn():
    """Create in-memory SQLite database with v59 schema."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            channel_range_start INTEGER DEFAULT 101,
            channel_range_end INTEGER,
            global_channel_mode TEXT DEFAULT 'auto',
            league_channel_starts JSON DEFAULT '{}',
            global_consolidation_mode TEXT DEFAULT 'consolidate'
        )
    """)
    db.execute("""
        INSERT INTO settings (id, channel_range_start, channel_range_end,
                              global_channel_mode)
        VALUES (1, 101, NULL, 'auto')
    """)
    db.execute("""
        CREATE TABLE event_epg_groups (
            id INTEGER PRIMARY KEY,
            name TEXT,
            sort_order INTEGER DEFAULT 0,
            total_stream_count INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        )
    """)
    db.execute("""
        CREATE TABLE managed_channels (
            id INTEGER PRIMARY KEY,
            event_epg_group_id INTEGER,
            channel_number TEXT,
            deleted_at TEXT,
            dispatcharr_channel_id INTEGER,
            channel_name TEXT,
            primary_stream_id TEXT,
            event_id TEXT,
            sport TEXT,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            event_date TEXT,
            exception_keyword TEXT,
            created_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE channel_sort_priorities (
            id INTEGER PRIMARY KEY,
            sport TEXT,
            league_code TEXT,
            sort_priority INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE channel_priority_teams (
            id INTEGER PRIMARY KEY,
            provider TEXT,
            provider_team_id TEXT,
            team_name TEXT,
            league TEXT,
            sport TEXT
        )
    """)
    db.commit()
    yield db
    db.close()


class TestAutoModeWithExternals:
    """Test AUTO mode skips external occupied numbers."""

    def test_auto_skips_external_numbers(self, conn):
        """AUTO mode skips externally occupied channel numbers."""
        from teamarr.database.channel_numbers import get_next_channel_number

        # External channels at 101, 102, 103
        external = {101, 102, 103}
        result = get_next_channel_number(conn, external_occupied=external)
        assert result == 104

    def test_auto_skips_both_teamarr_and_external(self, conn):
        """AUTO mode skips both Teamarr managed and external numbers."""
        from teamarr.database.channel_numbers import get_next_channel_number

        conn.execute("INSERT INTO event_epg_groups (id, name, enabled) VALUES (1, 'NHL', 1)")
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number) "
            "VALUES (1, 1, '104')"
        )
        conn.commit()

        # External at 101, 102, 103
        external = {101, 102, 103}
        result = get_next_channel_number(conn, external_occupied=external)
        # Skips 101-103 (external) and 104 (Teamarr) → 105
        assert result == 105

    def test_no_externals_works_as_before(self, conn):
        """Without external_occupied, starts from range_start."""
        from teamarr.database.channel_numbers import get_next_channel_number

        result = get_next_channel_number(conn, external_occupied=None)
        assert result == 101

    def test_empty_externals_works_as_before(self, conn):
        """Empty external set is same as None."""
        from teamarr.database.channel_numbers import get_next_channel_number

        result = get_next_channel_number(conn, external_occupied=set())
        assert result == 101

    def test_large_gap_skips_to_end(self, conn):
        """When externals fill range, assignment lands past them."""
        from teamarr.database.channel_numbers import get_next_channel_number

        # External channels cover 101-15000
        external = set(range(101, 15001))
        result = get_next_channel_number(conn, external_occupied=external)
        assert result == 15001

    def test_scattered_externals_finds_first_gap(self, conn):
        """Scattered externals: assignment finds first available number."""
        from teamarr.database.channel_numbers import get_next_channel_number

        # External at 101, 103, 105 — gaps at 102, 104, 106
        external = {101, 103, 105}
        result = get_next_channel_number(conn, external_occupied=external)
        assert result == 102


class TestManualModeWithExternals:
    """Test MANUAL mode with per-league starts."""

    def test_manual_uses_league_start(self, conn):
        """MANUAL mode uses per-league starting channel number."""
        from teamarr.database.channel_numbers import get_next_channel_number

        conn.execute(
            "UPDATE settings SET global_channel_mode = 'manual', "
            "league_channel_starts = '{\"nhl\": 500}' WHERE id = 1"
        )
        conn.commit()

        result = get_next_channel_number(conn, league="nhl")
        assert result == 500

    def test_manual_skips_externals(self, conn):
        """MANUAL mode skips external numbers within league range."""
        from teamarr.database.channel_numbers import get_next_channel_number

        conn.execute(
            "UPDATE settings SET global_channel_mode = 'manual', "
            "league_channel_starts = '{\"nhl\": 500}' WHERE id = 1"
        )
        conn.commit()

        external = {500, 501, 502}
        result = get_next_channel_number(conn, league="nhl", external_occupied=external)
        assert result == 503

    def test_manual_fallback_to_range_start(self, conn):
        """Leagues without configured starts use global range."""
        from teamarr.database.channel_numbers import get_next_channel_number

        conn.execute(
            "UPDATE settings SET global_channel_mode = 'manual', "
            "league_channel_starts = '{\"nhl\": 500}' WHERE id = 1"
        )
        conn.commit()

        # NBA has no configured start → falls back to range_start (101)
        result = get_next_channel_number(conn, league="nba")
        assert result == 101


class TestGlobalReassignWithExternals:
    """Test global reassignment skips external numbers."""

    def test_auto_reassign_skips_externals(self, conn):
        """reassign_all_channels skips external channel numbers."""
        from teamarr.database.channel_numbers import reassign_all_channels

        conn.execute("INSERT INTO event_epg_groups (id, name, enabled) VALUES (1, 'NHL', 1)")
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number, "
            "dispatcharr_channel_id, channel_name, sport, league) "
            "VALUES (1, 1, 101, 1001, 'Game 1', 'hockey', 'nhl')"
        )
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number, "
            "dispatcharr_channel_id, channel_name, sport, league) "
            "VALUES (2, 1, 102, 1002, 'Game 2', 'hockey', 'nhl')"
        )
        conn.commit()

        # External at 101 → channels should be moved to 102, 103
        external = {101}
        result = reassign_all_channels(conn, external_occupied=external)

        assert result["channels_moved"] == 2
        rows = conn.execute("SELECT channel_number FROM managed_channels ORDER BY id").fetchall()
        assert int(rows[0]["channel_number"]) == 102
        assert int(rows[1]["channel_number"]) == 103

    def test_auto_reassign_no_externals(self, conn):
        """Reassignment without externals keeps channels at same position."""
        from teamarr.database.channel_numbers import reassign_all_channels

        conn.execute("INSERT INTO event_epg_groups (id, name, enabled) VALUES (1, 'NHL', 1)")
        conn.execute(
            "INSERT INTO managed_channels (id, event_epg_group_id, channel_number, "
            "dispatcharr_channel_id, channel_name, sport, league) "
            "VALUES (1, 1, 101, 1001, 'Game 1', 'hockey', 'nhl')"
        )
        conn.commit()

        reassign_all_channels(conn, external_occupied=None)
        rows = conn.execute("SELECT channel_number FROM managed_channels ORDER BY id").fetchall()
        assert int(rows[0]["channel_number"]) == 101


class TestComputeExternalOccupied:
    """Test the compute_external_occupied standalone function."""

    def test_empty_dispatcharr(self):
        """No Dispatcharr channels → empty external set."""
        from teamarr.consumers.lifecycle import compute_external_occupied

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY,
                channel_number TEXT,
                deleted_at TEXT
            )
        """)
        db.commit()

        result = compute_external_occupied(lambda: db, channel_manager=None)
        assert result == set()
        db.close()

    def test_all_teamarr_managed(self):
        """All Dispatcharr channels are Teamarr-managed → empty external set."""
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle import compute_external_occupied
        from teamarr.dispatcharr.types import DispatcharrChannel

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY,
                channel_number TEXT,
                deleted_at TEXT
            )
        """)
        db.execute("INSERT INTO managed_channels (id, channel_number) VALUES (1, '500')")
        db.execute("INSERT INTO managed_channels (id, channel_number) VALUES (2, '501')")
        db.commit()

        mock_mgr = MagicMock()
        mock_mgr.get_channels.return_value = [
            DispatcharrChannel(id=1, uuid="a", name="Game 1", channel_number="500"),
            DispatcharrChannel(id=2, uuid="b", name="Game 2", channel_number="501"),
        ]

        result = compute_external_occupied(lambda: db, channel_manager=mock_mgr)
        assert result == set()
        db.close()

    def test_mixed_channels(self):
        """Mix of Teamarr and external channels → only externals returned."""
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle import compute_external_occupied
        from teamarr.dispatcharr.types import DispatcharrChannel

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY,
                channel_number TEXT,
                deleted_at TEXT
            )
        """)
        db.execute("INSERT INTO managed_channels (id, channel_number) VALUES (1, '500')")
        db.commit()

        mock_mgr = MagicMock()
        mock_mgr.get_channels.return_value = [
            DispatcharrChannel(id=1, uuid="a", name="Game 1", channel_number="500"),
            DispatcharrChannel(id=2, uuid="b", name="ESPN", channel_number="100"),
            DispatcharrChannel(id=3, uuid="c", name="NBC", channel_number="200"),
        ]

        result = compute_external_occupied(lambda: db, channel_manager=mock_mgr)
        assert result == {100, 200}
        db.close()

    def test_deleted_teamarr_channels_excluded(self):
        """Deleted Teamarr channels don't count — their numbers are external."""
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle import compute_external_occupied
        from teamarr.dispatcharr.types import DispatcharrChannel

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY,
                channel_number TEXT,
                deleted_at TEXT
            )
        """)
        db.execute(
            "INSERT INTO managed_channels (id, channel_number, deleted_at) "
            "VALUES (1, '500', '2026-01-01')"
        )
        db.commit()

        mock_mgr = MagicMock()
        mock_mgr.get_channels.return_value = [
            DispatcharrChannel(id=1, uuid="a", name="Orphan", channel_number="500"),
        ]

        result = compute_external_occupied(lambda: db, channel_manager=mock_mgr)
        assert result == {500}
        db.close()
