---
title: API Layer
parent: Architecture
grand_parent: Technical Reference
nav_order: 1
---

# API Layer

Teamarr's backend is a FastAPI application serving a REST API at `/api/v1/` and a React SPA for non-API routes.

## Route Modules

19 route modules with 206 total endpoints, registered in `app.py`:

| Module | Endpoints | Description |
|--------|-----------|-------------|
| `health.py` | 1 | Health check and startup state |
| `teams.py` | 9 | Team CRUD, active/inactive toggling |
| `templates.py` | 8 | Template CRUD, duplication, presets |
| `presets.py` | 5 | Condition preset library |
| `groups.py` | 26 | Event group CRUD, bulk ops, scheduling, soccer leagues |
| `epg.py` | 14 | Team/event EPG generation, status tracking, preview, stats, cancellation |
| `channels.py` | 12 | Channel management, numbering, search, reconciliation |
| `dispatcharr.py` | 8 | Dispatcharr settings, connection test, sync status |
| `cache.py` | 8 | Cache refresh, stats, clearing, game data cache |
| `stats.py` | 5 | Generation run stats, live game stats, homepage widget KPIs, processing history, cleanup |
| `sort_priorities.py` | 10 | Stream ordering rules (m3u, group, regex-based priority) |
| `aliases.py` | 7 | Team alias CRUD for stream matching |
| `keywords.py` | 7 | Game event keywords (pregame, postgame, filler) |
| `detection_keywords.py` | 9 | Detection keyword CRUD, import/export |
| `leagues.py` | 9 | Custom league CRUD |
| `manual_events.py` | 5 | API-first manual team fixture create/list/read/replace/cancel |
| `subscription.py` | 9 | Global/per-group subscription config, soccer mode |
| `variables.py` | 4 | Template variable discovery and introspection |
| `backup.py` | 11 | Database backup creation, restore, compression |
| `settings/` | 51 | Settings package: `models.py` plus 13 domain modules (`channel_numbering`, `channelsdvr`, `dispatcharr`, `display`, `emby`, `epg`, `feed_separation`, `jellyfin`, `lifecycle`, `plex`, `stream_ordering`, `team_filter`, `update_check`) — includes the media-server routes and the aggregate `GET /settings` in `__init__.py` |

## Manual fixture API (initial slice)

`/api/v1/manual-events` supplies missing team fixtures to the normal event-source
matcher. No ESPN event or TSDB key is required. The UI lives at
**Sources → Manual Events** (`/sources/manual-events`), beside the stream
sources it supplements: an add/edit form with
league/team pickers (configured `team_vs_team` leagues with cached teams only),
a timezone-aware kickoff, an upstream-duplicate warning, and soft cancel.
Provider-duplicate resolution remains manual — the UI warns but does not
reconcile; custom teams/competitions, rally coverage and ICS synchronization
are follow-up work tracked in #1131.

POST the collection with a configured, enabled `team_vs_team` league, two team
references from that league's team cache, and a timezone-aware start:

```json
{
  "league": "nba",
  "home_team": {"provider": "espn", "id": "2"},
  "away_team": {"provider": "espn", "id": "14"},
  "start_time": "2026-10-23T19:00:00-04:00",
  "season_type": "preseason"
}
```

Use your installation's actual team IDs. Optional fields are `name`, `venue`
and `neutral_site`; `season_type` accepts `preseason` (default), `regular` or
`postseason`. The response is a normalized event with a stable `manual:<uuid>`
identity and `provider: "manual"`; its teams retain their original identities.
Times are stored in UTC. Ambiguous local times must be supplied with the intended
UTC offset; naive date/time input is rejected.

| Method/path (relative to `/api/v1/manual-events`) | Behavior |
|---|---|
| `GET` | List fixtures, including cancelled; optional `?league=nba` |
| `POST` | Create a fixture; returns 201 |
| `GET /{id}?league=nba` | Read a fixture; missing/wrong league returns 404 |
| `PUT /{id}` | Replace editable fixture fields using the complete POST body; preserve ID and league |
| `DELETE /{id}?league=nba` | Idempotently soft-cancel an existing fixture; missing returns 404 |

Generation must still run (scheduled or manual). The league must be subscribed
globally or by the source override, with a template and an available matching
stream. Existing matching, team filters and source rules still apply; saving a
fixture does not create a stream or bypass those controls. This slice uses the
normal configured sport/template durations, not custom broadcast end times.

Manual events supplement, rather than replace, upstream candidates even on
cached or cache-only reads. Provider caches never store the merged schedule;
fixture writes clear cached failures and their own algorithmic matches while
retaining user corrections/skips. Cached manual matches reload the durable
fixture so edits and cancellation cannot replay an obsolete snapshot.

Only temporary event channels consume these schedules. Provider team-schedule
scans remain provider-only; manual events do not extend permanent team guides.
Cancellation retains the fixture and identity, and does not directly mutate
Dispatcharr. Normal generation/lifecycle remains responsible for channels.

Do not add a manual copy of a fixture that already exists upstream: this first
slice does not yet reconcile provider duplicates or adopt provider channels.

## Application Startup

The lifespan handler in `app.py` orchestrates startup in phases:

1. **INITIALIZING** — Database init and integrity check
2. **LOADING_SETTINGS** — Display settings, timezone from DB
3. **CONNECTING_DISPATCHARR** — Lazy factory initialization
4. **STARTING_SCHEDULER** — Background EPG cron scheduler
5. **READY** — Fully operational; the team/league cache refresh then runs in the background (skippable via `SKIP_CACHE_REFRESH`)

After a successful EPG generation, configured Emby, Jellyfin, and Channels DVR
guide refreshes run in a serialized background batch. Their outcomes are added
to the completed generation's run history without extending generation duration.

## Generation Status

`teamarr/consumers/generation_status.py` provides a global thread-safe state machine for EPG generation progress:

| Phase | Percent | Description |
|-------|---------|-------------|
| `init` | 3% | Generation initiated, M3U refresh |
| `teams` | 5-50% | Processing team EPGs |
| `groups` | 50-93% | Processing event groups |
| `ordering` | 93% | Stream ordering rules |
| `saving` | 95% | Writing XMLTV |
| `dispatcharr` | 96-97% | Dispatcharr EPG refresh + association |
| `lifecycle` | 98% | Channel lifecycle sync |
| `reconciliation` | 99% | Drift detection/repair |
| `cleanup` | 99% | Scheduled deletions, orphan sweeps |
| `complete` | 100% | Done |

Progress is **monotonic** — the percentage never decreases (prevents UI glitches). Cancellation is supported via a flag checked at phase boundaries.

## Dependencies

`dependencies.py` provides FastAPI dependency injection:

- **`get_sports_service()`** — LRU-cached singleton returning `SportsDataService` with all registered providers

## SPA Fallback

Non-API routes serve the React frontend:
- `/assets/*` — static files (JS, CSS)
- All other paths — `index.html` (client-side routing)

## File Locations

| File | Purpose |
|------|---------|
| `teamarr/api/app.py` | FastAPI app, lifespan, route registration |
| `teamarr/api/routes/` | 19 route modules |
| `teamarr/api/models.py` | Pydantic request/response models |
| `teamarr/api/dependencies.py` | Dependency injection |
| `teamarr/consumers/generation_status.py` | Generation progress state machine |
| `teamarr/api/cache_refresh_status.py` | Cache-refresh progress state |
| `teamarr/api/startup_state.py` | Startup phase tracking |
