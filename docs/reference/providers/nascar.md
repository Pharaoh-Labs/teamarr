---
title: NASCAR
parent: Providers
grand_parent: Technical Reference
nav_order: 3
---

# NASCAR

Official NASCAR public schedule API (`cf.nascar.com`). Serves the three national series with full race-weekend session detail — practice, qualifying, and race with precise UTC start times — which ESPN's NASCAR scoreboard does not provide (it exposes only the single race competition).

## Leagues

| League | ID | Series number |
|--------|-----|---------------|
| NASCAR Cup Series | `nascar-cup` | 1 |
| NASCAR O'Reilly Auto Parts Series | `nascar-xfinity` | 2 |
| NASCAR Craftsman Truck Series | `nascar-truck` | 3 |

The `nascar-xfinity` league code is kept for the O'Reilly Auto Parts Series (formerly Xfinity) so existing subscriptions and channels carry over across the sponsor rename.

## Endpoints

No authentication or API key required.

```
Cup:          https://cf.nascar.com/cacher/{year}/1/race_list_basic.json
ORAP/Trucks:  https://cf.nascar.com/cacher/{year}/race_list_basic.json   (keys: series_2, series_3)
```

## Behavior

- **Season schedule cache** — the full season is loaded lazily on first use and cached in memory for 6 hours. A failed or empty load retries after 15 minutes instead of pinning an empty schedule, and a failed *refresh* keeps the previously loaded schedule. The season year is resolved at load time, so long-running processes roll over automatically.
- **Sessions** — schedule entries map to session codes by `run_type` (1 = practice → `fp1`–`fp4`/`practice`, 2 = qualifying, 3 = race); admin entries (`run_type` 0, e.g. "Haulers Enter") are skipped. Events with no on-track sessions are dropped.
- **Race format data** — scheduled laps, distance, and per-stage lap counts populate the `{race_laps}`, `{race_distance}`, `{stage_N_laps}`, and `{stage_summary}` [template variables](../../guide/epg/variables#race-format).
- **Matching** — events carry per-session start times, so the racing matcher's date-coverage check works across the whole race weekend (same contract as the TSDB racing path).
- **Broadcasts** — the `television_broadcaster` field flows into the Broadcast variables (`{broadcast_simple}`, `{network}`).

## Limitations

- Schedule only — no live results, so results/grid variables (`{race_winner}`, `{grid}`, …) stay empty for NASCAR events.
- No team/driver rosters (`get_team_schedule`/`get_team` return nothing); NASCAR leagues are event-only.
