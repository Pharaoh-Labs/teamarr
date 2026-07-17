---
title: API Layer
parent: Architecture
grand_parent: Technical Reference
nav_order: 1
docs_version: "2.3.1"
---

# API Layer

Teamarr's backend is a FastAPI application serving a REST API at `/api/v1/` and a React SPA for non-API routes.

## Route Modules

18 route modules with ~134 total endpoints, registered in `app.py`:

| Module | Endpoints | Description |
|--------|-----------|-------------|
| `health.py` | 1 | Health check and startup state |
| `teams.py` | 8 | Team CRUD, active/inactive toggling |
| `templates.py` | 5 | Template CRUD, duplication, presets |
| `presets.py` | 5 | Condition preset library |
| `groups.py` | 21 | Event group CRUD, bulk ops, scheduling, soccer leagues |
| `epg.py` | 19 | Team/event EPG generation, status tracking, preview, stats, cancellation |
| `channels.py` | 11 | Channel management, numbering, search, reconciliation |
| `dispatcharr.py` | 8 | Dispatcharr settings, connection test, sync status |
| `cache.py` | 10 | Cache refresh, stats, clearing, game data cache |
| `stats.py` | 5 | Generation run stats, live game stats, homepage widget KPIs, processing history, cleanup |
| `sort_priorities.py` | 7 | Stream ordering rules (m3u, group, regex-based priority) |
| `aliases.py` | 7 | Team alias CRUD for stream matching |
| `keywords.py` | 7 | Game event keywords (pregame, postgame, filler) |
| `detection_keywords.py` | 9 | Detection keyword CRUD, import/export |
| `subscription.py` | 9 | Global/per-group subscription config, soccer mode |
| `variables.py` | 3 | Template variable discovery and introspection |
| `backup.py` | 11 | Database backup creation, restore, compression |

## Application Startup

The lifespan handler in `app.py` orchestrates startup in phases:

1. **INITIALIZING** — Database init and integrity check
2. **REFRESHING_CACHE** — Team/league cache refresh from providers (skippable via `SKIP_CACHE_REFRESH`)
3. **LOADING_SETTINGS** — Display settings, timezone from DB
4. **CONNECTING_DISPATCHARR** — Lazy factory initialization
5. **STARTING_SCHEDULER** — Background EPG cron scheduler
6. **READY** — Fully operational

## Generation Status

`generation_status.py` provides a global thread-safe state machine for EPG generation progress:

| Phase | Percent | Description |
|-------|---------|-------------|
| `starting` | 0% | Generation initiated |
| `teams` | 5-50% | Processing team EPGs |
| `groups` | 50-95% | Processing event groups |
| `saving` | 95-96% | Writing XMLTV |
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
| `teamarr/api/routes/` | 18 route modules |
| `teamarr/api/models.py` | Pydantic request/response models |
| `teamarr/api/dependencies.py` | Dependency injection |
| `teamarr/api/generation_status.py` | Generation progress state machine |
| `teamarr/api/startup_state.py` | Startup phase tracking |
