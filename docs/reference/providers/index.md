---
title: Providers
parent: Technical Reference
nav_order: 2
has_children: true
docs_version: "2.3.1"
---

# Data Providers

Teamarr uses a priority-based provider system to fetch sports data. When resolving events or teams for a league, the provider with the lowest priority number is tried first.

## Provider Registry

All providers implement the `SportsProvider` interface and are registered in `teamarr/providers/__init__.py` with a priority, factory function, and enabled flag.

```
Request for league data
        │
        ▼
  ProviderRegistry.get_for_league(league)
        │
        ├── ESPN (priority 0)         → supports? → Yes → use ESPN
        ├── Squiggle (priority 30)    → supports? → Yes → use Squiggle
        ├── MLB Stats (priority 40)   → supports? → Yes → use MLB Stats
        ├── HockeyTech (priority 50)  → supports? → Yes → use HockeyTech
        └── TSDB (priority 100)       → supports? → Yes → use TSDB
```

## Provider Summary

| Provider | Priority | Leagues | Auth | Rate Limit |
|----------|----------|---------|------|------------|
| [ESPN](espn) | 0 | 52 | None (public API) | Generous (DNS is usually the bottleneck) |
| [Squiggle](squiggle) | 30 | 1 (AFL) | None (free) | No hard limit — cache required |
| [MLB Stats](mlbstats) | 40 | 5 | None (public API) | None observed |
| [HockeyTech](hockeytech) | 50 | 14 | Public client keys | None observed |
| [TSDB](tsdb) | 100 | 11 | API key in URL path | 30/min free, 100/min premium |

## SportsProvider Interface

All providers implement these methods (defined in `teamarr/core/interfaces.py`):

| Method | Required | Description |
|--------|----------|-------------|
| `name` | Yes | Provider identifier (e.g., `"espn"`) |
| `supports_league(league)` | Yes | Whether this provider handles the given league code |
| `get_events(league, date)` | Yes | All events for a league on a specific date |
| `get_team_schedule(team_id, league, days_ahead)` | Yes | Upcoming schedule for a specific team |
| `get_team(team_id, league)` | Yes | Team details by ID |
| `get_event(event_id, league)` | Yes | Single event by ID |
| `get_team_stats(team_id, league)` | No | Detailed team statistics |
| `get_league_teams(league)` | No | All teams in a league (used by cache refresh) |
| `get_supported_leagues()` | No | List of supported league codes |

## League Mapping

Each league in `schema.sql` maps to a provider via the `provider` and `provider_league_id` columns. The format of `provider_league_id` varies by provider:

| Provider | Format | Example |
|----------|--------|---------|
| ESPN | `sport/league` | `football/nfl`, `soccer/eng.1` |
| Squiggle | `league_code` | `afl` |
| MLB Stats | `sport_id` | `11` (Triple-A) |
| HockeyTech | `client_code` | `ohl`, `ahl` |
| TSDB | `league_id` | `4460` (IPL) |

## Design Principles

- **No direct DB access** — providers receive configuration via dependency injection at instantiation
- **Lazy initialization** — providers are created on-demand via factory functions
- **Thread-safe HTTP clients** — connection pooling with configurable limits
- **Exponential backoff** — all providers retry with jitter on failure (base delay 0.5s, capped at 10s)
- **Rate limit handling** — 429 responses trigger longer backoff (5s base, capped at 60s) with Retry-After header support
