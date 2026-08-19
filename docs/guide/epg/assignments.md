---
title: Template Assignments
parent: EPG
grand_parent: User Guide
nav_order: 6
redirect_from:
  - /guide/templates/assignments/
  - /guide/templates/assignments.html
---

# Template Assignments

Event templates are assigned through **subscription-level rules**, not per-source. One set of template rules applies globally across all [Sources](../sources/).

## How Assignment Works

Template assignments use a priority system to decide which template applies to a given event:

1. **League-specific** — A template assigned to a specific league (e.g., "NHL") takes highest priority
2. **Sport-specific** — A template assigned to a sport (e.g., "Hockey") applies to all leagues in that sport
3. **Default** — The fallback template used when no sport or league match exists

When generating EPG, Teamarr checks the event's league first, then its sport, then falls back to the default. The most specific matching rule wins. Matching is **case-insensitive** on both league and sport, so `NHL` and `nhl` behave the same.

If two rules at the same tier both match (say, two league rules covering NHL), the first one wins — there's no explicit tie-breaking, so keep tiers non-overlapping. If **no** rule matches at all (including no default), the event renders with built-in generic formatting.

Because one rule-set is global, a multi-sport source resolves a *different* template per event — an NHL game and an NBA game in the same source each get their own league's template.

## Managing Assignments

The central manager lives at the bottom of **EPG → Templates** ("Template Assignments"). It shows every rule across all templates side by side — use it to spot overlaps.

Each template's editor also has an **Assignments** tab showing the picture from that template's point of view: the rules that assign it (with quick add/edit/delete scoped to that template), or — for team templates — the followed teams currently using it (per-team assignment stays on the Teams page).

The central manager shows:

- Current assignment rules listed in priority order
- Each rule has a **Template** dropdown, a **Sports** multi-select filter, and a **Leagues** multi-select filter
- Rules with leagues specified are more specific than rules with only sports
- A rule with no sports and no leagues acts as the default

You can add, edit, or remove rules. Changes apply to all sources on the next generation run.

## Example

| Template | Sports | Leagues | Effect |
|----------|--------|---------|--------|
| Soccer HD | Soccer | — | All soccer events use "Soccer HD" |
| NHL Premium | — | NHL, AHL | NHL and AHL events use "NHL Premium" |
| Default | — | — | Everything else uses "Default" |

An AHL event matches the league rule → "NHL Premium". A Premier League event has no league rule but matches the Soccer sport rule → "Soccer HD". An MLB event matches neither → "Default".

## Team Templates

Team-based EPG uses a separate assignment model: each team has a template assigned directly on the **EPG → Team EPG** page. The subscription-based assignment system described here only applies to event-based EPG.

See [Team vs Event Templates](team-vs-event) for more on the differences between the two modes.
