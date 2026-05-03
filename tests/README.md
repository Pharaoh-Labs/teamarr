# Test Suite Map

500 tests across 28 files. This index groups them by what they protect, so you
can navigate to the right place for a given concern instead of wading through
the full list.

To run everything: `pytest tests/ -v`. Full suite finishes in ~60s.

## Test categories at a glance

| Category | Files | Tests | What they protect |
|----------|-------|-------|-------------------|
| Migrations & schema | 7 | ~111 | Schema upgrades from old DBs don't lose or corrupt data |
| Template variables | 6 | ~91 | `{home}`, `{feed_team}`, `{matchup_short}` etc. resolve correctly |
| Stream & event matching | 5 | ~94 | Streams find their events; teams disambiguate; tournaments work |
| Channel lifecycle | 4 | ~90 | Channels created/deleted in the right order, sync recovers from errors |
| Subscription system | 3 | ~39 | Global league/sport selection, per-group overrides, master filter toggle |
| Bug regressions | 2 | ~41 | Specific shipped bugs that have a "do not regress" pin |
| Provider plumbing | 1 | 4 | TSDB key rotation reloads provider |
| Scheduler | 1 | 13 | Cron + sub-scheduler timing |

## Migrations & schema (~111 tests)

These cover schema upgrades. If you're touching `connection.py`, `schema.sql`,
or anything that runs at startup, look here.

- **`test_checkpoint_v43.py`** (16) — v43 checkpoint brings any v2-v42 DB to v43 cleanly. Pins idempotency; tests the table-rebuild paths.
- **`test_subscription_migration.py`** (17) — v58 migration turns per-group sport config into a global subscription. League union, soccer-mode merge priority, deduplication.
- **`test_channel_numbering_v59.py`** (21) — v59 hoists numbering / consolidation / sorting from groups to global settings.
- **`test_xmltv_filler_categories.py`** (10) — v72 splits `xmltv_categories` into independent event vs filler lists.
- **`test_migration_helpers.py`** (30) — Phase 3 of Apr/May audit: per-helper behavior + idempotency for v50, v53, v61, v62, v64, v66, v67, v69. Each test pins one branch or one property.
- **`test_migration_conventions.py`** (7) — static-analysis checks pinning the rules in `MIGRATIONS.md` (no inline `conn.execute` in `_run_migrations`, no inline `ALTER TABLE`, naming convention, signature stability).
- **`test_reconciliation.py`** (10) — schema reconciliation adds missing columns from `schema.sql` on startup; preserves data; handles weird states.

## Template variables (~91 tests)

These cover the EPG template engine — every `{whatever}` placeholder.

- **`test_feed_team_variables.py`** (36) — `{feed_team}`, `{feed_team_short}`, `{feed_team_abbrev}`, `{is_home_feed}`, `{is_away_feed}`, `{feed_home_away}` — the variables added when feed separation auto-creates per-team channels.
- **`test_short_name_variables.py`** (14) — `{team_short}`, `{opponent_short}`, `{matchup_short}`, `{home_team_short}`, `{away_team_short}`.
- **`test_soccer_match_league_vars.py`** (14) — soccer-specific league vars use `LeagueMappingService` correctly.
- **`test_variable_scope.py`** (11) — variables tagged team-only / event-only / all are filtered correctly by template type. The variable picker UI relies on this.
- **`test_template_resolution.py`** (9) — `get_subscription_template_for_event` resolves templates by specificity: leagues > sports > default.
- **`test_postgame_next_var.py`** (7) — regression: `{game_time.next}` works on the last game of the day (was previously empty).

## Stream & event matching (~94 tests)

These cover matching streams to events — the heart of how Teamarr decides
which Dispatcharr stream goes with which game.

- **`test_feed_separation.py`** (39) — full feed-separation pipeline: HOME/AWAY token detection, team-name detection, channel discrimination by `feed_team_id`, label generation, settings disabled = no detection.
- **`test_exception_keyword_tvg_id.py`** (28) — keyword-based tvg-id generation, slugify rules, template extra-vars override, backward compat.
- **`test_multi_sport_hints.py`** (23) — ambiguous terms ("football", "main card") map to multiple sports; classifier handles them correctly.
- **`test_ncaab_gender_classification.py`** (18) — NCAAB streams match both men's and women's leagues; (W)/(M) markers narrow the hint and get stripped from team names.
- **`test_stream_matching.py`** (18) — IOC country codes (3-letter abbreviations) match exactly without false positives.
- **`test_team_import_collisions.py`** (7) — ESPN returns duplicate team names; import handles UNIQUE constraint violations gracefully.

## Channel lifecycle (~90 tests)

These cover the create/sync/delete flow for managed channels.

- **`test_dispatcharr_sync_reliability.py`** (25) — `ChannelLifecycleService` checks `update_channel` results before persisting local state. Self-healing via scheduler retry.
- **`test_channel_collision_awareness.py`** (15) — Teamarr skips channel numbers occupied by non-Teamarr Dispatcharr channels. Updated for v59 global mode.
- **`test_multi_template_fixes.py`** (11) — epic ou3 fixes: per-event filler config, channel-name segment auto-append removal, per-stream error isolation in lifecycle batch.

## Subscription system (~39 tests)

- **`test_sports_subscription.py`** (20) — subscription DB module + API endpoints for the global sports subscription.
- **`test_subscription_override.py`** (10) — priority chain: group override > global subscription > empty override = no leagues. Cache key separation for overridden groups.
- **`test_team_filter_master_toggle.py`** (9) — global team-filter toggle off → `_get_effective_team_filter` returns no-filter regardless of group/global selections. End-to-end disable.

## Bug regressions (~41 tests)

Tests that exist specifically to prevent a shipped bug from coming back.

- **`test_playoff_bypass.py`** (34) — bead `sua` (#197): playoff detection across providers (ESPN scoreboard/summary, soccer knockout slugs, MLBStats gameType, HockeyTech seasons-info).
- **`test_postgame_next_var.py`** (7) — postgame `{game_time.next}` on the last game of the day. Listed under "Template variables" too because it's both.

## Provider plumbing (~4 tests)

- **`test_tsdb_provider_reload.py`** (4) — `ProviderRegistry.reinitialize_provider()` recreates the TSDB provider with the updated API key from the DB, no restart needed.

## Scheduler (~13 tests)

- **`test_sub_scheduler.py`** (13) — `CronScheduler` and `SubTaskScheduler` timing.

## How to find the test you want

| Symptom / Code area | Look in |
|---------------------|---------|
| EPG generation breaks after schema changes | `test_checkpoint_v43`, `test_migration_helpers`, `test_reconciliation` |
| A `{variable}` is wrong in templates | `test_feed_team_variables`, `test_short_name_variables`, `test_variable_scope` |
| Streams don't match events anymore | `test_stream_matching`, `test_multi_sport_hints`, `test_feed_separation` |
| Channels appear/disappear at wrong times | `test_dispatcharr_sync_reliability`, `test_channel_collision_awareness` |
| Sport/league subscription behavior | `test_sports_subscription`, `test_subscription_override` |
| Playoff bypass not working | `test_playoff_bypass` |
| Soccer-specific issues | `test_soccer_match_league_vars`, `test_feed_separation` |

## How to run a subset

```bash
# Just one file
pytest tests/test_migration_helpers.py -v

# Just one class
pytest tests/test_migration_helpers.py::TestV50SoccerModes -v

# Just one test
pytest tests/test_migration_helpers.py::TestV50SoccerModes::test_idempotent -v

# Match by name pattern (e.g., everything with "soccer")
pytest tests/ -k soccer -v

# Stop on first failure
pytest tests/ -x
```

## When to add a test

The bar is low — most "should I add a test?" questions deserve "yes":

- **Always**: bug fix that touches more than the obvious lines (regression pin)
- **Always**: new template variable, condition evaluator, or migration block
- **Always**: external API behavior change (route shape, response format)
- **Usually**: new branch in matching/classification logic
- **Sometimes**: helper function with non-trivial branching (judgment call)
- **Rarely**: pure refactor where behavior doesn't change (existing tests should already cover it; if they don't, that's the test gap)

If you're unsure, lean toward "yes" — the suite is healthy at 500 tests and a 60s runtime; redundancy is cheap, missed coverage is expensive.
