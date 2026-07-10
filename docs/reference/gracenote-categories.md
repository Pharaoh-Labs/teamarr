---
title: Gracenote EPG Reference
parent: Technical Reference
nav_order: 6
docs_version: "2.7.0"
---

# Gracenote EPG Reference

Authoritative field-shapes for the "best-in-class default templates" epic (`teamarrv2-tvnk`).
Captured directly from Gracenote's public tvlistings API. The earlier "ESPN not capturable"
blocker was a wrong-lineup artifact: OTA/DirecTV-OTA lineups don't carry ESPN. A **cable**
lineup does. See also [Gracenote-Modeled Template Design](architecture/gracenote-template-design)
for the resulting template design.

## Access recipe (reusable)

**Provider/lineup discovery** for a ZIP:
```
GET https://tvlistings.gracenote.com/gapzap_webapi/api/Providers/getPostalCodeProviders/USA/<zip>/gapzap/en-us
Headers: User-Agent: <browser UA>, Referer: https://tvlistings.gracenote.com/
```
Returns OTA / SATELLITE / **CABLE** lineups. Cable carries ESPN/ESPN2/ESPNU/FS1/FS2/SEC/ACC/TNT/TBS/MLBN.

**Grid (programs)** for a lineup:
```
GET https://tvlistings.gracenote.com/api/grid
  ?lineupId=<id>&headendId=<id>&country=USA&postalCode=<zip>
  &device=-&aid=orbebb&time=<epoch>&timespan=<hours>
Headers: User-Agent + Referer + X-Requested-With: XMLHttpRequest
```
Reference lineup used (NYC 10001): `USA-NY31519-DEFAULT` (Charter Spectrum, 275 channels w/ ESPN).
OTA for comparison: `USA-lineupId-DEFAULT` (164 channels, no ESPN).

JSON shape: `channels[].events[]` → `{startTime,endTime,filter,flag,tags,seriesId,program}`;
`program = {title, episodeTitle, shortDesc, season, episode, seriesId, isGeneric}`.
Sports events carry `filter: ["filter-sports"]` and usually `flag: ["Live","New"]`.

## Field-shape conventions (the model to template toward)

Mapping to Teamarr's 3 shapes: **team** = TEAM_VS_TEAM, **combat** = EVENT_CARD, **racing** = RACING_EVENT.

### TEAM shape — `title` = league/series, `episodeTitle` = matchup, `shortDesc` = article-aware prose
| Sport | title | episodeTitle (sub) | shortDesc convention |
|-------|-------|--------------------|----------------------|
| MLB | `MLB Baseball` | `Boston Red Sox at Seattle Mariners` (City+Name, **"at"**) | "The Boston Red Sox and the Seattle Mariners begin their three-game series at T-Mobile Park…" |
| MLB regional | `MLB Baseball` | `Regional Coverage` | "Brewers at Braves or Nationals at Rays (subject to blackout…)" |
| WNBA | `WNBA Basketball` | `Washington Mystics at New York Liberty` | club = **article**: "**The** New York Liberty host the Washington Mystics at Barclays Center…" |
| NBA/NFL/NHL | `NBA Basketball` / `NFL Football` / `NHL Hockey` | same City+Name **at** pattern | host/visit verbs, venue named |
| Soccer (club/intl) | `FIFA World Cup 2026` (= series) | `Group C: Scotland vs. Morocco` (**group prefix + "vs."**) | national teams = **NO article**: "Scotland meets Morocco in a Group C match…" |
| College basketball | `College Basketball` | `Texas A&M at Arkansas` | rankings + records: "No. 20 Arkansas (20-7) hosts Texas A&M (19-8) at Bud Walton Arena…" |
| College baseball | `College Baseball` | `NCAA Tournament: East Carolina vs. North Carolina` | round/region: "Chapel Hill Regional, Game 4." |
| CFB playoff | `CFP Quarterfinal at the Goodyear Cotton Bowl Classic` (bowl name in title) | `Miami vs. Ohio State` | "The No. 10 Miami Hurricanes face the No. 2 Ohio State Buckeyes at AT&T Stadium…" |
| Cricket | `Major League Cricket` | `Seattle Orcas vs. Washington Freedom` | "From Grand Prairie Stadium…" |

Key conventions:
- **"at" for US team sports** (visitor at home); **"vs." for soccer/college tournament/neutral-site**.
- **Article-awareness**: club teams take "The"; national teams omit it. (Teamarr's Team model
  lacks this today → drives tvnk.7 new vars.)
- Spanish duplicates exist: `Copa Mundial de la FIFA 2026` / `Escocia vs. Marruecos`.

### COMBAT shape — `title` carries event + headline, `episodeTitle` often null
| Example | title | sub | shortDesc |
|---------|-------|-----|-----------|
| MMA (UFC-shape) | `Legacy Fighting Alliance 235: Stewart vs. Havener` | `null` | "Andrew Stewart (6-1) vs. Zayne Havener (5-2). Plus, co-main event: Jake Woodley (7-1) vs. David Wright (6-2). From Freedom Hall…" |

- Pattern: `<Promotion> <Number>: <A> vs. <B>` in **title** (not sub). UFC follows identically
  (`UFC 318: …`, `UFC Fight Night: …`). Fighters + **records** listed in desc; co-main noted; venue "From …".
- (No live UFC card aired during the 2026-06-19/20 capture window — pull one when scheduled to confirm.)

### RACING shape — `title` = series, `episodeTitle` = race name (+ session)
| Example | title | sub |
|---------|-------|-----|
| NASCAR | `NASCAR Craftsman Truck Series` | `Navy 250` |
| IndyCar | `IndyCar Racing` | `XPEL Grand Prix at Road America, Practice 1` |

- Race/event name in sub, optional **`, <Session>`** suffix (Practice/Qualifying/Final).
- Golf uses the same pattern: `2026 U.S. Open Golf Championship` / `Second Round`;
  `LPGA Tour Golf` / `Meijer LPGA Classic, Second Round`.

## Implications for the epic
- **tvnk.5 ESPN gap: RESOLVED** — cable lineup recipe captures all ESPN-carried sports.
- **Third-party capture probe: DROPPED** — was a proxy for "hard-to-get Gracenote"; direct access makes it redundant.
- **tvnk.6 (gap analysis)** can proceed against this reference.
- **tvnk.7** confirmed needs: article-aware team naming, national-team distinction,
  "at" vs "vs." selection by sport/context, fighter-record vars for combat, race-session var.

## Channel name (distinct from EPG — ruthlessly concise)

Channel name is NOT an EPG field; it's the cramped grid column in Dispatcharr. EPG = rich;
channel name = short, scannable, sortable. Long names are a real UX pain. Goal: league prefix
for grouping + most-abbreviated unambiguous matchup. Reuse the EPG at/vs rule so both surfaces agree.

**Pattern:** `{LEAGUE_SHORT} | {abbreviated matchup}`

| Shape | Example | Rule |
|-------|---------|------|
| Team (US) | `NBA \| DET @ BOS` | `AWAY @ HOME`, team abbrevs, `@` = directional (matches EPG "at") |
| Team (college) | `NCAAB \| MIZ @ ARK` | same |
| Soccer (club) | `EPL \| ARS v CHE` | `v` (matches EPG "vs."), 3-letter club codes |
| Soccer (national) | `WC \| SCO v MAR` | national-team abbrevs |
| Combat | `UFC 318 \| Topuria v Oliveira` | card NUMBER + main-event LAST NAMES (no abbrevs exist); drop number if long |
| Racing | `NASCAR \| Navy 250` · `F1 \| Canadian GP` | series + race name, NO matchup |
| Golf | `PGA \| U.S. Open` | tournament; round (`R2`) optional, usually omit |

Rules: (1) league prefix via the **`{league_abbrev}`** variable (PR #252 — `construct_league_abbrev`
in templates/variables/identity.py): curated `league_alias` → ultra-short all-caps, falls back to
abbreviating the raw league_code, so it works for ANY league incl. obscure/custom. NBA→NBA, World
Cup→WC, F1→F1, Premier League→PL (UCL when alias set). This IS the "ultra-short league indicator";
the guaranteed-short fallback gap is already solved. (2) `|` separator; (3) `@` for US team sports /
`v` for soccer/neutral/combat — one rule shared with EPG; (4) abbrevs where they exist, last names
for combat, event-name-only for racing/golf; (5) target ≤~20 chars for the matchup portion; (6) keep
base short so feed-separation auto-suffix `(Home)/(Away)` still fits.

Buildability: team-sport form works TODAY — `{league_abbrev} | {away_abbrev} @ {home_abbrev}`
(all three vars exist; abbrev columns on managed_channels). Remaining new needs overlap tvnk.7:
at/vs selector (shared w/ EPG), combat last-name+card-number vars, racing/golf event-name var.

## Gap analysis (tvnk.6): Teamarr vars vs Gracenote conventions

Status legend: ✓ covered (single var or simple composition) · ◑ partial (exists but wrong concept/format) · ✗ missing.

### EPG — by surface
| Gracenote convention | Teamarr today | Status | tvnk.7 action |
|---|---|---|---|
| Title = league/series (`MLB Baseball`) | `{gracenote_category}` (curated → else `{display_name} {Sport}`) | ◑ | reconcile seeds — see deep-dive below |
| Team sub = `Away Full at Home Full` | compose `{away_team} {vs_at} {home_team}` | ◑ | `{vs_at}` is HOME/AWAY-perspective ("vs if home, at if away"), NOT sport-based. Need a perspective-free, sport-aware connector |
| Soccer sub = `Group C: A vs. B` | `{soccer_match_note}` = ESPN `altGameNote`, live-verified `"FIFA World Cup, Group C"` | ◑→✓ | DATA EXISTS. Only need a thin "stage-only" formatter to isolate `Group C` (and it doubles as a branded-title source — see note-vars below) |
| US round/marquee = `NCAA Tournament:` / `Game 4` | `{game_event_note}` = ESPN note headline (`NBA Finals - Game 5`, bowl names) | ◑→✓ | DATA EXISTS via the same var — no extension needed; just author into templates with empty-handling |
| CFB special = bowl name in title | `{game_event_note}` carries `CFP Quarterfinal at the Cotton Bowl Classic` | ◑→✓ | DATA EXISTS (note headline). No new var |
| Desc article-aware (`The` Liberty vs `Netherlands`) | `{team_name}` = full only | ✗ | **article-aware name var + national-team/club flag** (the headline gap) |
| Desc verb (`host`/`travel to`/`face`) | `{home_away_text}` = "at home"/"on the road" | ◑ | home/away VERB var for prose |
| Desc venue | `{venue_full}` / `{venue}` / `{venue_city}` | ✓ | — |
| Desc enrichment (records/ranks/standings/streaks/storylines) | cats 5,6,9,14,19 incl. `{game_preview}`/`{game_recap}` | ✓ | — (tvnk.10 already rich) |
| Combat title = `UFC 318: A vs. B` | `{event_title}` = `UFC 325: Volkanovski vs Lopes` | ✓ | — |
| Combat desc = fighters + records + co-main | `{fighter1}`/`{fighter1_record}`/…/`{fight_card}` | ✓ | — |
| Racing sub = `Race name, Session` | `{race_name}` + `{session_name}` | ✓ | — |

### Channel name (concise)
| Piece | Teamarr | Status |
|---|---|---|
| League prefix | `{league_abbrev}` | ✓ |
| Team matchup `DET @ BOS` | `{away_team_abbrev} @ {home_team_abbrev}` | ✓ (hardcoded `@`; soccer wants `v` → same sport-aware connector gap) |
| Combat `Holloway v Poirier` | `{fighter1}`/`{fighter2}` are FULL names | ✗ fighter last-name var |
| Racing `Navy 250` | `{race_name}` | ✓ |

### Deep-dive: is `{gracenote_category}` built the best way?
Construction = curated `leagues.gracenote_category` → else auto `{display_name} {sport_display}`. Verified against REAL captured Gracenote:
- ✓ **Correct** for major US leagues (MLB Baseball, NBA Basketball, College Basketball) and **club soccer** (Premier League Soccer, MLS Soccer — Gracenote really does suffix "Soccer" for clubs).
- ✗ **Racing**: real Gracenote uses the full series name (`NASCAR Craftsman Truck Series`, `IndyCar Racing`), NOT "X Racing". Worse, the curated `nascar-truck` value is `NASCAR Racing` — *worse than its own `display_name`* which already equals the real title. Racing categories must be curated per-league from the captured data (or auto-gen should fall back to `display_name` alone for `event`/racing leagues, not append the sport).
- ✗ **International tournaments**: real Gracenote is branded + **year** (`FIFA World Cup 2026`), but Teamarr yields `FIFA World Cup Soccer` (appends "Soccer", no year). No year mechanism exists in the static field.

Recommendations (own work items, candidates for tvnk.7/tvnk.8):
1. **Reconcile the 77 curated `gracenote_category` seeds** against captured Gracenote; fix racing (use series/display name) and tournament entries. Quick data-quality win; `nascar-truck` is an outright regression to fix now.
2. **Auto-gen fallback by `event_type`**: for `event`/`event_card`/racing leagues, fall back to `display_name` alone (don't append sport); keep `{display_name} {Sport}` only for `team_vs_team`.
3. **Year-aware tournaments**: either drop "Soccer" + allow template composition `{gracenote_category} {year}`, or add a dynamic year-stamped category. Decide in tvnk.8.
4. Bigger play (optional): since the Gracenote API is now cracked, auto-populate `gracenote_category` from the live feed (authoritative) instead of hand-curating.

### The note vars close more than expected (tvnk.10 — `{soccer_match_note}`, `{game_event_note}`)
Both are ESPN-populated per-event and live-verified, and they ARE the data source for three gaps:
- `{soccer_match_note}` = `altGameNote` → `"FIFA World Cup, Group C"`. Supplies (1) the soccer **stage prefix** and (2) a **branded tournament title** per-event — directly relevant to tvnk.12 (better than the static `"FIFA World Cup Soccer"` seed; carries the real brand, just needs year + de-grouping).
- `{game_event_note}` = note headline → `"NBA Finals - Game 5"`, `"CFP Quarterfinal at the Cotton Bowl Classic"`. Supplies the **US round/marquee prefix** and the **CFB bowl title**. Sparse by design (only marquee/playoff events have it) → templates must handle empty gracefully.

Caveats: ESPN-only (other providers may not populate); raw format differs from Gracenote (`"FIFA World Cup, Group C"` vs `"Group C:"`) so a light formatting helper or template shaping is needed, not a new data var.

### tvnk.7 build list (consolidated, trimmed)
Genuinely-missing NEW variables: (a) article-aware team name + club/national-team flag; (b) sport-aware matchup connector (perspective-free at/vs, also fixes channel-name `@`/`v`); (c) home/away prose verb; (d) fighter last-name. Optional thin formatters (not new data): stage-only extractor over `{soccer_match_note}`. Dropped from tvnk.7 — soccer stage prefix, college-round extension, and bowl title are already served by the existing note vars (template authoring in tvnk.8, not new vars). Plus the `gracenote_category` seed/fallback fixes (tvnk.12), which should cross-check against `{soccer_match_note}` for tournament branding.
Caveat: `{league_abbrev}` quality depends on `league_alias` being set (else "UEFA Champions League"→"UEFACL");
audit aliases for the subscribed leagues as part of tvnk.8.

## Live tmsapi capture — 2026-07-09 (Wimbledon week)

Full-region tmsapi build (`US.xml`, 2026-06-30, ~354k programmes) mined for
per-sport conventions; complements the cable-lineup capture above.

### The universal pattern

| Field | Convention | Live examples |
|-------|-----------|---------------|
| Title | `{sport-branded category}` — identical to our `{gracenote_category}` model | `MLB Baseball` · `WNBA Basketball` · `NHL Hockey` · `NFL Football` · `Minor League Baseball` · `Canadian Premier League Soccer` |
| Sub-title | `{Away} at {Home}` for hosted games; `{A} vs. {B}` for neutral-site (NFL classics) | `St. Louis Cardinals at Atlanta Braves` · `1994: San Francisco 49ers vs. Kansas City Chiefs` |
| Description | `From {venue} in {city}[, {state abbr}].` — the canonical baseline; marquee games get a preview paragraph | `From Truist Park in Atlanta.` · `The Tigers continue their three-game series against the Yankees at Yankee Stadium. Right-hander Troy Melton is the expected starter…` |
| Classics | Year-prefixed subtitles | `1986: Vancouver Canucks at Edmonton Oilers` |

### Tennis (validates the Tennis Event starter, with one nuance)

- Title: **`2026 Wimbledon Championships`** — year + tournament, NOT "ATP Tennis".
  Confirms tournament-led titles; note Gracenote prepends the year.
- Sub-title: **round only** (`First Round`, `Second Round`) — Gracenote's linear
  channels cover a whole day's play, so they *can't* name players. Teamarr's
  channels are per-match, so our `{tennis_round} - {player1} vs {player2}`
  subtitle is a strict superset of the convention, not a violation.
- Description: venue prose — `From the All England Lawn Tennis and Croquet
  Club in Wimbledon, England.` (our venue-led descriptions match).

### MiLB (settles the branding question)

Gracenote titles it **`Minor League Baseball`** — not "MiLB", not the level
(`Triple-A`). Sub-title/description follow the universal pattern
(`South Bend Cubs at Beloit Sky Carp` / `From ABC Supply Stadium in Beloit,
Wis.`). The MiLB starter template should adopt `Minor League Baseball`
branding when tvnk.8 revisits it.

### Historical windows: ~48-hour lookback only

Empirical lookback ladder against `tvlistings.gracenote.com` grid (2026-07-09,
proxy egress, same lineup/params throughout): `now` and `-1d` return full
grids (~164 channels / ~720 events); **`-3d` and everything beyond is empty**
(probed to -30d; February fails on tmsapi outright). So the grid serves a
~1–2 day rolling lookback — useful for "yesterday's" listings, useless for
last season. Winter-season conventions (NBA/NHL/NFL/EPL regular season)
cannot be fetched retroactively — **capture forward**: re-run this
extraction when those seasons start (October 2026); the pattern above
predicts them (`NBA Basketball` / `{Away} at {Home}` /
`From {venue} in {city}.`) and NFL/NHL classics already exhibit it.
