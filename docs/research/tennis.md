---
title: Tennis
parent: Research Notes
nav_order: 3
docs_version: "2.7.0"
---

# Tennis Support — Research (epic `teamarrv2-mf7`)

**Date:** 2026-07-05 (live-validated during Wimbledon 2026, middle weekend)
**Verdict: GO.** ESPN provides matchups, exact court assignments, start times, rounds, and status per match — and real IPTV stream names map directly onto all of it.

## ESPN Tennis API (validated live)

**Endpoint:** `https://site.api.espn.com/apis/site/v2/sports/tennis/{atp|wta}/scoreboard`

**Shape:** 1 event = 1 **tournament** (not 1 match). Matches live under `groupings[]`:

```
event {
  id: "188-2026", name: "Wimbledon", shortName: "Wimbledon"
  date: "2026-06-22T04:00Z", endDate: "2026-07-13T03:59Z"   ← tournament window
  venue: { displayName: "London, Great Britain" }
  groupings: [
    { grouping: { displayName: "Men's Singles", slug: "mens-singles" },
      competitions: [ ...239 matches... ] },
    ... Women's Singles (239), Men's Doubles (63), Women's Doubles (63), Mixed Doubles (31)
  ]
}
```

**Per match (`competition`):** everything needed to map IPTV streams:

| Field | Example | Use |
|-------|---------|-----|
| `id` | `177486` | stable event id (globally unique across groupings) |
| `date`/`startDate` | `2026-07-06T12:00Z` | channel window + `@ time` disambiguation |
| `competitors[].athlete.displayName` | `Alex de Minaur` | name matching |
| `competitors[].athlete.shortName` | `A. de Minaur` | abbrev matching + EPG |
| `competitors[].homeAway` | home/away | maps to home/away team slots |
| `competitors[].roster.displayName` | `Hugo Nys / Edouard Roger-Vasselin` | doubles pairs (athlete empty, roster set) |
| `venue.court` | `Centre Court`, `No. 1 Court`, `Court 18` | **court-feed mapping** (confirmed) |
| `round.displayName` | `Round 4`, `Qualifying 1st Round` | round feeds + EPG subtitle |
| `type.text` / `type.slug` | `Men's Singles` / `mens-singles` | grouping label for EPG |
| `status.type.name` | STATUS_SCHEDULED / STATUS_FINAL (+ live states) | lifecycle |
| `notes[].text` | `Piros (HUN) bt Ivanov (BUL) 6-2 6-2` | result summaries (rich vars) |
| `broadcasts[].names` | `["ESPN"]`, `["ESPN Unlmtd"]`, `["ESPN+"]` | broadcast vars |
| `format.regulation.periods` | 5 | best-of sets |
| `wasSuspended` | bool | rain-delay handling |

**Wimbledon 2026 volume:** 655 matches total (incl. qualifying at Roehampton). ~55 scheduled at any mid-tournament moment.

### Gotchas (validated)

1. **Grand slams are DUPLICATED across `atp` and `wta` endpoints** — identical event `188-2026` with ALL groupings (incl. Women's) appears in both. Provider must dedupe or gender-filter: e.g. league `atp` keeps Men's Singles/Doubles, `wta` keeps Women's Singles/Doubles; Mixed Doubles assigned to exactly one (suggest atp) — OR dedupe by `tournamentId` when both leagues are subscribed.
2. **`?dates=YYYYMMDD` does NOT filter matches** — it returns whole tournaments overlapping the window (727 matches for one day query). Per-day filtering must be client-side on `competition.date`.
3. **`athlete.id` is null** in scoreboard competitor payloads — matching must be name-based (no stable athlete-id cache). Fine: names are the join key to streams anyway.
4. **Qualifying courts** are named "Court N Roehampton" — distinct venue from main draw; early-tournament court feeds unlikely to reference them; harmless.
5. `venue.court` is empty (`""`) on 36 of 655 matches (mostly walkovers/unassigned) — court mapping must tolerate missing court.
6. WTA endpoint also carries non-slam WTA tournaments simultaneously (Grand Est Open, Hall of Fame Open) — one league fetch = all concurrent tournaments, each its own event with groupings.

## Real IPTV stream shapes (real-world Dispatcharr deployment, 1,525 "wimbledon" streams live)

Distribution from a 100-stream sample:

| Pattern | Share | Example | Mapping strategy |
|---------|-------|---------|------------------|
| **Match stream** | ~25% | `Wimbledon: Zheng vs Norrie @ Jun 29 12:30 PM :Tennis 13 [1080p]` | last-name vs last-name + date/time → exact match to a competition |
| **Court day-feed** | ~43% | `Wimbledon Day #6 No 1 Court ft Rybakina Zverev @ Jul 4 8:00 AM` | court name → all matches on `venue.court` that day (racing-session-style EPG expansion); `ft <names>` corroborates |
| **Round/day feed** | ~6% | `Wimbledon Second Round @ Jul 2 5:00 AM` | round label → day's matches for that round (catch-all) |
| **Non-match content** | ~26% | `Wimbledon Highlight Show`, `Press Conferences`, `Courtside Day 1` | leave unmatched (highlight shows are ESPN+ linear reruns) |

Key observations:
- Match streams use **surnames only** (`Zheng vs Norrie`), including multi-word surnames (`Ugo Carabelli vs Merida`, `Davidovich Fokina vs Cerundolo`, `Sorribes Tormo vs Jimenez Kasintseva`, `Bautista Agut vs Fonseca`). Matching must compare against the surname portion of `displayName` — token-suffix match, not full-name equality.
- Streams carry `@ <date> <time>` tails (the existing stream date-parsing handles this shape; #266 just hardened it).
- Court feeds name courts as `No 1 Court` / `Court 18` / `Centre Court` — near-exact match to ESPN `venue.court` values (`No. 1 Court` vs `No 1 Court` — needs punctuation-insensitive compare).
- Provider group observed: single "Tennis"-flavored M3U group carrying all of it.

## Fit to Teamarr's model (decision)

Tennis = individual-athlete, tournament-based → closest existing vertical is **racing** (tournament event + session expansion) but match streams behave like **TEAM_VS_TEAM** (two named sides). Plan:

- **1 ESPN competition = 1 Teamarr Event** — home/away = the two players (surname-keyed), event window from `date`, status from match status. Tournament is context, not the Event.
- **Sport `tennis`, leagues `atp` + `wta`** (schema rows; ESPN provider, priority 0). Gender-filter groupings per league to solve the grand-slam duplication.
- **Match streams** → classify as tennis matchup (`X vs Y`), match on surnames + date/time — reuses the TEAM_VS_TEAM-style pipeline with athlete names instead of team_cache teams (combat #239 precedent: fuzzy name matching without a team cache).
- **Court feeds (phase 2)** → map court name → the day's matches on that court; EPG = sequence of that court's matches (racing per-session EPG precedent).
- **Round feeds (phase 2/3)** → round label → day's matches in that round.
- **Doubles**: `roster.displayName` ("A / B") — phase 1 supports singles + doubles via surname extraction from either athlete or roster.

## Open questions (decided during implementation)

- Mixed Doubles league assignment (atp vs wta vs both-deduped).
- Whether tennis needs its own classification category (like RACING) or extends TEAM_VS_TEAM with an athlete-name path — decide after reading matcher internals.
- Channel volume control: a slam has ~40-60 matches/day; users will want the singles-only / show-courts-only knobs eventually. Phase 1: match streams only (channel count = stream count, self-limiting).

## Phase-1 implementation + live validation (2026-07-05, branch `feature/tennis`)

Shipped: `espn/tennis.py` (TennisParserMixin, per-match Events, draw-type
split), `StreamCategory.TENNIS_MATCH` + `is_tennis()` + sport-aware
`is_racing()` guard (new `event_league_sport` discriminator threaded from
matcher), `tennis_matcher.py` (surname-subset + fuzzy scoring, both-sides
requirement, time tie-break, widened-date fallback with uniqueness guard),
atp/wta schema rows, 4 template vars (`{tournament_name}`, `{tennis_round}`,
`{tennis_court}`, `{tennis_draw}` → 236 vars/20 cats), Tennis removed from
`UNSUPPORTED_SPORTS`, cache round-trips (provider_cache + team_matcher
reconstruct). 22 new tests; 1286 pass.

**Live corpus validation** (1,204 unique real stream names from a real-world
Dispatcharr deployment, real classify→TennisMatcher.match() path against live ESPN):
- Classification: 1204/1204 TENNIS_MATCH (683 player-pair, 521 court/round feeds)
- Match rate on player-pair streams: **613/683 = 89.8%** (610 direct, 3 fuzzy), 0 ambiguous ties
- Remaining misses: juniors/wheelchair/invitational draws ESPN doesn't carry
  (~41) + "Highlights" replay streams (correct to leave unmatched)
- The widened-date fallback recovered ~140 replay/delayed streams stamped with
  airing date instead of match date (safe: a pair meets once per tournament)

## Related

- Epic: `teamarrv2-mf7`. Racing precedent: PR #242 + #263 take-and-fix. Combat fuzzy matching: PR #239. Golf research (same tournament-shape problem): #82.
