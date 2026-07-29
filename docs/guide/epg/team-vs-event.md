---
title: Team vs Event
parent: EPG
grand_parent: User Guide
nav_order: 2
redirect_from:
  - /guide/templates/team-vs-event/
  - /guide/templates/team-vs-event.html
---

# Team vs Event Templates

Teamarr supports two template types designed for different EPG workflows. The key difference is *where each one lives*:

- **Team templates** populate the **XMLTV channel** Teamarr writes for that team. You map the XMLTV channel to one of your existing Dispatcharr channels.
- **Event templates** populate the **Dispatcharr channels** Teamarr creates from matched event streams.

## Team Templates

Team templates fill in the EPG for a **persistent XMLTV channel dedicated to a specific team**. Teamarr does not create a Dispatcharr channel here — you point one of your existing Dispatcharr channels at this XMLTV channel id.

- Each team has its own XMLTV channel that exists 24/7 in the guide Teamarr generates
- The template is assigned to a specific team, so Teamarr knows the "viewpoint"
- Content is written from that team's perspective using variables like `{team_name}` and `{opponent}` — whether the team is home or away, `{team_name}` is always your team
- Filler programmes (pregame, postgame, idle) keep the channel populated even when no game is live

Typical use: a "Detroit Lions" channel in your guide showing all Lions games — regional-sports-network style, one XMLTV channel per team mapped onto a fixed Dispatcharr channel you already have.

### Variable Context

Team templates have access to three game contexts:

| Context | Suffix | Example | Use Case |
|---------|--------|---------|----------|
| Current | (none) | `{opponent}` | During a game or when one game today |
| Next | `.next` | `{opponent.next}` | Pregame content, idle content |
| Last | `.last` | `{opponent.last}` | Postgame content, recaps |

Suffix availability is **per variable** — many variables are base-only, and using an unsupported suffix renders literally. The [Variables](variables) tables list each variable's supported suffixes, and the editor warns inline.

### Assigned To

Team templates are assigned to **teams** on the [EPG → Team EPG](teams) page. One template can be shared across multiple teams — useful for consistent formatting across a league or even multiple sports.

---

## Event Templates

Event templates are for **dynamic channels created per-game**.

- Channels are created when a matching stream appears, and deleted after the game ends (configurable)
- Each channel represents one specific game — there's no "team viewpoint"
- Content uses positional variables: `{home_team}` / `{away_team}` (and their `_record`, `_score`, … families)
- Event templates additionally get the **feed-team** family (`{feed_team}`, `{is_home_feed}`, …) for feed-separated channels

Typical use: IPTV providers with game-specific streams ("NFL: Bills vs Dolphins") matched through your [Sources](../sources/).

### Variable Context

Event templates reference only the current event — no suffixes, because the channel only exists for one game.

### Assigned To

Event templates are routed by **subscription-level assignment rules** (league → sport → default), managed on the Templates page — see [Template Assignments](assignments). There is no per-source template setting: one global rule-set covers every source, and a multi-sport source resolves a *different* template per event based on each event's league and sport.

---

## How the picker enforces the split

Every variable is tagged with a scope — available to **all** templates, **team-only**, or **event-only** — and the editor's variable picker is filtered server-side by the template type you're editing: about 210 variables appear for team templates and 182 for event templates (of 252 total).

Notable scope groups:

- **Team-only**: the team-perspective family — `{team_name}`, `{opponent}`, `{result}`, `{team_record}`, streaks, and similar.
- **Event-only**: the feed-team family, plus all **Motorsports** and **Tennis** variables (individual-competitor sports have no team perspective).
- **Both**: most of the list — positional teams, venue, date/time, playoffs, soccer, and (perhaps surprisingly) all **Combat** variables.

## Comparison

| Feature | Team Templates | Event Templates |
|---------|---------------|-----------------|
| Channel target | XMLTV channel per team (you map it to a Dispatcharr channel) | Dispatcharr channel per matched game (Teamarr creates it) |
| Channel lifetime | Persistent (24/7) | Temporary (per game) |
| Perspective | Team-specific ("our team") | Positional (home/away) |
| Suffix support | `.next`, `.last` (per variable) | None needed |
| Idle content | Yes | No |
| Assigned to | Teams (Teams page) | Sport/league assignment rules |
| Variables | ~210 (team-scoped picker) | ~182 (event-scoped picker) |

Many setups use both — team templates for favorite teams and event templates for catching other games from IPTV streams.
