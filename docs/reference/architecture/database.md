---
title: Database
parent: Architecture
grand_parent: Technical Reference
nav_order: 5
---

# Database

Teamarr uses SQLite in WAL mode for all persistent storage. The database file (`teamarr.db`) is the single source of truth for configuration, teams, templates, event groups, channel state, and run history.

## Connection Settings

```
journal_mode = WAL          (Write-Ahead Logging for concurrency)
busy_timeout = 30000        (30 seconds, milliseconds)
foreign_keys = ON           (referential integrity)
connect timeout = 30.0s     (Python-level)
check_same_thread = False   (thread-safe access)
row_factory = sqlite3.Row   (dict-like access)
```

## Schema Version

**Current version: 84** (stored in `settings.schema_version`)

Schema changes use the [checkpoint + incremental migration](migrations) system. The schema source of truth is `teamarr/database/schema.sql`.

## Core Tables

| Table | Purpose |
|-------|---------|
| `settings` | Single-row global configuration (123 columns) |
| `templates` | EPG title/description/filler templates |
| `teams` | Per-team EPG configuration (provider, leagues, logo, template, XMLTV channel id) |
| `event_epg_groups` | Event group config (leagues, filters, M3U account, template) |
| `leagues` | League definitions (provider, sport, display name, logos, TSDB tier) |
| `managed_channels` | Channels created in Dispatcharr (tvg_id, delete_at, profiles) |
| `detection_keywords` | User-defined stream classification patterns |
| `team_aliases` | Team name aliases for matching |
| `team_cache` | Cached team data from providers |
| `service_cache` | Cached events/teams/stats with TTL |
| `stream_match_cache` | Fingerprint cache for stream matching |
| `processing_runs` | EPG generation run statistics (28 columns) |

The schema contains **35 tables** in total; the table above shows the core subset. Other notable tables: `managed_channel_streams` (time-windowed stream membership), `epg_matched_streams`, `epg_failed_matches`, `match_corrections`, `subscription_league_config`, `channel_sort_priorities`, `numbering_exceptions` (pinned blocks, #333), `lifetime_stats`, `stats_snapshots`, `league_overrides`, `team_epg_xmltv`, `event_epg_xmltv`.

## Settings Table

The settings table is a single row with 133 columns, organized into these groups (a sample of columns per group is shown):

### Lookahead Windows

| Column | Default | Description |
|--------|---------|-------------|
| `team_schedule_days_ahead` | 30 | Days to fetch for `.next` variables |
| `event_match_days_ahead` | 3 | Event matching window forward |
| `event_match_days_back` | 7 | Event matching window backward |
| `epg_output_days_ahead` | 14 | Days in XMLTV output |
| `epg_lookback_hours` | 6 | Check for in-progress games |

### Channel Lifecycle

| Column | Default | Description |
|--------|---------|-------------|
| `channel_create_timing` | `same_day` | `same_day` or `before_event` |
| `channel_delete_timing` | `same_day` | `same_day` or `after_event` |
| `channel_pre_buffer_minutes` | 60 | Buffer for `before_event` create |
| `channel_post_buffer_minutes` | 60 | Buffer for `after_event` delete |

### Channel Numbering

| Column | Default | Description |
|--------|---------|-------------|
| `channel_range_start` | 101 | First channel number of the default lane (everything not pinned) |
| `channel_range_end` | null | Last number (null = no limit) |
| `channel_stability_mode` | `compact` | `compact`, `gap`, or `strict` — applied inside every lane |
| `channel_gap_size` | 3 | Spacing between events in `gap` mode |
| `global_channel_mode` | `auto` | Always `auto` since v88 (manual mode retired, #333); kept one release for rollback |
| `league_channel_starts` | JSON | Legacy manual-mode starts, migrated to `numbering_exceptions` in v88; no longer read |

### Sport Durations (hours)

| Column | Default |
|--------|---------|
| `duration_basketball` | 3.0 |
| `duration_football` | 3.5 |
| `duration_hockey` | 3.0 |
| `duration_baseball` | 3.5 |
| `duration_soccer` | 2.5 |
| `duration_mma` | 5.0 |
| `duration_golf` | 6.0 |
| `duration_default` | 3.0 |

### Dispatcharr Integration

| Column | Default | Description |
|--------|---------|-------------|
| `dispatcharr_enabled` | 0 | Enable Dispatcharr sync |
| `dispatcharr_url` | null | Dispatcharr URL |
| `dispatcharr_username` | null | Auth username |
| `dispatcharr_password` | null | Auth password |
| `dispatcharr_epg_id` | null | EPG source ID in Dispatcharr |
| `default_channel_group_id` | null | Default channel group |
| `default_channel_group_mode` | `static` | `static`, `sport`, `league`, or custom |
| `default_channel_profile_ids` | JSON | Default channel profiles |
| `default_stream_profile_id` | null | Default stream profile |

### Provider SOCKS5 Proxy

| Column | Default | Description |
|--------|---------|-------------|
| `proxy_enabled` | 0 | Master switch for provider SOCKS5 routing |
| `proxy_url` | null | Credential-bearing `socks5://` URL, masked by the API |
| `proxy_user_agent` | null | Optional User-Agent override for all provider requests |
| `proxy_excluded_providers` | `[]` | Registered provider names that bypass the proxy |

## Database Modules

22 top-level Python modules plus 3 subpackages (`channels/`, `migrations/`, `settings/`) in `teamarr/database/`:

| Module | Purpose |
|--------|---------|
| `connection.py` | Connection management, schema init |
| `migrations/` | Structural pre-migrations + versioned data migrations |
| `reconciliation.py` | Schema reconciliation against `schema.sql` |
| `teams.py` | Team CRUD with parsed leagues |
| `groups.py` | Event group CRUD (73-field `EventEPGGroup` dataclass) |
| `templates.py` | Template CRUD |
| `default_templates.py` | Default template seeding |
| `leagues.py` | League queries, sport lookup, league ID resolution |
| `settings/` | Settings package (`AllSettings` dataclass with 19 sub-groups; `types.py`, `registry.py`, `read.py`, `update.py`) |
| `channels/` | Managed channel package: channel CRUD, history, stream membership (`streams.py`) |
| `channel_numbers.py` | Channel allocation algorithm |
| `stats.py` | Processing run tracking (`processing_runs`, 28 columns) |
| `priority_teams.py` | Priority-team channel ordering preferences |
| `seed.py` | Seeds team/league cache from bundled TSDB seed data |
| `detection_keywords.py` | Detection keyword CRUD, import/export |
| `aliases.py` | Team alias CRUD |
| `subscription.py` | Subscription override management |
| `team_cache.py` | Cached team data from providers |
| `provider_cache.py` | Provider metadata cache |
| `sort_priorities.py` | Channel sort priority storage |
| `condition_presets.py` | Conditional description presets |
| `exception_keywords.py` | Exception keyword configuration |
| `safe_sql.py` | SQL injection prevention (column validation) |
| `checkpoint_v43.py` | V2 schema-version checkpoint (consolidates v2–v43 migrations) |
| `migration.py` | Backup-restore validation helpers |

## Channel Numbering Algorithm

`channel_numbers.py` numbers channels inside **lanes**: one per pinned block
(`numbering_exceptions` — a team, league, or sport pin, most specific wins) plus
the default lane (the global range). The stability mode (`compact` / `gap` /
`strict`, with sticky locks and the daily re-layout) is applied inside each lane
over a shared set of used numbers, so blocks spill forward rather than collide.
External Dispatcharr channel numbers are always skipped.

See [Channel Numbering](channel-numbering) for the model, precedence rules, and
the v88 migration from manual mode.

## File Locations

| File | Purpose |
|------|---------|
| `teamarr/database/schema.sql` | Authoritative schema for fresh installs |
| `teamarr/database/connection.py` | Connection manager, startup orchestration |
| `teamarr/database/migrations/` | Pre-migrations (`pre.py`) + versioned migrations (`versioned.py`) |
| `teamarr/database/settings/` | Settings package: typed dataclasses (`types.py`), declarative field registry mapping each field to its DB column and serialization (`registry.py`), registry-driven readers (`read.py`) and updaters (`update.py`) |
| `teamarr/database/channel_numbers.py` | Numbering algorithm |
