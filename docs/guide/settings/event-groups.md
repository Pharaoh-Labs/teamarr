---
title: Event Groups
parent: Settings
grand_parent: User Guide
nav_order: 3
docs_version: "2.6.0"
---

# Event Group Settings

Configure defaults for event-based EPG generation.

## Event Matching

### Event Lookahead

How far ahead to match streams to sporting events. Streams are matched to events within this window. Default is 3 days.

Options: 1, 3, 7, 14, or 30 days.

## EPG Program Matching

Traditional linear channels (ESPN, NBA1, FS1) carry many different games across a day under a single static stream name, so Teamarr can't match them by name. **EPG program-data matching** uses Dispatcharr's program guide to match these streams to events by the program *title* (e.g. "MLB Baseball" / "Chicago Cubs at St. Louis Cardinals"), then **time-shares** one linear stream across many event channels — attaching it to each event's channel only near game time and detaching it after.

EPG matching is enabled **per Event Group** (there is no global switch); the settings in this tile are global tuning that applies to every group that opts in. Has no effect unless the connected Dispatcharr exposes the program-search API.

| Setting | Description |
|---------|-------------|
| **Attach before (minutes)** | How long before a program's start the stream attaches to the event channel. |
| **Detach after (minutes)** | How long after a program's end the stream detaches. |
| **Use Dispatcharr channels as an EPG source** | Opt-in additive source (default off). Alongside per-group M3U matching, Teamarr pulls candidate streams from the channels you've already curated in Dispatcharr — using each channel's own linked EPG to match its assigned streams to events. Lets you match only the channel versions you've mapped instead of every stream in a provider group. Runs as a hidden system group ("Dispatcharr Channels"); Teamarr's own generated channels are excluded (they are output, not input). |
| **Dispatcharr groups to include** | (Shown when the above is on.) Pick which Dispatcharr channel groups to scan. Only channels in the selected groups are matched — fewer groups means faster generation. Leave empty to include all groups. The selected groups also appear as a **Dispatcharr Group** rule under [Channels → Stream Ordering](channels.md#stream-ordering). |
| **Fall back to Xtream (XC) provider EPG** | Opt-in backup (default off). EPG matching normally needs a valid stream-to-EPG mapping in Dispatcharr; when on, for Xtream Codes (XC) M3U accounts Teamarr fetches the provider's own EPG and matches the still-unresolved streams against it — covering channels (e.g. regional sports networks) Dispatcharr has no guide for. The provider guide is cached on disk per XC account. |
| **Cache for (hours)** | (Shown when the XC fallback is on.) How long a downloaded XC provider guide is reused before re-fetching. Default 24. Provider guides change slowly, so a longer cache avoids redundant downloads and keeps generations fast. |

Turn matching **on per Event Group** (each group's *EPG program matching* toggle) — only groups that opt in are scanned. The channel still exists for its normal lifecycle (filler + upcoming guide); only the linear *stream* swaps in and out near game time.

{: .note }
Requires a recent Dispatcharr build with the program-search endpoint (`/api/epg/programs/search/`). Older builds ignore the setting. Attach/detach precision is bounded by how often EPG generation runs.

See the full [EPG Program Matching guide](../epg-matching.md) for how stream→guide resolution works (no manual EPG mapping needed), requirements, the **EPG Matched** badge and stream-ordering rule, and troubleshooting.

## Exception Keywords

When using [Consolidate mode](channels#stream-consolidation-mode), exception keywords allow special handling for certain streams. Streams matching these terms get sub-consolidated or separated instead of following the default consolidation behavior.

Exception keywords only appear when consolidation mode is set to Consolidate in [Settings > Channels](channels#stream-consolidation-mode).

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

{: .note }
The default team filter for event groups is configured in [Event Groups > Global Defaults](../event-groups/creating-groups), not in Settings. Stream consolidation mode is in [Settings > Channels](channels#stream-consolidation-mode).
