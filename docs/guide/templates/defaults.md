---
title: Default Templates
parent: EPG
grand_parent: User Guide
nav_order: 10
---

# Default Templates

Teamarr seeds a curated set of starter templates — modeled on how professional
EPG providers (Gracenote) title and describe sports programming. They ship
**unassigned**: pick the ones that match your setup and assign them by sport
or league (Templates → Template Assignments), or set one as your global
default.

Seeding is safe and idempotent: on every startup, any set member missing by
name is added, and **your edits are never overwritten**. Installs that still
carry the original pristine `Team`/`Event` seeds (with the old
`localhost:3000` placeholder art) have them upgraded in place — same template,
same assignments, fixed art.

Starters you've **never edited** stay current automatically: when a Teamarr
update improves a starter's content, an untouched copy is upgraded in place
(same template, same assignments). Editing any part of a starter — title,
subtitle, descriptions, filler — makes it yours, and upgrades never touch it
again.

## The Set

| Template | Type | Designed for | Channel name style | Assign to |
|----------|------|--------------|--------------------|-----------|
| **Default Team (Starter)** | team | Any team channel (US-pro travel-line register) | `{team_name}` | Global team default |
| **Soccer Team (Starter)** | team | Soccer team channels, club or national — "face" match register, article-aware naming | `{team_name}` | Soccer teams |
| **College Team (Starter)** | team | NCAA team channels — home-led host framing with rank, record, and conference context | `{team_name}` | NCAA teams |
| **Default Event (Starter)** | event | Any matchup league — team abbreviations fall back to short/full names automatically | `NBA \| DET/LAL` | Global event default |
| **College Event (Starter)** | event | NCAA event channels — ranked matchups lead with `No. {rank}` | `NCAAB \| MIZ/ARK` | NCAA sports |
| **Soccer Club Event (Starter)** | event | Club soccer leagues | `EPL \| ARS v CHE` | Club soccer leagues (EPL, La Liga, MLS, …) |
| **Combat Event (Starter)** | event | UFC / PFL / boxing (card segments) | `UFC 310 Main Card` | UFC, PFL, boxing leagues |
| **International Event (Starter)** | event | National-team tournaments — year-composed title (`FIFA World Cup 2026`) | `NED v JPN` | National-team tournaments (World Cup, Euro, …) |
| **Tennis Event (Starter)** | event | ATP / WTA (per-match channels) — year-prefixed tournament title | `Alcaraz v Sinner` | ATP, WTA |
| **Racing Event (Starter)** | event | NASCAR / F1 / IndyCar / IMSA / WEC (per-session channels) — series-led title, race + session subtitle (`Navy 250, Practice 1`) | `NASCAR Cup \| Race` | Racing leagues |

Minor-league baseball needs no dedicated starter: **Default Event** titles
every MiLB level as Gracenote's real `Minor League Baseball` (from the league
data) and prefixes channels with the level (`AAA | ABQ/SUG`). An earlier
"MiLB Event (Starter)" is removed on upgrade only if you never edited **or
assigned** it — a starter that's in use anywhere (a team, a source, or an
assignment rule) is protected from retirement even when unedited.

Team starters exist only for sport families that support **team subscriptions**
(persistent team channels): the universal default plus soccer and college.
Combat, tennis, and racing have no meaningful team channels, so they get event
starters only.

Every starter template carries a **"(Starter)"** suffix so it's always clear
which templates shipped with Teamarr; rename freely — a renamed or edited
starter is yours and is never touched by upgrades.

Channel names are deliberately **short**: TV guide grids truncate channel
names aggressively (often ~15–20 visible characters), so the set leads with
abbreviations and surnames.

## Descriptions: provider copy first

Starter descriptions prefer ESPN's own editorial copy and fall back to
constructed prose when it isn't available:

- **Pregame / main program** — when ESPN publishes a preview blurb (usually
  on game day), it's used verbatim via a `has_preview → {game_preview}`
  conditional row; marquee games lead with the provider's designation when
  one exists ("NBA Finals - Game 5. …", "FIFA World Cup, Group C. …" via
  `has_event_note` / `has_match_note` rows); neutral-site games (bowls,
  CFP/NCAA tournament rounds) drop host framing for "X and Y meet at {venue}"
  via an `is_neutral_site` row; for games further out, a structured-preview
  row enriches the constructed line with recent form and series state ("The
  Rays have won 2 of their last five… BOS leads series 3-2"); otherwise the
  plain constructed "X travel to Y…" line renders.
- **Subtitles** — the US-register starters connect matchups with the
  neutral-aware `{at_vs}` variable: "Pistons at Celtics" for hosted games,
  "Ohio State vs. Texas" at neutral sites (the Gracenote convention).
- **Idle / offseason filler** — soccer team channels phrase filler in the
  match register ("No Chelsea Match Today", "No upcoming Chelsea matches
  scheduled."); other families keep the US "game" phrasing.
- **Postgame** — when ESPN publishes a recap headline, the filler shows it
  via a `has_recap → {game_recap}` condition row; a game that's still
  running gets an `is_not_final` in-progress line; a final game with no
  recap falls to the constructed result line ("The X defeated the Y 4–2").
  Tennis gates its constructed `{tennis_result}` on `is_final` instead —
  it's built from score data, not provider copy.

The underlying mechanism (for your own templates): each filler register
carries **condition rows** evaluated against its reference game — see
[Filler condition rows](../epg/conditions#filler-condition-rows). A winning
row's description that resolves empty — e.g. `{game_recap}` before a recap
exists — cascades to the next matching row, then the register's base
description. Pregame fillers also support a simple `description_fallback`
field for the preview-first pattern without any rows.

## Art

Program art uses **relative paths** (e.g.
`{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png`) combined with
the **art base URL** setting — point it at your image server and every
template resolves against it. Absolute URLs in your own templates bypass the
base URL.

The racing starter ships without program art: race weekends have no home/away
matchup for the cover path to compose from.

## Deleting and restoring starters

Starter templates you **delete** stay deleted, and starters you **rename**
become fully yours — neither reappears after a restart. Teamarr records a
tombstone for the old name and skips it when seeding.

To get the full starter set back, use **Restore Starter Templates** at the
bottom of the Templates table. Restoring only recreates *missing* starters —
templates you've modified or created yourself are never touched.
