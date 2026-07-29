---
title: API Layer
parent: Architecture
grand_parent: Technical Reference
nav_order: 1
---

# API Layer

Teamarr's backend is a FastAPI application serving a REST API at `/api/v1/` and a React SPA for non-API routes.

## Route Modules

19 route modules with 205 total endpoints, registered in `app.py`:

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
| `keywords.py` | 6 | Game event keywords (pregame, postgame, filler) |
| `detection_keywords.py` | 9 | Detection keyword CRUD, import/export |
| `leagues.py` | 9 | Custom league CRUD |
| `subscription.py` | 9 | Global/per-group subscription config, soccer mode |
| `variables.py` | 4 | Template variable discovery and introspection |
| `backup.py` | 11 | Database backup creation, restore, compression |
| `settings/` | 44 | Settings package: `models.py` plus 12 domain modules (`channel_numbering`, `channelsdvr`, `dispatcharr`, `display`, `emby`, `epg`, `feed_separation`, `jellyfin`, `lifecycle`, `stream_ordering`, `team_filter`, `update_check`) — includes the media-server routes |

## Application Startup

The lifespan handler in `app.py` orchestrates startup in phases:

1. **INITIALIZING** — Database init and integrity check
2. **REFRESHING_CACHE** — Team/league cache refresh from providers (skippable via `SKIP_CACHE_REFRESH`)
3. **LOADING_SETTINGS** — Display settings, timezone from DB
4. **CONNECTING_DISPATCHARR** — Lazy factory initialization
5. **STARTING_SCHEDULER** — Background EPG cron scheduler
6. **READY** — Fully operational

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
