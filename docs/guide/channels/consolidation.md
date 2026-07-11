---
title: Consolidation
parent: Channels
grand_parent: User Guide
nav_order: 2
docs_version: "2.7.0"
---

# Consolidation

When an event has multiple streams (different providers, qualities, or feeds), Consolidation decides whether those streams merge into a single channel or split into separate ones.

## Default Mode

| Mode | Description |
|------|-------------|
| **Consolidate** | Merge multiple streams for the same event into a single channel with multiple sources. Exception keywords can override this per-stream. |
| **Separate** | Each stream gets its own channel, even if they're for the same event. More channels, no merging. |

In Consolidate mode, [Stream Priority](stream-priority) rules decide which stream is listed first within the merged channel.

## Exception Keywords

When using Consolidate mode, exception keywords let certain streams break out of the default merge. Streams whose names match one of these terms get sub-consolidated or separated instead of folding into the main channel — useful for keeping, say, a 4K or alternate-language feed on its own channel.

Exception keywords only apply in Consolidate mode.

## Feed Separation

When multiple IPTV providers carry separate home and away broadcast feeds for the same event, Feed Separation detects them and creates distinct channels for each.

### How It Works

1. **Literal token detection** — stream names containing terms like "HOME" or "AWAY" are detected before team matching. The token is stripped so it doesn't interfere with team-name parsing.
2. **Broadcast-market detection** — the stream name is matched against the event's actual broadcast listings from the provider (ESPN reports each network's market: national, home, or away). This is how team-branded channels ("Brewers.TV") and regional networks that don't carry the team's name at all ("YES", "Marquee Sports Network") resolve to the right feed. Matching tolerates the usual stream-name drift — punctuation and casing ("BREWERS TV"), run-together forms ("BrewersTV"), and abbreviated words ("Bally Sports WI" for "Bally Sports Wisconsin"). Always on; national networks never count as a team feed.
3. **Team-name detection** — if enabled, stream names are scanned for team names in a feed context (e.g., "Orioles Feed", "Orioles.TV", "Orioles.US") and matched against the event's home and away teams.
4. **Channel discrimination** — streams resolved to different teams get separate channels, even for the same event. Unlabeled streams go to their own channel as usual.

### Settings

| Setting | Default | Description |
|---------|---------|-------------|
| **Enable Feed Separation** | Off | Master toggle for the feature |
| **Home Terms** | `HOME` | Comma-separated terms that indicate a home feed |
| **Away Terms** | `AWAY` | Comma-separated terms that indicate an away feed |
| **Detect Team Names** | On | Also match team names in stream names (e.g., "Orioles Feed") |
| **Label Style** | Team Name | How feed channels are labeled — see below |

### Label Styles

Controls the text appended to channel names when a feed team is detected:

| Style | Example |
|-------|---------|
| **Team Name** | `NYY @ BAL (Baltimore Orioles)` |
| **Short Name** | `NYY @ BAL (Orioles)` |
| **Home/Away** | `NYY @ BAL (Home)` |

### Example

Given an event "NYY @ BAL" with streams:

- `MLB: NYY @ BAL HOME` → detected as home feed → channel: `NYY @ BAL (Orioles)`
- `MLB: NYY @ BAL AWAY` → detected as away feed → channel: `NYY @ BAL (Yankees)`
- `MLB: NYY @ BAL` → no feed detected → channel: `NYY @ BAL`

This creates three separate channels, each consolidating their respective streams.
