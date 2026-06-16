"""Tests for team import channel_id collision handling (GitHub #159).

ESPN returns duplicate team names with different provider IDs in some leagues.
The import must handle these without crashing on UNIQUE constraint violations.
"""

import sqlite3

import pytest

from teamarr.services.team_import import ImportTeam, bulk_import_teams


@pytest.fixture
def conn():
    """Create in-memory SQLite database with minimal teams schema."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            provider_team_id TEXT NOT NULL,
            primary_league TEXT NOT NULL,
            leagues TEXT DEFAULT '[]',
            sport TEXT NOT NULL,
            team_name TEXT NOT NULL,
            team_abbrev TEXT,
            team_logo_url TEXT,
            channel_id TEXT NOT NULL UNIQUE,
            active INTEGER DEFAULT 1
        )
    """)
    db.execute("""
        CREATE TABLE leagues (
            league_code TEXT PRIMARY KEY,
            league_id TEXT,
            display_name TEXT,
            sport TEXT
        )
    """)
    db.execute(
        "INSERT INTO leagues VALUES (?, ?, ?, ?)",
        ("baseball/college-baseball", "ncaabb", "NCAA Baseball", "baseball"),
    )
    db.execute(
        "INSERT INTO leagues VALUES (?, ?, ?, ?)",
        ("baseball/college-softball", "ncaasbw", "NCAA Softball", "softball"),
    )
    db.commit()
    return db


class TestTBDFiltering:
    def test_tbd_teams_filtered(self, conn):
        """TBD placeholder teams should be silently filtered out."""
        teams = [
            ImportTeam("TBD", "TBD", "espn", "1153", "baseball/college-baseball", "baseball", None),
            ImportTeam(
                "TBD TBD", None, "espn", "1154", "baseball/college-baseball", "baseball", None
            ),
            ImportTeam(
                "Boise State Broncos",
                "BSU",
                "espn",
                "322",
                "baseball/college-baseball",
                "baseball",
                None,
            ),
        ]
        result = bulk_import_teams(conn, teams)
        assert result.imported == 1
        assert result.skipped == 0

        rows = conn.execute("SELECT team_name FROM teams").fetchall()
        assert len(rows) == 1
        assert rows[0]["team_name"] == "Boise State Broncos"

    def test_tbd_case_insensitive(self, conn):
        """TBD filtering should be case-insensitive."""
        teams = [
            ImportTeam("tbd", None, "espn", "1", "baseball/college-baseball", "baseball", None),
            ImportTeam("Tbd Tbd", None, "espn", "2", "baseball/college-baseball", "baseball", None),
        ]
        result = bulk_import_teams(conn, teams)
        assert result.imported == 0


class TestChannelIdCollision:
    def test_duplicate_team_names_different_ids(self, conn):
        """Two ESPN entries with same name but different IDs should both import."""
        teams = [
            ImportTeam(
                "Boise State Broncos",
                "BSU",
                "espn",
                "322",
                "baseball/college-baseball",
                "baseball",
                None,
            ),
            ImportTeam(
                "Boise State Broncos",
                "BSU",
                "espn",
                "1139",
                "baseball/college-baseball",
                "baseball",
                None,
            ),
        ]
        result = bulk_import_teams(conn, teams)
        assert result.imported == 2

        rows = conn.execute("SELECT channel_id FROM teams ORDER BY channel_id").fetchall()
        ids = [r["channel_id"] for r in rows]
        assert len(ids) == 2
        assert len(set(ids)) == 2  # All unique
        assert "BoiseStateBroncos.ncaabb" in ids
        assert "BoiseStateBroncos.ncaabb.1139" in ids

    def test_same_name_different_schools(self, conn):
        """Distinct teams sharing a display name (e.g., multiple 'Tigers') get unique IDs."""
        teams = [
            ImportTeam(
                "Tigers", "BEN", "espn", "800", "baseball/college-softball", "softball", None
            ),
            ImportTeam(
                "Tigers", "CAM", "espn", "801", "baseball/college-softball", "softball", None
            ),
            ImportTeam(
                "Tigers", "STI", "espn", "802", "baseball/college-softball", "softball", None
            ),
        ]
        result = bulk_import_teams(conn, teams)
        assert result.imported == 3

        rows = conn.execute("SELECT channel_id FROM teams ORDER BY channel_id").fetchall()
        ids = [r["channel_id"] for r in rows]
        assert len(set(ids)) == 3  # All unique

    def test_collision_with_existing_db_row(self, conn):
        """New import colliding with a pre-existing DB entry gets disambiguated."""
        # Pre-existing team
        conn.execute(
            "INSERT INTO teams "
            "(provider, provider_team_id, primary_league, leagues, sport, team_name, channel_id) "
            "VALUES ('espn', '322', 'baseball/college-baseball', "
            "'[\"baseball/college-baseball\"]', 'baseball', 'Boise State Broncos', "
            "'BoiseStateBroncos.ncaabb')"
        )
        conn.commit()

        teams = [
            ImportTeam(
                "Boise State Broncos",
                "BSU",
                "espn",
                "1139",
                "baseball/college-baseball",
                "baseball",
                None,
            ),
        ]
        result = bulk_import_teams(conn, teams)
        assert result.imported == 1

        new_row = conn.execute(
            "SELECT channel_id FROM teams WHERE provider_team_id = '1139'"
        ).fetchone()
        assert new_row["channel_id"] == "BoiseStateBroncos.ncaabb.1139"

    def test_no_collision_no_suffix(self, conn):
        """When there's no collision, channel_id should not have a suffix."""
        teams = [
            ImportTeam(
                "Clemson Tigers",
                "CLEM",
                "espn",
                "529",
                "baseball/college-baseball",
                "baseball",
                None,
            ),
        ]
        result = bulk_import_teams(conn, teams)
        assert result.imported == 1

        row = conn.execute("SELECT channel_id FROM teams").fetchone()
        assert row["channel_id"] == "ClemsonTigers.ncaabb"


class TestMixedImport:
    def test_tbd_and_duplicates_combined(self, conn):
        """Real-world NCAA Baseball scenario: TBDs + true duplicates + normal teams."""
        teams = [
            ImportTeam("TBD", "TBD", "espn", "1153", "baseball/college-baseball", "baseball", None),
            ImportTeam("TBD", "TBD", "espn", "1154", "baseball/college-baseball", "baseball", None),
            ImportTeam(
                "Boise State Broncos",
                "BSU",
                "espn",
                "322",
                "baseball/college-baseball",
                "baseball",
                None,
            ),
            ImportTeam(
                "Boise State Broncos",
                "BSU",
                "espn",
                "1139",
                "baseball/college-baseball",
                "baseball",
                None,
            ),
            ImportTeam(
                "Clemson Tigers",
                "CLEM",
                "espn",
                "529",
                "baseball/college-baseball",
                "baseball",
                None,
            ),
            ImportTeam(
                "Clemson Tigers",
                "CLEM",
                "espn",
                "1140",
                "baseball/college-baseball",
                "baseball",
                None,
            ),
        ]
        result = bulk_import_teams(conn, teams)
        assert result.imported == 4  # 2 TBDs filtered, 4 real teams imported
        assert result.skipped == 0

        rows = conn.execute("SELECT channel_id FROM teams ORDER BY channel_id").fetchall()
        ids = [r["channel_id"] for r in rows]
        assert len(set(ids)) == 4  # All unique
