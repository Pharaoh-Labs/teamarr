---
title: Numbering
parent: Channels
grand_parent: User Guide
nav_order: 3
docs_version: "2.7.0"
---

# Numbering

How channel numbers are assigned and how channels are ordered within the lineup.

## Numbering Mode

| Mode | Description |
|------|-------------|
| **Auto** | Sequential numbering from the channel range start. Order is determined by sport/league priority. |
| **Manual** | Per-league starting channel numbers. Each league gets its own block. |

## Channel Range

Both modes use a global channel range:

| Field | Description |
|-------|-------------|
| **Channel Range Start** | First channel number Teamarr can use. In Manual mode, this is the default start for leagues without a configured start. |
| **Channel Range End** | Last channel number — leave empty for no upper limit |

{: .tip }
Set the range start above your existing Dispatcharr channels (e.g., start at 1000 if you already use 1–500) to avoid number collisions.

## Per-League Starting Channels (Manual Mode)

When Manual mode is selected, a table lists all leagues with a configurable starting channel number for each. Use the search field and the **Subscribed only** toggle to filter the list.

Each league gets sequential numbers starting from its configured start. This lets you group sports into predictable channel ranges (e.g., NFL at 500, NBA at 600, NHL at 700). Leagues without a configured start fall back to the channel range start.

## Channel Ordering

Channel ordering controls *where channels land in the lineup* — distinct from [Stream Priority](stream-priority), which orders streams *inside* a channel.

**Priority Teams** — add teams here and their channels float to the very top of the channel list, ahead of all sport/league/time ordering. A team floats up wherever it plays (league and cup), matched by name within its sport. This is purely an ordering preference — it has no connection to the [Teams](../epg/teams) page or EPG generation.

The **Sort Priority Order** list lets you drag and drop sports and leagues into your preferred order. Higher items get lower channel numbers. Click **Auto-populate** to pre-fill with all currently subscribed sports and leagues.

The full order is: **Priority Teams → Sport → League → Event time**.

{: .note }
Channel numbers are updated on the next EPG generation run.
