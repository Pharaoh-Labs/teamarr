---
title: Channels
parent: Settings
grand_parent: User Guide
nav_order: 5
docs_version: "2.3.1"
---

# Channel Settings

Configure channel lifecycle, numbering, consolidation, per-league configuration, and stream ordering.

## Channel Lifecycle

Controls when event channels are created and deleted in Dispatcharr.

### Create Timing

| Mode | Description |
|------|-------------|
| **Same day** | Create channels on the day of the event |
| **Before event + buffer** | Create channels a configurable number of hours before the event starts |

When "Before event + buffer" is selected, a **Pre-Event Buffer** field appears where you set the number of hours before the event to create the channel (e.g., 6 hours before).

### Delete Timing

| Mode | Description |
|------|-------------|
| **Same day** | Delete channels at midnight on the day of the event |
| **After event + buffer** | Delete channels a configurable number of hours after the event ends |

The **Post-Event Buffer** sets how many hours after the event ends to keep the channel (e.g., 2 hours after for postgame coverage).

{: .note }
Create and delete timing work together with EPG generation. Channels are only actually created or deleted when a generation run executes — the timing determines *eligibility*, not the exact moment.

## Channel Numbering & Consolidation

### Numbering Mode

| Mode | Description |
|------|-------------|
| **Auto** | Sequential numbering from the start of the channel range. Sport/league priority determines order. |
| **Manual** | Per-league starting channel numbers. Each league gets its own block. |

### Channel Range

Both modes use a global channel range:

| Field | Description |
|-------|-------------|
| **Channel Range Start** | First channel number Teamarr can use |
| **Channel Range End** | Last channel number (optional — leave empty for no upper limit) |

### Per-League Starting Channels (Manual Mode)

When Manual mode is selected, a table appears listing all leagues with a configurable starting channel number for each. Use the search field and "Subscribed only" toggle to filter the list.

Each league gets sequential numbers starting from its configured start. This lets you group sports into predictable channel ranges (e.g., NFL at 500, NBA at 600, NHL at 700).

### Stream Consolidation Mode

Controls how duplicate streams for the same event are handled:

| Mode | Description |
|------|-------------|
| **Consolidate** | Merge multiple streams for the same event into a single channel with multiple sources. Exception keywords (configured in [Settings > Event Groups](event-groups)) can override this per-stream. |
| **Separate** | Each stream gets its own channel, even if they're for the same event |

### Channel Ordering

Configure how channels are ordered within the channel range. The **Sort Priority Manager** lets you drag and drop sports and leagues into your preferred order. Higher items get lower channel numbers.

Click **Auto-populate** to pre-fill with all currently subscribed sports and leagues.

## Per-League Channel Config

Override channel profiles, channel groups, and group modes on a per-league basis. This table lists all leagues — click a league row to expand its configuration.

### Available Overrides

| Setting | Options | Description |
|---------|---------|-------------|
| **Channel Profiles** | Default, None, or specific profiles | Which Dispatcharr profiles this league's channels appear in |
| **Channel Group** | Default or specific group | Which Dispatcharr channel group to assign channels to |
| **Group Mode** | Default, Static, Dynamic by Sport, Dynamic by League, Custom | How the channel group is determined |

When Group Mode is set to **Custom**, a pattern field appears where you can enter a template like `{sport} - {league}` that dynamically creates groups.

{: .note }
Per-league overrides take precedence over the defaults in [Settings > Dispatcharr](dispatcharr). Use the **X** button to clear an override and revert to the default.

### Filtering

Use the search field to find specific leagues, and toggle "Subscribed only" to hide leagues you haven't enabled.

## Feed Separation

When multiple IPTV providers include separate home and away broadcast feeds for the same event, Feed Separation detects these and creates distinct channels for each.

### How It Works

1. **Literal token detection**: Stream names containing terms like "HOME" or "AWAY" are detected before team matching. The token is stripped so it doesn't interfere with team name parsing.
2. **Team name detection**: If enabled, stream names are scanned for team names (e.g., "Orioles Feed") and matched against the event's home and away teams.
3. **Channel discrimination**: Streams resolved to different teams get separate channels — even for the same event. Unlabeled streams go to their own channel as usual.

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

## Stream Ordering

Configure priority rules for ordering streams within consolidated channels. When multiple streams are consolidated into a single channel, these rules determine which stream is listed first (the "primary" stream).

### Rule Types

| Type | Description | Example |
|------|-------------|---------|
| **M3U Account** | Prioritize streams from a specific M3U account | "Premium IPTV" = priority 1 |
| **Event Group** | Prioritize streams from a specific event group | "ESPN+ Group" = priority 2 |
| **Regex Pattern** | Prioritize streams matching a regex | `(?i)1080p` = priority 1 |
| **Stream Type** | Match by how the stream was matched: **event stream** or **team stream**. Optionally narrow a team-stream rule to specific teams. | "Team stream" → priority 3 |
| **Home/Away Feed** | Match streams that look like a team's own broadcast (its home or away feed), detected from the stream name. Pick one or more teams. **Invert** flips it to match feeds that are *not* your selected teams (useful for pushing other teams' feeds to the back). | Selected teams → priority 1 |
| **Everything Else** | Catch-all fallback applied to any stream not matched by the rules above. Always present and cannot be removed; set its priority to control where unmatched streams land. | Everything else → priority 99 |

Lower priority numbers = higher priority. Rules are evaluated in order — the first matching rule determines the stream's priority.

#### Team filters

Both **Stream Type** (team streams) and **Home/Away Feed** rules let you pick specific teams. Leaving the team selection empty makes the rule a no-op — a Stream Type rule with no teams matches *all* team streams, while a Home/Away Feed rule with no teams matches nothing. Use the **Default** button to load your configured team-filter include list, or **Clear** to start fresh.

#### How Home/Away Feed detection works

Teamarr builds a name-matching pattern from your selected teams' names and abbreviations, then looks for feed indicators in the stream name — a matchup (`vs`, `at`, `@`), a side (`home`/`away`), a camera label (`cam 01`/`cam 02`), or a `(Team feed)` marker. A stream like `Cubs vs Pirates (Home)` is recognized as the Pirates' home feed. Generic streams with no feed markers (for example a plain `Pirates vs Cubs` with no side) are left for other rules to handle. Because detection relies on the stream name, results depend on your provider's naming conventions.
