---
title: ESPN
parent: Providers
grand_parent: Technical Reference
nav_order: 1
---

# ESPN Provider

ESPN is the primary data provider (priority 0), serving 99 pre-configured leagues (98 enabled — MotoGP ships disabled) plus ~228 dynamically discovered soccer leagues. The API is free, public, and requires no authentication.

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
| `/{sport}/{league}/rankings` | Poll rankings — college leagues only |

## HTTP Client Configuration

| Setting | Default | Env Variable |
|---------|---------|-------------|
| Max connections | 100 | `ESPN_MAX_CONNECTIONS` |
| Timeout | 10s | `ESPN_TIMEOUT` |
| Retry count | 3 | `ESPN_RETRY_COUNT` |
| Max workers | 100 (team processing) / 50 (cache refresh) / 24 (event prefetch) | `ESPN_MAX_WORKERS` |

`ESPN_MAX_WORKERS` is read by the consumers, not the HTTP client, and has three defaults: 100 in the team processor, 50 in cache refresh (lower because refresh makes more API calls per league), and 24 in the event-match prefetch (which fans a league x date window out across threads). Setting the env var overrides all three.

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
| Basketball | NBA, WNBA, G League, NCAAM, NCAAW, NBL (Australia) | FIBA World Cup (M/W) is TSDB — ESPN only tracks the final, not qualifiers |
| Hockey | NHL, NCAA M/W, Olympics M/W | |
| Baseball | MLB, NCAA Baseball, World Baseball Classic, Little League Baseball | MiLB handled by MLB Stats provider; LLB is the August World Series only |
| Soccer | 48 pre-configured, ~228 discovered | Dot notation: `eng.1`, `ger.2` |
| Rugby | 20 leagues (Six Nations, Rugby World Cup, Super Rugby, URC, Premiership, Top 14, MLR, NRL, Olympic 7s, …) | Second-largest ESPN sport by league count; NRL and Super Rugby Pacific migrated here from TSDB |
| Combat Sports | UFC | Event Card matching |
| Motorsports | F1, IndyCar | Race weekend sessions |
| Tennis | ATP, WTA | One event per match; grand slams split by draw type |
| Lacrosse | NLL, PLL, NCAA M/W | |
| Volleyball | NCAA M/W | |
| Softball | NCAA Softball | |

## Soccer League Discovery

ESPN's API exposes a couple hundred soccer leagues through its `/v2/sports/soccer/leagues` discovery endpoint (Teamarr requests `limit=500`; ~228 discovered leagues is typical after filtering). During cache refresh, Teamarr discovers available leagues and makes them selectable in the league picker under the Soccer sport. These discovered leagues support event matching in event groups but don't have pre-configured team import. A small number of real soccer leagues (e.g. Swiss Super League, Israeli Premier League) are omitted from ESPN's discovery index despite being fully served by the data endpoints — these are registered as primary leagues in `schema.sql` as a workaround.

Soccer leagues use ESPN's dot notation: `{country}.{tier}` (e.g., `eng.1` for Premier League, `ger.2` for 2. Bundesliga).

Rugby uses numeric slug IDs instead of string slugs — `rugby/180659` (Six Nations), `rugby/242041` (Super Rugby) — and rugby league is a separate ESPN sport path: `rugby-league/3` (NRL).

## Special Behaviors

- **Status mapping**: ESPN event statuses are normalized to Teamarr's internal `scheduled`, `in_progress`, `final`, `postponed`, `cancelled`
- **Season type normalization**: ESPN's `season.slug` field is parsed to canonical `preseason` / `regular` / `postseason` / `offseason` values. The slug is the primary source (handles soccer knockouts: `semifinals`, `round-of-16`, `final`, etc.), falling back to the numeric `season.type` (1–4) for leagues where slug is absent. The summary endpoint (`/summary?event=`) nests `season` under `header.season`, so `get_event` passes it through explicitly — otherwise a refresh would wipe the season_type set during the initial scoreboard fetch.
- **Team ID corrections**: Hardcoded mapping for known ESPN data mismatches (e.g., some women's hockey teams)
- **NCAA scoreboards**: NCAA leagues whose ungrouped ESPN scoreboard omits subdivisions fetch and merge ESPN's division groups. This includes FBS, FCS, lower-division, and cross-division fixtures when ESPN lists them. Teamarr cannot match fixtures ESPN does not expose in a public scoreboard group.
- **Tournament sports**: Racing events have no home/away teams — parsed via `TournamentParserMixin`. (Golf is wired into the same code path but no golf leagues are currently seeded.) Tennis is the exception: `TennisParserMixin` expands each tournament into one Event per MATCH, with the two players as home/away teams (surname as abbreviation). Grand slams appear on both the atp and wta endpoints, so each league keeps only its own draw types (atp: men's + mixed doubles; wta: women's). Tennis quirks: ESPN ignores `?dates=YYYYMMDD` for tennis and returns whole tournaments overlapping the window, so Teamarr slices per-day client-side; scoreboard `athlete.id` is null, so tennis team ids are name-derived and matching is name-based; doubles competitors carry only `roster.displayName` ("A / B"), no athlete objects; `venue.court` can be empty (walkovers/unassigned) and qualifying courts are named "Court N Roehampton", both tolerated by court mapping.
- **Poll rankings**: ESPN's team payload carries no rank field for any league, so `TeamStats.rank` comes from the league's `/rankings` polls, fetched once per league and cached for 6 hours. Only college leagues publish polls (pro leagues 404, and the endpoint is not called for them). Every live poll in the payload is merged, AP first, so an FBS team gets its AP rank while FCS and Division II teams get theirs from their own polls. Tournament seedings are ignored (that is `playoff_seed`), and a poll older than 45 days is treated as an ended season — ESPN keeps serving a season's final poll all offseason, so without that cutoff last season's ranks would appear on this season's listings.
- **UFC**: Parsed via `UFCParserMixin` with fighter name extraction from the core API

## File Locations

| File | Purpose |
|------|---------|
| `teamarr/providers/espn/provider.py` | ESPNProvider class |
| `teamarr/providers/espn/client.py` | HTTP client with retry logic; `ESPN_TEAM_ID_CORRECTIONS` (team ID corrections) |
| `teamarr/providers/espn/constants.py` | Status mapping |
| `teamarr/providers/espn/tournament.py` | TournamentParserMixin (racing; golf code path unused) |
| `teamarr/providers/espn/editorial_canary.py` | Drift canary for editorial fields (headlines, notes, altGameNote, neutralSite) |
| `teamarr/providers/espn/tennis.py` | TennisParserMixin (per-match events, draw-type split) |
| `teamarr/providers/espn/ufc.py` | UFCParserMixin |
