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

## Number Stability (Auto Mode)

Controls whether a channel can be **renumbered while its event is live**. Dispatcharr relies on channel numbers staying put, so a game shouldn't jump numbers just because another event started or ended.

| Mode | Behaviour |
|------|-----------|
| **Compact** | Re-sorts every channel into tidy contiguous order on every run (legacy default). A live channel's number can shift when events start or end. |
| **Gapped (sticky)** | Channels are spaced apart by the **gap size** (e.g. 3 → 101, 104, 107). A new event slots into a free number near where it sorts (filling the gap, or reusing a slot freed by an ended event); existing channels keep their number for the whole event lifecycle. |
| **Strict (no drift)** | Existing channels never move. A new event that would displace others is appended to the end of the range instead. Gaps left by ended events are reclaimed only at the daily reset. |

In both **Gapped** and **Strict** modes, a channel's number is fixed for the life of its event. The only time existing numbers change is the **daily re-layout**.

{: .note }
**Feeds stay together.** When feed separation splits an event into Home / Away / Regular channels, they're treated as one block and placed on **adjacent** numbers — the gap is only ever applied *between* events, never between feeds of the same game. A multi-feed event simply consumes more of its gap (e.g. with gap size 3, a 3-feed event fills 101–103 and the next event starts at 104).

### Daily Re-Layout

To stop gaps accumulating and to restore priority order, a full re-grid runs once per day. It is gated into your generation schedule: the **first generation at or after the configured reset time** re-grids every channel, then it won't run again until the next day.

| Field | Description |
|-------|-------------|
| **Gap Size** | (Gapped mode) spacing between channels at reset. Larger gaps leave more room for late events to slot in without moving anyone. |
| **Daily re-layout** | Toggle the periodic re-grid on/off. With it off, numbers stay sticky indefinitely and gaps are never reclaimed automatically. |
| **Reset Time** | Local time of the low-traffic window for the re-layout (default `04:00`). |

{: .note }
Reset Time is the **server's** local time. In Docker this is usually UTC unless you set the container `TZ` — pick the value accordingly.

### Re-grid now

You don't have to wait for the daily window. **Re-grid channels now** queues a one-shot re-layout that runs on the **next generation** — renumbering every channel back into priority order and reclaiming gaps, regardless of the reset time (and even if the daily re-layout is turned off).

Changing the **gap size**, switching **stability mode**, or reordering **sort priority / priority teams** queues the same re-grid automatically, so the change takes effect on the next run instead of silently waiting for the daily reset. (This is non-destructive — channels keep their identity and streams; only their numbers change.)

{: .note }
Number Stability applies to **Auto** mode. Manual mode uses its own per-league sequential numbering.

### Trade-off: ordering vs. stability

You can't have perfectly priority-ordered numbers *and* numbers that never move when the slate changes — so the sticky modes choose stability and reclaim ordering at the daily reset.

Between resets, ordering is **best-effort**. A new event slots into a free number near where it sorts, but if it would sort **above every existing channel** and there's no room below them (for example a [Priority Team](#channel-ordering) game, or an earlier-starting game in your top league, that's only discovered on a later run), it is placed at the **end of the range** rather than displacing anyone. It stays there until the next daily re-layout puts it back in priority order.

If keeping the top of your lineup in strict priority order matters more than holding numbers steady, run the daily reset more often (or keep **Compact** mode, which re-sorts every run at the cost of live channels shifting).

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
