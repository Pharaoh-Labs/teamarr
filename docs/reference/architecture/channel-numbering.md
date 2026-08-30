---
title: Channel Numbering
parent: Architecture
grand_parent: Technical Reference
nav_order: 9
---

# Channel Numbering

How Teamarr assigns channel numbers: the global sort, **pinned blocks**
(numbering exceptions, #333), the stability modes that govern renumbering
across runs, and the migration that retired manual mode.

Code: `teamarr/database/channel_numbers.py` (allocators),
`teamarr/database/numbering_exceptions.py` (pinned blocks + lane resolution).

## Model: lanes

Every managed channel is numbered inside exactly one **lane**. A lane is a
range of numbers with its own start:

| Lane | Where it comes from |
|------|---------------------|
| Pinned block | One row in `numbering_exceptions` (a team, league or sport pin), or several rows sharing a start under one label (a *group*) |
| Default | The global channel range (`channel_range_start` / `channel_range_end`) |

The allocator runs the **same placement code per lane** — compact, gap or
strict, sticky locks, daily re-layout — with the lane's start in place of the
global range start. Pinned lanes are placed first, in ascending start order,
then the default lane. All lanes share one set of used numbers (plus external
Dispatcharr channels), so a block that outgrows its space *spills forward* and
later lanes skip over it with a warning rather than colliding.

With zero pinned blocks there is one lane (the default) and the allocator is
byte-for-byte the pre-#333 behaviour. `tests/lifecycle/test_numbering_lanes.py`
holds golden-equivalence tests that assert this for compact, gap and strict.

## Resolution: most specific wins

`resolve_lane(sport, league, home_team, away_team)` returns the lane for a
channel. Precedence:

1. **Team** pin matching the home team
2. **Team** pin matching the away team
3. **League** pin
4. **Sport** pin
5. Default lane

Within one level a channel can match only one row (one league, one sport,
one team per side), so there is no user-facing tie-break; `(sort_order, id)`
remains as a deterministic fallback for legacy rows. Team matching is `(sport, team_name)` case-insensitive on either side
of the event — the same key `channel_priority_teams` uses — so a team pin
follows the club into cup competitions. A team pin covers both the team's
dedicated team channel and every event channel it plays in.

Resolution is deterministic from fields that never change during an event
(sport, league, teams), so a channel's lane is stable for its lifetime. It
changes only when the user edits pinned blocks — which arms a re-layout in
sticky modes, exactly as changing the channel range does.

## Block semantics

- `start` is required. `end` is optional; when set, a block that fills up
  overflows into the **default** lane (with a warning) instead of spilling
  forward.
- Feeds and keyword variants of one event stay contiguous — they resolve to
  the same lane and `_group_consecutive` places them as one block, so the
  existing invariant ("gap only between events") holds inside every lane.
- A **group** is just several rows with the same `start` and `label`; there
  is no separate table. "850 — Big events: World Cup, Olympics" is two rows.
- **A start belongs to one block.** `LaneResolver` keys lanes on `start`
  alone, so any two rows at one start *are* one lane whatever their labels.
  Because users read "Brewers at 550 + MLB at 550" as "Brewers first in the
  MLB block" (it is not — the merged lane sorts in normal lineup order, which
  is the 2.14.0 Discord confusion), `add_numbering_exception` and
  `update_numbering_exception` raise `StartConflict` (→ HTTP 400 with a
  what-to-do-instead message) unless every existing row at that start shares
  the new row's non-empty label (case-insensitive). Toggling `enabled` alone
  never re-validates, so rows created before this rule keep working. The
  reorder endpoint and UI arrows were removed with it — they never changed
  placement (lanes place in ascending `start`), only the never-exercised
  within-level tie-break.

## Stability modes inside lanes

`channel_stability_mode` is global and applies inside every lane:

| Mode | Inside a lane |
|------|---------------|
| compact | Re-sorted contiguously from the lane start every run |
| gap | Sticky; new events slot into the lane's grid (`gap_size`); locked channels never move except at the daily reset |
| strict | Sticky; new events append past the lane's frontier |

The sticky allocator's "invalid anchor" rule — a locked channel whose number
is outside its range is re-placed — now uses the **lane's** range, so moving
a block (say Lions from 800 to 900) re-places those channels on the next run.

## Creation-time allocation

`get_next_channel_number(conn, league, sport, home_team, away_team, ...)`
resolves the lane and returns the first free number from the lane start.
Full ordering happens in the end-of-run `reassign_all_channels` pass, as
before.

## Migration from manual mode (schema v88)

Before #333, `global_channel_mode='manual'` numbered each league sequentially
from `league_channel_starts[league]` in global sort order — which is exactly a
league-scoped pinned block in compact mode. The v88 migration therefore:

1. Inserts one `numbering_exceptions` row (`scope='league'`) per entry in
   `league_channel_starts`, preserving each start.
2. Sets `global_channel_mode='auto'`.
3. Sets `channel_stability_mode='compact'` for manual-mode installs (manual
   never had stability; compact is the only value that reproduces its
   numbers).
4. Leaves `league_channel_starts` and the `'manual'` CHECK value in place, unread,
   as a rollback aid for one release.

Auto-mode installs are untouched: no rows are inserted and every setting keeps
its value.

One deliberate difference: the old manual reassign pass tracked each league's
counter independently and avoided only *external* numbers, so two leagues whose
blocks overlapped could be assigned the **same** number. Lanes share the used
set, so those installs get corrected (non-colliding) numbers after upgrading.

## Storage

```sql
CREATE TABLE numbering_exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL CHECK(scope IN ('team', 'league', 'sport')),
    sport TEXT NOT NULL,            -- always set (team + league pins are sport-scoped)
    league_code TEXT,               -- scope='league'
    team_name TEXT,                 -- scope='team' (match key, case-insensitive)
    provider TEXT,                  -- scope='team' (identity, from team_cache)
    provider_team_id TEXT,          -- scope='team'
    start INTEGER NOT NULL,
    "end" INTEGER,                  -- NULL = spill forward
    label TEXT,                     -- group label (rows sharing start + label)
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

API: `/api/v1/numbering-exceptions` (list — ascending start —, create,
update, delete, `preview` = effective layout of today's channels). UI:
Channels → Numbering → Pinned Blocks.
