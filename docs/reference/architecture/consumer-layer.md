---
title: Consumer Layer
parent: Architecture
grand_parent: Technical Reference
nav_order: 2
---

# Consumer Layer

The consumer layer orchestrates EPG generation, stream matching, channel lifecycle, and Dispatcharr synchronization. It sits between the API routes and the service/provider layers.

## Generation Workflow

`generation.py` provides the single entry point: `run_full_generation()`.

A global lock prevents concurrent runs. The workflow progresses through these phases (names match `generation_status` progress events):

| Phase | % | Description |
|-------|---|-------------|
| `init` | 3% | M3U refresh, setup |
| `teams` | 5-50% | Process all active team EPGs |
| `groups` | 50-93% | Match streams, create channels, generate EPG |
| `ordering` | 93% | Apply stream-ordering priority rules |
| (channel reassignment) | 94% | Global channel number rebalancing (`_sync_global_channels`) |
| `saving` | 95% | Merge team + group XMLTV output |
| `dispatcharr` | 96-97% | EPG refresh, channel association, stream audit |
| `channelsdvr`/`emby`/`jellyfin` | 97% | Parallel media-server EPG refreshes (`_run_media_server_refreshes`) |
| `lifecycle` | 98% | Channel lifecycle sync |
| `reconciliation` | 99% | Detect/fix channel drift |
| `cleanup` | 99% | Scheduled deletions, orphan sweeps |
| `complete` | 100% | Done |

**Shared state across phases:**
- Single `SportsDataService` instance keeps the event cache warm across all teams and groups
- Shared events cache (`league:date` keyed dict) prevents duplicate API calls across groups
- Shared generation counter ensures cache fingerprint coherence

**Cancellation:** `GenerationCancelled` exception raised when the cancellation flag is set, checked at phase boundaries.

## Event Group Processor

The `event_group_processor/` package handles the core matching and channel lifecycle for event groups. `processor.py` holds the `EventGroupProcessor` coordinator; the pipeline stages live in sibling modules (`stream_fetcher.py`, `matching.py`, `team_filter.py`, `persistence.py`, `xmltv.py`, `preview.py`, `results.py`).

### Processing Pipeline

```
1. Load group config (leagues, team filters, M3U account)
2. Fetch streams from Dispatcharr
3. Filter streams (stale, placeholder, regex include/exclude)
4. Fetch events from providers (parallel, cached)
5. Match streams to events (StreamMatcher)
6. Exclude by timing (past/final/before window)
7. Subscription league filtering (per-group overrides)
8. Create/update channels (ChannelLifecycleService)
9. Generate XMLTV (template resolution)
10. Push to Dispatcharr
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

`team_processor.py` generates XMLTV programmes for each team's XMLTV channel (schedule tracking). It does not create or modify Dispatcharr channels — that's the lifecycle service's job and only happens for event-based workflows.

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
| `FIELD_EVENT` | Field/competitor events (racing, tennis, golf) | `"NASCAR Cup: Daytona 500"` |
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
| `epg` | Matched via EPG program title (see below); persisted as `MatchMethod.EPG` |

**Caching:** Fingerprint-based cache keyed by `hash(stream_name, group_id, generation)`. The generation counter increments per EPG run to bust stale cache entries.

### EPG-title matching (`matching/epg_matcher.py`, `matching/epg_index.py`)

For static-named linear channels (ESPN, NBA1) the stream name is unmatchable, but the Dispatcharr EPG guide carries the real matchup. When a group opts in, `StreamMatcher` augments name matching with EPG-title matching:

1. **Resolve** — `matching/epg_resolver.py` bridges the stream `tvg_id` → program `tvg_id` namespace gap via a cascade (curated channel `epg_data_id` → direct tvg_id → strict name match → Xtream provider guide, `matching/epg_xtream.py`). Does not require streams to be pre-built into channels.
2. **Index + match** — `EPGProgramIndex` (built once per run, scoped to resolved `tvg_id`s) fetches programs; `build_match_input()` pipe-joins program `title + sub_title` and feeds it through the **same** `classify_stream → TeamMatcher` pipeline. Studio/talk and replay program categories are skipped.
3. **Fan-out** — one linear stream matches **many** events (one per program); results carry `MatchMethod.EPG` and the program's start/end window for the lifecycle layer.
4. **Reconciliation** — `_reconcile_epg()`: linear `tvg_id` + EPG match → EPG wins (time-windowed), name match discarded; dedicated `tvg_id` → name match kept, EPG only fills when name found nothing.

The persisted `MatchMethod` is carried onto each `managed_channel_streams` row (`match_method` column) so the `epg_match` stream-ordering rule can prioritize time-shared linear streams. See [Program Matching](../../guide/matching/program-matching) for the user-facing behavior.

## Channel Lifecycle

### Service (`lifecycle/service.py` + stage modules)

`ChannelLifecycleService` manages channel creation, sync, and deletion in Dispatcharr. `service.py` holds the coordinator (shared state, `_safe_update_channel`, profile-change batching); the paths live in sibling modules: `creator.py` (matched-stream driver, duplicate modes, channel creation), `syncer.py` (settings/profiles/logo sync, EPG association), `cleanup.py` (scheduled deletions, missing/rotated streams, orphan + disabled-group sweeps), `naming.py` (name/logo/template resolution shared by create and sync).

**Safe update pattern** — `_safe_update_channel()`:
- Calls Dispatcharr API
- Checks `OperationResult.success` before writing to local DB
- On failure: DB stays unchanged, drift re-detected on next run (self-healing)
- No retry queue needed

**Three parallel context resolution paths** (must stay in sync):

| Path | Purpose | File |
|------|---------|------|
| `_create_channel` | New channel from matched stream | `lifecycle/creator.py` |
| `_sync_channel_settings` | Update existing channel | `lifecycle/syncer.py` |
| EPG Generator | XMLTV channel name/icon | `event_epg.py` |

All three resolve: name, tvg_id, logo, channel group, profiles, stream profile, channel number, and delete timing from the same event + template context.

### Dynamic Resolver (`lifecycle/dynamic_resolver.py`)

Resolves `{sport}` and `{league}` wildcards in channel group and profile names:

- Looks up display names from the database
- Auto-creates groups/profiles in Dispatcharr if they don't exist
- Caches resolved IDs for fast repeated lookups

### Reconciliation (`consumers/reconciliation.py`)

`ChannelReconciler` detects and fixes inconsistencies between the local DB and Dispatcharr:

| Issue Type | Description | Action |
|------------|-------------|--------|
| `orphan_teamarr` | DB record but no Dispatcharr channel | Delete DB record |
| `orphan_dispatcharr` | Dispatcharr channel but no DB record | Link or ignore |
| `duplicate` | Multiple channels for same event | Merge or keep first |
| `drift` | Settings mismatch (name, streams, profiles) | Update Dispatcharr |

Runs automatically at the end of each generation. Issues have severity levels (critical/warning/info) and `auto_fixable` flags.

### Timing (`lifecycle/timing.py`)

`ChannelLifecycleManager` computes create/delete times based on:
- Event start time
- Sport-specific duration
- Pre/post buffer minutes
- Create/delete timing mode (`same_day` or `before_event`/`after_event`)

### Time-windowed stream membership (`managed_channel_streams.attach_at`/`detach_at`)

For EPG-matched linear streams, membership in a channel is **time-windowed** so one linear stream (ESPN, NBA1) rotates across many event channels, attached to each only near game time. This is **separate** from channel create/delete timing — the channel exists for its whole lifecycle; only the *stream* swaps in and out.

- `compute_stream_window()` (`lifecycle/timing.py`) derives `attach_at`/`detach_at` from the matched EPG program slot ± the global `epg_stream_pre/post_buffer_minutes` settings, clipped to the neighbouring programs on that `tvg_id`.
- `NULL` window = full-life membership (dedicated/name-matched streams — unchanged behavior). `get_ordered_stream_ids()` enforces the window gate; it's the set pushed to Dispatcharr, and reconciliation drift uses the same window-gated set as "expected".

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

`services/stream_ordering.py` assigns priority to a channel's streams based on configurable rules. Nine rule types:

| Rule Type | Matches On |
|-----------|-----------|
| `m3u` | M3U account name |
| `group` | Source group name |
| `regex` | Stream name pattern (case-insensitive) |
| `stream_type` | Stream type |
| `team_feed` / `not_team_feed` | Whether the stream is a team feed |
| `epg_match` | Stream was EPG-matched (`match_method`) |
| `dispatcharr_group` | Dispatcharr channel group |
| `stats_metric` | Stream stats metric (score mode) |

Each rule runs in one of two modes: `priority` (band assignment) or `score` (numeric ranking); bands and scores are collapsed into a single ordering (`_collapse`). No match defaults to priority 999 (sorted to end), though a user rule can override the catch-all band. Ties break by `added_at` for stable ordering.

## Other Consumer Modules

| Module | Purpose |
|--------|---------|
| `consumers/cache/` | Unified team/league reverse-lookup cache (queries, refresh) driving event matching, multi-league resolution, soccer league discovery |
| `consumers/enforcement/` | Post-processing enforcers: `KeywordEnforcer`, `CrossGroupEnforcer`, `KeywordOrderingEnforcer` |
| `consumers/filler/` | Team and event filler programme generation |
| `consumers/team_epg.py` / `consumers/event_epg.py` | XMLTV programme generation for team and event channels |
| `consumers/scheduler.py` | Background EPG cron scheduler |
| `consumers/racing_segments.py` / `consumers/ufc_segments.py` | Racing-weekend and fight-card segment expansion |
| `consumers/channel_lifecycle.py` | Lifecycle helpers shared across consumers |
| `consumers/stream_match_cache.py` | Fingerprint match cache persistence |
| `consumers/generation_status.py` | Generation progress state machine |
| `consumers/event_matcher.py` | Event matching helpers |

`consumers/matching/` contains 14 modules; beyond those described above: `team_matcher.py`, `racing_matcher.py`, `tennis_matcher.py`, `country_resolver.py`, `normalizer.py`, `constants.py`, `result.py`, `event_matcher.py`.

## File Locations

| File | Purpose |
|------|---------|
| `consumers/generation.py` | Unified generation workflow |
| `consumers/event_group_processor/` | Event group processing pipeline (coordinator + stage modules) |
| `consumers/team_processor.py` | Team EPG generation |
| `consumers/matching/classifier.py` | Stream classification |
| `consumers/matching/matcher.py` | Stream-to-event matching |
| `consumers/matching/epg_index.py` | Per-run scoped EPG program index (tvg_id → programs) |
| `consumers/matching/epg_matcher.py` | EPG title/category matching helpers |
| `consumers/lifecycle/` | Channel lifecycle management (service coordinator + creator/syncer/cleanup/naming) |
| `consumers/lifecycle/dynamic_resolver.py` | Wildcard resolution |
| `consumers/reconciliation.py` | Drift detection and repair |
| `consumers/lifecycle/timing.py` | Channel create/delete timing |
| `services/sports_data.py` | Provider orchestration with caching |
| `services/stream_ordering.py` | Channel priority rules |
