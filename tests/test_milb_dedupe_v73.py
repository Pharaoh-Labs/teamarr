"""Tests for v73 migration: dedupe MiLB league codes after the v2.2 rename.

Background
----------
Commit db53687 (Apr 13, 2026) renamed the MiLB league codes:

    a       → milb-a
    aa      → milb-aa
    aaa     → milb-aaa
    higha   → milb-high-a

`schema.sql` uses ``INSERT OR REPLACE INTO leagues`` keyed on ``league_code``.
The new rows were inserted but the old rows were never deleted, leaving
duplicate MiLB entries in the league selector and orphaned teams in
``team_cache``. v73 cleans this up and remaps any user-data references.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from teamarr.database.connection import _run_migrations, init_db

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_v72_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a minimal v72 schema with the tables touched by v73."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version INTEGER DEFAULT 72
        )
        """
    )
    conn.execute("INSERT INTO settings (id, schema_version) VALUES (1, 72)")

    conn.execute(
        """
        CREATE TABLE leagues (
            league_code TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            provider_league_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            sport TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE team_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_team_id TEXT NOT NULL,
            league TEXT NOT NULL,
            sport TEXT NOT NULL,
            UNIQUE(provider, provider_team_id, league)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE managed_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE team_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE channel_sort_priorities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sport TEXT NOT NULL,
            league_code TEXT,
            sort_priority INTEGER NOT NULL DEFAULT 0,
            UNIQUE(sport, league_code)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE sports_subscription (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            leagues JSON
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE epg_matched_streams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_league TEXT
        )
        """
    )

    conn.commit()
    return conn


def _seed_duplicate_milb_state(conn: sqlite3.Connection) -> None:
    """Insert the orphan-old-codes + new-codes state that v73 must clean up."""
    rows = [
        ("a", "mlbstats", "14", "Single-A", "baseball"),
        ("aa", "mlbstats", "12", "Double-A", "baseball"),
        ("aaa", "mlbstats", "11", "Triple-A", "baseball"),
        ("higha", "mlbstats", "13", "High-A", "baseball"),
        ("milb-a", "mlbstats", "14", "Single-A", "baseball"),
        ("milb-aa", "mlbstats", "12", "Double-A", "baseball"),
        ("milb-aaa", "mlbstats", "11", "Triple-A", "baseball"),
        ("milb-high-a", "mlbstats", "13", "High-A", "baseball"),
        ("rookie", "mlbstats", "16", "Rookie", "baseball"),
        ("mlb", "espn", "baseball/mlb", "Major League Baseball", "baseball"),
    ]
    conn.executemany(
        "INSERT INTO leagues VALUES (?, ?, ?, ?, ?)",
        rows,
    )

    # team_cache: same teams cached under both old and new codes.
    for old_code, new_code in (
        ("a", "milb-a"),
        ("aa", "milb-aa"),
        ("aaa", "milb-aaa"),
        ("higha", "milb-high-a"),
    ):
        for team_id in range(1, 4):
            conn.execute(
                "INSERT INTO team_cache "
                "(team_name, provider, provider_team_id, league, sport) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"Team{team_id}", "mlbstats", str(team_id), old_code, "baseball"),
            )
            conn.execute(
                "INSERT INTO team_cache "
                "(team_name, provider, provider_team_id, league, sport) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"Team{team_id}", "mlbstats", str(team_id), new_code, "baseball"),
            )

    conn.commit()


# ---------------------------------------------------------------------------
# Migration: v72 → v73 deletes the orphan league rows
# ---------------------------------------------------------------------------


class TestV73DeletesDuplicateLeagues:
    def test_old_milb_codes_removed_from_leagues(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)

        _run_migrations(conn)

        codes = {r["league_code"] for r in conn.execute("SELECT league_code FROM leagues")}
        assert "a" not in codes
        assert "aa" not in codes
        assert "aaa" not in codes
        assert "higha" not in codes

    def test_new_milb_codes_preserved(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)

        _run_migrations(conn)

        codes = {r["league_code"] for r in conn.execute("SELECT league_code FROM leagues")}
        assert {"milb-a", "milb-aa", "milb-aaa", "milb-high-a", "rookie"} <= codes
        assert "mlb" in codes

    def test_schema_version_advanced_to_73(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)

        _run_migrations(conn)

        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        assert row["schema_version"] == 76


class TestV73CleansTeamCache:
    def test_orphan_team_rows_deleted(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)

        _run_migrations(conn)

        leagues_in_cache = {r["league"] for r in conn.execute("SELECT league FROM team_cache")}
        assert leagues_in_cache.isdisjoint({"a", "aa", "aaa", "higha"})

    def test_new_coded_teams_preserved(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)

        _run_migrations(conn)

        for new_code in ("milb-a", "milb-aa", "milb-aaa", "milb-high-a"):
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM team_cache WHERE league = ?",
                (new_code,),
            ).fetchone()["c"]
            assert count == 3, f"expected 3 teams under {new_code}, got {count}"


class TestV73RemapsUserData:
    def test_managed_channels_league_remapped(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)
        conn.execute("INSERT INTO managed_channels (league) VALUES ('aaa')")
        conn.execute("INSERT INTO managed_channels (league) VALUES ('higha')")
        conn.execute("INSERT INTO managed_channels (league) VALUES ('mlb')")
        conn.commit()

        _run_migrations(conn)

        leagues = [
            r["league"] for r in conn.execute("SELECT league FROM managed_channels ORDER BY id")
        ]
        assert leagues == ["milb-aaa", "milb-high-a", "mlb"]

    def test_team_aliases_league_remapped(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)
        conn.execute("INSERT INTO team_aliases (league) VALUES ('a')")
        conn.commit()

        _run_migrations(conn)

        leagues = [r["league"] for r in conn.execute("SELECT league FROM team_aliases")]
        assert leagues == ["milb-a"]

    def test_sports_subscription_json_array_remapped(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)
        conn.execute(
            "INSERT INTO sports_subscription (leagues) VALUES (?)",
            (json.dumps(["mlb", "aaa", "aa", "rookie", "higha", "a"]),),
        )
        conn.commit()

        _run_migrations(conn)

        row = conn.execute("SELECT leagues FROM sports_subscription").fetchone()
        leagues = json.loads(row["leagues"])
        assert "a" not in leagues
        assert "aa" not in leagues
        assert "aaa" not in leagues
        assert "higha" not in leagues
        assert {"milb-a", "milb-aa", "milb-aaa", "milb-high-a", "rookie", "mlb"} <= set(leagues)

    def test_sports_subscription_dedupes_when_old_and_new_both_present(self, tmp_path):
        """If a user had both 'aaa' and 'milb-aaa' in their array, the result
        should contain 'milb-aaa' exactly once."""
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)
        conn.execute(
            "INSERT INTO sports_subscription (leagues) VALUES (?)",
            (json.dumps(["aaa", "milb-aaa", "mlb"]),),
        )
        conn.commit()

        _run_migrations(conn)

        row = conn.execute("SELECT leagues FROM sports_subscription").fetchone()
        leagues = json.loads(row["leagues"])
        assert leagues.count("milb-aaa") == 1
        assert "aaa" not in leagues

    def test_channel_sort_priorities_dedupes_when_old_and_new_both_present(self, tmp_path):
        """Regression for #202 / teamarrv2-98x: a user with sort priorities
        configured under both the old MiLB code and the new code for the same
        sport used to crash startup with UNIQUE(sport, league_code) violation.
        The migration should now drop the colliding old row in favor of the
        existing new row."""
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)
        conn.execute(
            "INSERT INTO channel_sort_priorities (sport, league_code, sort_priority)"
            " VALUES ('baseball', 'aaa', 5)"
        )
        conn.execute(
            "INSERT INTO channel_sort_priorities (sport, league_code, sort_priority)"
            " VALUES ('baseball', 'milb-aaa', 7)"
        )
        # Different sport, same old code — should still be remapped (no collision).
        conn.execute(
            "INSERT INTO channel_sort_priorities (sport, league_code, sort_priority)"
            " VALUES ('softball', 'aaa', 9)"
        )
        conn.commit()

        # Must not raise. Pre-fix this would have aborted with sqlite3.IntegrityError.
        _run_migrations(conn)

        rows = list(
            conn.execute(
                "SELECT sport, league_code, sort_priority"
                " FROM channel_sort_priorities ORDER BY sport, league_code"
            )
        )
        assert (rows[0]["sport"], rows[0]["league_code"], rows[0]["sort_priority"]) == (
            "baseball",
            "milb-aaa",
            7,
        )
        assert (rows[1]["sport"], rows[1]["league_code"], rows[1]["sort_priority"]) == (
            "softball",
            "milb-aaa",
            9,
        )
        assert len(rows) == 2

    def test_log_table_remapped(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)
        conn.execute("INSERT INTO epg_matched_streams (detected_league) VALUES ('aaa')")
        conn.commit()

        _run_migrations(conn)

        row = conn.execute("SELECT detected_league FROM epg_matched_streams").fetchone()
        assert row["detected_league"] == "milb-aaa"


class TestV73Idempotent:
    def test_running_twice_is_safe(self, tmp_path):
        conn = _make_v72_db(tmp_path)
        _seed_duplicate_milb_state(conn)

        _run_migrations(conn)
        _run_migrations(conn)  # second run is a no-op (version is already 73)

        codes = {r["league_code"] for r in conn.execute("SELECT league_code FROM leagues")}
        assert "a" not in codes
        assert {"milb-a", "milb-aa", "milb-aaa", "milb-high-a"} <= codes


class TestV73MissingTablesGraceful:
    def test_runs_when_optional_tables_absent(self, tmp_path):
        """v73 must not crash if a table referenced for remap doesn't exist —
        e.g. fresh installs or DBs that never created stream_match_cache.
        """
        db_path = tmp_path / "minimal.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                schema_version INTEGER DEFAULT 72
            )
            """
        )
        conn.execute("INSERT INTO settings (id, schema_version) VALUES (1, 72)")
        conn.execute(
            """
            CREATE TABLE leagues (
                league_code TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                provider_league_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                sport TEXT NOT NULL
            )
            """
        )
        conn.commit()

        # Should not raise even though managed_channels, team_cache, etc. are missing.
        _run_migrations(conn)

        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        assert row["schema_version"] == 76


# ---------------------------------------------------------------------------
# Fresh install: schema.sql ships with no duplicate MiLB rows
# ---------------------------------------------------------------------------


class TestFreshInstall:
    def test_no_duplicate_milb_codes_on_fresh_install(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        init_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        codes = {
            r["league_code"]
            for r in conn.execute("SELECT league_code FROM leagues WHERE sport = 'baseball'")
        }
        assert "a" not in codes
        assert "aa" not in codes
        assert "aaa" not in codes
        assert "higha" not in codes
        assert {"milb-a", "milb-aa", "milb-aaa", "milb-high-a", "rookie"} <= codes

    def test_fresh_install_schema_version_73(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        init_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        assert row["schema_version"] == 76
