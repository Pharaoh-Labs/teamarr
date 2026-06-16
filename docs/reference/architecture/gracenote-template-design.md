---
title: Gracenote-Modeled Template Design
parent: Architecture
nav_order: 20
docs_version: "2.7.0"
---

# Gracenote-Modeled Best-in-Class Templates — Design & Research

Reference + design spec for the curated default templates (epic `teamarrv2-tvnk`).
Captures everything learned modeling Teamarr EPG output on authoritative Gracenote
data across sports, the available data sources, the confirmed gaps, and the
resulting template/scoping/fallback design.

> **Methodology:** Gracenote is the authoritative *target* we model the *shape* of.
> ESPN + TSDB are our *sources*. We **model on** Gracenote conventions; we do **not**
> redistribute Gracenote's proprietary copy (see "Why not pipe Gracenote directly").

---

## 1. Gracenote EPG conventions (evidence-based, 2026-06-14)

Pulled live from `tvlistings.gracenote.com/api/grid` (OTA lineup `USA-OTA<zip>-DEFAULT`,
`headendId=lineupId`, `device=-`, browser headers). Real samples:

| Element | Convention | Real example |
|---------|-----------|--------------|
| **title** | `"{League} {Sport}"` (= our `{gracenote_category}`) | "MLB Baseball", "WNBA Basketball", "FIFA World Cup 2026", "PGA Tour Golf" |
| **sub-title — team sports** | `"{Away City+Name} at {Home City+Name}"` (separator **at**) | "Chicago Cubs at San Francisco Giants"; "Carolina Hurricanes at Vegas Golden Knights" |
| **sub-title — soccer** | `"{Group}: {A} vs. {B}"` (**vs.** w/ period; group prefix) | "Group E: Germany vs. Curaçao" |
| **sub-title — combat** | `"{Fighter1} vs. {Fighter2}"` (+ card segment) | ESPN event "UFC Freedom 250: Topuria vs. Gaethje" |
| **sub-title — golf/tennis** | tournament + round | "RBC Canadian Open, Final Round" |
| **desc** | natural sentence, **venue**, **article-aware** | clubs: "**The** Washington Mystics play **the** New York Liberty in Brooklyn…"; nationals: "Germany take on Curaçao… at Houston Stadium" (no article) |
| **flags** | Live / New | `flag: ["Live","New"]` |
| **category** | sports marker | `filter-sports` |

**Definite-article rule (confirmed both ways in real data):**
- **Club / city teams** → "**The** Detroit Pistons"
- **National teams** → "Netherlands", "Japan" (no article)

**Critical timing fact:** Gracenote's *rich* descriptions only populate **near air-time**.
Days ahead they are generic placeholders ("Group C.", "From Shinnecock Hills…").
The structured **subtitle** ("Group C: Scotland vs. Morocco") *is* present days ahead.

---

## 2. Data source matrix (ESPN + TSDB)

| Data | Source | Cost | Days-ahead viable? | Coverage |
|------|--------|------|--------------------|----------|
| **Recap copy** | ESPN scoreboard `headlines[0].description` | **free** (bulk) | ✅ fills after final, on regen | all ESPN sports |
| **Round/group** | ESPN scoreboard `competitions[0].altGameNote` | **free** (bulk) | ✅ all states | tournaments/playoffs |
| **Preview prose** | ESPN summary `article` (type Preview) | per-event call | ❌ **same-day only** | US-pro only (MLB/NHL); soccer **none** |
| **Structured preview** | ESPN summary (odds/H2H/lastFiveGames/standings/probables) | per-event call | ✅ | ESPN sports |
| **Event description** | TSDB `strDescriptionEN` | per-call | ⚠️ | marquee events only — **empty for the niche leagues TSDB serves** |
| **Event thumb/video** | TSDB `strThumb`/`strVideo` | per-call | ⚠️ sparse | sparse |

**Takeaways:**
- `{game_recap}` + `{game_note}`/`{round}` are **free** from the scoreboard Teamarr
  already fetches — high value, no extra calls.
- ESPN **preview prose is not viable** (same-day + US-pro only → blank across the
  14-day EPG window). Pregame previews must be **templated from structured data**.
- TSDB does **not** provide reliable copy for its own coverage area.

---

## 3. Why not pipe Gracenote descriptions directly

The idea: scrape the public Gracenote grid for upcoming events' descriptions. Blocked by:
1. **Timing (decisive):** rich descriptions don't exist days ahead — you'd get
   "Group C." across ~the whole EPG window.
2. **Legal:** Gracenote/Nielsen data is proprietary + licensed. Modeling on it is fine;
   **redistributing their editorial copy into every user's EPG is a copyright/ToS risk.**
3. **Matching:** the grid is channel×time, not event-keyed — fuzzy, error-prone.
4. **Coverage:** US lineups only (OTA + market-specific cable/RSN); international/niche absent.
5. **Fragility:** undocumented endpoint, rate limits, can break.

**Use Gracenote for modeling + hardening only** (diff our output vs theirs on demand).

---

## 4. Confirmed variable gaps → new variables

| New var | Source | Purpose | Notes |
|---------|--------|---------|-------|
| `{home_team_the}` / `{away_team_the}` | article heuristic + national-team detection | "The Lions" vs "Netherlands" | needs national-team signal (soccer international leagues / provider hint); `Team` model has no flag today |
| `{game_recap}` | ESPN `headlines[0].description` | authentic postgame recap | **free/bulk**; strip leading AP `"— "`; postgame-only → fallback |
| `{game_note}` (+ `{round}`) | ESPN `competitions[0].altGameNote` | tournament/playoff context | free/bulk; `{round}` strips league prefix → "Group E" |

`Event` model additions: `alt_game_note`, `game_recap` (or parse at generation).
All new vars require the CLAUDE.md docs-table updates (variables count, etc.).

**`gracenote_category` gaps** (majors match perfectly): curate **UFC** (`"Ultimate
Fighting Championship Mma"` → "UFC ...") and the **56 import-enabled fallback leagues**
that auto-gen awkwardly ("Canadian Hockey League Hockey", "…Ice Hockey - Olympics Hockey").

---

## 5. Design principles (maintainer-locked)

1. **Simplify to Gracenote *style*, not *substance*.** Match grammar/separators/article/
   venue — do **not** chase per-game editorial copy. **Zero copy-maintenance burden.**
2. **Variety via randomization.** Ship **multiple priority-100 description variants**;
   the condition selector already "randomly selects if multiple" (`conditions.py`). No new
   feature needed. Keep shipped pools **modest** (don't ship the big team pools).
3. **Graceful fallback.** Recap/round/preview empty → collapse to generic templated copy.
   The resolver already drops empty `{var}` phrases.
4. **Article-awareness** where copy names teams.
5. **Provider-aware scoping** (see §6).

---

## 6. Template scoping model

Two tiers by **provider coverage** (rich copy vars are ESPN-only):

| Tier | Leagues | Template content |
|------|---------|------------------|
| **ESPN-rich** | NBA/NFL/MLB/NHL/WNBA/NCAA/MiLB/UFC/ESPN-soccer | `{gracenote_category}` title · sport-specific subtitle · `{round}` context · `{game_recap}` postgame (→ fallback) · structured pregame · article-aware copy |
| **Lean** | TSDB/niche (Swedish, Canadian Premier, Scandinavian, uru.2, etc.) | matchup + venue + generic randomized copy — **no ESPN-only vars** |

Templates ship **unassigned**; each carries a **recommended scoping** (provider + sport).
Recommended scoping must factor **provider**, not just sport.

---

## 7. Per-sport-family template specs

All titles = `{gracenote_category}`. Art = **relative paths** (epic z02s) + the user's
game-thumbs base URL. Flags new+live. Descriptions = multiple priority-100 variants
(randomized) with article-aware names, collapsing to generic when data absent.

### Team sports (MLB / NBA / NHL / NFL / WNBA / college)
- **subtitle:** `{away_team} at {home_team}`
- **pregame desc (randomized):** "{away_team_the} visit {venue_city} to take on {home_team_the}." / "{home_team_the} host {away_team_the} at {venue}."
- **postgame desc:** `{game_recap}` → fallback "{team_name} {result_text} {opponent} {final_score}."

### Soccer — international (national teams)
- **subtitle:** `{round}: {away_team} vs. {home_team}` → collapses to `{away_team} vs. {home_team}`
- **desc:** **article-OFF** ("Germany take on Curaçao…")

### Soccer — club
- **subtitle:** `{away_team} vs. {home_team}`
- **desc:** **article-ON** ("The Gunners host…")

### Combat (UFC / boxing)
- **subtitle:** main-event fighters + `{card_segment_display}` (we have `segment_times`/`main_card_start`)
- title `gracenote_category` (after UFC curation)

### Golf / tennis (tournament)
- **subtitle:** tournament + round
- no home/away

### Lean / TSDB niche
- **subtitle:** `{away_team} vs/at {home_team}`; **desc:** generic matchup + venue only

---

## 8. Shipping / seeding

- Seed **unassigned** on fresh install (guard: no existing templates).
- Art = **relative paths** (z02s); user sets the game-thumbs base URL once.
- Replace the 2 generic seeds (Default Team/Event supersede them) — *maintainer decision pending*.
- Recommended scoping surfaced via docs + (optionally) template name/description.

---

## 9. Hardening (test method)

Re-pull the live Gracenote grid (§1 recipe) and **diff** each rendered template's
output against the actual Gracenote title/subtitle/desc shape for that sport —
checking separators, article usage, venue, round context. Add a rendering test per
template (against realistic sample data). Edge cases: national teams, no-abbrev leagues,
combat segments, doubleheaders, postponed, missing recap/round.

---

## Appendix — reusable research commands

```bash
# Gracenote grid (modeling/hardening only — not for redistribution)
curl -s -H "User-Agent: Mozilla/5.0" -H "Referer: https://tvlistings.gracenote.com/" \
  -H "X-Requested-With: XMLHttpRequest" \
  "https://tvlistings.gracenote.com/api/grid?lineupId=USA-OTA10001-DEFAULT&headendId=lineupId&device=-&country=USA&postalCode=10001&isOverride=true&timespan=4&time=$(date -u +%s)&pref=16,128&userId=-&aid=orbebb&languagecode=en-us"

# ESPN recap (free, bulk) — per sport/league
curl -s "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard" \
  | jq -r '.events[] | select(.competitions[0].headlines[0].description) | "\(.shortName): \(.competitions[0].headlines[0].description)"'

# ESPN round/group (free, bulk)
curl -s "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard" \
  | jq -r '.events[] | "\(.shortName) | \(.competitions[0].altGameNote // "—")"'
```
