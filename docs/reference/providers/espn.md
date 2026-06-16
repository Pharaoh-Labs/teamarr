---
title: ESPN
parent: Providers
grand_parent: Technical Reference
nav_order: 1
docs_version: "2.3.1"
---

# ESPN Provider

ESPN is the primary data provider (priority 0), serving 87 pre-configured leagues plus ~250 dynamically discovered soccer leagues. The API is free, public, and requires no authentication.

## API Details

| | |
|---|---|
| **Base URL** | `https://site.api.espn.com/apis/site/v2/sports` |
| **Auth** | None required |
| **Rate Limit** | Generous (practically impossible to hit — DNS throttling is the usual bottleneck) |

## Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `/{sport}/{league}/scoreboard?dates={YYYYMMDD}` | Games on a specific date |
| `/{sport}/{league}/teams/{team_id}/schedule` | Team schedule |
| `/{sport}/{league}/teams/{team_id}` | Team details |
| `/{sport}/{league}/summary?event={event_id}` | Event details and scores |
| `/{sport}/{league}/teams` | All teams in a league (cache refresh) |

## HTTP Client Configuration

| Setting | Default | Env Variable |
|---------|---------|-------------|
| Max connections | 100 | `ESPN_MAX_CONNECTIONS` |
| Timeout | 10s | `ESPN_TIMEOUT` |
| Retry count | 3 | `ESPN_RETRY_COUNT` |
| Max workers | 100 | `ESPN_MAX_WORKERS` |

Retry logic uses exponential backoff: 0.5s → 1s → 2s → 4s (capped at 10s) with ±30% jitter. Rate limit (429) responses trigger longer backoff: 5s → 10s → 20s (capped at 60s), respecting the `Retry-After` header if present.

## League ID Format

ESPN leagues are configured in `schema.sql` with `provider_league_id` in `sport/league` format:

```
football/nfl
basketball/nba
hockey/nhl
soccer/eng.1
baseball/mlb
```

## Sports Coverage

| Sport | Leagues | Notes |
|-------|---------|-------|
| Football | NFL, NCAAF, UFL | |
| Basketball | NBA, WNBA, G League, NCAAM, NCAAW | |
| Hockey | NHL, NCAA M/W, Olympics M/W | |
| Baseball | MLB | MiLB handled by MLB Stats provider |
| Soccer | 44 pre-configured, ~250 discovered | Dot notation: `eng.1`, `ger.2` |
| Combat Sports | UFC | Event Card matching |
| Lacrosse | NLL, PLL, NCAA M/W | |
| Volleyball | NCAA M/W | |

## Soccer League Discovery

ESPN's API exposes ~250 soccer leagues through its `/v2/sports/soccer/leagues` discovery endpoint (hard-capped at 250 by ESPN; we've seen ~247–248 after filtering). During cache refresh, Teamarr discovers available leagues and makes them selectable in the league picker under the Soccer sport. These discovered leagues support event matching in event groups but don't have pre-configured team import. A small number of real soccer leagues (e.g. Swiss Super League, Israeli Premier League) are omitted from ESPN's discovery index despite being fully served by the data endpoints — these are registered as primary leagues in `schema.sql` as a workaround.

Soccer leagues use ESPN's dot notation: `{country}.{tier}` (e.g., `eng.1` for Premier League, `ger.2` for 2. Bundesliga).

## Special Behaviors

- **Status mapping**: ESPN event statuses are normalized to Teamarr's internal `scheduled`, `in_progress`, `final`, `postponed`, `cancelled`
- **Season type normalization**: ESPN's `season.slug` field is parsed to canonical `preseason` / `regular` / `postseason` / `offseason` values. The slug is the primary source (handles soccer knockouts: `semifinals`, `round-of-16`, `final`, etc.), falling back to the numeric `season.type` (1–4) for leagues where slug is absent. The summary endpoint (`/summary?event=`) nests `season` under `header.season`, so `get_event` passes it through explicitly — otherwise a refresh would wipe the season_type set during the initial scoreboard fetch.
- **Team ID corrections**: Hardcoded mapping for known ESPN data mismatches (e.g., some women's hockey teams)
- **Tournament sports**: Golf, tennis, and racing events have no home/away teams — parsed via `TournamentParserMixin`
- **UFC**: Parsed via `UFCParserMixin` with fighter name extraction from the core API

## File Locations

| File | Purpose |
|------|---------|
| `teamarr/providers/espn/provider.py` | ESPNProvider class |
| `teamarr/providers/espn/client.py` | HTTP client with retry logic |
| `teamarr/providers/espn/constants.py` | Status mapping |
| `teamarr/providers/espn/tournament.py` | TournamentParserMixin (golf, tennis, racing) |
| `teamarr/providers/espn/ufc.py` | UFCParserMixin |
