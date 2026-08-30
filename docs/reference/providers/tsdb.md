---
title: TSDB
parent: Providers
grand_parent: Technical Reference
nav_order: 7
---

# TheSportsDB Provider

TheSportsDB (TSDB) is a community-driven sports data API. Teamarr uses it as a fallback provider (priority 100) for leagues not covered by ESPN, including cricket, boxing, Scandinavian leagues, Brazilian state championships, and motorsports (IMSA, WEC). It serves 49 leagues in total — **all of them require a TheSportsDB premium API key**.

## API Details

| | |
|---|---|
| **Base URL** | `https://www.thesportsdb.com/api/v1/json/{api_key}/{endpoint}` |
| **Auth** | Premium API key in URL path (**required**) |
| **Priority** | 100 (last resort) |
| **Rate Limit** | 100 req/min (premium) |

## Premium Key Required

**As of v2.15, TheSportsDB support is premium-key only.** TSDB tightened its free tier during 2026 (measured 2026-08-04: a rolling 1-event next/past window, a premium-gated `eventsday` league filter, a 15-event `eventsseason` cap) to the point where a keyless install got day-of event channels at best and zero team-channel support. The free tier — and the free test key `123` — are no longer used.

Without a key configured, the TSDB provider is **not constructed at all**: no requests are made, and every TSDB league is unavailable (the league picker shows a crown on TSDB leagues and warns when one is selected keyless; a startup log lists subscribed TSDB leagues that will produce no events). Add a key and it takes effect immediately — no restart.

With a key, coverage is the full premium capability set: 100 req/min, 20-event next/past windows, league-filtered `eventsday` (which is what makes team channels work), and 3,000-event season fetches. A premium key costs ~$9/month.

### League migration notes

AFL was formerly a TSDB league but is now served by the free [Squiggle](squiggle) provider. NRL and Super Rugby Pacific also migrated from TSDB to ESPN. Super League stays on TSDB: ESPN's `rugby-league` tree carries only the NRL.

The `tsdb_tier` column that used to classify leagues as `free`/`premium` is retired (values cleared at schema v92; the column is dropped one release later).

## Configuration

Add your premium key in **Settings > General > TheSportsDB API Key**. The key takes effect immediately (no restart required). Keyless, the league picker shows a crown icon on every TSDB league and warns if you select one.

Get a key at [thesportsdb.com/pricing](https://www.thesportsdb.com/pricing).

## Supported Leagues

TSDB serves **49 leagues** in total. The table below is representative, not exhaustive — it omits the 23 Brazilian state championships, `fiba`/`fibaw` (FIBA Basketball World Cup M/W), and `uru.2` (Uruguayan Segunda División), among others. See [Supported Leagues](../supported-leagues) for the full list.

| League | Code | TSDB ID | Sport |
|--------|------|---------|-------|------|
| Unrivaled | `unrivaled` | 5622 | Basketball |
| Norwegian Fjordkraft-ligaen | `norwegian-hockey` | 4926 | Hockey |
| Boxing | `boxing` | 4445 | Boxing |
| Major League Cricket | `mlc` | 5401 | Cricket |
| WPBL | `wpbl` | 5929 | Baseball |
| Swedish Hockey League | `shl` | 4419 | Hockey |
| Indian Premier League | `ipl` | 4460 | Cricket |
| Big Bash League | `bbl` | 4461 | Cricket |
| South Africa Twenty20 (SA20) | `sa20` | 5532 | Cricket |
| Svenska Cupen | `svenska-cupen` | 4756 | Soccer |
| Canadian Premier League | `can.1` | 4820 | Soccer |
| Swedish Superettan | `swe.2` | 4403 | Soccer |
| Swedish Division 1 North | `swe.3.n` | 4674 | Soccer |
| Swedish Division 1 South | `swe.3.s` | 4845 | Soccer |
| Icelandic Úrvalsdeild karla | `ice.1` | 4642 | Soccer |
| Icelandic 1. deild karla | `ice.2` | 4906 | Soccer |
| Venezuelan Segunda División | `ven.2` | 5659 | Soccer |
| Gambia GFA League | `gam.1` | 5238 | Soccer |
| Aruban Division di Honor | `arb.1` | 5230 | Soccer |
| Northern Irish Premiership | `nifl.1` | 4659 | Soccer |
| IMSA SportsCar Championship | `imsa` | 4488 | Motor Racing |
| FIA World Endurance Championship | `wec` | 4413 | Motor Racing |
| English Rugby League Super League | `super-league` | 4415 | Rugby |

## Event Resolution

TSDB uses a three-step fallback chain when fetching events:

1. **`eventsday.php`** — date-specific lookup (primary, works for most leagues)
2. **`eventsnextleague.php`** — upcoming events filtered by date (fallback; kept after the premium-only change because `eventsday` queries by league *name* while this queries by *ID*, guarding against provider-side name drift)
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
