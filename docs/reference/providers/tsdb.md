---
title: TSDB
parent: Providers
grand_parent: Technical Reference
nav_order: 7
---

# TheSportsDB Provider

TheSportsDB (TSDB) is a community-driven sports data API. Teamarr uses it as a fallback provider (priority 100) for leagues not covered by ESPN, including cricket, boxing, Scandinavian leagues, Brazilian state championships, and motorsports (IMSA, WEC). It serves 48 leagues in total (5 free-tier, 43 premium).

## API Details

| | |
|---|---|
| **Base URL** | `https://www.thesportsdb.com/api/v1/json/{api_key}/{endpoint}` |
| **Auth** | API key in URL path (`123` for free tier) |
| **Priority** | 100 (last resort) |
| **Rate Limit** | 30 req/min free, 100 req/min premium |

## API Tiers

Measured 2026-08-04 (two networks, three client types; matches TSDB's published limits — TSDB quietly tightened the free tier sometime in 2026):

| | Free (`123`) | Premium |
|---|---|---|
| **Rate Limit** | 30 req/min | 100 req/min |
| **`eventsnextleague` / `eventspastleague`** | **1 event** (rolling next/last) | 20 |
| **`eventsday` with `l=` league filter** | **always 0 — the filter is premium-gated** (unfiltered returns the global top-3 events/day) | full |
| **`eventsseason`** | 15-event cap | 3,000 |
| **`all_leagues`** | sample only | full list |
| **Cost** | Free | ~$9/month |

### How the free tier actually behaves in Teamarr

Teamarr's event pipeline polls `get_events(league, date)` per date on 30min–8h cache TTLs. Each game enters the guide **the moment it becomes the league's rolling "next" game** — so on the free tier every game does appear, but with short lead time (day-of for stacked schedules), and a second same-day game only appears after the first finishes (replacing it in that date's cache). **Team channels get zero events on the free tier**: `get_team_schedule` iterates only the league-filtered `eventsday` endpoint, which free keys can't use. In short: free = event-source channels with day-of lead; premium = full forward guide + working team channels.

### Free Tier Leagues

These leagues remain classified free: their event-source channels work through the rolling-next capture described above (team channels still require a premium key, as on every TSDB league):

- CFL, Unrivaled, Norwegian Hockey, Boxing
- Major League Cricket (MLC) — its short US T20 season fits within the free rolling next-events window
- WPBL (Women's Pro Baseball League) — 4 teams, ~30-game season, roughly one game per day

### Premium Tier Leagues

These leagues have high event volume or unreliable free-tier data and require a premium key for full coverage:

- SHL (Swedish Hockey League) — a full ~52-round, 14-team season far exceeds the free tier's 15-events/call cap
- IPL, BBL, SA20 (cricket)
- Svenska Cupen and other regional soccer leagues (Canadian Premier League, Swedish Superettan / Division 1, Icelandic, Venezuelan, Gambian, Aruban, Northern Irish)
- 23 Brazilian state championships (*campeonatos estaduais*) — every state except the four ESPN already covers (Carioca, Paulista, Gaúcho, Mineiro); see [Supported Leagues](../supported-leagues#brazilian-state-championships)
- IMSA and WEC (motor racing). WEC's 62 events/season exceeds the free `eventsseason.php` 15-event cap; IMSA fits it but is gated premium too, so all TSDB racing is premium (no silent truncation if a schedule grows).
- FIBA Basketball World Cup (M/W: `fiba`, `fibaw`) — gated premium since qualifiers run in parallel across multiple confederations, which can exceed the free tier's 5-events/day/league cap during busy qualifying windows.
- Uruguayan Segunda División (`uru.2`)

The `tsdb_tier` column in `schema.sql` classifies each league as `free` or `premium`.

AFL was formerly a TSDB premium league but is now served by the free [Squiggle](squiggle) provider. NRL and Super Rugby Pacific also migrated from TSDB to ESPN.

## Configuration

Add your premium key in **Settings > General > TheSportsDB API Key**. The key takes effect immediately (no restart required). The league picker shows a crown icon on premium-tier leagues and warns if you select one without a key configured.

Get a key at [thesportsdb.com/pricing](https://www.thesportsdb.com/pricing).

## Supported Leagues

TSDB serves **48 leagues** in total. The table below is representative, not exhaustive — it omits the 23 Brazilian state championships, `fiba`/`fibaw` (FIBA Basketball World Cup M/W), and `uru.2` (Uruguayan Segunda División), among others. See [Supported Leagues](../supported-leagues) for the full list.

| League | Code | TSDB ID | Sport | Tier |
|--------|------|---------|-------|------|
| Unrivaled | `unrivaled` | 5622 | Basketball | Free |
| Norwegian Fjordkraft-ligaen | `norwegian-hockey` | 4926 | Hockey | Free |
| Boxing | `boxing` | 4445 | Boxing | Free |
| Major League Cricket | `mlc` | 5401 | Cricket | Free |
| WPBL | `wpbl` | 5929 | Baseball | Free |
| Swedish Hockey League | `shl` | 4419 | Hockey | Premium |
| Indian Premier League | `ipl` | 4460 | Cricket | Premium |
| Big Bash League | `bbl` | 4461 | Cricket | Premium |
| South Africa Twenty20 (SA20) | `sa20` | 5532 | Cricket | Premium |
| Svenska Cupen | `svenska-cupen` | 4756 | Soccer | Premium |
| Canadian Premier League | `can.1` | 4820 | Soccer | Premium |
| Swedish Superettan | `swe.2` | 4403 | Soccer | Premium |
| Swedish Division 1 North | `swe.3.n` | 4674 | Soccer | Premium |
| Swedish Division 1 South | `swe.3.s` | 4845 | Soccer | Premium |
| Icelandic Úrvalsdeild karla | `ice.1` | 4642 | Soccer | Premium |
| Icelandic 1. deild karla | `ice.2` | 4906 | Soccer | Premium |
| Venezuelan Segunda División | `ven.2` | 5659 | Soccer | Premium |
| Gambia GFA League | `gam.1` | 5238 | Soccer | Premium |
| Aruban Division di Honor | `arb.1` | 5230 | Soccer | Premium |
| Northern Irish Premiership | `nifl.1` | 4659 | Soccer | Premium |
| IMSA SportsCar Championship | `imsa` | 4488 | Motor Racing | Premium |
| FIA World Endurance Championship | `wec` | 4413 | Motor Racing | Premium |

## Event Resolution

TSDB uses a three-step fallback chain when fetching events:

1. **`eventsday.php`** — date-specific lookup (primary, works for most leagues)
2. **`eventsnextleague.php`** — upcoming events filtered by date (fallback)
3. **`eventsseason.php`** — full-season events filtered by date (last resort, gated to sparse leagues like Unrivaled where the day endpoints return nothing)

### Racing Leagues (IMSA, WEC)

Motorsport leagues bypass the fallback chain entirely. `eventsday.php` and
`eventsnextleague.php` both return "Invalid League ID" for `imsa`/`wec`, so
these leagues fetch the full season via `eventsseason.php` exclusively and
filter client-side by session date.

TSDB models a race weekend as several flat, per-session events (Free
Practice 1, Qualifying, Race, ...) that share a season/round. `teamarr/providers/tsdb/racing.py`
groups these by `(strSeason, intRound)` into the same `Event(sessions=[...],
circuit_name=...)` shape the racing pipeline expects from ESPN/static
providers — one EPG program block per session (Practice, Qualifying,
Hyperpole, Race).

Both racing leagues are gated premium — see the free-cap rationale under
[Premium Tier Leagues](#premium-tier-leagues) above.

## Rate Limiting

Teamarr enforces rate limits **preemptively** using a sliding window limiter — it tracks request timestamps and waits before approaching the limit, rather than waiting for 429 responses.

If the API does return HTTP 429, Teamarr retries with exponential backoff (5s → 10s → 20s → 40s → 80s).

Rate limit statistics (total requests, preemptive waits, reactive waits) are tracked and available for UI feedback.

## TSDB League Configuration

Each TSDB league requires **two** identifiers in `schema.sql`:

| Column | Used By | Example |
|--------|---------|---------|
| `provider_league_id` | `eventsnextleague.php`, `lookupleague.php` | `4460` |
| `provider_league_name` | `eventsday.php`, `search_all_teams.php` | `Indian Premier League` |

Both are needed because `eventsday.php` and team search filter by league **name**, not ID. The values must match TSDB's internal data exactly. Use `search_all_leagues.php` to discover correct values.

## Cache TTLs

| Data | TTL |
|------|-----|
| Teams | 24 hours |
| Next events | 1 hour |
| Past games | 7 days |
| Today's games | 30 minutes |
| Tomorrow's games | 4 hours |
| 3-7 days out | 8 hours |
| 8+ days out | 24 hours |

## Season Type Normalization

TSDB has no dedicated playoff/season-type field, but TheSportsDB's API convention assigns special `intRound` values to knockout stages. The provider maps these to canonical `postseason`:

| `intRound` | Canonical | Stage |
|------------|-----------|-------|
| `125` | `postseason` | Quarter-Final (also used for NBA Conference Semi-Finals in some leagues) |
| `150` | `postseason` | Semi-Final / Conference Finals |
| `160` | `postseason` | First Round / Play-in |
| `170` | `postseason` | Playoff Semi-Final (e.g. NBA Conference Semis) |
| `180` | `postseason` | Playoff Final (e.g. NBA Conference Finals) |
| `200` | `postseason` | Final / Championship |

Verified on 2026-04-22 against NBA 2024 Playoffs, NHL 2024 Stanley Cup Final, and IPL 2024 playoffs — all use these codes. UCL knockouts, international tournaments, and other cup competitions also use them.

**Known gap:** Not every TSDB league opts into the special codes — some keep simple sequential round numbering through their finals, so their postseason can't be distinguished from the regular season. (AFL was the canonical example before it migrated to the Squiggle provider.) For those leagues `{season_type}` returns empty. Adding per-league heuristics (e.g. "round 24+ is finals") would be fragile and unmaintainable — the provider deliberately returns `None` rather than `regular` for non-postseason events so the gap is detectable.

Preseason is not detected for any TSDB league — there's no corresponding convention.

Other season-adjacent fields (`strSeason` year string, `strGroup`) don't help. Premium tier doesn't expose additional playoff signals — it only unlocks higher rate limits, livescores, highlights, and full team schedules (verified across `lookupevent.php`, `eventsseason.php`, `eventsnextleague.php`, `search_all_seasons.php`, `lookupleague.php`).

## File Locations

| File | Purpose |
|------|---------|
| `teamarr/providers/tsdb/provider.py` | TSDBProvider class |
| `teamarr/providers/tsdb/client.py` | HTTP client with preemptive rate limiting |
| `teamarr/providers/tsdb/racing.py` | Race-weekend session grouping (IMSA, WEC) |
