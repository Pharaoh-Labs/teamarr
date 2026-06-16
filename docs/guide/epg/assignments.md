---
title: Template Assignments
parent: EPG
grand_parent: User Guide
nav_order: 6
docs_version: "2.7.0"
redirect_from:
  - /guide/templates/assignments/
  - /guide/templates/assignments.html
---

# Template Assignments

Templates are assigned through the **subscription** system, not per-group. This means one set of template rules applies globally across all event groups.

## How Assignment Works

Template assignments use a priority system to decide which template applies to a given event:

1. **League-specific** — A template assigned to a specific league (e.g., "NHL") takes highest priority
2. **Sport-specific** — A template assigned to a sport (e.g., "Hockey") applies to all leagues in that sport
3. **Default** — The fallback template used when no sport or league match exists

When generating EPG, Teamarr checks the event's league first, then its sport, then falls back to the default. The most specific matching rule wins.

## Managing Assignments

Go to **Event Groups > Global Defaults** and click **Manage** next to "Template Assignments".

The assignment modal shows:

- Current assignment rules listed in priority order
- Each rule has a **Template** dropdown, a **Sports** multi-select filter, and a **Leagues** multi-select filter
- Rules with leagues specified are more specific than rules with only sports
- A rule with no sports and no leagues acts as the default

You can add, edit, or remove rules. Changes apply to all event groups on the next generation run.

## Examples

| Template | Sports | Leagues | Effect |
|----------|--------|---------|--------|
| Soccer HD | Soccer | — | All soccer events use "Soccer HD" |
| NHL Premium | — | NHL, AHL | NHL and AHL events use "NHL Premium" |
| Default | — | — | Everything else uses "Default" |

If an AHL event is generated, Teamarr checks:

1. Is there a league-specific rule for AHL? **Yes** — "NHL Premium" matches. Use it.

If a Premier League event is generated:

1. Is there a league-specific rule for Premier League? **No.**
2. Is there a sport-specific rule for Soccer? **Yes** — "Soccer HD" matches. Use it.

If an MLB event is generated:

1. Is there a league-specific rule for MLB? **No.**
2. Is there a sport-specific rule for Baseball? **No.**
3. Use the default — "Default".

## Per-Group Overrides

Individual event groups can override the global template assignment by selecting a specific template in their group settings. This takes absolute priority over the subscription-based rules.

Use per-group overrides when a single event group needs different formatting than the rest of its sport or league.

## Team Templates

Team-based EPG uses a separate assignment model: each team has a template assigned directly on the **Teams** page. The subscription-based assignment system described here only applies to event-based EPG.

See [Team vs Event Templates](team-vs-event) for more on the differences between the two modes.
