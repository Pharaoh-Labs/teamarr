---
title: MLB Stats
parent: Providers
grand_parent: Technical Reference
nav_order: 4
---

# MLB Stats Provider

The MLB Stats provider serves Minor League Baseball (MiLB) data via MLB's public Stats API. Added in v2.3.1.

## API Details

| | |
|---|---|
| **Base URL** | `https://statsapi.mlb.com/api/v1` |
| **Auth** | None (public, free) |
| **Priority** | 40 |
| **Rate Limit** | None observed |

## Supported Leagues

| League | Code | Sport ID |
|--------|------|----------|
| Triple-A | `milb-aaa` | 11 |
| Double-A | `milb-aa` | 12 |
| High-A | `milb-high-a` | 13 |
| Single-A | `milb-a` | 14 |
| Rookie | `rookie` | 16 |

The `provider_league_id` in `schema.sql` is the MLB Stats `sport_id` value.

## Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `/sports` | List all sports/leagues |
| `/teams?sportId={id}` | All teams in a sport |
| `/teams/{team_id}` | Team details |
| `/schedule?sportId={id}&date={YYYY-MM-DD}&hydrate=teams,venue` | Games on a specific date |
| `/schedule?sportId={id}&startDate=...&endDate=...&hydrate=teams,venue` | Games in a date range |

The `hydrate=teams,venue` parameter enriches responses with full team and venue objects.

## HTTP Client Configuration

| Setting | Default | Env Variable |
|---------|---------|-------------|
| Max connections | 20 | `MLBSTATS_MAX_CONNECTIONS` |
| Timeout | 15s | `MLBSTATS_TIMEOUT` |
| Retry count | 3 | `MLBSTATS_RETRY_COUNT` |

Uses the same exponential backoff pattern as the ESPN provider.

## Team Data

The provider parses team short names from the `teamName` field (e.g., "Pirates" from "Pittsburgh Pirates"). Team logos use the MLB Static CDN:

```
https://www.mlbstatic.com/team-logos/{team_id}.svg
```

## Season Type Normalization

Each game from the `/schedule` endpoint has a `gameType` field (a single character code) that the provider maps to the canonical season_type values:

| `gameType` | Canonical | MLB meaning |
|------------|-----------|-------------|
| `R` | `regular` | Regular Season |
| `S` | `preseason` | Spring Training |
| `E` | `preseason` | Exhibition |
| `F` | `postseason` | Wild Card |
| `D` | `postseason` | Division Series |
| `L` | `postseason` | League Championship Series |
| `W` | `postseason` | World Series |
| `P` | `postseason` | Generic playoffs (used by minor leagues) |
| `A` | *(none)* | All-Star — not a season type |

All five playoff codes (`F`/`D`/`L`/`W`/`P`) map to `postseason` so consumer logic (template variables, playoff-bypass filter) doesn't need to know MLB's series structure.

## Limitations

- No single-event lookup (`get_event()` returns `None`) — the API lacks a simple single-event endpoint
- MLB itself (Major League Baseball) is served by the ESPN provider, not this one

## File Locations

| File | Purpose |
|------|---------|
| `teamarr/providers/mlbstats/provider.py` | MLBStatsProvider class |
| `teamarr/providers/mlbstats/client.py` | HTTP client |
