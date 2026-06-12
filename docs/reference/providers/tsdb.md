---
title: TSDB
parent: Providers
grand_parent: Technical Reference
nav_order: 5
docs_version: "2.3.1"
---

# TheSportsDB Provider

TheSportsDB (TSDB) is a community-driven sports data API. Teamarr uses it as a fallback provider (priority 100) for leagues not covered by ESPN, including Australian sports, cricket, boxing, CFL, Scandinavian leagues, and motorsports (IMSA, WEC).

## API Details

| | |
|---|---|
| **Base URL** | `https://www.thesportsdb.com/api/v1/json/{api_key}/{endpoint}` |
| **Auth** | API key in URL path (`123` for free tier) |
| **Priority** | 100 (last resort) |
| **Rate Limit** | 30 req/min free, 100 req/min premium |

## API Tiers

| | Free | Premium |
|---|---|---|
| **API Key** | `123` (default) | Your own key (6+ digits) |
| **Rate Limit** | 30 req/min | 100 req/min |
| **Events per Query** | 5 per day per league | Full coverage |
| **Team Search** | 10 teams | 3,000 teams |
| **Cost** | Free | ~$9/month |

### Free Tier Leagues

These leagues have low enough event volume to work within free tier limits:

- CFL, Unrivaled, Norwegian Hockey, Boxing
- IMSA (one event per round, well under the 15-event/season cap)

### Premium Tier Leagues

These leagues have high event volume or unreliable free-tier data and require a premium key for full coverage:

- AFL (Australian football)
- IPL, BBL, SA20 (cricket)
- Svenska Cupen and other regional soccer leagues (Canadian Premier League, Swedish Superettan / Division 1, Icelandic, Venezuelan, Gambian, Aruban, Northern Irish)
- WEC (62 events/season across 8 rounds + Prologue — free tier's 15-event/season cap on `eventsseason.php` only returns the first 2-3 rounds)

The `tsdb_tier` column in `schema.sql` classifies each league as `free` or `premium`.

## Configuration

Add your premium key in **Settings > System > TheSportsDB API Key**. The key takes effect immediately (no restart required). The league picker shows a crown icon on premium-tier leagues and warns if you select one without a key configured.

Get a key at [thesportsdb.com/pricing](https://www.thesportsdb.com/pricing).

## Supported Leagues

| League | Code | TSDB ID | Sport | Tier |
|--------|------|---------|-------|------|
| Canadian Football League | `cfl` | 4405 | Football | Free |
| Unrivaled | `unrivaled` | 5622 | Basketball | Free |
| Norwegian Fjordkraft-ligaen | `norwegian-hockey` | 4926 | Hockey | Free |
| Boxing | `boxing` | 4445 | Boxing | Free |
| Australian Football League | `afl` | 4456 | Australian Football | Premium |
| Indian Premier League | `ipl` | 4460 | Cricket | Premium |
| Big Bash League | `bbl` | 4461 | Cricket | Premium |
| SA20 | `sa20` | 5532 | Cricket | Premium |
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
| IMSA SportsCar Championship | `imsa` | 4488 | Motor Racing | Free |
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

Because `eventsseason.php` is capped at 15 events/season on the free tier,
WEC (62 events/season) only returns its first 2-3 rounds without a premium
key. IMSA (12 events/season, one per round) fits comfortably under the cap
and works fully on free tier.

## Rate Limiting

Teamarr enforces rate limits **preemptively** using a sliding window limiter — it tracks request timestamps and waits before approaching the limit, rather than waiting for 429 responses.

If the API does return HTTP 429, Teamarr retries with exponential backoff (5s → 10s → 20s → 40s → 80s).

Rate limit statistics (total requests, preemptive waits, reactive waits) are tracked and available for UI feedback.

## TSDB League Configuration

Each TSDB league requires **two** identifiers in `schema.sql`:

| Column | Used By | Example |
|--------|---------|---------|
| `provider_league_id` | `eventsnextleague.php`, `lookupleague.php` | `5159` |
| `provider_league_name` | `eventsday.php`, `search_all_teams.php` | `Canadian OHL` |

These must match TSDB's internal data exactly. Use `search_all_leagues.php` to discover correct values.

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

**Known gap:** Not every TSDB league opts into the special codes. AFL keeps simple round numbering through finals (AFL Grand Final → `intRound=19`), so we can't distinguish its postseason from regular season. For those leagues `{season_type}` returns empty. Adding per-league heuristics (e.g. "AFL round 24+ is finals") would be fragile and unmaintainable — the provider deliberately returns `None` rather than `regular` for non-postseason events so the gap is detectable.

Preseason is not detected for any TSDB league — there's no corresponding convention.

Other season-adjacent fields (`strSeason` year string, `strGroup`) don't help. Premium tier doesn't expose additional playoff signals — it only unlocks higher rate limits, livescores, highlights, and full team schedules (verified across `lookupevent.php`, `eventsseason.php`, `eventsnextleague.php`, `search_all_seasons.php`, `lookupleague.php`).

## File Locations

| File | Purpose |
|------|---------|
| `teamarr/providers/tsdb/provider.py` | TSDBProvider class |
| `teamarr/providers/tsdb/client.py` | HTTP client with preemptive rate limiting |

For detailed API endpoint documentation, see the [TSDB API Reference](tsdb-api).
