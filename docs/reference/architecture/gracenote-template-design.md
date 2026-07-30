---
title: Gracenote-Modeled Template Design
parent: Architecture
grand_parent: Technical Reference
nav_order: 20
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
| **Preview prose** | ESPN summary `article` (type Preview) | per-event call | ⚠️ **~T-0 to T-1 only** | broad — MLB/WNBA **and soccer** (incl. World Cup) |
| **Structured preview** | ESPN summary (odds/H2H/lastFiveGames/leaders/standings/seasonseries/predictor) | per-event call | ✅ **available days ahead** | broad — incl. soccer |
| **Event description** | TSDB `strDescriptionEN` | per-call | ⚠️ | marquee events only — **empty for the niche leagues TSDB serves** |
| **Event thumb/video** | TSDB `strThumb`/`strVideo` | per-call | ⚠️ sparse | sparse |

> **Validated live against the ESPN API on 2026-06-16** (multi-league probe). Corrections to the prior draft:
> - **Preview prose is NOT "US-pro only / soccer none."** Same-day scheduled games carry a full `article` (type Preview) for MLB, WNBA **and soccer** — the 2026 World Cup game *Senegal at France* had complete preview prose. It only populates ~T-0 to T-1, so it's blank for events several days out.
> - **Structured preview data IS available days ahead** (verified at T+4/T+5 for both MLB and the World Cup): `lastFiveGames`, `leaders`, `standings`, `seasonseries`, `headToHeadGames`, `predictor`, `injuries`, `againstTheSpread` (odds/pickcenter fill closer to game). So **templated previews are viable across the whole window**, across leagues including soccer.
> - **Recap is free/bulk, confirmed:** all 10 of the prior day's MLB finals carried recap headlines *inside the scoreboard* (no per-event call).

**Takeaways:**
- `{game_recap}` + `{game_event_note}`/`{soccer_match_note}` are **free** from the
  scoreboard Teamarr already fetches — high value, no extra calls (Tier 1).
- **Preview prose is viable for the common case** (most users generate same-day, and
  it populates ~T-0/T-1 across MLB/WNBA/soccer). It just can't fill the *far* end of a
  14-day window — which a **fallback chain** handles: recap (postgame) → preview prose
  (same-day) → templated structured preview (days ahead) → generic templated copy.
- **Structured preview is the across-window source** and the richest lever, but it costs
  **one per-event summary call** — so it needs a fetch budget (cache, and/or gate to
  within N days / followed teams / priority leagues). This is Tier 2.
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
| `{game_recap}` | ESPN scoreboard `headlines[type=Recap].shortLinkText` (clean headline; falls back to dash-stripped `.description`) | EPG-friendly postgame recap, self-contained with the result | **free/bulk**; postgame-only → fallback |
| `{game_event_note}` | ESPN scoreboard `notes[0].headline` (type `event`) | marquee/playoff designation ("NBA Finals - Game 5", "Stanley Cup Final", cups, bowls) | free/bulk; marquee-only, empty for regular season |
| `{soccer_match_note}` | ESPN scoreboard `competitions[0].altGameNote` | soccer competition + group, untouched ("FIFA World Cup, Group J") | free/bulk; soccer-only, empty otherwise |

The three free-tier vars above shipped as raw 1:1 field maps (new variable category:
`SUMMARY`; `Event` model fields of the same names). An earlier normalized
`{game_note}`/`{round}` idea was **dropped** — `altGameNote` is soccer-only and mostly
equals the league name, while the cross-sport round/stage lives in `notes[0].headline`
with per-sport shapes — so it became the two honest vars above rather than one
normalized field. `{game_recap}` prefers ESPN's `shortLinkText` (a clean, EPG-sized
headline that carries the score) over the long `.description` wire body, falling back
to the body with the AP dateline em dash stripped. Per-event `{game_preview}` (summary
`article` type Preview) and `{series_summary}` (`seasonseries[0].summary`) are the
gated Tier-2 follow-ups.

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
| **ESPN-rich** | NBA/NFL/MLB/NHL/WNBA/NCAA/MiLB/UFC/ESPN-soccer | `{gracenote_category}` title · sport-specific subtitle · `{game_event_note}`/`{soccer_match_note}` context · `{game_recap}` postgame (→ fallback) · structured pregame · article-aware copy |
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
- **subtitle:** `{away_team} vs. {home_team}` (stage prefix available via `{soccer_match_note}`)
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

## 8. `{gracenote_category}` construction

The `{gracenote_category}` value is built by a three-step cascade
(`teamarr/services/league_mappings.py::get_gracenote_category`, tests in
`tests/templates/test_gracenote_category.py`):

1. **User override** from the `league_overrides` table (editable at
   Settings → Advanced → Gracenote Category Overrides; survives re-seeds).
2. **Curated** `leagues.gracenote_category` seed value.
3. **Auto-generated fallback**, shaped by the league's `event_type`:
   - **team_vs_team** → `{display_name} {Sport}` (`NFL Football`,
     `Ontario Hockey League Hockey`) — matches captured Gracenote for US majors
     and club soccer (`Premier League Soccer`, `MLS Soccer`).
   - **event / event_card** → `display_name` alone — Gracenote titles
     racing/combat by series or promotion name (`NASCAR Craftsman Truck Series`,
     never "X Racing").

Seed curation choices:

- **Racing**: the NASCAR Cup/Xfinity/Truck, IMSA, and WEC curations are **NULL** —
  the event-aware fallback serves the series name, so sponsor renames
  (e.g. Xfinity → O'Reilly) can't drift a duplicated string. Kept curated:
  `Formula 1 Racing`, `IndyCar Racing`, `MotoGP Racing`, and `Tennis` for ATP/WTA.
- **International tournaments** (fifa.world, fifa.wwc, uefa.euro,
  conmebol.america, concacaf.gold, concacaf.nations.league) are curated
  **without** the " Soccer" suffix (`FIFA World Cup`), matching the captured
  branded shape. Club competitions keep it (`FA Cup Soccer`,
  `UEFA Champions League Soccer`).
- **Year-stamping is template composition, not dynamic.** Real Gracenote brands
  tournaments with a year (`FIFA World Cup 2026`); a static year-stamped seed
  would go stale annually, so templates compose `{gracenote_category} {year}`
  where wanted.
