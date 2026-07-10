---
title: Default Templates
parent: Templates
grand_parent: User Guide
nav_order: 5
docs_version: "2.9.1"
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

## The Set

| Template | Type | Designed for | Channel name style |
|----------|------|--------------|--------------------|
| **Default Team (Starter)** | team | Any team channel | `{team_name}` |
| **Default Event (Starter)** | event | Any matchup league — team abbreviations fall back to short/full names automatically | `NBA \| DET/LAL` |
| **Combat Event (Starter)** | event | UFC / PFL / boxing (card segments) | `UFC 310 Main Card` |
| **International Event (Starter)** | event | National teams, international competitions | `NED v JPN` |
| **MiLB Event (Starter)** | event | Minor-league baseball | `MiLB \| ABQ/SUG` |
| **Tennis Event (Starter)** | event | ATP / WTA (per-match channels) | `Alcaraz v Sinner` |

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
  conditional row; for games further out, a structured-preview row enriches
  the constructed line with recent form and series state ("The Rays have won
  2 of their last five… BOS leads series 3-2"); otherwise the plain
  constructed "X travel to Y…" line renders.
- **Postgame** — once a game is final and ESPN publishes a recap headline,
  the filler shows `{game_recap}`; until then a constructed result line
  ("The X defeated the Y 4–2") renders instead.

The underlying precedence (for your own templates): an enabled **postgame
conditional** beats the postgame fallback, but if its text resolves to an
empty string — e.g. `{game_recap}` before a recap exists — the fallback
description is used. Pregame fillers support the same pattern via the
`description_fallback` field.

## Recommended scoping

| Template | Assign to |
|----------|-----------|
| Default Team | Global team default |
| Default Event | Global event default |
| Combat Event | UFC, PFL, boxing leagues |
| International Event | Soccer + international competitions |
| MiLB Event | MiLB levels (Triple-A … Rookie) |
| Tennis Event | ATP, WTA |

## Art

Program art uses **relative paths** (e.g.
`{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png`) combined with
the **art base URL** setting — point it at your image server and every
template resolves against it. Absolute URLs in your own templates bypass the
base URL.
