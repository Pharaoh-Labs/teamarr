"""Behavior + idempotency tests for individual migration helpers.

Each helper extracted from _run_migrations gets a focused test that pins its
data transform AND verifies running it twice is safe. Idempotency is the key
property that makes a future v72 checkpoint consolidation feasible — we can
re-derive the consolidated logic FROM these tests without re-reasoning about
each migration block.

Existing dedicated tests (not duplicated here):
  - v43 checkpoint            → tests/test_checkpoint_v43.py
  - v58 sports subscription   → tests/test_subscription_migration.py
  - v59 channel numbering     → tests/test_channel_numbering_v59.py
  - v72 xmltv categories      → tests/test_xmltv_filler_categories.py
"""

from __future__ import annotations

import json
import sqlite3

import pytest


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _settings_table(db: sqlite3.Connection) -> None:
    """Minimal settings table used by every migration."""
    db.execute("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version INTEGER DEFAULT 0,
            api_timeout INTEGER DEFAULT 10,
            api_retry_count INTEGER DEFAULT 3,
            default_duplicate_event_handling TEXT DEFAULT 'consolidate'
        )
    """)
    db.execute("INSERT INTO settings (id) VALUES (1)")


# =============================================================================
# v50: soccer selection modes
# =============================================================================


class TestV50SoccerModes:
    """v50 derives soccer_mode per group: 'all' if it has every soccer league,
    'manual' if it has a subset, NULL if it has none."""

    def _setup(self, db: sqlite3.Connection) -> None:
        _settings_table(db)
        db.execute("""
            CREATE TABLE leagues (
                id INTEGER PRIMARY KEY,
                league_code TEXT NOT NULL UNIQUE,
                sport TEXT,
                enabled INTEGER DEFAULT 1
            )
        """)
        for code in ("eng.1", "esp.1", "ita.1"):
            db.execute(
                "INSERT INTO leagues (league_code, sport, enabled) VALUES (?, 'soccer', 1)",
                (code,),
            )
        db.execute(
            "INSERT INTO leagues (league_code, sport, enabled) VALUES ('mlb', 'baseball', 1)"
        )
        db.execute("""
            CREATE TABLE event_epg_groups (
                id INTEGER PRIMARY KEY,
                name TEXT,
                leagues JSON
            )
        """)

    def test_group_with_all_soccer_leagues_becomes_all(self, db):
        from teamarr.database.migrations import _migrate_v50_soccer_modes

        self._setup(db)
        db.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'Soccer All', ?)",
            (json.dumps(["eng.1", "esp.1", "ita.1"]),),
        )

        _migrate_v50_soccer_modes(db)

        row = db.execute("SELECT soccer_mode FROM event_epg_groups WHERE id = 1").fetchone()
        assert row["soccer_mode"] == "all"

    def test_group_with_subset_becomes_manual(self, db):
        from teamarr.database.migrations import _migrate_v50_soccer_modes

        self._setup(db)
        db.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'EPL Only', ?)",
            (json.dumps(["eng.1"]),),
        )

        _migrate_v50_soccer_modes(db)

        row = db.execute("SELECT soccer_mode FROM event_epg_groups WHERE id = 1").fetchone()
        assert row["soccer_mode"] == "manual"

    def test_non_soccer_group_stays_null(self, db):
        from teamarr.database.migrations import _migrate_v50_soccer_modes

        self._setup(db)
        db.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'Baseball', ?)",
            (json.dumps(["mlb"]),),
        )

        _migrate_v50_soccer_modes(db)

        row = db.execute("SELECT soccer_mode FROM event_epg_groups WHERE id = 1").fetchone()
        assert row["soccer_mode"] is None

    def test_idempotent(self, db):
        from teamarr.database.migrations import _migrate_v50_soccer_modes

        self._setup(db)
        db.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'EPL', ?)",
            (json.dumps(["eng.1"]),),
        )
        _migrate_v50_soccer_modes(db)
        _migrate_v50_soccer_modes(db)
        row = db.execute("SELECT soccer_mode FROM event_epg_groups WHERE id = 1").fetchone()
        assert row["soccer_mode"] == "manual"

    def test_no_soccer_leagues_in_db_is_safe(self, db):
        """If the leagues table has no soccer entries, leave everything NULL."""
        from teamarr.database.migrations import _migrate_v50_soccer_modes

        _settings_table(db)
        db.execute("""
            CREATE TABLE leagues (
                id INTEGER PRIMARY KEY,
                league_code TEXT NOT NULL UNIQUE,
                sport TEXT,
                enabled INTEGER DEFAULT 1
            )
        """)
        db.execute("""
            CREATE TABLE event_epg_groups (
                id INTEGER PRIMARY KEY,
                name TEXT,
                leagues JSON
            )
        """)
        db.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'Empty', ?)",
            (json.dumps(["mlb"]),),
        )

        _migrate_v50_soccer_modes(db)  # should not error

        row = db.execute("SELECT soccer_mode FROM event_epg_groups WHERE id = 1").fetchone()
        assert row["soccer_mode"] is None


# =============================================================================
# v53: api timeout/retry defaults
# =============================================================================


class TestV53ApiDefaults:
    """v53 lifts api_timeout from old default 10 → 30 and api_retry_count 3 → 5
    only for users still on the old defaults. Customized values stay."""

    def test_lifts_old_defaults(self, db):
        from teamarr.database.migrations import _migrate_v53_api_defaults

        _settings_table(db)
        # Both at old defaults
        _migrate_v53_api_defaults(db)
        row = db.execute("SELECT api_timeout, api_retry_count FROM settings").fetchone()
        assert row["api_timeout"] == 30
        assert row["api_retry_count"] == 5

    def test_preserves_customized_values(self, db):
        from teamarr.database.migrations import _migrate_v53_api_defaults

        _settings_table(db)
        db.execute("UPDATE settings SET api_timeout = 60, api_retry_count = 7 WHERE id = 1")
        _migrate_v53_api_defaults(db)
        row = db.execute("SELECT api_timeout, api_retry_count FROM settings").fetchone()
        assert row["api_timeout"] == 60
        assert row["api_retry_count"] == 7

    def test_idempotent(self, db):
        from teamarr.database.migrations import _migrate_v53_api_defaults

        _settings_table(db)
        _migrate_v53_api_defaults(db)
        _migrate_v53_api_defaults(db)
        row = db.execute("SELECT api_timeout, api_retry_count FROM settings").fetchone()
        # Once we've upgraded to 30/5 the second run finds nothing matching
        # the old defaults and leaves them alone.
        assert row["api_timeout"] == 30
        assert row["api_retry_count"] == 5


# =============================================================================
# v61: subscription_league_config table creation
# =============================================================================


class TestV61SubscriptionLeagueConfig:
    def test_creates_table(self, db):
        from teamarr.database.migrations import _migrate_v61_subscription_league_config

        _migrate_v61_subscription_league_config(db)
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='subscription_league_config'"
        )
        assert cursor.fetchone() is not None

    def test_idempotent(self, db):
        from teamarr.database.migrations import _migrate_v61_subscription_league_config

        _migrate_v61_subscription_league_config(db)
        # Insert a row
        db.execute("INSERT INTO subscription_league_config (league_code) VALUES ('eng.1')")
        _migrate_v61_subscription_league_config(db)  # second call should be no-op
        # Row still there
        cursor = db.execute(
            "SELECT league_code FROM subscription_league_config WHERE league_code = 'eng.1'"
        )
        assert cursor.fetchone() is not None


# =============================================================================
# v62: default channel group + relax CHECK on subscription_league_config
# =============================================================================


class TestV62DefaultChannelGroup:
    def _setup(self, db: sqlite3.Connection) -> None:
        _settings_table(db)
        db.execute("""
            CREATE TABLE subscription_league_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_code TEXT NOT NULL UNIQUE,
                channel_profile_ids JSON DEFAULT NULL,
                channel_group_id INTEGER DEFAULT NULL,
                channel_group_mode TEXT DEFAULT NULL
                    CHECK(channel_group_mode IS NULL
                          OR channel_group_mode IN ('static', 'sport', 'league'))
            )
        """)

    def test_adds_default_channel_group_columns(self, db):
        from teamarr.database.migrations import _migrate_v62_default_channel_group

        self._setup(db)
        _migrate_v62_default_channel_group(db)

        cols = {row[1] for row in db.execute("PRAGMA table_info(settings)")}
        assert "default_channel_group_id" in cols
        assert "default_channel_group_mode" in cols

    def test_relaxes_check_constraint_allowing_custom_pattern(self, db):
        from teamarr.database.migrations import _migrate_v62_default_channel_group

        self._setup(db)
        _migrate_v62_default_channel_group(db)

        # Should accept a custom pattern post-migration (was blocked by CHECK before)
        db.execute(
            "INSERT INTO subscription_league_config (league_code, channel_group_mode) "
            "VALUES ('eng.1', '{sport} | {league}')"
        )
        row = db.execute(
            "SELECT channel_group_mode FROM subscription_league_config WHERE league_code='eng.1'"
        ).fetchone()
        assert row["channel_group_mode"] == "{sport} | {league}"

    def test_preserves_existing_rows(self, db):
        from teamarr.database.migrations import _migrate_v62_default_channel_group

        self._setup(db)
        db.execute(
            "INSERT INTO subscription_league_config "
            "(league_code, channel_group_mode) VALUES ('mlb', 'sport')"
        )
        _migrate_v62_default_channel_group(db)

        row = db.execute(
            "SELECT channel_group_mode FROM subscription_league_config WHERE league_code='mlb'"
        ).fetchone()
        assert row["channel_group_mode"] == "sport"

    def test_idempotent(self, db):
        from teamarr.database.migrations import _migrate_v62_default_channel_group

        self._setup(db)
        _migrate_v62_default_channel_group(db)
        # Second run shouldn't error or duplicate columns.
        _migrate_v62_default_channel_group(db)

        cols = {row[1] for row in db.execute("PRAGMA table_info(settings)")}
        assert "default_channel_group_id" in cols


# =============================================================================
# v66: TSDB tiered provider model
# =============================================================================


class TestV66TsdbTiers:
    def _setup(self, db: sqlite3.Connection) -> None:
        db.execute("""
            CREATE TABLE leagues (
                id INTEGER PRIMARY KEY,
                league_code TEXT NOT NULL UNIQUE
            )
        """)
        for code in ("cfl", "ipl", "mlb", "boxing"):
            db.execute("INSERT INTO leagues (league_code) VALUES (?)", (code,))

    def test_tags_free_leagues(self, db):
        from teamarr.database.migrations import _migrate_v66_tsdb_tiers

        self._setup(db)
        _migrate_v66_tsdb_tiers(db)

        row = db.execute("SELECT tsdb_tier FROM leagues WHERE league_code='cfl'").fetchone()
        assert row["tsdb_tier"] == "free"
        row = db.execute("SELECT tsdb_tier FROM leagues WHERE league_code='boxing'").fetchone()
        assert row["tsdb_tier"] == "free"

    def test_tags_premium_leagues(self, db):
        from teamarr.database.migrations import _migrate_v66_tsdb_tiers

        self._setup(db)
        _migrate_v66_tsdb_tiers(db)

        row = db.execute("SELECT tsdb_tier FROM leagues WHERE league_code='ipl'").fetchone()
        assert row["tsdb_tier"] == "premium"

    def test_unrecognized_leagues_stay_null(self, db):
        from teamarr.database.migrations import _migrate_v66_tsdb_tiers

        self._setup(db)
        _migrate_v66_tsdb_tiers(db)

        row = db.execute("SELECT tsdb_tier FROM leagues WHERE league_code='mlb'").fetchone()
        assert row["tsdb_tier"] is None

    def test_idempotent(self, db):
        from teamarr.database.migrations import _migrate_v66_tsdb_tiers

        self._setup(db)
        _migrate_v66_tsdb_tiers(db)
        _migrate_v66_tsdb_tiers(db)
        row = db.execute("SELECT tsdb_tier FROM leagues WHERE league_code='ipl'").fetchone()
        assert row["tsdb_tier"] == "premium"

    def test_handles_missing_leagues_table(self, db):
        """No leagues table (minimal test DB) — should not raise."""
        from teamarr.database.migrations import _migrate_v66_tsdb_tiers

        # Just create something — column-add will look for `leagues` and skip.
        _migrate_v66_tsdb_tiers(db)


# =============================================================================
# v67: remove Cricbuzz provider
# =============================================================================


class TestV67RemoveCricbuzz:
    def _setup(self, db: sqlite3.Connection) -> None:
        db.execute("""
            CREATE TABLE leagues (
                id INTEGER PRIMARY KEY,
                league_code TEXT NOT NULL UNIQUE,
                fallback_provider TEXT,
                fallback_league_id TEXT,
                series_slug_pattern TEXT
            )
        """)

    def test_clears_cricbuzz_fallback(self, db):
        from teamarr.database.migrations import _migrate_v67_remove_cricbuzz

        self._setup(db)
        db.execute(
            "INSERT INTO leagues "
            "(league_code, fallback_provider, fallback_league_id, series_slug_pattern) "
            "VALUES ('ipl', 'cricbuzz', 'leagueX', 'pattern')"
        )
        _migrate_v67_remove_cricbuzz(db)

        row = db.execute(
            "SELECT fallback_provider, fallback_league_id, series_slug_pattern "
            "FROM leagues WHERE league_code='ipl'"
        ).fetchone()
        assert row["fallback_provider"] is None
        assert row["fallback_league_id"] is None
        assert row["series_slug_pattern"] is None

    def test_preserves_non_cricbuzz_fallbacks(self, db):
        from teamarr.database.migrations import _migrate_v67_remove_cricbuzz

        self._setup(db)
        db.execute("INSERT INTO leagues (league_code, fallback_provider) VALUES ('cfl', 'tsdb')")
        _migrate_v67_remove_cricbuzz(db)

        row = db.execute("SELECT fallback_provider FROM leagues WHERE league_code='cfl'").fetchone()
        assert row["fallback_provider"] == "tsdb"

    def test_idempotent(self, db):
        from teamarr.database.migrations import _migrate_v67_remove_cricbuzz

        self._setup(db)
        db.execute(
            "INSERT INTO leagues (league_code, fallback_provider) VALUES ('ipl', 'cricbuzz')"
        )
        _migrate_v67_remove_cricbuzz(db)
        _migrate_v67_remove_cricbuzz(db)

        row = db.execute("SELECT fallback_provider FROM leagues WHERE league_code='ipl'").fetchone()
        assert row["fallback_provider"] is None

    def test_handles_missing_leagues_table(self, db):
        from teamarr.database.migrations import _migrate_v67_remove_cricbuzz

        _migrate_v67_remove_cricbuzz(db)


# =============================================================================
# v69: feed team channel discrimination
# =============================================================================


class TestV69FeedTeamChannels:
    def _setup(self, db: sqlite3.Connection) -> None:
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY,
                event_id TEXT,
                event_provider TEXT,
                exception_keyword TEXT,
                primary_stream_id INTEGER,
                deleted_at TIMESTAMP
            )
        """)

    def test_adds_feed_team_id_column(self, db):
        from teamarr.database.migrations import _migrate_v69_feed_team_channels

        self._setup(db)
        _migrate_v69_feed_team_channels(db)

        cols = {row[1] for row in db.execute("PRAGMA table_info(managed_channels)")}
        assert "feed_team_id" in cols

    def test_creates_unique_index_with_feed_team(self, db):
        from teamarr.database.migrations import _migrate_v69_feed_team_channels

        self._setup(db)
        _migrate_v69_feed_team_channels(db)

        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mc_unique_event_v2'"
        )
        assert cursor.fetchone() is not None

    def test_idempotent(self, db):
        from teamarr.database.migrations import _migrate_v69_feed_team_channels

        self._setup(db)
        _migrate_v69_feed_team_channels(db)
        _migrate_v69_feed_team_channels(db)

        cols = {row[1] for row in db.execute("PRAGMA table_info(managed_channels)")}
        assert "feed_team_id" in cols

    def test_skips_when_managed_channels_missing(self, db):
        """No managed_channels table — should not error (test schemas may lack it)."""
        from teamarr.database.migrations import _migrate_v69_feed_team_channels

        _migrate_v69_feed_team_channels(db)


# =============================================================================
# v64: cross-group channel dedup + event-scoped index
# =============================================================================


class TestV64DedupChannels:
    def _setup(self, db: sqlite3.Connection) -> None:
        # Minimal managed_channels + managed_channel_streams shape
        db.execute("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP,
                event_id TEXT,
                event_provider TEXT,
                event_epg_group_id INTEGER,
                exception_keyword TEXT,
                primary_stream_id INTEGER,
                channel_name TEXT,
                dispatcharr_channel_id INTEGER,
                deleted_at TIMESTAMP,
                delete_reason TEXT
            )
        """)
        db.execute("""
            CREATE TABLE managed_channel_streams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                managed_channel_id INTEGER,
                dispatcharr_stream_id INTEGER,
                stream_name TEXT,
                source_group_id INTEGER,
                source_group_type TEXT,
                priority INTEGER,
                m3u_account_id INTEGER,
                m3u_account_name TEXT,
                UNIQUE(managed_channel_id, dispatcharr_stream_id)
            )
        """)

    def test_merges_duplicate_channels_keeping_oldest(self, db):
        from teamarr.database.migrations import _migrate_v64_dedup_channels

        self._setup(db)
        # Two channels for the same event/provider/keyword/stream across groups.
        db.execute(
            "INSERT INTO managed_channels "
            "(id, created_at, event_id, event_provider, event_epg_group_id, "
            " exception_keyword, primary_stream_id, channel_name) "
            "VALUES (1, '2026-01-01', 'evt1', 'espn', 100, NULL, 555, 'A')"
        )
        db.execute(
            "INSERT INTO managed_channels "
            "(id, created_at, event_id, event_provider, event_epg_group_id, "
            " exception_keyword, primary_stream_id, channel_name) "
            "VALUES (2, '2026-01-02', 'evt1', 'espn', 200, NULL, 555, 'B')"
        )
        # Loser has a stream the winner doesn't.
        db.execute(
            "INSERT INTO managed_channel_streams "
            "(managed_channel_id, dispatcharr_stream_id) VALUES (2, 999)"
        )

        _migrate_v64_dedup_channels(db)

        # Loser is soft-deleted with reason
        row = db.execute(
            "SELECT deleted_at, delete_reason FROM managed_channels WHERE id = 2"
        ).fetchone()
        assert row["deleted_at"] is not None
        assert row["delete_reason"] == "migration_dedup_v64"

        # Winner stayed
        row = db.execute("SELECT deleted_at FROM managed_channels WHERE id = 1").fetchone()
        assert row["deleted_at"] is None

        # Stream moved to winner (without duplicating)
        row = db.execute(
            "SELECT managed_channel_id FROM managed_channel_streams "
            "WHERE dispatcharr_stream_id = 999"
        ).fetchall()
        # Both rows exist (loser's row + new winner row from INSERT OR IGNORE) but
        # the winner now also has the stream.
        assert any(r["managed_channel_id"] == 1 for r in row)

    def test_creates_event_scoped_unique_index(self, db):
        from teamarr.database.migrations import _migrate_v64_dedup_channels

        self._setup(db)
        _migrate_v64_dedup_channels(db)

        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mc_unique_event'"
        )
        assert cursor.fetchone() is not None

    def test_idempotent_when_no_dupes(self, db):
        from teamarr.database.migrations import _migrate_v64_dedup_channels

        self._setup(db)
        db.execute(
            "INSERT INTO managed_channels "
            "(id, created_at, event_id, event_provider, primary_stream_id, channel_name) "
            "VALUES (1, '2026-01-01', 'evt1', 'espn', 555, 'Solo')"
        )
        _migrate_v64_dedup_channels(db)
        _migrate_v64_dedup_channels(db)

        # Channel still alive
        row = db.execute("SELECT deleted_at FROM managed_channels WHERE id = 1").fetchone()
        assert row["deleted_at"] is None
