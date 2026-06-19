---
title: Sources
parent: User Guide
nav_order: 4
has_children: true
docs_version: "2.7.0"
redirect_from:
  - /guide/event-groups/
  - /guide/event-groups.html
  - /guide/settings/event-groups/
  - /guide/settings/event-groups.html
---

# Sources

A **Source** is an IPTV stream group (event-based) that Teamarr matches to real-world sporting events. Event-based EPG creates dynamic channels from those M3U streams: unlike team channels (which are persistent), event channels appear when a game is about to start and disappear after it ends.

{: .note }
> Sources were called **Event Groups** before v2.7.0. The app route is now `/sources`, and the per-source settings that used to live under *Settings → Event Groups* now live in the Source editor.

## How It Works

1. Your IPTV provider delivers streams organized into groups (e.g., "NFL", "ESPN+", "DAZN")
2. You import these stream groups into Teamarr as **Sources**
3. Teamarr parses each stream name, matches it to a real sporting event, and creates a channel with rich EPG data
4. Channels are created in Dispatcharr with proper names, logos, EPG data, and group/profile assignments

## Global Defaults vs Per-Source Settings

Teamarr uses a **subscription model** where global defaults apply to all sources:

- **League subscriptions** — which sports and leagues to scan for events
- **Soccer configuration** — follow teams, select leagues, or include all
- **Template assignments** — which EPG template to use by sport/league
- **Team filter** — include/exclude specific teams from matching

These are configured in the **Global Defaults** panel at the top of the Sources page.

Individual sources can override these defaults when needed (e.g., a hockey-only stream source that shouldn't scan for football events).

## The Sources Table

Below Global Defaults, the sources table shows all configured sources with:

| Column | Description |
|--------|-------------|
| **Name** | Source name and M3U account |
| **Matched** | Stream coverage — how many of the source's eligible streams matched at least one event, as a 0–100% rate. Hover for the total *matches produced* and the last-run timestamp. |
| **Status** | Enable/disable toggle |
| **Actions** | Preview matches, clear cache, edit, delete |

Click **Matched** numbers to see which streams matched to which events. Click the preview button to see current stream matches without running a full generation.

{: .note }
> The percentage is **stream coverage**: distinct streams matched ÷ eligible streams (always 0–100%). The hover tooltip shows **matches produced** — the total number of stream→event matches. With [EPG matching](../matching/program-matching), one linear stream (ESPN, FS1…) is time-shared across many events, so matches produced can far exceed the stream count. These are tracked separately so coverage stays a true health signal.

## Importing Sources

Click **Import** to pull stream groups from your Dispatcharr M3U accounts. Teamarr shows available groups with stream counts. Select the groups you want and they'll be created as sources with default settings.

## Stream Matching Pipeline

When EPG generation runs, each stream goes through:

1. **Filtering** — include/exclude regex, built-in filters for non-sport content
2. **Classification** — parse stream name to extract teams, league, date, time
3. **Matching** — find the corresponding real-world event from provider data
4. **Channel creation** — create/update the Dispatcharr channel with EPG data

Streams that can't be matched appear in the **Failed** count. Click it to see details and use the **Fix** button to manually link a stream to an event.

## Matching Types

Each Source declares which matching pipeline(s) it runs. The three types are **independent** — enable any combination, and each stream is routed to whichever applies. Every Source must have at least one enabled. The Sources table shows a color-coded badge per active type.

| Type | Badge | Matches | Example |
|------|-------|---------|---------|
| **Stream Name** | blue | Streams whose name identifies a specific event | `Bills vs Dolphins`, `DAZN: Man City vs Arsenal` |
| **Team** | green | A team's branded stream → that team's games in the window (one stream → many events) | `NHL \| Toronto Maple Leafs` |
| **EPG** | violet | Static linear channels → events via Dispatcharr's program guide, time-sharing one stream across events | `ESPN`, `NBA1` |

{: .note }
> A Source that does **only** Team or EPG (Stream Name off) shows a raw stream **count** in the Matched column instead of a coverage percentage — those types fan one stream out to many events, so a `matched ÷ total` percentage isn't a meaningful health signal.

Set these on a Source in the editor (and at bulk add / bulk edit). **EPG** requires a Dispatcharr build with the program-search API — see [EPG Program Matching](#epg-program-matching) below.

## Event Matching Window

The **Event Lookahead** controls how far ahead Teamarr matches streams to sporting events — streams are matched only to events within this window. Default is 3 days; options are 1, 3, 7, 14, or 30 days.

## EPG Program Matching

Traditional linear channels (ESPN, NBA1, FS1) carry many different games across a day under a single static stream name, so Teamarr can't match them by name. **EPG program-data matching** uses Dispatcharr's program guide to match these streams to events by the program *title* (e.g. "MLB Baseball" / "Chicago Cubs at St. Louis Cardinals"), then **time-shares** one linear stream across many event channels — attaching it to each event's channel only near game time and detaching it after.

EPG matching is enabled **per Source** (there is no global switch); the global tuning below applies to every source that opts in. It has no effect unless the connected Dispatcharr exposes the program-search API.

| Setting | Description |
|---------|-------------|
| **Attach before (minutes)** | How long before a program's start the stream attaches to the event channel. |
| **Detach after (minutes)** | How long after a program's end the stream detaches. |
| **Use Dispatcharr channels as an EPG source** | Opt-in additive source (default off). Alongside per-source M3U matching, Teamarr pulls candidate streams from the channels you've already curated in Dispatcharr — using each channel's own linked EPG to match its assigned streams to events. Lets you match only the channel versions you've mapped instead of every stream in a provider group. Runs as a hidden system source ("Dispatcharr Channels"); Teamarr's own generated channels are excluded (they are output, not input). |
| **Dispatcharr groups to include** | (Shown when the above is on.) Pick which Dispatcharr channel groups to scan. Only channels in the selected groups are matched — fewer groups means faster generation. Leave empty to include all groups. The selected groups also appear as a **Dispatcharr Group** rule under [Channels → Stream Ordering](../channels/stream-priority). |
| **Fall back to Xtream (XC) provider EPG** | Opt-in backup (default off). EPG matching normally needs a valid stream-to-EPG mapping in Dispatcharr; when on, for Xtream Codes (XC) M3U accounts Teamarr fetches the provider's own EPG and matches the still-unresolved streams against it — covering channels (e.g. regional sports networks) Dispatcharr has no guide for. The provider guide is cached on disk per XC account. |
| **Cache for (hours)** | (Shown when the XC fallback is on.) How long a downloaded XC provider guide is reused before re-fetching. Default 24. Provider guides change slowly, so a longer cache avoids redundant downloads and keeps generations fast. |

Turn matching **on per Source** (each source's *EPG program matching* toggle) — only sources that opt in are scanned. The channel still exists for its normal lifecycle (filler + upcoming guide); only the linear *stream* swaps in and out near game time.

{: .note }
> Requires a recent Dispatcharr build with the program-search endpoint (`/api/epg/programs/search/`). Older builds ignore the setting. Attach/detach precision is bounded by how often EPG generation runs.

See the full [EPG Program Matching guide](../matching/program-matching) for how stream→guide resolution works (no manual EPG mapping needed), requirements, the **EPG Matched** badge and stream-ordering rule, and troubleshooting.

## Exception Keywords

When using [Consolidate mode](../channels/consolidation), exception keywords allow special handling for certain streams. Streams matching these terms get sub-consolidated or separated instead of following the default consolidation behavior.

Exception keywords only appear when consolidation mode is set to Consolidate in [Settings → Channels](../channels/consolidation).

### Example Use Case

Your IPTV provider carries both English and Spanish streams for the same game. With consolidation enabled, they'd merge into one channel. Adding a "Spanish" exception keyword with "Separate" behavior creates a separate channel for the Spanish stream.

### Keyword Fields

| Field | Description |
|-------|-------------|
| **Label** | Display name (available as `{exception_keyword}` in templates) |
| **Match Terms** | Comma-separated terms to match in stream names |
| **Behavior** | Sub-Consolidate, Separate, or Ignore |

| Behavior | Description |
|----------|-------------|
| **Sub-Consolidate** | Group matching streams together, separate from the main consolidated channel |
| **Separate** | Each matching stream gets its own channel |
| **Ignore** | Skip matching streams entirely |

See [Adding a Source](creating-groups) for detailed configuration options.
