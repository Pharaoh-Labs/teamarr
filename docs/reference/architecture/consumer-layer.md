---
title: Consumer Layer
parent: Architecture
grand_parent: Technical Reference
nav_order: 2
docs_version: "2.3.1"
---

# Consumer Layer

The consumer layer orchestrates EPG generation, stream matching, channel lifecycle, and integration-target synchronization. It sits between the API routes and the service/provider layers.

## Generation Workflow

`generation.py` provides the single entry point: `run_full_generation()`.

A global lock prevents concurrent runs. The workflow progresses through 8 phases:

| Phase | % Range | Description |
|-------|---------|-------------|
| Source Refresh | 0-5% | Refresh the active integration's source inventory |
| Teams | 5-50% | Process all active team EPGs |
| Event Groups | 50-95% | Match streams, create channels, generate EPG |
| Channel Reassignment | 93-95% | Global channel number rebalancing |
| Stream Ordering | 93-95% | Apply priority rules to channels |
| Merge XMLTV | 95-96% | Combine team + group XMLTV output |
| Integration Ops | 96-98% | EPG refresh, channel association, cleanup |
| Reconciliation | 99-100% | Detect/fix channel drift |

**Shared state across phases:**
- Single `SportsDataService` instance keeps the event cache warm across all teams and groups
- Shared events cache (`league:date` keyed dict) prevents duplicate API calls across groups
- Shared generation counter ensures cache fingerprint coherence

**Cancellation:** `GenerationCancelled` exception raised when the cancellation flag is set, checked at phase boundaries.

## Event Group Processor

`event_group_processor.py` handles the core matching and channel lifecycle for event groups.

### Processing Pipeline

```
1. Load group config (leagues, team filters, stream source account)
2. Fetch streams from Headendarr playlists or Dispatcharr
3. Filter streams (stale, placeholder, regex include/exclude)
4. Fetch events from providers (parallel, cached)
5. Match streams to events (StreamMatcher)
6. Exclude by timing (past/final/before window)
7. Subscription league filtering (per-group overrides)
8. Create/update channels (ChannelLifecycleService)
9. Generate XMLTV (template resolution)
10. Push to the group's configured integration target
11. Track stats
```

### Key Methods

| Method | Description |
|--------|-------------|
| `process_group(group_id)` | Full processing for one group — returns match/channel/EPG stats |
| `process_all_groups(callback)` | Parallel processing of all groups with ThreadPoolExecutor |
| `preview_group(group_id)` | Test matching without persisting — returns match details |

### Subscription Leagues

`_resolve_subscription_leagues()` resolves which leagues a group should search:

- **Global subscription** — default for all groups
- **Per-group override** — group can specify its own leagues
- **Soccer modes:** `all` (expand all enabled), `teams` (discover from followed teams), `manual` (explicit selection)

## Team Processor

`team_processor.py` generates EPG for team-based channels (schedule tracking).

| Method | Description |
|--------|-------------|
| `process_team(team_id)` | Single team EPG — load config, fetch schedule, generate programmes |
| `process_all_teams(callback)` | Parallel processing with ThreadPoolExecutor (up to `ESPN_MAX_WORKERS`) |

## Stream Matching

### Classifier (`matching/classifier.py`)

`classify_stream()` categorizes streams into:

| Category | Description | Examples |
|----------|-------------|---------|
| `TEAM_VS_TEAM` | Contains separator (vs/@/at) | `"Cowboys vs Eagles"` |
| `EVENT_CARD` | Combat sports pattern | `"UFC 315: Main Card"` |
| `PLACEHOLDER` | No event info | `"ESPN+ 1"`, `"Coming Soon"` |

Output includes: extracted team names, detected league/sport hints, card segment (combat sports), and whether custom regex was used.

### Matcher (`matching/matcher.py`)

`StreamMatcher` matches classified streams to real sporting events.

**Match methods** (in priority order):

| Method | Description |
|--------|-------------|
| `cache` | Fingerprint cache hit from previous match |
| `exact` | Exact team name match |
| `alias` | Team alias lookup (Detection Library) |
| `fuzzy` | Fuzzy string matching on team names |
| `league_hint` | Detected league hint narrows search space |

**Caching:** Fingerprint-based cache keyed by `hash(stream_name, group_id, generation)`. The generation counter increments per EPG run to bust stale cache entries.

## Channel Lifecycle

### Service (`lifecycle/service.py`)

`ChannelLifecycleService` manages channel creation, sync, and deletion in Headendarr or Dispatcharr.

**Safe update pattern** — `_safe_update_channel()`:
- Calls the selected integration API
- Checks `OperationResult.success` before writing to local DB
- On failure: DB stays unchanged, drift re-detected on next run (self-healing)
- No retry queue needed

**Three parallel context resolution paths** (must stay in sync):

| Path | Purpose | File |
|------|---------|------|
| `_create_channel` | New channel from matched stream | `lifecycle/service.py` |
| `_sync_channel_settings` | Update existing channel | `lifecycle/service.py` |
| EPG Generator | XMLTV channel name/icon | `event_epg.py` |

All three resolve: name, tvg_id, logo, channel group, profiles, stream profile, channel number, and delete timing from the same event + template context.

### Dynamic Resolver (`lifecycle/dynamic_resolver.py`)

Resolves `{sport}` and `{league}` wildcards in channel group and profile names:

- Looks up display names from the database
- Auto-creates groups and profiles in Dispatcharr when those features are enabled there
- Caches resolved IDs for fast repeated lookups

### Reconciliation (`lifecycle/reconciliation.py`)

`ChannelReconciler` detects and fixes inconsistencies between the local DB and the active integration target:

| Issue Type | Description | Action |
|------------|-------------|--------|
| `orphan_teamarr` | DB record but no platform channel | Delete DB record |
| `orphan_dispatcharr` | Platform channel but no DB record | Link or ignore |
| `duplicate` | Multiple channels for same event | Merge or keep first |
| `drift` | Settings mismatch (name, streams, profiles) | Update the target platform |

Runs automatically at the end of each generation. Issues have severity levels (critical/warning/info) and `auto_fixable` flags.

### Timing (`lifecycle/timing.py`)

`ChannelLifecycleManager` computes create/delete times based on:
- Event start time
- Sport-specific duration
- Pre/post buffer minutes
- Create/delete timing mode (`same_day` or `before_event`/`after_event`)

## Sports Data Service

`services/sports_data.py` orchestrates provider calls with caching.

**Key design:**
- `PersistentTTLCache` — in-memory during generation (fast), background flush to SQLite every 2 minutes
- Provider selection by priority (ESPN → MLB Stats → HockeyTech → TSDB)
- TTLs: 30 days for final events, 8h for schedules, 30m for live events, 24h for team info

| Method | TTL | Description |
|--------|-----|-------------|
| `get_events(league, date)` | 8h (30d if all final) | All events for a league on a date |
| `get_team_schedule(team_id, league)` | 8h | Team's upcoming schedule |
| `get_team(team_id, league)` | 24h | Team metadata |
| `get_team_stats(team_id, league)` | 4h | Record, standings |
| `get_single_event(event_id, league)` | 30m | Live event with scores |

## Stream Ordering

`services/stream_ordering.py` assigns priority to channels based on configurable rules.

| Rule Type | Matches On |
|-----------|-----------|
| `m3u` | M3U account name |
| `group` | Source group name |
| `regex` | Stream name pattern (case-insensitive) |

No match defaults to priority 999 (sorted to end). Channels are sorted by priority, then by `added_at` for stable ordering.

## File Locations

| File | Purpose |
|------|---------|
| `consumers/generation.py` | Unified generation workflow |
| `consumers/event_group_processor.py` | Event group processing pipeline |
| `consumers/team_processor.py` | Team EPG generation |
| `consumers/matching/classifier.py` | Stream classification |
| `consumers/matching/matcher.py` | Stream-to-event matching |
| `consumers/lifecycle/service.py` | Channel lifecycle management |
| `consumers/lifecycle/dynamic_resolver.py` | Wildcard resolution |
| `consumers/lifecycle/reconciliation.py` | Drift detection and repair |
| `consumers/lifecycle/timing.py` | Channel create/delete timing |
| `services/sports_data.py` | Provider orchestration with caching |
| `services/stream_ordering.py` | Channel priority rules |
