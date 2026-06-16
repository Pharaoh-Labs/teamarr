---
title: Event Groups
parent: User Guide
nav_order: 6
has_children: true
docs_version: "2.3.0"
---

# Event Groups

Event-based EPG creates dynamic channels from M3U streams. Unlike team channels (which are persistent), event channels appear when a game is about to start and disappear after it ends.

## How It Works

1. Your IPTV provider delivers streams organized into groups (e.g., "NFL", "ESPN+", "DAZN")
2. You import these stream groups into Teamarr as **event groups**
3. Teamarr parses each stream name, matches it to a real sporting event, and creates a channel with rich EPG data
4. Channels are created in Dispatcharr with proper names, logos, EPG data, and group/profile assignments

## Global Defaults vs Per-Group Settings

Teamarr uses a **subscription model** where global defaults apply to all groups:

- **League subscriptions** — which sports and leagues to scan for events
- **Soccer configuration** — follow teams, select leagues, or include all
- **Template assignments** — which EPG template to use by sport/league
- **Team filter** — include/exclude specific teams from matching

These are configured in the **Global Defaults** panel at the top of the Event Groups page.

Individual groups can override these defaults when needed (e.g., a hockey-only stream source that shouldn't scan for football events).

## The Event Groups Table

Below Global Defaults, the event groups table shows all configured groups with:

| Column | Description |
|--------|-------------|
| **Name** | Group name and M3U account |
| **Matched** | Stream coverage — how many of the group's eligible streams matched at least one event, as a 0–100% rate. Hover for the total *matches produced* and the last-run timestamp. |
| **Status** | Enable/disable toggle |
| **Actions** | Preview matches, clear cache, edit, delete |

Click **Matched** numbers to see which streams matched to which events. Click the preview button to see current stream matches without running a full generation.

!!! info "Coverage vs. matches produced"
    The percentage is **stream coverage**: distinct streams matched ÷ eligible streams (always 0–100%). The hover tooltip shows **matches produced** — the total number of stream→event matches. With [EPG matching](../epg-matching.md), one linear stream (ESPN, FS1…) is time-shared across many events, so matches produced can far exceed the stream count. These are tracked separately so coverage stays a true health signal.

## Importing Groups

Click **Import** to pull stream groups from your Dispatcharr M3U accounts. Teamarr shows available groups with stream counts. Select the groups you want and they'll be created with default settings.

## Stream Matching Pipeline

When EPG generation runs, each stream goes through:

1. **Filtering** — include/exclude regex, built-in filters for non-sport content
2. **Classification** — parse stream name to extract teams, league, date, time
3. **Matching** — find the corresponding real-world event from provider data
4. **Channel creation** — create/update the Dispatcharr channel with EPG data

Streams that can't be matched appear in the **Failed** count. Click it to see details and use the **Fix** button to manually link a stream to an event.

See [Creating Groups](creating-groups) for detailed configuration options.
