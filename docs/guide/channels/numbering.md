---
title: Numbering
parent: Channels
grand_parent: User Guide
nav_order: 3
---

# Numbering

How channel numbers are assigned and how channels are ordered within the lineup.

![Channels → Numbering — range, pinned blocks, and number-stability options](../../assets/images/channels-numbering.png)

Numbers come from two places: **pinned blocks** you define for the teams, leagues,
or sports you care about, and the **channel range** for everything else. Channels
are ordered by priority inside each.

## Channel Range

| Field | Description |
|-------|-------------|
| **Channel Range Start** | First channel number for everything that isn't pinned. |
| **Channel Range End** | Last channel number — leave empty for no upper limit. If a run fills the range, allocation stops there (with a log warning) rather than numbering past the end. |

Teamarr automatically **skips numbers already used by non-Teamarr channels** in Dispatcharr, and logs a warning when the configured range overlaps external channels. Setting the range start above your existing channels (e.g., 1000 if you use 1–500) is still tidier — contiguous blocks without skips — but collisions are prevented either way.

## Pinned Blocks

A pinned block gives a **team**, **league**, or **sport** its own block of channel numbers starting at a number you choose. For example:

| Start | Scope | Result |
|-------|-------|--------|
| 800 | Team · Detroit Lions | The Lions team channel and every Lions game, from 800 |
| 850 | Group "Big events" · FIFA World Cup, Olympics | Both competitions share one block from 850 |
| 1700 | League · NFL | Every other NFL game from 1700 |
| 8000 | *(channel range start)* | Everything else |

**Add block** picks the scope (the team picker, a league, or a sport), a start channel, and optionally a group name. Blocks that share a group name *and* start share one block of numbers — type an existing group's name and its start fills in.

Rules:

- **Most specific wins.** A channel goes to the team block if either team is pinned, else the league block, else the sport block, else the channel range. When both teams are pinned, the **home** team's block wins; among equals, the block higher in the list wins — use the arrows to reorder.
- **A team pin follows the team everywhere** — league games and cup games alike, matched by name within the sport (the same rule Priority Teams use).
- **Feeds stay together.** Home/away feeds and keyword variants of one game land on adjacent numbers inside the block, exactly as in the channel range.
- **Blocks spill forward.** A block with more channels than room simply continues past its start; the next block skips over it (you'll see a ⚠ in the effective-layout preview). Set an **end channel** (under *advanced*) if you'd rather overflow into the channel range.
- **Disable** a block with its switch to keep it without applying it.

Block changes are saved immediately and queue a re-grid in Gapped/Strict modes, so they take effect on the next generation. The **effective layout** strip under the list shows where today's channels would land under the current blocks.

{: .note }
**Upgrading from Manual mode.** Manual mode's per-league starting channels became league-scoped pinned blocks automatically — same starts, same numbers. Leagues that had no configured start now share the channel range in priority order instead of each restarting at the range start (which could hand two leagues the same number).

## Number Stability

Controls whether a channel can be **renumbered while its event is live**. Dispatcharr relies on channel numbers staying put, so a game shouldn't jump numbers just because another event started or ended.

| Mode | Behaviour |
|------|-----------|
| **Compact** | Re-sorts every channel into tidy contiguous order on every run (the default). A live channel's number can shift when events start or end. |
| **Gapped (sticky)** | Channels are spaced apart by the **gap size** (e.g. 3 → 101, 104, 107). A new event slots into a free number near where it sorts (filling a gap, or reusing a slot freed by an ended event); existing channels keep their number for the whole event lifecycle. A new event that sorts above everything with no room below is appended to the end of the used range until the next re-layout. |
| **Strict (no drift)** | Existing channels never move. **Every** new event is appended to the end of the used range, regardless of where it would sort. Gaps left by ended events are reclaimed only at the daily reset. |

You can't have perfectly priority-ordered numbers *and* numbers that never move — the sticky modes choose stability between resets and restore ordering at the daily re-layout. If strict ordering at the top of the lineup matters more, keep **Compact**.

In Gapped and Strict modes, existing numbers change outside the daily re-layout only in two edge cases: a channel whose number now **collides with an external Dispatcharr channel** (or falls outside a changed range) is re-placed on the next run, and a keyword-variant channel that ended up numbered *below* its main channel is swapped with it so the main channel always has the lower number.

{: .note }
**Feeds and keyword variants stay together.** When feed separation or exception keywords split an event into multiple channels, they're treated as one block on **adjacent** numbers — the gap is only applied *between* events. With gap size 3, a 3-feed event fills 101–103 and the next event starts at 106 (a full gap always follows the block).

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

You don't have to wait for the daily window. **Re-grid channels now** (shown in Gapped/Strict modes only) queues a one-shot re-layout that runs on the **next generation** — renumbering every channel back into priority order and reclaiming gaps, regardless of the reset time and even if the daily re-layout is turned off. The flag clears once that run completes.

Changing the **gap size**, switching **stability mode**, adjusting the **channel range**, editing **pinned blocks**, or reordering **sort priority / priority teams** queues the same re-grid automatically, so the change takes effect on the next run instead of silently waiting for the daily reset.

{: .note }
Number Stability applies **inside every pinned block** as well as the channel range: with Gapped and gap size 3, a block starting at 800 lays out 800, 803, 806…; the daily re-layout re-grids each block from its own start.

## Channel Ordering

Channel ordering controls *where channels land in the lineup* — distinct from [Stream Priority](stream-priority), which orders streams *inside* a channel.

**Priority Teams** — add teams here and their channels float to the very top of the channel list, ahead of all sport/league/time ordering. A team floats up wherever it plays (league and cup), matched by name within its sport. This is purely an ordering preference — it has no connection to the [Teams](../epg/teams) page or EPG generation.

The **Sort Priority Order** list lets you drag and drop sports and leagues into your preferred order. Higher items get lower channel numbers. Click **Auto-populate** to pre-fill with all currently subscribed sports and leagues.

The full order is: **Priority Teams → Sport → League → Event time**, with two deterministic tie-breakers after that — event id, then main channel before its keyword variants (your Spanish feed always sorts right after the main channel).

{: .note }
Channel numbers are updated on the next EPG generation run.
