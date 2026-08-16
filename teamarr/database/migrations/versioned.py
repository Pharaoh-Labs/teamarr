"""Versioned data migrations (schema_version-gated blocks).

Run AFTER schema reconciliation and executescript. Policy (Jul 2026): ALL
versioned migrations are kept forever, plus checkpoint_v43, so installations
that update infrequently can always walk forward — never squash or delete a
block. New data migration = new `if current_version < N:` block in
_run_migrations() + bump the schema_version DEFAULT in schema.sql.
"""

import json
import logging
import re
import sqlite3

from teamarr.database.checkpoint_v43 import apply_checkpoint_v43

logger = logging.getLogger(__name__)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run database migrations for existing databases.

    Uses schema_version in settings table to track applied migrations.
    Safe to call multiple times - checks version before running.

    Schema versions:
    - 2: Initial V2 schema
    - 3: Teams consolidated (league -> primary_league + leagues array)
    - 4: Added eng.2 (Championship), eng.3 (League One), nrl leagues; fixed NRL logo
    - 5: Renamed league_id_alias -> league_id
    - 6: Added league_alias column, fixed managed_channels UNIQUE constraint
    - 7: Added gracenote_category column
    - 8: Added custom_regex_date/time columns to event_epg_groups
    - 9: Added keyword_ordering to change_source CHECK constraint
    - 10: Updated channel timing CHECK constraints
    - 11: Removed UNIQUE constraint from tvg_id
    - 12: Removed per-group timing settings
    - 13: Added display_name to event_epg_groups
    - 14: Added streams_excluded to event_epg_groups
    - 15: Renamed filtered_no_match -> failed_count (clearer stat categories)
    - 16-22: Various additions (see individual migrations)
    - 23: Added default_channel_profile_ids to settings
    - 24: Added excluded and exclusion_reason to epg_matched_streams
    - 25: Changed event_epg_groups name uniqueness from global to per-account
    - 46: Added stream_profile_id to event_epg_groups
    - 47: Added stream_timezone to event_epg_groups
    - 48: Added channel_reset_enabled and channel_reset_cron to settings
    - 49: Added combat sports custom regex columns (fighters, event_name, config)
    """
    _recover_schema_version_from_v65_backup_if_needed(conn)
    current_version = _get_current_schema_version(conn)

    # ==========================================================================
    # CHECKPOINT v43: Consolidated migration for versions 2-43
    # ==========================================================================
    # Instead of running 43 individual procedural migrations, we use a single
    # idempotent checkpoint that ensures the v43 schema state regardless of
    # starting version. This is safer and handles partial migrations better.
    #
    # The checkpoint replaces all v3-v43 migrations below. The old migration
    # code is preserved but will be skipped since version becomes 43.
    # ==========================================================================
    if current_version < 43:
        logger.info("[MIGRATE] Applying v43 checkpoint (from v%d)", current_version)
        apply_checkpoint_v43(conn, current_version)
        current_version = 43
        logger.info("[MIGRATE] Checkpoint complete, now at v43")

    # Legacy v3-v43 migrations removed — checkpoint system stable since v2.1.0.

    # ==========================================================================
    # v44+: data migrations
    # ==========================================================================
    # Each migration is a guard + helper call. Helper bodies live below as
    # _migrate_v{N}_*. Reconciliation handles all column-shape changes; this
    # function is for data transforms only.

    if current_version < 49:
        # v44-v49: column additions only — handled entirely by reconciliation.
        _advance_version(
            conn, 49,
            "reconciliation: update check / logo cleanup / stream profile-timezone / "
            "channel reset / combat-sports regex",
        )
        current_version = 49

    if current_version < 50:
        _apply_migration(conn, 50, "soccer selection modes", _migrate_v50_soccer_modes)
        current_version = 50

    if current_version < 51:
        # soccer_followed_teams column — reconciliation adds it; the v58 data
        # migration uses the data, so we just advance the version here.
        _advance_version(conn, 51, "reconciliation: soccer_followed_teams")
        current_version = 51

    if current_version < 52:
        _advance_version(conn, 52, "reconciliation: playoff bypass columns")
        current_version = 52

    if current_version < 53:
        _apply_migration(conn, 53, "api timeout/retry defaults", _migrate_v53_api_defaults)
        current_version = 53

    if current_version < 57:
        # v54-v57: column additions only — handled by reconciliation.
        _advance_version(
            conn, 57,
            "reconciliation: scheduled backup / gold zone / playoff bypass re-apply",
        )
        current_version = 57

    if current_version < 58:
        _apply_migration(conn, 58, "sports subscription", _migrate_v58_sports_subscription)
        current_version = 58

    if current_version < 59:
        _apply_migration(conn, 59, "channel numbering overhaul", _migrate_v59_channel_numbering)
        current_version = 59

    if current_version < 60:
        _advance_version(conn, 60, "reconciliation: per-group subscription overrides")
        current_version = 60

    if current_version < 61:
        _apply_migration(
            conn, 61, "subscription league config table",
            _migrate_v61_subscription_league_config,
        )
        current_version = 61

    if current_version < 62:
        _apply_migration(
            conn, 62, "global default channel group", _migrate_v62_default_channel_group
        )
        current_version = 62

    if current_version < 63:
        _apply_migration(
            conn, 63, "channel ownership: nullable source group",
            _migrate_v63_nullable_managed_channel_group,
        )
        current_version = 63

    if current_version < 64:
        _apply_migration(conn, 64, "event-scoped unique index", _migrate_v64_dedup_channels)
        current_version = 64

    # v65 has a special structure: the structural pre-migration in init_db
    # backs up + drops the settings table. The data restore here keys off the
    # backup table's existence rather than schema_version (which gets reset
    # to default by the executescript that recreates settings). The version
    # bump runs unconditionally for any DB still below v65.
    _migrate_v65_lifecycle_timing_restore_if_needed(conn)
    _migrate_detection_keywords_restore_if_needed(conn)
    _migrate_stream_match_cache_restore_if_needed(conn)
    if current_version < 65:
        _advance_version(conn, 65, "event-anchored lifecycle timing")
        current_version = 65

    if current_version < 66:
        _apply_migration(conn, 66, "TSDB tiered provider model", _migrate_v66_tsdb_tiers)
        current_version = 66

    if current_version < 67:
        _apply_migration(conn, 67, "remove Cricbuzz provider", _migrate_v67_remove_cricbuzz)
        current_version = 67

    if current_version < 68:
        _advance_version(conn, 68, "reconciliation: feed separation columns")
        current_version = 68

    if current_version < 69:
        _apply_migration(
            conn, 69, "feed team channel discrimination",
            _migrate_v69_feed_team_channels,
        )
        current_version = 69

    if current_version < 71:
        # v70-v71: column additions only — handled by reconciliation.
        _advance_version(
            conn, 71, "reconciliation: month/day regex / Emby integration"
        )
        current_version = 71

    if current_version < 72:
        _apply_migration(
            conn, 72, "split xmltv event/filler categories",
            _migrate_v72_split_xmltv_categories,
        )
        current_version = 72

    if current_version < 73:
        _apply_migration(
            conn, 73, "dedupe MiLB league codes after rename",
            _migrate_v73_dedupe_milb_renamed_codes,
        )
        current_version = 73

    if current_version < 74:
        _apply_migration(
            conn, 74, "preserve EPG-match off-state after global switch removal",
            _migrate_v74_preserve_epg_match_offstate,
        )
        current_version = 74

    if current_version < 75:
        _apply_migration(
            conn, 75, "extract common art base URL from templates (epic z02s)",
            _migrate_v75_extract_art_base_url,
        )
        current_version = 75

    if current_version < 76:
        _apply_migration(
            conn, 76, "normalize relative template art paths to leading slash (z02s)",
            _migrate_v76_leading_slash_art_paths,
        )
        current_version = 76

    if current_version < 77:
        # Structural work happens in _migrate_stream_match_cache_check /
        # _restore (keyed on the CHECK content, not this version) — this
        # bump is bookkeeping.
        _advance_version(
            conn, 77, "stream_match_cache CHECK allows 'direct'/'epg' match methods"
        )
        current_version = 77

    if current_version < 78:
        _apply_migration(
            conn, 78,
            "strip corrupting leading slash before variable-led art values (#275)",
            _migrate_v78_strip_slash_before_art_variable,
        )
        current_version = 78

    if current_version < 79:
        _apply_migration(
            conn, 79,
            "backfill managed_channels team abbrevs + feed_team_name from team_cache (#403)",
            _migrate_v79_backfill_channel_team_display,
        )
        current_version = 79

    if current_version < 80:
        _apply_migration(
            conn, 80,
            "convert filler final/not-final conditionals to condition rows (#420)",
            _migrate_v80_filler_conditionals_to_rows,
        )
        current_version = 80

    if current_version < 81:
        _apply_migration(
            conn, 81,
            "seed 'Sports event' into template event categories (#423)",
            _migrate_v81_seed_sports_event_category,
        )
        current_version = 81

    if current_version < 82:
        _apply_migration(
            conn, 82,
            "fold scalar Channels DVR settings into channelsdvr_servers list (#381)",
            _migrate_v82_channelsdvr_servers_list,
        )
        current_version = 82

    if current_version < 83:
        _apply_migration(
            conn, 83,
            "fold scalar Emby/Jellyfin settings into server lists (#471)",
            _migrate_v83_media_server_lists,
        )
        current_version = 83

    if current_version < 84:
        _apply_migration(
            conn, 84,
            "rewrite retired transform variables to base|filter form (#484)",
            _migrate_v84_filter_consolidation,
        )
        current_version = 84

    if current_version < 85:
        _apply_migration(conn, 85, "migrate CFL to Bell Media", _migrate_v85_cfl_bellmedia)
        current_version = 85

    if current_version < 86:
        _apply_migration(conn, 86, "clear CFL provider cache", _migrate_v86_cfl_service_cache)
        current_version = 86

    if current_version < 87:
        _apply_migration(conn, 87, "remap CFL team selections", _migrate_v87_cfl_team_selections)
        current_version = 87


# =============================================================================
# Migration helpers
# =============================================================================
# Two patterns wrap the otherwise-repetitive guard/transform/bump/log work:
#
#   _advance_version(conn, target, reason)
#       For version ranges that are entirely handled by reconciliation
#       (i.e. only added columns; data is unchanged). Caller checks the
#       version guard.
#
#   _apply_migration(conn, target, description, fn)
#       For real data migrations. fn(conn) does the transform; this helper
#       bumps schema_version and emits the standard log line.
#
# Each migration body lives below as _migrate_v{N}_*. Schema (column shape)
# changes belong in schema.sql; reconciliation adds missing columns on every
# startup. Migration helpers should only contain data transforms.


def _advance_version(conn: sqlite3.Connection, target: int, reason: str) -> None:
    """Bump schema_version to `target`. Used for reconciliation-handled ranges."""
    conn.execute("UPDATE settings SET schema_version = ? WHERE id = 1", (target,))
    logger.info("[MIGRATE] Schema advanced to v%d (%s)", target, reason)


def _apply_migration(
    conn: sqlite3.Connection,
    target: int,
    description: str,
    migration_fn,
) -> None:
    """Run a data migration and bump schema_version. Caller checks the guard."""
    migration_fn(conn)
    conn.execute("UPDATE settings SET schema_version = ? WHERE id = 1", (target,))
    logger.info("[MIGRATE] Schema upgraded to v%d (%s)", target, description)


def _get_current_schema_version(conn: sqlite3.Connection) -> int:
    """Read settings.schema_version, defaulting to v2 (initial V2 schema)."""
    try:
        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        return row["schema_version"] if row else 2
    except Exception:
        return 2


def _recover_schema_version_from_v65_backup_if_needed(conn: sqlite3.Connection) -> None:
    """Restore schema_version from the v65 backup table if present (issue #178).

    The v65 pre-migration drops+recreates the settings table to change a
    CHECK constraint, which causes schema_version to be reseeded to its
    DEFAULT (latest) value. That makes all subsequent migrations appear
    already applied and silently skips column additions. If the v65 backup
    table is still around, restore the original schema_version so migrations
    re-run correctly.
    """
    try:
        has_v65_backup = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='_settings_v65_backup'"
        ).fetchone()[0]
        if not has_v65_backup:
            return

        backup_row = conn.execute(
            "SELECT schema_version FROM _settings_v65_backup WHERE id = 1"
        ).fetchone()
        if backup_row and backup_row[0] is not None:
            original_version = backup_row[0]
            conn.execute(
                "UPDATE settings SET schema_version = ? WHERE id = 1",
                (original_version,),
            )
            logger.info(
                "[MIGRATE] Corrected schema_version from v65 backup: %d",
                original_version,
            )
    except Exception as e:
        logger.warning("[MIGRATE] Could not check v65 backup: %s", e)


# =============================================================================
# Migration helper functions (v44+)
# =============================================================================
# These run only when crossing their version. They assume reconciliation has
# already added any new columns from schema.sql; they only transform existing
# data. Pre-v43 migrations are consolidated in checkpoint_v43.py.


def _migrate_v50_soccer_modes(conn: sqlite3.Connection) -> None:
    """v50: derive event_epg_groups.soccer_mode from each group's league set.

    Groups containing every soccer league become 'all'; groups with a subset
    become 'manual' (preserving the user's selection); groups with no soccer
    leagues stay NULL.
    """
    _add_column_if_not_exists(conn, "event_epg_groups", "soccer_mode", "TEXT")

    # Test databases may lack the leagues table; in that case there are no
    # soccer leagues to compare against, so nothing to migrate.
    try:
        cursor = conn.execute(
            "SELECT league_code FROM leagues WHERE sport = 'soccer' AND enabled = 1"
        )
        all_soccer_leagues = {row[0] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        return

    if not all_soccer_leagues:
        return

    cursor = conn.execute(
        "SELECT id, leagues FROM event_epg_groups WHERE leagues IS NOT NULL"
    )
    for row in cursor.fetchall():
        group_id = row[0]
        try:
            if not row[1]:
                continue
            group_leagues = set(json.loads(row[1]))
        except (json.JSONDecodeError, TypeError):
            continue

        group_soccer = group_leagues & all_soccer_leagues
        if not group_soccer:
            continue
        mode = "all" if group_soccer == all_soccer_leagues else "manual"
        conn.execute(
            "UPDATE event_epg_groups SET soccer_mode = ? WHERE id = ?",
            (mode, group_id),
        )


def _migrate_v53_api_defaults(conn: sqlite3.Connection) -> None:
    """v53: bump dispatcharr api_timeout/api_retry_count from old defaults.

    The DispatcharrClient effectively used 30s/5 retries via hard-coded
    fallbacks; the DB setting (10s/3 retries) was never wired up. Now that
    it is, lift existing users from the old defaults to avoid regression.
    """
    conn.execute("UPDATE settings SET api_timeout = 30 WHERE api_timeout = 10 AND id = 1")
    conn.execute(
        "UPDATE settings SET api_retry_count = 5 WHERE api_retry_count = 3 AND id = 1"
    )


def _migrate_v58_sports_subscription(conn: sqlite3.Connection) -> None:
    """v58: replace per-group sport/league/template config with a global subscription.

    Steps:
        1. Create sports_subscription + subscription_templates tables.
        2. Collect every league referenced by any group → subscription.
        3. Merge soccer config across groups (priority: 'all' > 'teams' > 'manual').
        4. Migrate group_templates → subscription_templates (deduped).
        5. Migrate legacy template_id from groups without group_templates rows.
        6. Set every group to group_mode='multi', parent_group_id=NULL.
        7. Update each group's leagues to match subscription (downgrade safety).
    """
    # Defensive: reconciliation adds this column in production, but standalone
    # _run_migrations test paths bypass reconciliation.
    _add_column_if_not_exists(conn, "event_epg_groups", "soccer_followed_teams", "TEXT")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sports_subscription (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            leagues JSON NOT NULL DEFAULT '[]',
            soccer_mode TEXT DEFAULT NULL
                CHECK(soccer_mode IS NULL OR soccer_mode IN ('all', 'teams', 'manual')),
            soccer_followed_teams JSON DEFAULT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO sports_subscription (id) VALUES (1);

        CREATE TABLE IF NOT EXISTS subscription_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            sports JSON,
            leagues JSON,
            FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
        );
    """)

    # Collect every league mentioned by any group (enabled or disabled — user
    # may re-enable a disabled group later).
    all_leagues: set[str] = set()
    cursor = conn.execute("SELECT leagues FROM event_epg_groups WHERE leagues IS NOT NULL")
    for row in cursor.fetchall():
        try:
            group_leagues = json.loads(row[0])
            if isinstance(group_leagues, list):
                all_leagues.update(group_leagues)
        except (json.JSONDecodeError, TypeError):
            continue

    subscription_leagues = sorted(all_leagues)
    logger.info(
        "[MIGRATE v58] Collected %d unique leagues from all groups: %s",
        len(subscription_leagues),
        subscription_leagues[:10],
    )

    # Merge soccer config across groups. Priority: 'all' > 'teams' > 'manual'.
    best_soccer_mode = None
    merged_followed_teams: list[dict] = []
    seen_team_keys: set[str] = set()

    cursor = conn.execute(
        "SELECT soccer_mode, soccer_followed_teams FROM event_epg_groups "
        "WHERE soccer_mode IS NOT NULL"
    )
    for row in cursor.fetchall():
        mode = row[0]
        if mode == "all":
            best_soccer_mode = "all"
        elif mode == "teams":
            if best_soccer_mode != "all":
                best_soccer_mode = "teams"
            if row[1]:
                try:
                    teams = json.loads(row[1])
                    if isinstance(teams, list):
                        for team in teams:
                            key = f"{team.get('provider', '')}:{team.get('team_id', '')}"
                            if key not in seen_team_keys:
                                seen_team_keys.add(key)
                                merged_followed_teams.append(team)
                except (json.JSONDecodeError, TypeError):
                    pass
        elif mode == "manual" and best_soccer_mode is None:
            best_soccer_mode = "manual"

    conn.execute(
        """UPDATE sports_subscription SET
            leagues = ?,
            soccer_mode = ?,
            soccer_followed_teams = ?,
            updated_at = CURRENT_TIMESTAMP
           WHERE id = 1""",
        (
            json.dumps(subscription_leagues),
            best_soccer_mode,
            json.dumps(merged_followed_teams) if merged_followed_teams else None,
        ),
    )
    logger.info(
        "[MIGRATE v58] Sports subscription: %d leagues, soccer_mode=%s, %d followed teams",
        len(subscription_leagues),
        best_soccer_mode,
        len(merged_followed_teams),
    )

    # Migrate group_templates → subscription_templates, deduplicated by
    # (template_id, sports, leagues).
    seen_template_keys: set[str] = set()
    try:
        cursor = conn.execute(
            "SELECT template_id, sports, leagues FROM group_templates ORDER BY id"
        )
        for row in cursor.fetchall():
            template_id, sports_val, leagues_val = row[0], row[1], row[2]
            dedup_key = f"{template_id}:{sports_val}:{leagues_val}"
            if dedup_key not in seen_template_keys:
                seen_template_keys.add(dedup_key)
                conn.execute(
                    "INSERT INTO subscription_templates (template_id, sports, leagues) "
                    "VALUES (?, ?, ?)",
                    (template_id, sports_val, leagues_val),
                )
    except sqlite3.OperationalError:
        # group_templates may not exist in minimal test databases.
        pass

    # Legacy template_id on groups without group_templates rows → defaults.
    try:
        cursor = conn.execute(
            "SELECT DISTINCT template_id FROM event_epg_groups "
            "WHERE template_id IS NOT NULL "
            "  AND id NOT IN (SELECT DISTINCT group_id FROM group_templates)"
        )
        for row in cursor.fetchall():
            template_id = row[0]
            dedup_key = f"{template_id}:None:None"
            if dedup_key not in seen_template_keys:
                seen_template_keys.add(dedup_key)
                conn.execute(
                    "INSERT INTO subscription_templates (template_id, sports, leagues) "
                    "VALUES (?, NULL, NULL)",
                    (template_id,),
                )
    except sqlite3.OperationalError:
        pass

    # Flatten group hierarchy.
    conn.execute(
        "UPDATE event_epg_groups SET group_mode = 'multi', parent_group_id = NULL"
    )

    # Downgrade safety: every group's leagues mirror the subscription.
    if subscription_leagues:
        conn.execute(
            "UPDATE event_epg_groups SET leagues = ?",
            (json.dumps(subscription_leagues),),
        )


def _migrate_v59_channel_numbering(conn: sqlite3.Connection) -> None:
    """v59: hoist channel numbering / consolidation / sorting from groups to global settings.

    Manual mode is sticky: if any enabled group was manual, the global mode
    becomes manual and the per-league channel-start numbers are derived from
    the lowest start number of any manual group containing that league.
    """
    _add_column_if_not_exists(
        conn, "settings", "global_channel_mode",
        "TEXT DEFAULT 'auto' CHECK(global_channel_mode IN ('auto', 'manual'))",
    )
    _add_column_if_not_exists(
        conn, "settings", "league_channel_starts", "JSON DEFAULT '{}'"
    )
    _add_column_if_not_exists(
        conn, "settings", "global_consolidation_mode", "TEXT DEFAULT 'consolidate'"
    )

    has_manual = 0
    try:
        has_manual = conn.execute(
            "SELECT COUNT(*) FROM event_epg_groups "
            "WHERE channel_assignment_mode = 'manual' AND enabled = 1"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pass

    global_mode = "manual" if has_manual > 0 else "auto"
    conn.execute(
        "UPDATE settings SET global_channel_mode = ? WHERE id = 1", (global_mode,)
    )

    if has_manual > 0:
        league_starts: dict[str, int] = {}
        try:
            cursor = conn.execute(
                "SELECT leagues, channel_start_number FROM event_epg_groups "
                "WHERE channel_assignment_mode = 'manual' "
                "  AND channel_start_number IS NOT NULL "
                "  AND enabled = 1"
            )
            for row in cursor.fetchall():
                try:
                    group_leagues = json.loads(row[0])
                    start_num = row[1]
                    if isinstance(group_leagues, list) and start_num:
                        for lc in group_leagues:
                            existing = league_starts.get(lc)
                            if existing is None or start_num < existing:
                                league_starts[lc] = start_num
                except (json.JSONDecodeError, TypeError):
                    continue
        except sqlite3.OperationalError:
            pass

        if league_starts:
            conn.execute(
                "UPDATE settings SET league_channel_starts = ? WHERE id = 1",
                (json.dumps(league_starts),),
            )

    try:
        row = conn.execute(
            "SELECT default_duplicate_event_handling FROM settings WHERE id = 1"
        ).fetchone()
        if row and row[0]:
            mode = row[0] if row[0] in ("consolidate", "separate") else "consolidate"
            conn.execute(
                "UPDATE settings SET global_consolidation_mode = ? WHERE id = 1",
                (mode,),
            )
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute(
            "UPDATE settings SET "
            "  channel_sorting_scope = 'global', "
            "  channel_sort_by = 'sport_league_time' "
            "WHERE id = 1"
        )
    except sqlite3.OperationalError:
        pass


def _migrate_v61_subscription_league_config(conn: sqlite3.Connection) -> None:
    """v61: add subscription_league_config table for per-league overrides."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscription_league_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_code TEXT NOT NULL UNIQUE,
            channel_profile_ids JSON DEFAULT NULL,
            channel_group_id INTEGER DEFAULT NULL,
            channel_group_mode TEXT DEFAULT NULL
                CHECK(channel_group_mode IS NULL
                      OR channel_group_mode IN ('static', 'sport', 'league'))
        )
    """)


def _migrate_v62_default_channel_group(conn: sqlite3.Connection) -> None:
    """v62: add global default channel group + relax CHECK on subscription_league_config.

    The old CHECK constrained channel_group_mode to {static,sport,league}; we
    now also allow free-form patterns like '{sport} | {league}', so the
    table is rebuilt without the CHECK clause.
    """
    _add_column_if_not_exists(conn, "settings", "default_channel_group_id", "INTEGER")
    _add_column_if_not_exists(
        conn, "settings", "default_channel_group_mode", "TEXT DEFAULT 'static'"
    )

    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscription_league_config_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_code TEXT NOT NULL UNIQUE,
                channel_profile_ids JSON DEFAULT NULL,
                channel_group_id INTEGER DEFAULT NULL,
                channel_group_mode TEXT DEFAULT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO subscription_league_config_new
                (id, league_code, channel_profile_ids, channel_group_id, channel_group_mode)
            SELECT id, league_code, channel_profile_ids, channel_group_id, channel_group_mode
            FROM subscription_league_config
        """)
        conn.execute("DROP TABLE subscription_league_config")
        conn.execute(
            "ALTER TABLE subscription_league_config_new "
            "RENAME TO subscription_league_config"
        )
    except sqlite3.OperationalError as e:
        logger.warning("[MIGRATE v62] Could not recreate subscription_league_config: %s", e)


def _migrate_v63_nullable_managed_channel_group(conn: sqlite3.Connection) -> None:
    """v63: rebuild managed_channels so event_epg_group_id is nullable + FK is SET NULL.

    Channels are owned by events, not groups. Deleting a group should null
    the provenance link, not cascade-delete channels. SQLite requires a full
    table rebuild to change NOT NULL or FK actions.
    """
    has_mc = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='managed_channels'"
    ).fetchone()[0]
    if not has_mc:
        return

    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("""
            CREATE TABLE managed_channels_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                event_epg_group_id INTEGER,
                event_id TEXT NOT NULL,
                event_provider TEXT NOT NULL,
                tvg_id TEXT NOT NULL,
                channel_name TEXT NOT NULL,
                channel_number TEXT,
                logo_url TEXT,
                dispatcharr_channel_id INTEGER,
                dispatcharr_uuid TEXT,
                dispatcharr_logo_id INTEGER,
                channel_group_id INTEGER,
                channel_profile_ids TEXT,
                primary_stream_id INTEGER,
                exception_keyword TEXT,
                home_team TEXT,
                home_team_abbrev TEXT,
                home_team_logo TEXT,
                away_team TEXT,
                away_team_abbrev TEXT,
                away_team_logo TEXT,
                event_date TIMESTAMP,
                event_name TEXT,
                league TEXT,
                sport TEXT,
                venue TEXT,
                broadcast TEXT,
                scheduled_delete_at TIMESTAMP,
                deleted_at TIMESTAMP,
                delete_reason TEXT,
                sync_status TEXT DEFAULT 'pending'
                    CHECK(sync_status IN (
                        'pending', 'created', 'in_sync',
                        'drifted', 'orphaned', 'error'
                    )),
                sync_message TEXT,
                last_verified_at TIMESTAMP,
                expires_at TIMESTAMP,
                external_channel_id INTEGER,
                FOREIGN KEY (event_epg_group_id)
                    REFERENCES event_epg_groups(id) ON DELETE SET NULL
            )
        """)
        conn.execute("""
            INSERT INTO managed_channels_new
            SELECT id, created_at, updated_at, event_epg_group_id,
                   event_id, event_provider, tvg_id, channel_name,
                   channel_number, logo_url, dispatcharr_channel_id,
                   dispatcharr_uuid, dispatcharr_logo_id,
                   channel_group_id, channel_profile_ids,
                   primary_stream_id, exception_keyword,
                   home_team, home_team_abbrev, home_team_logo,
                   away_team, away_team_abbrev, away_team_logo,
                   event_date, event_name, league, sport, venue,
                   broadcast, scheduled_delete_at, deleted_at,
                   delete_reason, sync_status, sync_message,
                   last_verified_at, expires_at, external_channel_id
            FROM managed_channels
        """)
        conn.execute("DROP TABLE managed_channels")
        conn.execute("ALTER TABLE managed_channels_new RENAME TO managed_channels")

        # Recreate indexes + trigger.
        for stmt in (
            "CREATE INDEX IF NOT EXISTS idx_managed_channels_group "
            "ON managed_channels(event_epg_group_id)",
            "CREATE INDEX IF NOT EXISTS idx_managed_channels_event "
            "ON managed_channels(event_id, event_provider)",
            "CREATE INDEX IF NOT EXISTS idx_managed_channels_expires "
            "ON managed_channels(expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_managed_channels_delete "
            "ON managed_channels(scheduled_delete_at) WHERE deleted_at IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_managed_channels_dispatcharr "
            "ON managed_channels(dispatcharr_channel_id)",
            "CREATE INDEX IF NOT EXISTS idx_managed_channels_tvg "
            "ON managed_channels(tvg_id)",
            "CREATE INDEX IF NOT EXISTS idx_managed_channels_sync "
            "ON managed_channels(sync_status)",
            # Group-scoped unique index (later changed to event-scoped in v64).
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_mc_unique_event "
            "ON managed_channels("
            "  event_epg_group_id, event_id, event_provider, "
            "  COALESCE(exception_keyword, ''), primary_stream_id"
            ") WHERE deleted_at IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_managed_channels_sport_league "
            "ON managed_channels(sport, league) WHERE deleted_at IS NULL",
        ):
            conn.execute(stmt)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS update_managed_channels_timestamp
            AFTER UPDATE ON managed_channels
            BEGIN
                UPDATE managed_channels
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = NEW.id;
            END
        """)
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.OperationalError as e:
        # Old test schemas may have different columns — clean up the temp table.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DROP TABLE IF EXISTS managed_channels_new")
        logger.warning(
            "[MIGRATE v63] Could not rebuild managed_channels (schema mismatch): %s", e
        )


def _migrate_v64_dedup_channels(conn: sqlite3.Connection) -> None:
    """v64: dedup cross-group duplicate channels and swap to an event-scoped unique index.

    Before v64 the unique index was group-scoped; after v64 channels are
    identified by (event_id, provider, keyword, stream_id) regardless of
    source group. _dedup_cross_group_channels merges duplicate sets first,
    then we replace the index.
    """
    has_mc = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='managed_channels'"
    ).fetchone()[0]
    if not has_mc:
        return

    try:
        _dedup_cross_group_channels(conn)
    except Exception as e:
        logger.warning("[MIGRATE v64] Dedup failed (non-fatal): %s", e)

    try:
        conn.execute("DROP INDEX IF EXISTS idx_mc_unique_event")
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mc_unique_event
            ON managed_channels(
                event_id, event_provider,
                COALESCE(exception_keyword, ''),
                primary_stream_id
            )
            WHERE deleted_at IS NULL
        """)
    except sqlite3.OperationalError as e:
        logger.warning(
            "[MIGRATE v64] Could not create event-scoped unique index: %s", e
        )


def _migrate_v65_lifecycle_timing_restore_if_needed(conn: sqlite3.Connection) -> None:
    """v65: restore settings from the pre-migration backup with mapped timing values.

    The structural pre-migration in init_db drops + recreates the settings
    table (CHECK-constraint change). That makes schema_version unreliable
    here, so we key off the existence of the backup table instead.
    """
    has_v65_backup = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='_settings_v65_backup'"
    ).fetchone()[0]
    if not has_v65_backup:
        return

    try:
        # Map old enum values to new ones in the backup table (no CHECK
        # constraints there, so UPDATEs are unconstrained).
        conn.execute("""
            UPDATE _settings_v65_backup SET
                channel_pre_buffer_minutes = CASE channel_create_timing
                    WHEN 'stream_available' THEN 0
                    WHEN 'day_before' THEN 1440
                    WHEN '2_days_before' THEN 2880
                    WHEN '3_days_before' THEN 4320
                    WHEN '1_week_before' THEN 10080
                    ELSE COALESCE(channel_pre_buffer_minutes, 60)
                    END,
                channel_create_timing = CASE channel_create_timing
                    WHEN 'stream_available' THEN 'before_event'
                    WHEN 'day_before' THEN 'before_event'
                    WHEN '2_days_before' THEN 'before_event'
                    WHEN '3_days_before' THEN 'before_event'
                    WHEN '1_week_before' THEN 'before_event'
                    ELSE 'same_day' END,
                channel_post_buffer_minutes = CASE channel_delete_timing
                    WHEN 'stream_removed' THEN 0
                    WHEN '6_hours_after' THEN 360
                    WHEN 'day_after' THEN 1440
                    WHEN '2_days_after' THEN 2880
                    WHEN '3_days_after' THEN 4320
                    WHEN '1_week_after' THEN 10080
                    ELSE COALESCE(channel_post_buffer_minutes, 60)
                    END,
                channel_delete_timing = CASE channel_delete_timing
                    WHEN 'stream_removed' THEN 'after_event'
                    WHEN '6_hours_after' THEN 'after_event'
                    WHEN 'day_after' THEN 'after_event'
                    WHEN '2_days_after' THEN 'after_event'
                    WHEN '3_days_after' THEN 'after_event'
                    WHEN '1_week_after' THEN 'after_event'
                    ELSE 'same_day' END
        """)

        backup_cols = [r[1] for r in conn.execute("PRAGMA table_info(_settings_v65_backup)")]
        settings_cols = [r[1] for r in conn.execute("PRAGMA table_info(settings)")]
        common = [c for c in settings_cols if c in backup_cols]
        col_list = ", ".join(common)

        conn.execute("DELETE FROM settings WHERE id = 1")
        conn.execute(
            f"INSERT INTO settings ({col_list}) "
            f"SELECT {col_list} FROM _settings_v65_backup"
        )
        conn.execute("UPDATE settings SET schema_version = 65 WHERE id = 1")
        conn.execute("DROP TABLE _settings_v65_backup")
        logger.info("[MIGRATE v65] Restored settings with mapped lifecycle timing values")
    except Exception as e:
        logger.warning("[MIGRATE v65] Settings restore failed: %s", e)
        conn.execute("DROP TABLE IF EXISTS _settings_v65_backup")


def _migrate_detection_keywords_restore_if_needed(conn: sqlite3.Connection) -> None:
    """Restore detection_keywords from the pre-migration backup.

    The structural pre-migration drops/recreates the table to refresh the stale
    category CHECK constraint. Keyed off the backup table's existence. Maps the
    renamed combat_sports category to event_type_keywords on the way back in.
    """
    has_backup = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='_detection_keywords_backup'"
    ).fetchone()[0]
    if not has_backup:
        return

    try:
        conn.execute(
            "UPDATE _detection_keywords_backup SET category = 'event_type_keywords' "
            "WHERE category = 'combat_sports'"
        )
        backup_cols = [r[1] for r in conn.execute("PRAGMA table_info(_detection_keywords_backup)")]
        new_cols = [r[1] for r in conn.execute("PRAGMA table_info(detection_keywords)")]
        common = [c for c in new_cols if c in backup_cols]
        col_list = ", ".join(common)

        conn.execute(
            f"INSERT OR IGNORE INTO detection_keywords ({col_list}) "
            f"SELECT {col_list} FROM _detection_keywords_backup"
        )
        conn.execute("DROP TABLE _detection_keywords_backup")
        logger.info("[MIGRATE] Restored detection_keywords after CHECK constraint refresh")
    except Exception as e:
        logger.warning("[MIGRATE] detection_keywords restore failed: %s", e)
        conn.execute("DROP TABLE IF EXISTS _detection_keywords_backup")


def _migrate_stream_match_cache_restore_if_needed(conn: sqlite3.Connection) -> None:
    """Restore user-corrected stream matches after the CHECK constraint rebuild.

    Keyed off the backup table's existence (the pre-migration only backs up
    user_corrected rows — algorithmic cache entries re-derive on the next run).
    """
    has_backup = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='_stream_match_cache_backup'"
    ).fetchone()[0]
    if not has_backup:
        return

    try:
        backup_cols = [
            r[1] for r in conn.execute("PRAGMA table_info(_stream_match_cache_backup)")
        ]
        new_cols = [r[1] for r in conn.execute("PRAGMA table_info(stream_match_cache)")]
        common = [c for c in new_cols if c in backup_cols]
        col_list = ", ".join(common)

        conn.execute(
            f"INSERT OR IGNORE INTO stream_match_cache ({col_list}) "
            f"SELECT {col_list} FROM _stream_match_cache_backup"
        )
        conn.execute("DROP TABLE _stream_match_cache_backup")
        logger.info(
            "[MIGRATE] Restored user-corrected stream matches after "
            "match_method CHECK refresh"
        )
    except Exception as e:
        logger.warning("[MIGRATE] stream_match_cache restore failed: %s", e)
        conn.execute("DROP TABLE IF EXISTS _stream_match_cache_backup")


def _migrate_v66_tsdb_tiers(conn: sqlite3.Connection) -> None:
    """v66: tag TSDB leagues with free/premium tier for capability gating."""
    _add_column_if_not_exists(conn, "leagues", "tsdb_tier", "TEXT")

    try:
        free_leagues = ["cfl", "unrivaled", "norwegian-hockey", "boxing"]
        premium_leagues = ["ipl", "bbl", "sa20", "afl", "nrl", "super-rugby"]

        for code in free_leagues:
            conn.execute(
                "UPDATE leagues SET tsdb_tier = 'free' WHERE league_code = ?", (code,)
            )
        for code in premium_leagues:
            conn.execute(
                "UPDATE leagues SET tsdb_tier = 'premium' WHERE league_code = ?", (code,)
            )
    except sqlite3.OperationalError:
        # leagues table absent in minimal test databases.
        pass


def _migrate_v85_cfl_bellmedia(conn: sqlite3.Connection) -> None:
    """v85: replace TSDB's CFL IDs and clear its stale cache entries.

    Bell Media competitor IDs are captured from TSN's public score widget. CFL
    team records are remapped by their stable display name so existing team
    channels keep their configuration while future events use Bell Media IDs.
    """
    cfl_teams = {
        "bc lions": "93775",
        "calgary stampeders": "112939",
        "edmonton elks": "114347",
        "hamilton tiger-cats": "83579",
        "montreal alouettes": "86680",
        "ottawa redblacks": "88019",
        "saskatchewan roughriders": "106752",
        "toronto argonauts": "122345",
        "winnipeg blue bombers": "110380",
    }

    if _table_exists(conn, "team_cache"):
        conn.execute("DELETE FROM team_cache WHERE league = 'cfl'")
    if _table_exists(conn, "league_cache"):
        conn.execute("DELETE FROM league_cache WHERE league_slug = 'cfl'")
    _clear_cfl_service_cache(conn)

    for table, league_column in (("teams", "primary_league"), ("channel_priority_teams", "league")):
        if not _table_exists(conn, table) or not all(
            _column_exists(conn, table, column)
            for column in ("provider", "provider_team_id", league_column, "team_name")
        ):
            continue
        for name, competitor_id in cfl_teams.items():
            conn.execute(
                f"UPDATE OR IGNORE {table} SET provider = 'bellmedia', provider_team_id = ? "
                f"WHERE provider = 'tsdb' AND {league_column} = 'cfl' "
                "AND LOWER(team_name) = ?",
                (competitor_id, name),
            )

    if _table_exists(conn, "managed_channels") and all(
        _column_exists(conn, "managed_channels", column)
        for column in ("deleted_at", "delete_reason", "event_provider", "league")
    ):
        # Provider event IDs are not interoperable. Mark old channels deleted so
        # normal generation can recreate them without a duplicate active row.
        conn.execute(
            "UPDATE managed_channels SET deleted_at = CURRENT_TIMESTAMP, "
            "delete_reason = 'provider_migration' "
            "WHERE event_provider = 'tsdb' AND league = 'cfl' AND deleted_at IS NULL"
        )


def _migrate_v86_cfl_service_cache(conn: sqlite3.Connection) -> None:
    """v86: invalidate cached CFL values created before the provider migration."""
    _clear_cfl_service_cache(conn)


def _migrate_v87_cfl_team_selections(conn: sqlite3.Connection) -> None:
    """v87: remap persisted CFL team-selection JSON to Bell Media IDs."""
    team_ids = {
        "135006": "93775",
        "135007": "112939",
        "135008": "114347",
        "135002": "83579",
        "135003": "86680",
        "135004": "88019",
        "135009": "106752",
        "135005": "122345",
        "135010": "110380",
    }

    def remap(value: str | None) -> str | None:
        if not value:
            return value
        try:
            teams = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value
        if not isinstance(teams, list):
            return value
        changed = False
        for team in teams:
            if not isinstance(team, dict):
                continue
            if team.get("provider") != "tsdb" or team.get("league") != "cfl":
                continue
            bellmedia_id = team_ids.get(str(team.get("team_id")))
            if not bellmedia_id:
                continue
            team["provider"] = "bellmedia"
            team["team_id"] = bellmedia_id
            changed = True
        return json.dumps(teams) if changed else value

    targets = (
        ("settings", "id = 1", ("default_include_teams", "default_exclude_teams")),
        ("event_epg_groups", "1 = 1", ("include_teams", "exclude_teams")),
    )
    for table, where, columns in targets:
        if not _table_exists(conn, table):
            continue
        for column in columns:
            if not _column_exists(conn, table, column):
                continue
            rows = conn.execute(
                f"SELECT rowid AS _rowid, {column} FROM {table} WHERE {where}"
            ).fetchall()
            for row in rows:
                updated = remap(row[column])
                if updated != row[column]:
                    conn.execute(
                        f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                        (updated, row["_rowid"]),
                    )


def _clear_cfl_service_cache(conn: sqlite3.Connection) -> None:
    """Remove provider-agnostic service-cache entries for CFL."""
    if not _table_exists(conn, "service_cache") or not _column_exists(
        conn, "service_cache", "cache_key"
    ):
        return
    # Service-cache keys do not include the provider. A cached empty TSDB
    # response would otherwise hide Bell Media events until its TTL expires.
    conn.execute(
        "DELETE FROM service_cache WHERE cache_key LIKE 'events:cfl:%' "
        "OR cache_key LIKE 'schedule:cfl:%' OR cache_key LIKE 'team:cfl:%' "
        "OR cache_key LIKE 'event:cfl:%' OR cache_key LIKE 'stats:cfl:%'"
    )


def _migrate_v67_remove_cricbuzz(conn: sqlite3.Connection) -> None:
    """v67: clear Cricbuzz fallback references; cricket now uses TSDB exclusively."""
    try:
        conn.execute(
            "UPDATE leagues SET fallback_provider = NULL, fallback_league_id = NULL, "
            "  series_slug_pattern = NULL "
            "WHERE fallback_provider = 'cricbuzz'"
        )
    except sqlite3.OperationalError:
        pass


def _migrate_v69_feed_team_channels(conn: sqlite3.Connection) -> None:
    """v69: add feed_team_id to managed_channels and rebuild the unique index to include it.

    Same-event home/away feeds need separate channels per feed-team, so the
    uniqueness key gains feed_team_id (COALESCEd to '' for null).
    """
    has_mc = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='managed_channels'"
    ).fetchone()[0]
    if not has_mc:
        return

    _add_column_if_not_exists(conn, "managed_channels", "feed_team_id", "TEXT")

    conn.execute("DROP INDEX IF EXISTS idx_mc_unique_event")
    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mc_unique_event_v2
            ON managed_channels(
                event_id, event_provider,
                COALESCE(exception_keyword, ''),
                COALESCE(feed_team_id, ''),
                primary_stream_id
            )
            WHERE deleted_at IS NULL
        """)
    except Exception as e:
        logger.warning("[MIGRATE v69] Could not create unique index: %s", e)


def _migrate_v72_split_xmltv_categories(conn: sqlite3.Connection) -> None:
    """v72: split xmltv_categories / categories_apply_to into independent fields.

    Reconciliation already added xmltv_filler_categories. We populate it from
    the old shared xmltv_categories for templates that had categories_apply_to='all'
    (so filler kept those tags), then drop the obsolete column.
    """
    try:
        cursor = conn.execute(
            "SELECT id, xmltv_categories FROM templates WHERE categories_apply_to = 'all'"
        )
        rows = cursor.fetchall()
        for row in rows:
            template_id = row[0]
            categories_json = row[1] or "[]"
            conn.execute(
                "UPDATE templates SET xmltv_filler_categories = ? WHERE id = ?",
                (categories_json, template_id),
            )
        if rows:
            logger.info(
                "[MIGRATE v72] Copied xmltv_categories → xmltv_filler_categories "
                "for %d template(s) where categories_apply_to='all'",
                len(rows),
            )
    except sqlite3.OperationalError:
        # Column may already be dropped on rerun.
        pass

    # SQLite >= 3.35 (2021) supports DROP COLUMN. Older SQLite or already-dropped
    # column both surface as OperationalError; the leftover column is harmless
    # because the dataclass no longer reads it.
    try:
        conn.execute("ALTER TABLE templates DROP COLUMN categories_apply_to")
        logger.info("[MIGRATE v72] Dropped templates.categories_apply_to column")
    except sqlite3.OperationalError as e:
        logger.warning(
            "[MIGRATE v72] DROP COLUMN templates.categories_apply_to skipped: %s", e
        )


# Renames applied by commit db53687 (Apr 2026): old league_code → new league_code.
# schema.sql uses INSERT OR REPLACE keyed on league_code, so the new rows were
# inserted but the old rows were never deleted, leaving duplicate MiLB entries
# in the league selector and orphan teams in team_cache.
_MILB_RENAMED_LEAGUES: dict[str, str] = {
    "a": "milb-a",
    "aa": "milb-aa",
    "aaa": "milb-aaa",
    "higha": "milb-high-a",
}


def _migrate_v73_dedupe_milb_renamed_codes(conn: sqlite3.Connection) -> None:
    """v73: clean up duplicate MiLB league rows orphaned by the v2.2 rename.

    Remaps user-data references (managed_channels, team_aliases, JSON-encoded
    league lists) from the old codes to the new codes, then deletes the
    orphaned rows from `leagues` and `team_cache`. Log/cache tables get the
    same remap for consistency.
    """
    rename = _MILB_RENAMED_LEAGUES
    old_codes = tuple(rename.keys())
    placeholders = ",".join("?" for _ in old_codes)

    # Each tuple: (table, column, unique_scope_columns_or_None).
    # unique_scope_columns is set when the table has a UNIQUE constraint that
    # includes the league column. For those tables, a blanket UPDATE
    # old->new can collide if both rows already exist (GitHub #202), so we
    # delete the old row in favor of the existing new row before updating.
    scalar_targets = (
        ("managed_channels", "league", None),
        ("team_aliases", "league", None),
        ("channel_sort_priorities", "league_code", ("sport",)),
        # Logs and detection caches (best-effort consistency).
        ("epg_matched_streams", "detected_league", None),
        ("epg_failed_matches", "detected_league", None),
        ("stream_match_cache", "league", None),
        ("match_corrections", "incorrect_league", None),
        ("match_corrections", "correct_league", None),
    )

    # 1. Scalar league columns. Skip silently if the table or column is missing
    # — partial schemas (e.g. unit-test fixtures, mid-migration restarts) would
    # otherwise log a noisy warning per old code per missing target.
    for table, column, unique_scope in scalar_targets:
        if not _column_exists(conn, table, column):
            continue
        # Only attempt the UNIQUE-aware delete-before-update when every scope
        # column is actually present. Partial schemas (test fixtures, in-flight
        # migrations) without the scope columns can't have the corresponding
        # UNIQUE constraint either, so a plain UPDATE is safe there.
        scope = unique_scope if unique_scope and all(
            _column_exists(conn, table, c) for c in unique_scope
        ) else None
        for old, new in rename.items():
            if scope:
                # If a row with the new code already exists for the same
                # unique-scope (e.g. same sport), drop the old-coded row so
                # the UPDATE below doesn't violate UNIQUE(sport, league_code).
                scope_cols = ", ".join(scope)
                conn.execute(
                    f"""DELETE FROM {table}
                        WHERE {column} = ?
                          AND ({scope_cols}) IN (
                            SELECT {scope_cols} FROM {table} WHERE {column} = ?
                          )""",
                    (old, new),
                )
            conn.execute(
                f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                (new, old),
            )

    # 2. JSON-encoded league arrays
    _v73_remap_json_array(conn, "sports_subscription", "leagues", rename)
    _v73_remap_json_array(conn, "subscription_templates", "leagues", rename)
    _v73_remap_json_array(conn, "event_epg_groups", "leagues", rename)
    _v73_remap_json_array(conn, "event_epg_groups", "subscription_leagues", rename)

    # 4. Drop orphan team_cache rows. The new codes are repopulated by cache
    # refresh; old-coded duplicates are stale and would not match anything.
    if _table_exists(conn, "team_cache"):
        try:
            cur = conn.execute(
                f"DELETE FROM team_cache WHERE league IN ({placeholders})",
                old_codes,
            )
            if cur.rowcount:
                logger.info(
                    "[MIGRATE v73] Deleted %d orphan team_cache rows under "
                    "old MiLB codes %s", cur.rowcount, old_codes,
                )
        except sqlite3.OperationalError as e:
            logger.warning("[MIGRATE v73] team_cache cleanup skipped: %s", e)

    # 5. Drop the orphan league rows themselves — the actual selector fix.
    if _table_exists(conn, "leagues"):
        try:
            cur = conn.execute(
                f"DELETE FROM leagues WHERE league_code IN ({placeholders})",
                old_codes,
            )
            if cur.rowcount:
                logger.info(
                    "[MIGRATE v73] Deleted %d duplicate MiLB league rows %s",
                    cur.rowcount, old_codes,
                )
        except sqlite3.OperationalError as e:
            logger.warning("[MIGRATE v73] leagues cleanup skipped: %s", e)


def _migrate_v74_preserve_epg_match_offstate(conn: sqlite3.Connection) -> None:
    """v74: preserve "EPG matching off" intent after the global switch removal.

    The global ``settings.epg_match_enabled`` master switch (epic 3lp1.1) was
    removed: EPG program matching and the Dispatcharr channel-source now activate
    on the per-group ``event_epg_groups.epg_match_enabled`` /
    ``settings.epg_channel_source_enabled`` flags ALONE, no longer gated by the
    global switch. A user who left those flags set while keeping the global switch
    OFF would otherwise have matching silently turn on at this upgrade.

    Fix: if the (now-vestigial) global switch was OFF, clear the dependent flags so
    the user's effective "off" state carries across the upgrade. When the global
    switch was ON, every flag is left exactly as-is — matching continues unchanged.
    The vestigial ``settings.epg_match_enabled`` column is only read here; it stays
    in the schema for back-compat.
    """
    if not _column_exists(conn, "settings", "epg_match_enabled"):
        return  # nothing to read (fresh/partial schema) — no-op

    row = conn.execute("SELECT epg_match_enabled FROM settings WHERE id = 1").fetchone()
    if row is None or row[0]:
        return  # global switch was ON (or no settings row) — leave all flags untouched

    # Global switch was OFF: matching was globally inert. Preserve that off-state
    # so it doesn't silently activate now that the gate is gone.
    if _column_exists(conn, "settings", "epg_channel_source_enabled"):
        conn.execute("UPDATE settings SET epg_channel_source_enabled = 0 WHERE id = 1")
    if _column_exists(conn, "event_epg_groups", "epg_match_enabled"):
        cleared = conn.execute(
            "UPDATE event_epg_groups SET epg_match_enabled = 0 WHERE epg_match_enabled = 1"
        ).rowcount
        logger.info(
            "[MIGRATE v74] Global EPG-match was off; cleared %d per-group "
            "epg_match_enabled flag(s) and channel-source to preserve off-state",
            cleared,
        )


def _migrate_v75_extract_art_base_url(conn: sqlite3.Connection) -> None:
    """v75: adopt the game-thumbs base URL convention for existing templates (z02s).

    Templates historically stored FULL art URLs (program_art_url,
    event_channel_logo_url, and art_url inside the pregame/postgame/idle fallback
    JSON). The new convention lets users set one base URL in settings and store
    only relative paths. This migration makes existing installs follow it:

    - Collect every absolute art URL across all templates and parse its origin
      (scheme://host[:port]).
    - If a SINGLE origin is shared by all of them, set settings.art_base_url to it
      and strip that origin prefix from each field (leaving the relative path).
    - If templates span MULTIPLE origins (ambiguous) or have none, do nothing —
      absolute URLs keep working unchanged via the resolver's passthrough.

    Idempotent: once base_url is set + URLs are relative, a re-run finds no
    absolute URLs to migrate and no-ops.
    """
    from urllib.parse import urlsplit

    if not _table_exists(conn, "templates"):
        return

    # Safety net for tests that call _run_migrations directly (production adds the
    # column via reconciliation before migrations run).
    _add_column_if_not_exists(conn, "settings", "art_base_url", "TEXT DEFAULT ''")

    # Already configured — don't second-guess a user-set base.
    existing = conn.execute("SELECT art_base_url FROM settings WHERE id = 1").fetchone()
    if existing and (existing[0] or "").strip():
        return

    # Only operate on art columns the templates table actually has (tests may
    # build a partial schema).
    art_columns = [
        c for c in ("program_art_url", "event_channel_logo_url")
        if _column_exists(conn, "templates", c)
    ]
    json_columns = [
        c for c in ("pregame_fallback", "postgame_fallback", "idle_content")
        if _column_exists(conn, "templates", c)
    ]
    if not art_columns and not json_columns:
        return

    def origin_of(url: object) -> str | None:
        if not url or not isinstance(url, str):
            return None
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            return None  # relative or non-URL — nothing to strip
        return f"{parts.scheme}://{parts.netloc}"

    select_cols = ["id", *art_columns, *json_columns]
    rows = conn.execute(
        f"SELECT {', '.join(select_cols)} FROM templates"
    ).fetchall()

    # Pass 1: tally how often each origin appears across every art value.
    from collections import Counter

    origin_counts: Counter[str] = Counter()
    for row in rows:
        for col in art_columns:
            o = origin_of(row[col])
            if o:
                origin_counts[o] += 1
        for col in json_columns:
            try:
                blob = json.loads(row[col]) if row[col] else None
            except (TypeError, ValueError):
                blob = None
            if isinstance(blob, dict):
                o = origin_of(blob.get("art_url"))
                if o:
                    origin_counts[o] += 1

    if not origin_counts:
        return  # no absolute art URLs to migrate

    # Pick the most frequent origin as the base. When origins diverge, the
    # winner's URLs become relative; the rest stay absolute (resolver passes
    # them through untouched). most_common ties break on first-seen insertion.
    base, _ = origin_counts.most_common(1)[0]
    if len(origin_counts) > 1:
        logger.info(
            "[MIGRATE] v75: templates span %d art origins %s — picking most "
            "frequent %r as the base; others left absolute",
            len(origin_counts),
            dict(origin_counts),
            base,
        )
    prefix = base + "/"

    def strip(url):
        # Drop the origin, keep a leading-slash-rooted path (e.g. "/{league}/cover.png").
        if isinstance(url, str) and url.startswith(prefix):
            return "/" + url[len(prefix):]
        return url

    # Pass 2: strip the origin from every matching field.
    for row in rows:
        updates: dict[str, str | None] = {}
        for col in art_columns:
            new = strip(row[col])
            if new != row[col]:
                updates[col] = new
        for col in json_columns:
            try:
                blob = json.loads(row[col]) if row[col] else None
            except (TypeError, ValueError):
                blob = None
            if isinstance(blob, dict) and isinstance(blob.get("art_url"), str):
                new = strip(blob["art_url"])
                if new != blob["art_url"]:
                    blob["art_url"] = new
                    updates[col] = json.dumps(blob)
        if updates:
            sets = ", ".join(f"{c} = ?" for c in updates)
            conn.execute(
                f"UPDATE templates SET {sets} WHERE id = ?",
                (*updates.values(), row["id"]),
            )

    conn.execute("UPDATE settings SET art_base_url = ? WHERE id = 1", (base,))
    logger.info(
        "[MIGRATE] v75: set art base URL %r and converted template art to relative paths",
        base,
    )


def _migrate_v76_leading_slash_art_paths(conn: sqlite3.Connection) -> None:
    """v76: enforce the leading-slash convention on relative template art paths.

    The v75 migration (and early dev DBs) could leave relative art as
    "{league}/cover.png" without a leading slash. The convention is a leading
    slash ("/{league}/cover.png") for consistency. This normalizes any relative
    (non-absolute, non-empty) art value to start with "/" across the direct art
    columns and the art_url nested in the filler-fallback JSON. Idempotent —
    already-slashed and absolute values are untouched.
    """
    from urllib.parse import urlsplit

    if not _table_exists(conn, "templates"):
        return

    art_columns = [
        c for c in ("program_art_url", "event_channel_logo_url")
        if _column_exists(conn, "templates", c)
    ]
    json_columns = [
        c for c in ("pregame_fallback", "postgame_fallback", "idle_content")
        if _column_exists(conn, "templates", c)
    ]
    if not art_columns and not json_columns:
        return

    def normalize(value):
        # Leave empty, absolute (has scheme://), and already-rooted paths alone.
        if not isinstance(value, str) or not value:
            return value
        if urlsplit(value).scheme:
            return value
        return value if value.startswith("/") else "/" + value

    select_cols = ["id", *art_columns, *json_columns]
    rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM templates").fetchall()

    changed = 0
    for row in rows:
        updates: dict[str, str] = {}
        for col in art_columns:
            new = normalize(row[col])
            if new != row[col]:
                updates[col] = new
        for col in json_columns:
            try:
                blob = json.loads(row[col]) if row[col] else None
            except (TypeError, ValueError):
                blob = None
            if isinstance(blob, dict) and isinstance(blob.get("art_url"), str):
                new = normalize(blob["art_url"])
                if new != blob["art_url"]:
                    blob["art_url"] = new
                    updates[col] = json.dumps(blob)
        if updates:
            sets = ", ".join(f"{c} = ?" for c in updates)
            conn.execute(
                f"UPDATE templates SET {sets} WHERE id = ?",
                (*updates.values(), row["id"]),
            )
            changed += 1

    if changed:
        logger.info(
            "[MIGRATE] v76: added leading slash to relative art paths in %d template(s)",
            changed,
        )


def _migrate_v78_strip_slash_before_art_variable(conn: sqlite3.Connection) -> None:
    """v78: undo the v76 leading-slash normalization for VARIABLE-LED art values (#275).

    v76 prepended "/" to every non-absolute art value, including ones that
    start with a template variable (e.g. "{feed_team_logo}"). Variables like
    {feed_team_logo} resolve to ABSOLUTE URLs at render time, so the stored
    "/{feed_team_logo}" rendered as "/https://…" — broken logos in XMLTV and
    the dashboard. This strips leading slash(es) when immediately followed by
    "{". Genuinely relative paths with a mid-path variable
    ("/art/{league}.png") are untouched. Idempotent.
    """
    if not _table_exists(conn, "templates"):
        return

    art_columns = [
        c for c in ("program_art_url", "event_channel_logo_url")
        if _column_exists(conn, "templates", c)
    ]
    json_columns = [
        c for c in ("pregame_fallback", "postgame_fallback", "idle_content")
        if _column_exists(conn, "templates", c)
    ]
    if not art_columns and not json_columns:
        return

    def repair(value):
        if not isinstance(value, str):
            return value
        return re.sub(r"^/+(?=\{)", "", value)

    select_cols = ["id", *art_columns, *json_columns]
    rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM templates").fetchall()

    changed = 0
    for row in rows:
        updates: dict[str, str] = {}
        for col in art_columns:
            new = repair(row[col])
            if new != row[col]:
                updates[col] = new
        for col in json_columns:
            try:
                blob = json.loads(row[col]) if row[col] else None
            except (TypeError, ValueError):
                blob = None
            if isinstance(blob, dict) and isinstance(blob.get("art_url"), str):
                new = repair(blob["art_url"])
                if new != blob["art_url"]:
                    blob["art_url"] = new
                    updates[col] = json.dumps(blob)
        if updates:
            sets = ", ".join(f"{c} = ?" for c in updates)
            conn.execute(
                f"UPDATE templates SET {sets} WHERE id = ?",
                (*updates.values(), row["id"]),
            )
            changed += 1

    if changed:
        logger.info(
            "[MIGRATE] v78: stripped corrupting leading slash from variable-led "
            "art values in %d template(s) (#275)",
            changed,
        )


def _migrate_v79_backfill_channel_team_display(conn: sqlite3.Connection) -> None:
    """v79: backfill managed_channels team abbrevs from team_cache (#403).

    home/away_team_abbrev columns existed but the lifecycle creator never
    wrote them. New channels get them at creation; this fills existing
    non-deleted rows so the compact event format ("MLB | LAA/MIN") renders
    immediately instead of waiting for channel churn. Best-effort: rows
    without a team_cache match stay NULL and the UI falls back to full team
    names.
    """
    if not _table_exists(conn, "managed_channels") or not _table_exists(conn, "team_cache"):
        return
    # Old fixture/backup DBs may carry a pre-abbrev team_cache shape — nothing
    # to backfill from, so skip (columns still arrive via reconciliation).
    if not _column_exists(conn, "team_cache", "team_abbrev"):
        return
    for col in ("home_team_abbrev", "away_team_abbrev"):
        _add_column_if_not_exists(conn, "managed_channels", col, "TEXT")
    for required_col in ("league", "event_provider", "deleted_at"):
        if not _column_exists(conn, "managed_channels", required_col):
            return

    for abbrev_col, name_col in (
        ("home_team_abbrev", "home_team"),
        ("away_team_abbrev", "away_team"),
    ):
        conn.execute(
            f"""
            UPDATE managed_channels SET {abbrev_col} = (
                SELECT tc.team_abbrev FROM team_cache tc
                WHERE tc.team_name = managed_channels.{name_col}
                  AND tc.league = managed_channels.league
                  AND tc.provider = managed_channels.event_provider
                LIMIT 1
            )
            WHERE deleted_at IS NULL
              AND {abbrev_col} IS NULL
              AND {name_col} IS NOT NULL
            """
        )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return any(
        row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})")
    )


def _v73_remap_json_array(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    rename: dict[str, str],
) -> None:
    """Rewrite a JSON-array column in `table.column`, remapping codes via `rename`.

    Each row's array is parsed, each element substituted using `rename` (when
    present), and duplicates collapsed while preserving order. Rows whose value
    isn't a JSON array are left alone.
    """
    if not _table_exists(conn, table):
        return
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        return
    if "id" in cols:
        pk = "id"
    elif "rowid" in cols:
        pk = "rowid"
    else:
        pk = "rowid"

    try:
        rows = conn.execute(f"SELECT {pk} AS pk, {column} AS val FROM {table}").fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("[MIGRATE v73] read %s.%s skipped: %s", table, column, e)
        return

    updated = 0
    for row in rows:
        raw = row["val"]
        if not raw:
            continue
        try:
            arr = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(arr, list):
            continue
        new_arr: list = []
        seen: set = set()
        changed = False
        for item in arr:
            mapped = rename.get(item, item) if isinstance(item, str) else item
            if mapped != item:
                changed = True
            if isinstance(mapped, str | int | float | bool | None):
                key = mapped
            else:
                key = json.dumps(mapped)
            if key in seen:
                changed = True
                continue
            seen.add(key)
            new_arr.append(mapped)
        if changed:
            conn.execute(
                f"UPDATE {table} SET {column} = ? WHERE {pk} = ?",
                (json.dumps(new_arr), row["pk"]),
            )
            updated += 1
    if updated:
        logger.info(
            "[MIGRATE v73] Remapped MiLB codes in %d row(s) of %s.%s",
            updated, table, column,
        )


def _dedup_cross_group_channels(conn: sqlite3.Connection) -> None:
    """Merge duplicate channels that exist for the same event across groups.

    For each set of duplicates (same event_id + provider + keyword + stream_id),
    keeps the earliest-created channel and merges streams from losers.
    """
    # Find duplicate sets (active channels only)
    cursor = conn.execute("""
        SELECT event_id, event_provider,
               COALESCE(exception_keyword, '') AS kw,
               primary_stream_id,
               COUNT(*) AS cnt
        FROM managed_channels
        WHERE deleted_at IS NULL
        GROUP BY event_id, event_provider,
                 COALESCE(exception_keyword, ''),
                 primary_stream_id
        HAVING cnt > 1
    """)
    dup_groups = cursor.fetchall()

    if not dup_groups:
        logger.info("[MIGRATE v64] No duplicate channels found")
        return

    total_merged = 0
    for dup in dup_groups:
        event_id = dup[0]
        event_provider = dup[1]
        kw = dup[2]
        stream_id = dup[3]

        # Get all channels in this duplicate set, ordered by created_at
        channels = conn.execute(
            """SELECT id, event_epg_group_id, channel_name,
                      dispatcharr_channel_id, created_at
               FROM managed_channels
               WHERE event_id = ? AND event_provider = ?
                 AND COALESCE(exception_keyword, '') = ?
                 AND primary_stream_id IS ?
                 AND deleted_at IS NULL
               ORDER BY created_at ASC""",
            (event_id, event_provider, kw, stream_id),
        ).fetchall()

        if len(channels) < 2:
            continue

        # Winner = first created
        winner_id = channels[0][0]
        winner_name = channels[0][2]

        for loser in channels[1:]:
            loser_id = loser[0]
            loser_name = loser[2]

            # Move streams from loser to winner (skip duplicates)
            conn.execute(
                """INSERT OR IGNORE INTO managed_channel_streams
                   (managed_channel_id, dispatcharr_stream_id,
                    stream_name, source_group_id, source_group_type,
                    priority, m3u_account_id, m3u_account_name)
                   SELECT ?, dispatcharr_stream_id,
                          stream_name, source_group_id,
                          source_group_type, priority,
                          m3u_account_id, m3u_account_name
                   FROM managed_channel_streams
                   WHERE managed_channel_id = ?""",
                (winner_id, loser_id),
            )

            # Soft-delete the loser
            conn.execute(
                """UPDATE managed_channels
                   SET deleted_at = CURRENT_TIMESTAMP,
                       delete_reason = 'migration_dedup_v64'
                   WHERE id = ?""",
                (loser_id,),
            )
            total_merged += 1
            logger.info(
                "[MIGRATE v64] Merged channel '%s' (id=%d) into "
                "'%s' (id=%d) for event %s",
                loser_name, loser_id, winner_name, winner_id,
                event_id,
            )

    logger.info(
        "[MIGRATE v64] Dedup complete: %d duplicate(s) merged "
        "from %d duplicate group(s)",
        total_merged, len(dup_groups),
    )


# =============================================================================
# LEGACY MIGRATION HELPER FUNCTIONS
# =============================================================================
# STATUS: DEPRECATED - Scheduled for removal with legacy migrations above
#
# These helper functions are only called by the legacy v3-v43 migrations.
# They are preserved as part of the safety fallback.
# Delete these when removing the legacy migration code above.
# =============================================================================






























def _add_column_if_not_exists(
    conn: sqlite3.Connection, table: str, column: str, column_def: str
) -> None:
    """Add a column to a table if it doesn't exist.

    Args:
        conn: Database connection
        table: Table name
        column: Column name to add
        column_def: Column definition (type and default)
    """
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = {row["name"] for row in cursor.fetchall()}
    if not columns:
        # Table doesn't exist yet — schema.sql will create it with all columns
        return
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")












def _migrate_v80_filler_conditionals_to_rows(conn: sqlite3.Connection) -> None:
    """v80: convert filler final/not-final conditionals to condition rows (#420).

    Faithful conversion, never invention: each ENABLED legacy conditional
    (postgame_conditional / idle_conditional) becomes up to two DISJOINT rows —
    ``is_final`` carrying the *_final fields, ``is_not_final`` carrying the
    *_not_final fields — in the hehg.2 row shape (description under the legacy
    key ``template``). Disjointness is the fidelity-critical property: on a
    final game the is_not_final row matches nothing, so fields the is_final
    row doesn't set fall through to the base register, exactly like today's
    ``cond.title_final or base.title`` per-field selection. Falsy legacy
    values (None/"") count as unset, matching the generator's ``or`` chain.

    The legacy columns are left in place untouched (rollback safety; never
    read again after cajd.3). Skips any template whose rows column is already
    non-empty, so the transform is idempotent beyond the schema_version guard.
    """
    for col in (
        "pregame_conditional_rows",
        "postgame_conditional_rows",
        "idle_conditional_rows",
    ):
        _add_column_if_not_exists(conn, "templates", col, "JSON DEFAULT '[]'")

    conversions = (
        ("postgame_conditional", "postgame_conditional_rows"),
        ("idle_conditional", "idle_conditional_rows"),
    )
    try:
        templates = conn.execute(
            "SELECT id, postgame_conditional, idle_conditional, "
            "postgame_conditional_rows, idle_conditional_rows FROM templates"
        ).fetchall()
    except sqlite3.OperationalError as e:
        # Minimal/legacy templates table without the filler columns (test
        # fixtures, pre-conditional-era DBs) — nothing to convert.
        logger.warning("[MIGRATE v80] filler conversion skipped: %s", e)
        return

    converted = 0
    for row in templates:
        for legacy_col, rows_col in conversions:
            try:
                existing_rows = json.loads(row[rows_col] or "[]")
            except (json.JSONDecodeError, TypeError):
                existing_rows = []
            if existing_rows:
                continue  # already converted (idempotence)

            try:
                legacy = json.loads(row[legacy_col] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(legacy, dict) or not legacy.get("enabled"):
                continue

            rows: list[dict] = []
            for condition, suffix, label in (
                ("is_final", "_final", "Final (migrated)"),
                ("is_not_final", "_not_final", "In progress (migrated)"),
            ):
                fields: dict = {}
                if legacy.get(f"title{suffix}"):
                    fields["title"] = legacy[f"title{suffix}"]
                if legacy.get(f"subtitle{suffix}"):
                    fields["subtitle"] = legacy[f"subtitle{suffix}"]
                if legacy.get(f"description{suffix}"):
                    fields["template"] = legacy[f"description{suffix}"]
                if fields:
                    rows.append(
                        {
                            "condition": condition,
                            "condition_value": None,
                            "priority": 50,
                            "label": label,
                            **fields,
                        }
                    )

            if rows:
                conn.execute(
                    f"UPDATE templates SET {rows_col} = ? WHERE id = ?",
                    (json.dumps(rows), row["id"]),
                )
                converted += 1

    if converted:
        logger.info(
            "[MIGRATE v80] Converted %d filler conditional(s) to condition rows",
            converted,
        )


def _migrate_v81_seed_sports_event_category(conn: sqlite3.Connection) -> None:
    """v81: append 'Sports event' to every template's event categories (#423).

    'Sports event' is the Gracenote-standard genre string guide clients key
    on; it becomes a seeded default alongside 'Sports' (user decision,
    2026-07-13). Normalizes our own historical starter variants ('Sports
    Event', 'Sporting Event') to the canonical string in place, appends
    when absent, and never removes or reorders anything else — idempotent
    and safe on user lists. Filler categories (#199, independent) untouched.
    """
    try:
        rows = conn.execute("SELECT id, xmltv_categories FROM templates").fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("[MIGRATE v81] category seed skipped: %s", e)
        return

    # Our own historical starter seeds used two variants of the same intent
    # ("Sports Event" on team starters, "Sporting Event" on event starters).
    # Normalize those to the canonical Gracenote string in place — they're
    # our strings, not user data. Anything else is left untouched.
    _OUR_VARIANTS = {"sports event", "sporting event"}

    seeded = 0
    for row in rows:
        try:
            cats = json.loads(row["xmltv_categories"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(cats, list):
            continue

        changed = False
        normalized: list = []
        for c in cats:
            if isinstance(c, str) and c.strip().lower() in _OUR_VARIANTS:
                if "Sports event" not in normalized:
                    if c != "Sports event":
                        changed = True
                    normalized.append("Sports event")
                else:
                    changed = True  # collapse duplicate variants
            else:
                normalized.append(c)
        if "Sports event" not in normalized:
            normalized.append("Sports event")
            changed = True

        if changed:
            conn.execute(
                "UPDATE templates SET xmltv_categories = ? WHERE id = ?",
                (json.dumps(normalized), row["id"]),
            )
            seeded += 1

    if seeded:
        logger.info("[MIGRATE v81] Seeded 'Sports event' into %d template(s)", seeded)


def _migrate_v82_channelsdvr_servers_list(conn: sqlite3.Connection) -> None:
    """v82: fold scalar Channels DVR settings into channelsdvr_servers (#381).

    Multi-server fan-out replaces the single url/source_name/lineup_id
    columns with a JSON list. An existing configured server becomes the
    list's only entry; the scalar columns are left in place (unread) —
    reconciliation never drops columns, and keeping them makes the
    migration trivially reversible.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "channelsdvr_url" not in cols:
        return  # fresh database — scalar columns never existed

    row = conn.execute(
        """
        SELECT channelsdvr_url, channelsdvr_source_name, channelsdvr_lineup_id,
               channelsdvr_servers
        FROM settings WHERE id = 1
        """
    ).fetchone()
    if not row or not row["channelsdvr_url"] or row["channelsdvr_servers"]:
        return  # nothing configured, or servers list already populated

    servers = [
        {
            "name": "Channels DVR",
            "url": row["channelsdvr_url"].rstrip("/"),
            "source_name": row["channelsdvr_source_name"],
            "lineup_id": row["channelsdvr_lineup_id"],
        }
    ]
    conn.execute(
        "UPDATE settings SET channelsdvr_servers = ? WHERE id = 1",
        (json.dumps(servers),),
    )
    logger.info("[MIGRATE v82] Folded Channels DVR scalar settings into servers list")


def _migrate_v83_media_server_lists(conn: sqlite3.Connection) -> None:
    """v83: fold scalar Emby/Jellyfin settings into servers lists (#471).

    Same pattern as v82 (Channels DVR): an existing configured server
    becomes the list's only entry; the scalar columns are left in place
    (unread) — reconciliation never drops columns.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}

    for kind in ("emby", "jellyfin"):
        if f"{kind}_url" not in cols:
            continue  # fresh database — scalar columns never existed

        row = conn.execute(
            f"""
            SELECT {kind}_url AS url, {kind}_username AS username,
                   {kind}_password AS password, {kind}_api_key AS api_key,
                   {kind}_servers AS servers
            FROM settings WHERE id = 1
            """
        ).fetchone()
        if not row or not row["url"] or row["servers"]:
            continue  # nothing configured, or servers list already populated

        servers = [
            {
                "name": kind.capitalize(),
                "url": row["url"].rstrip("/"),
                "username": row["username"],
                "password": row["password"],
                "api_key": row["api_key"],
            }
        ]
        conn.execute(
            f"UPDATE settings SET {kind}_servers = ? WHERE id = 1",
            (json.dumps(servers),),
        )
        logger.info("[MIGRATE v83] Folded %s scalar settings into servers list", kind)


# Retired pure-transform variables (#484): old token -> (base, implied filter).
# sport_lower maps to |slug (not |lower): it returned the hyphenated sport
# CODE ('australian-football'), and slug(display name) reproduces that.
_V84_RETIRED_TRANSFORMS = {
    "team_name_pascal": ("team_name", "pascal"),
    "home_team_pascal": ("home_team", "pascal"),
    "away_team_pascal": ("away_team", "pascal"),
    "team_abbrev_lower": ("team_abbrev", "lower"),
    "home_team_abbrev_lower": ("home_team_abbrev", "lower"),
    "away_team_abbrev_lower": ("away_team_abbrev", "lower"),
    "opponent_abbrev_lower": ("opponent_abbrev", "lower"),
    "feed_team_abbrev_lower": ("feed_team_abbrev", "lower"),
    "result_lower": ("result", "lower"),
    "sport_lower": ("sport", "slug"),
}

# Template-bearing columns on the templates table (TEXT fields and JSON blobs
# whose string values may hold {variable} tokens). The rewrite is textual, which
# is JSON-safe: tokens contain no quotes or backslashes.
_V84_TEMPLATE_COLUMNS = [
    "title_format",
    "subtitle_template",
    "description_template",
    "program_art_url",
    "event_channel_name",
    "event_channel_logo_url",
    "conditional_descriptions",
    "pregame_periods",
    "pregame_fallback",
    "pregame_conditional_rows",
    "postgame_periods",
    "postgame_fallback",
    "postgame_conditional",
    "postgame_conditional_rows",
    "idle_content",
    "idle_conditional",
    "idle_conditional_rows",
    "idle_offseason",
]


def _v84_rewrite_tokens(text: str) -> str:
    """Rewrite retired transform tokens to base|filter form.

    {team_name_pascal} -> {team_name|pascal}; suffixes carry over
    ({home_team_pascal.next} -> {home_team.next|pascal}); an existing filter
    chain stays appended ({team_name_pascal|urlencode} ->
    {team_name|pascal|urlencode}). 1:1 substitution — rendered output is
    identical.
    """
    import re

    for old, (new, filt) in _V84_RETIRED_TRANSFORMS.items():
        text = re.sub(
            r"\{" + old + r"(\.[a-z]+)?((?:\|[a-z_]+)*)\}",
            r"{" + new + r"\g<1>|" + filt + r"\g<2>}",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _migrate_v84_filter_consolidation(conn: sqlite3.Connection) -> None:
    """Rewrite stored templates + channel_id_format to base|filter form (#484).

    The resolver keeps the retired names as permanent legacy aliases, so this
    is belt-and-suspenders: anything missed still renders old-style.
    """
    template_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(templates)").fetchall()
    }
    cols = [c for c in _V84_TEMPLATE_COLUMNS if c in template_cols]
    rewritten = 0
    if cols:
        for row in conn.execute(f"SELECT id, {', '.join(cols)} FROM templates").fetchall():
            updates = {}
            for col in cols:
                value = row[col]
                if not value or not isinstance(value, str):
                    continue
                new_value = _v84_rewrite_tokens(value)
                if new_value != value:
                    updates[col] = new_value
            if updates:
                sets = ", ".join(f"{c} = ?" for c in updates)
                conn.execute(
                    f"UPDATE templates SET {sets} WHERE id = ?",
                    [*updates.values(), row["id"]],
                )
                rewritten += 1

    settings_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()
    }
    row = (
        conn.execute("SELECT channel_id_format FROM settings WHERE id = 1").fetchone()
        if "channel_id_format" in settings_cols
        else None
    )
    if row and row["channel_id_format"]:
        new_format = _v84_rewrite_tokens(row["channel_id_format"])
        if new_format != row["channel_id_format"]:
            conn.execute(
                "UPDATE settings SET channel_id_format = ? WHERE id = 1",
                (new_format,),
            )
            rewritten += 1

    logger.info("[MIGRATE v84] Rewrote retired transform tokens in %d row(s)", rewritten)
