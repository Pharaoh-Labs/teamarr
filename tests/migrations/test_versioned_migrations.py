"""Versioned data-migration tests (v73–v77), one section per migration.

Each versioned migration gets a banner section below; the original per-file
docstrings are preserved as section comments. Merged from four one-off files
(iua3.5 step 4). Add new versioned-migration tests as a new section here.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from teamarr.database.connection import init_db
from teamarr.database.migrations import (
    _migrate_stream_match_cache_check,
    _migrate_stream_match_cache_restore_if_needed,
    _migrate_v74_preserve_epg_match_offstate,
    _migrate_v75_extract_art_base_url,
    _run_migrations,
)
from teamarr.utilities.xmltv import apply_art_base_url

# ===========================================================================
# v73 — MiLB duplicate-league dedupe
# ===========================================================================
# Tests for v73 migration: dedupe MiLB league codes after the v2.2 rename.
#
# Background
# ----------
# Commit db53687 (Apr 13, 2026) renamed the MiLB league codes:
#
#     a       → milb-a
#     aa      → milb-aa
#     aaa     → milb-aaa
#     higha   → milb-high-a
#
# `schema.sql` uses ``INSERT OR REPLACE INTO leagues`` keyed on ``league_code``.
# The new rows were inserted but the old rows were never deleted, leaving
# duplicate MiLB entries in the league selector and orphaned teams in
# ``team_cache``. v73 cleans this up and remaps any user-data references.


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
        assert row["schema_version"] == 83


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
        assert row["schema_version"] == 83


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
        assert row["schema_version"] == 83


# ===========================================================================
# v74 — preserve EPG-matching off-state
# ===========================================================================
# Tests for v74 migration: preserve EPG-matching off-state after the global
# switch removal (epic 3lp1.1).
#
# The global ``settings.epg_match_enabled`` master switch was removed; EPG program
# matching and the Dispatcharr channel-source now activate on the per-group
# ``event_epg_groups.epg_match_enabled`` / ``settings.epg_channel_source_enabled``
# flags ALONE. v74 clears those flags when the (now-vestigial) global switch was
# OFF, so a user's effective "off" state survives the upgrade instead of silently
# turning matching on.


def _v74_make_db(
    global_on: bool, channel_source: int, group_flags: list[int]
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            epg_match_enabled BOOLEAN DEFAULT 0,
            epg_channel_source_enabled BOOLEAN DEFAULT 0,
            schema_version INTEGER DEFAULT 73
        )
        """
    )
    conn.execute(
        "INSERT INTO settings (id, epg_match_enabled, epg_channel_source_enabled) "
        "VALUES (1, ?, ?)",
        (int(global_on), channel_source),
    )
    conn.execute(
        """
        CREATE TABLE event_epg_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            epg_match_enabled BOOLEAN DEFAULT 0
        )
        """
    )
    for f in group_flags:
        conn.execute("INSERT INTO event_epg_groups (epg_match_enabled) VALUES (?)", (f,))
    conn.commit()
    return conn


def _group_flags(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT epg_match_enabled FROM event_epg_groups ORDER BY id")
    return [r[0] for r in rows]


def _channel_source(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT epg_channel_source_enabled FROM settings WHERE id = 1").fetchone()
    return row[0]


def test_global_off_clears_dependent_flags():
    # Global switch was OFF → matching was globally inert; preserve that off-state.
    conn = _v74_make_db(global_on=False, channel_source=1, group_flags=[1, 0, 1])
    _migrate_v74_preserve_epg_match_offstate(conn)
    assert _channel_source(conn) == 0
    assert _group_flags(conn) == [0, 0, 0]


def test_global_on_leaves_flags_untouched():
    # Global switch was ON → matching ran before and must continue unchanged.
    conn = _v74_make_db(global_on=True, channel_source=1, group_flags=[1, 0, 1])
    _migrate_v74_preserve_epg_match_offstate(conn)
    assert _channel_source(conn) == 1
    assert _group_flags(conn) == [1, 0, 1]


def test_missing_vestigial_column_is_noop():
    # Partial schema without the vestigial global column → no crash, no changes.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
        "epg_channel_source_enabled BOOLEAN DEFAULT 1)"
    )
    conn.execute("INSERT INTO settings (id, epg_channel_source_enabled) VALUES (1, 1)")
    conn.commit()
    _migrate_v74_preserve_epg_match_offstate(conn)  # must not raise
    assert _channel_source(conn) == 1


# ===========================================================================
# v75/v76 — art base-URL extraction + leading-slash normalization
# ===========================================================================
# Tests for the v75 game-thumbs base URL migration (epic z02s).
#
# Verifies _migrate_v75_extract_art_base_url:
# - extracts a single shared origin and rewrites template art to leading-slash paths
# - leaves URLs absolute when templates span multiple origins (ambiguous)
# - is idempotent and a no-op when already configured
# - and the apply_art_base_url resolver helper round-trips with the stored form.


def _art_make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, art_base_url TEXT DEFAULT '')")
    conn.execute("INSERT INTO settings (id, art_base_url) VALUES (1, '')")
    conn.execute(
        """CREATE TABLE templates (
            id INTEGER PRIMARY KEY,
            program_art_url TEXT,
            event_channel_logo_url TEXT,
            pregame_fallback TEXT,
            postgame_fallback TEXT,
            idle_content TEXT
        )"""
    )
    return conn


def test_single_origin_extracted_and_paths_relativized():
    conn = _art_make_db()
    conn.execute(
        "INSERT INTO templates (id, program_art_url, event_channel_logo_url, "
        "pregame_fallback, postgame_fallback, idle_content) VALUES (1, ?, ?, ?, ?, ?)",
        (
            "http://localhost:3000/{league}/cover.png",
            "http://localhost:3000/logo.png",
            json.dumps({"art_url": "http://localhost:3000/pre.png"}),
            json.dumps({"art_url": None}),
            json.dumps({"title": "x"}),
        ),
    )

    _migrate_v75_extract_art_base_url(conn)

    base = conn.execute("SELECT art_base_url FROM settings WHERE id = 1").fetchone()[0]
    assert base == "http://localhost:3000"
    row = conn.execute("SELECT * FROM templates WHERE id = 1").fetchone()
    assert row["program_art_url"] == "/{league}/cover.png"  # leading slash kept
    assert row["event_channel_logo_url"] == "/logo.png"
    assert json.loads(row["pregame_fallback"])["art_url"] == "/pre.png"
    # base + stored path resolves back to the original absolute URL
    assert (
        apply_art_base_url(row["program_art_url"], base)
        == "http://localhost:3000/{league}/cover.png"
    )


def test_divergent_origins_pick_most_frequent_winner():
    conn = _art_make_db()
    # a.com appears twice, b.com once -> a.com wins; b.com left absolute.
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (1, 'http://a.com/x.png')")
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (2, 'http://a.com/y.png')")
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (3, 'http://b.com/z.png')")

    _migrate_v75_extract_art_base_url(conn)

    assert (
        conn.execute("SELECT art_base_url FROM settings WHERE id = 1").fetchone()[0]
        == "http://a.com"
    )

    # winner's URLs relativized (leading slash)
    def art(i):
        return conn.execute("SELECT program_art_url FROM templates WHERE id = ?", (i,)).fetchone()[
            0
        ]

    assert art(1) == "/x.png"
    assert art(2) == "/y.png"
    # loser's URL left absolute (resolver passes it through)
    assert (
        conn.execute("SELECT program_art_url FROM templates WHERE id = 3").fetchone()[0]
        == "http://b.com/z.png"
    )


def test_noop_when_already_configured():
    conn = _art_make_db()
    conn.execute("UPDATE settings SET art_base_url = 'http://preset.com' WHERE id = 1")
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (1, 'http://other.com/x.png')")

    _migrate_v75_extract_art_base_url(conn)

    # User-set base preserved; URL untouched.
    assert (
        conn.execute("SELECT art_base_url FROM settings WHERE id = 1").fetchone()[0]
        == "http://preset.com"
    )
    assert (
        conn.execute("SELECT program_art_url FROM templates WHERE id = 1").fetchone()[0]
        == "http://other.com/x.png"
    )


def test_idempotent_second_run_noops():
    conn = _art_make_db()
    conn.execute(
        "INSERT INTO templates (id, program_art_url) VALUES (1, 'http://localhost:3000/a.png')"
    )
    _migrate_v75_extract_art_base_url(conn)
    first = conn.execute("SELECT program_art_url FROM templates WHERE id = 1").fetchone()[0]
    _migrate_v75_extract_art_base_url(conn)  # already configured -> no-op
    second = conn.execute("SELECT program_art_url FROM templates WHERE id = 1").fetchone()[0]
    assert first == second == "/a.png"


@pytest.mark.parametrize(
    "value,base,expected",
    [
        ("/a.png", "http://x:3000", "http://x:3000/a.png"),
        ("a.png", "http://x:3000/", "http://x:3000/a.png"),
        ("https://espn.com/a.png", "http://x:3000", "https://espn.com/a.png"),
        ("", "http://x", ""),
        ("a.png", "", "a.png"),
        # v76-corrupted "/{var}" templates rendered "/https://…" (#275) —
        # repaired at the choke point, with and without a base configured.
        ("/https://espn.com/a.png", "", "https://espn.com/a.png"),
        ("/https://espn.com/a.png", "http://x:3000", "https://espn.com/a.png"),
    ],
)
def test_apply_art_base_url(value, base, expected):
    assert apply_art_base_url(value, base) == expected


# --- v76: leading-slash normalization -------------------------------------


def test_v76_adds_leading_slash_to_relative_paths():
    from teamarr.database.migrations import _migrate_v76_leading_slash_art_paths

    conn = _art_make_db()
    conn.execute(
        "INSERT INTO templates (id, program_art_url, event_channel_logo_url, pregame_fallback) "
        "VALUES (1, ?, ?, ?)",
        (
            "{league}/cover.png",  # relative, no slash
            "https://espn.com/logo.png",  # absolute — untouched
            json.dumps({"art_url": "pre.png"}),  # relative, no slash
        ),
    )

    _migrate_v76_leading_slash_art_paths(conn)

    row = conn.execute("SELECT * FROM templates WHERE id = 1").fetchone()
    assert row["program_art_url"] == "/{league}/cover.png"
    assert row["event_channel_logo_url"] == "https://espn.com/logo.png"  # absolute kept
    assert json.loads(row["pregame_fallback"])["art_url"] == "/pre.png"


def test_v76_idempotent_on_already_slashed():
    from teamarr.database.migrations import _migrate_v76_leading_slash_art_paths

    conn = _art_make_db()
    conn.execute("INSERT INTO templates (id, program_art_url) VALUES (1, '/already/ok.png')")
    _migrate_v76_leading_slash_art_paths(conn)
    val = conn.execute("SELECT program_art_url FROM templates WHERE id = 1").fetchone()[0]
    assert val == "/already/ok.png"


# --- create/update normalization ------------------------------------------


def test_resolve_art_applies_base_uniformly(monkeypatch):
    """resolve_art (the single shared art entry point) prefixes the base for
    relative values, passes absolute through, and no-ops with no base — so every
    sink that uses it (EPG icon, Dispatcharr channel logo, fillers) reconstructs
    identically."""
    from teamarr.templates.resolver import TemplateResolver

    r = TemplateResolver("http://host:4999")
    # relative -> base prefixed
    monkeypatch.setattr(r, "resolve", lambda t, c: "/nba/cover.png")
    assert r.resolve_art("x", None) == "http://host:4999/nba/cover.png"
    # absolute -> passthrough (idempotent; another sink can't double-apply)
    monkeypatch.setattr(r, "resolve", lambda t, c: "http://other:9196/c.png")
    assert r.resolve_art("x", None) == "http://other:9196/c.png"
    # no base -> unchanged
    r2 = TemplateResolver("")
    monkeypatch.setattr(r2, "resolve", lambda t, c: "/nba/cover.png")
    assert r2.resolve_art("x", None) == "/nba/cover.png"


def test_create_update_normalize_art_paths():
    from teamarr.database.templates import _normalize_art_in_kwargs

    kw = {
        "program_art_url": "art/{league}/cover.png",
        "event_channel_logo_url": "https://espn.com/x.png",
        "pregame_fallback": {"art_url": "pre.png", "title": "t"},
        "name": "x",
    }
    _normalize_art_in_kwargs(kw)
    assert kw["program_art_url"] == "/art/{league}/cover.png"
    assert kw["event_channel_logo_url"] == "https://espn.com/x.png"  # absolute untouched
    assert kw["pregame_fallback"]["art_url"] == "/pre.png"
    assert kw["name"] == "x"  # non-art untouched


def test_create_update_never_roots_variable_led_art():
    """Variable-led art values must not get a leading slash (#275) — the
    variable may resolve to an absolute URL. Corrupted '/{var}' input is
    repaired on save."""
    from teamarr.database.templates import _normalize_art_in_kwargs

    kw = {
        "program_art_url": "{feed_team_logo}",
        "event_channel_logo_url": "/{feed_team_logo}",  # corrupted by old save path
        "pregame_fallback": {"art_url": "{league_logo}", "title": "t"},
    }
    _normalize_art_in_kwargs(kw)
    assert kw["program_art_url"] == "{feed_team_logo}"
    assert kw["event_channel_logo_url"] == "{feed_team_logo}"  # repaired
    assert kw["pregame_fallback"]["art_url"] == "{league_logo}"


# --- v78: strip corrupting slash before variable-led art values (#275) ------


def test_v78_strips_slash_before_variable_led_art():
    from teamarr.database.migrations import _migrate_v78_strip_slash_before_art_variable

    conn = _art_make_db()
    conn.execute(
        "INSERT INTO templates (id, program_art_url, event_channel_logo_url, pregame_fallback) "
        "VALUES (1, ?, ?, ?)",
        (
            "/{feed_team_logo}",  # corrupted by v76 -> repaired
            "/art/{league}.png",  # genuinely relative, mid-path var -> kept
            json.dumps({"art_url": "//{game_thumbnail}"}),  # multi-slash -> repaired
        ),
    )

    _migrate_v78_strip_slash_before_art_variable(conn)

    row = conn.execute("SELECT * FROM templates WHERE id = 1").fetchone()
    assert row["program_art_url"] == "{feed_team_logo}"
    assert row["event_channel_logo_url"] == "/art/{league}.png"
    assert json.loads(row["pregame_fallback"])["art_url"] == "{game_thumbnail}"


def test_v78_idempotent_and_leaves_clean_values():
    from teamarr.database.migrations import _migrate_v78_strip_slash_before_art_variable

    conn = _art_make_db()
    conn.execute(
        "INSERT INTO templates (id, program_art_url, event_channel_logo_url) VALUES (1, ?, ?)",
        ("{feed_team_logo}", "https://espn.com/logo.png"),
    )
    _migrate_v78_strip_slash_before_art_variable(conn)
    _migrate_v78_strip_slash_before_art_variable(conn)
    row = conn.execute("SELECT * FROM templates WHERE id = 1").fetchone()
    assert row["program_art_url"] == "{feed_team_logo}"
    assert row["event_channel_logo_url"] == "https://espn.com/logo.png"


# --- v79: backfill managed_channels team abbrevs (#403) ---------------------


def _v79_make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE managed_channels (
            id INTEGER PRIMARY KEY, event_provider TEXT, league TEXT,
            home_team TEXT, home_team_abbrev TEXT,
            away_team TEXT, away_team_abbrev TEXT, deleted_at TIMESTAMP
        )"""
    )
    conn.execute(
        """CREATE TABLE team_cache (
            id INTEGER PRIMARY KEY, team_name TEXT, team_abbrev TEXT,
            provider TEXT, league TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO team_cache (team_name, team_abbrev, provider, league) VALUES "
        "('Minnesota Twins', 'MIN', 'espn', 'mlb'), "
        "('Los Angeles Angels', 'LAA', 'espn', 'mlb')"
    )
    return conn


def test_v79_backfills_abbrevs():
    from teamarr.database.migrations import _migrate_v79_backfill_channel_team_display

    conn = _v79_make_db()
    conn.execute(
        "INSERT INTO managed_channels (id, event_provider, league, home_team, away_team) "
        "VALUES (1, 'espn', 'mlb', 'Minnesota Twins', 'Los Angeles Angels')"
    )
    # Deleted row and unmatched team must stay untouched/NULL
    conn.execute(
        "INSERT INTO managed_channels (id, event_provider, league, home_team, away_team, "
        "deleted_at) VALUES (2, 'espn', 'mlb', 'Minnesota Twins', 'Los Angeles Angels', "
        "'2026-01-01')"
    )
    conn.execute(
        "INSERT INTO managed_channels (id, event_provider, league, home_team) "
        "VALUES (3, 'espn', 'mlb', 'Unknown Club')"
    )

    _migrate_v79_backfill_channel_team_display(conn)

    row = conn.execute("SELECT * FROM managed_channels WHERE id = 1").fetchone()
    assert row["home_team_abbrev"] == "MIN"
    assert row["away_team_abbrev"] == "LAA"

    deleted = conn.execute("SELECT * FROM managed_channels WHERE id = 2").fetchone()
    assert deleted["home_team_abbrev"] is None

    unmatched = conn.execute("SELECT * FROM managed_channels WHERE id = 3").fetchone()
    assert unmatched["home_team_abbrev"] is None


def test_v79_skips_gracefully_on_old_team_cache_shape():
    from teamarr.database.migrations import _migrate_v79_backfill_channel_team_display

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE managed_channels (id INTEGER PRIMARY KEY, home_team TEXT)")
    conn.execute("CREATE TABLE team_cache (id INTEGER PRIMARY KEY, team_name TEXT)")
    # Pre-abbrev team_cache shape: nothing to backfill from — must not raise
    _migrate_v79_backfill_channel_team_display(conn)


# ===========================================================================
# v77 — stream_match_cache CHECK rebuild
# ===========================================================================
# v77: stream_match_cache CHECK rebuild — allow 'direct'/'epg' match methods.
#
# RacingMatcher (v2.8.0) and TennisMatcher (mf7) cache matches with
# match_method='direct', which the pre-v77 CHECK rejected — every direct-match
# cache write failed silently. The rebuild must preserve user-corrected rows
# (pinned matches are user data) while discarding disposable algorithmic rows.


_OLD_TABLE = """
CREATE TABLE stream_match_cache (
    fingerprint TEXT PRIMARY KEY,
    group_id INTEGER,
    stream_id INTEGER,
    stream_name TEXT,
    event_id TEXT,
    league TEXT,
    cached_data TEXT,
    generation INTEGER,
    match_method TEXT DEFAULT 'fuzzy'
        CHECK(match_method IN ('cache', 'user_corrected', 'alias', 'pattern',
                               'fuzzy', 'keyword', 'no_match')),
    user_corrected BOOLEAN DEFAULT 0,
    corrected_at TIMESTAMP
)
"""

_NEW_TABLE = _OLD_TABLE.replace("'no_match')", "'no_match', 'direct', 'epg')")


def _seed(conn):
    conn.execute(
        "INSERT INTO stream_match_cache "
        "(fingerprint, stream_name, event_id, match_method, user_corrected) "
        "VALUES ('fp-user', 'PINNED', 'e1', 'user_corrected', 1)"
    )
    conn.execute(
        "INSERT INTO stream_match_cache "
        "(fingerprint, stream_name, event_id, match_method, user_corrected) "
        "VALUES ('fp-algo', 'ALGO', 'e2', 'fuzzy', 0)"
    )


def test_old_check_rejects_direct():
    conn = sqlite3.connect(":memory:")
    conn.execute(_OLD_TABLE)
    try:
        conn.execute(
            "INSERT INTO stream_match_cache (fingerprint, match_method) "
            "VALUES ('x', 'direct')"
        )
        rejected = False
    except sqlite3.IntegrityError:
        rejected = True
    assert rejected  # documents the bug the migration fixes


def test_rebuild_preserves_user_corrections_and_allows_direct():
    conn = sqlite3.connect(":memory:")
    conn.execute(_OLD_TABLE)
    _seed(conn)

    # Pre-migration: stale CHECK detected → backup corrections, drop table
    _migrate_stream_match_cache_check(conn)
    assert not conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='stream_match_cache'"
    ).fetchone()[0]
    assert conn.execute(
        "SELECT COUNT(*) FROM _stream_match_cache_backup"
    ).fetchone()[0] == 1  # only the pinned row

    # executescript would recreate with the new CHECK
    conn.execute(_NEW_TABLE)
    _migrate_stream_match_cache_restore_if_needed(conn)

    rows = conn.execute(
        "SELECT fingerprint, user_corrected FROM stream_match_cache"
    ).fetchall()
    assert rows == [("fp-user", 1)]  # pinned survived, algo row discarded

    # 'direct' now inserts cleanly (the original failure mode)
    conn.execute(
        "INSERT INTO stream_match_cache (fingerprint, match_method) "
        "VALUES ('fp-direct', 'direct')"
    )
    # backup cleaned up
    assert not conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='_stream_match_cache_backup'"
    ).fetchone()[0]


def test_rebuild_skipped_when_check_current():
    conn = sqlite3.connect(":memory:")
    conn.execute(_NEW_TABLE)
    _seed(conn)
    _migrate_stream_match_cache_check(conn)
    # Table untouched
    assert conn.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# v80: filler final/not-final conditionals -> condition rows (#420)
# ---------------------------------------------------------------------------


def _v80_make_db(postgame_cond=None, idle_cond=None, rows_precontent=None):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE templates (
            id INTEGER PRIMARY KEY,
            postgame_conditional JSON,
            idle_conditional JSON,
            pregame_conditional_rows JSON DEFAULT '[]',
            postgame_conditional_rows JSON DEFAULT '[]',
            idle_conditional_rows JSON DEFAULT '[]'
        )"""
    )
    conn.execute(
        "INSERT INTO templates (id, postgame_conditional, idle_conditional, "
        "postgame_conditional_rows) VALUES (1, ?, ?, ?)",
        (
            json.dumps(postgame_cond) if postgame_cond else None,
            json.dumps(idle_cond) if idle_cond else None,
            json.dumps(rows_precontent) if rows_precontent else "[]",
        ),
    )
    return conn


def _v80_rows(conn, col="postgame_conditional_rows"):
    return json.loads(conn.execute(f"SELECT {col} FROM templates WHERE id=1").fetchone()[0])


def test_v80_converts_enabled_pair_to_disjoint_rows():
    from teamarr.database.migrations import _migrate_v80_filler_conditionals_to_rows

    conn = _v80_make_db(
        postgame_cond={
            "enabled": True,
            "title_final": "Recap",
            "description_final": "{game_recap.last}",
            "title_not_final": None,
            "description_not_final": "Still going",
        }
    )
    _migrate_v80_filler_conditionals_to_rows(conn)

    rows = _v80_rows(conn)
    assert [r["condition"] for r in rows] == ["is_final", "is_not_final"]
    final, not_final = rows
    # Only SET fields ride each row — unset fields must fall to base at
    # render time, so they must NOT appear here.
    assert final["title"] == "Recap"
    assert final["template"] == "{game_recap.last}"
    assert "subtitle" not in final
    assert not_final["template"] == "Still going"
    assert "title" not in not_final


def test_v80_disabled_and_empty_produce_no_rows():
    from teamarr.database.migrations import _migrate_v80_filler_conditionals_to_rows

    # Disabled with content: today the switch never fires -> no rows.
    conn = _v80_make_db(postgame_cond={"enabled": False, "title_final": "X"})
    _migrate_v80_filler_conditionals_to_rows(conn)
    assert _v80_rows(conn) == []

    # Enabled but all fields falsy (None/""): today falls to base -> no rows.
    conn = _v80_make_db(
        postgame_cond={
            "enabled": True,
            "title_final": None,
            "description_final": "",
            "description_not_final": None,
        }
    )
    _migrate_v80_filler_conditionals_to_rows(conn)
    assert _v80_rows(conn) == []


def test_v80_idle_converts_independently():
    from teamarr.database.migrations import _migrate_v80_filler_conditionals_to_rows

    conn = _v80_make_db(
        idle_cond={"enabled": True, "description_final": "Last game recap line"}
    )
    _migrate_v80_filler_conditionals_to_rows(conn)
    assert _v80_rows(conn) == []  # postgame untouched
    idle_rows = _v80_rows(conn, "idle_conditional_rows")
    assert len(idle_rows) == 1
    assert idle_rows[0]["condition"] == "is_final"
    assert idle_rows[0]["template"] == "Last game recap line"


def test_v80_skips_templates_with_existing_rows():
    from teamarr.database.migrations import _migrate_v80_filler_conditionals_to_rows

    user_rows = [{"condition": "has_recap", "template": "custom", "priority": 5}]
    conn = _v80_make_db(
        postgame_cond={"enabled": True, "title_final": "X"},
        rows_precontent=user_rows,
    )
    _migrate_v80_filler_conditionals_to_rows(conn)
    assert _v80_rows(conn) == user_rows  # never clobbered


def test_v80_idempotent_second_run_is_noop():
    from teamarr.database.migrations import _migrate_v80_filler_conditionals_to_rows

    conn = _v80_make_db(postgame_cond={"enabled": True, "title_final": "X"})
    _migrate_v80_filler_conditionals_to_rows(conn)
    first = _v80_rows(conn)
    _migrate_v80_filler_conditionals_to_rows(conn)
    assert _v80_rows(conn) == first


def test_v80_legacy_columns_untouched():
    from teamarr.database.migrations import _migrate_v80_filler_conditionals_to_rows

    legacy = {"enabled": True, "title_final": "X", "description_not_final": "Y"}
    conn = _v80_make_db(postgame_cond=legacy)
    _migrate_v80_filler_conditionals_to_rows(conn)
    stored = json.loads(
        conn.execute("SELECT postgame_conditional FROM templates WHERE id=1").fetchone()[0]
    )
    assert stored == legacy


# ---------------------------------------------------------------------------
# v81: seed 'Sports event' into template event categories (#423)
# ---------------------------------------------------------------------------


def _v81_make_db(cats_json):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE templates (id INTEGER PRIMARY KEY, xmltv_categories JSON)")
    conn.execute("INSERT INTO templates (id, xmltv_categories) VALUES (1, ?)", (cats_json,))
    return conn


def _v81_cats(conn):
    return json.loads(
        conn.execute("SELECT xmltv_categories FROM templates WHERE id=1").fetchone()[0]
    )


def test_v81_appends_sports_event_when_missing():
    from teamarr.database.migrations import _migrate_v81_seed_sports_event_category

    conn = _v81_make_db('["Sports"]')
    _migrate_v81_seed_sports_event_category(conn)
    assert _v81_cats(conn) == ["Sports", "Sports event"]


def test_v81_preserves_custom_categories_and_order():
    from teamarr.database.migrations import _migrate_v81_seed_sports_event_category

    conn = _v81_make_db('["Basketball", "Sports", "My Custom"]')
    _migrate_v81_seed_sports_event_category(conn)
    assert _v81_cats(conn) == ["Basketball", "Sports", "My Custom", "Sports event"]


def test_v81_idempotent_when_already_present():
    from teamarr.database.migrations import _migrate_v81_seed_sports_event_category

    conn = _v81_make_db('["Sports", "Sports event"]')
    _migrate_v81_seed_sports_event_category(conn)
    assert _v81_cats(conn) == ["Sports", "Sports event"]


def test_v81_skips_malformed_json():
    from teamarr.database.migrations import _migrate_v81_seed_sports_event_category

    conn = _v81_make_db("not json")
    _migrate_v81_seed_sports_event_category(conn)  # must not raise
    row = conn.execute("SELECT xmltv_categories FROM templates WHERE id=1").fetchone()
    assert row[0] == "not json"


def test_v81_normalizes_our_starter_variants_in_place():
    from teamarr.database.migrations import _migrate_v81_seed_sports_event_category

    # "Sports Event" (team starters) and "Sporting Event" (event starters)
    # were OUR seeded strings — normalize to canonical, preserving position.
    conn = _v81_make_db('["Sports", "Sports Event"]')
    _migrate_v81_seed_sports_event_category(conn)
    assert _v81_cats(conn) == ["Sports", "Sports event"]

    conn = _v81_make_db('["Sports", "Sporting Event", "My Custom"]')
    _migrate_v81_seed_sports_event_category(conn)
    assert _v81_cats(conn) == ["Sports", "Sports event", "My Custom"]


def test_v81_collapses_duplicate_variants():
    from teamarr.database.migrations import _migrate_v81_seed_sports_event_category

    conn = _v81_make_db('["Sporting Event", "Sports Event"]')
    _migrate_v81_seed_sports_event_category(conn)
    assert _v81_cats(conn) == ["Sports event"]


# ---------------------------------------------------------------------------
# v82: fold scalar Channels DVR settings into channelsdvr_servers list (#381)
# ---------------------------------------------------------------------------


def _make_v81_cdvr_db(tmp_path: Path, url, source, lineup) -> sqlite3.Connection:
    """Minimal v81 settings table with the pre-#381 scalar CDVR columns."""
    db_path = tmp_path / "cdvr.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version INTEGER DEFAULT 81,
            channelsdvr_enabled BOOLEAN DEFAULT 0,
            channelsdvr_url TEXT,
            channelsdvr_source_name TEXT,
            channelsdvr_lineup_id TEXT,
            channelsdvr_servers JSON
        )
        """
    )
    conn.execute(
        """
        INSERT INTO settings
            (id, schema_version, channelsdvr_enabled, channelsdvr_url,
             channelsdvr_source_name, channelsdvr_lineup_id)
        VALUES (1, 81, 1, ?, ?, ?)
        """,
        (url, source, lineup),
    )
    return conn


class TestV82ChannelsDVRServersList:
    def test_scalar_settings_fold_into_servers_list(self, tmp_path):
        conn = _make_v81_cdvr_db(
            tmp_path, "http://cdvr:8089/", "Teamarr", "XMLTV-Teamarr"
        )

        _run_migrations(conn)

        row = conn.execute(
            "SELECT schema_version, channelsdvr_servers FROM settings WHERE id = 1"
        ).fetchone()
        assert row["schema_version"] == 83
        servers = json.loads(row["channelsdvr_servers"])
        assert servers == [
            {
                "name": "Channels DVR",
                "url": "http://cdvr:8089",  # trailing slash stripped
                "source_name": "Teamarr",
                "lineup_id": "XMLTV-Teamarr",
            }
        ]

    def test_unconfigured_scalar_leaves_servers_null(self, tmp_path):
        conn = _make_v81_cdvr_db(tmp_path, None, None, None)

        _run_migrations(conn)

        row = conn.execute(
            "SELECT schema_version, channelsdvr_servers FROM settings WHERE id = 1"
        ).fetchone()
        assert row["schema_version"] == 83
        assert row["channelsdvr_servers"] is None

    def test_settings_roundtrip_servers_list(self, db_conn):
        from teamarr.database.settings import (
            get_channelsdvr_settings,
            update_channelsdvr_settings,
        )

        update_channelsdvr_settings(
            db_conn,
            enabled=True,
            servers=[
                {"name": "East", "url": "http://east:8089/", "source_name": "Teamarr",
                 "lineup_id": "XMLTV-Teamarr"},
                {"name": "West", "url": "http://west:8089", "source_name": "Teamarr",
                 "lineup_id": None},
            ],
        )

        settings = get_channelsdvr_settings(db_conn)
        assert settings.enabled is True
        assert len(settings.servers) == 2
        assert settings.servers[0].name == "East"
        assert settings.servers[0].url == "http://east:8089"  # slash stripped
        assert settings.servers[1].lineup_id is None
