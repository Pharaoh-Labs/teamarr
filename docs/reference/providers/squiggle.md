---
title: Squiggle
parent: Providers
grand_parent: Technical Reference
nav_order: 2
---

# Squiggle Provider

The Squiggle provider serves Australian Football League (AFL) data via [api.squiggle.com.au](https://api.squiggle.com.au/). It is free, requires no API key, and replaces the previous TSDB premium requirement for AFL.

## API Details

| | |
|---|---|
| **Base URL** | `https://api.squiggle.com.au/` |
| **Auth** | None (public, free) |
| **Priority** | 30 |
| **Rate Limit** | No hard limit — cache aggressively, set a proper UserAgent |

## Supported Leagues

| League | Code |
|--------|------|
| Australian Football League | `afl` |

## Available Template Variables

Variables populated from Squiggle data:

| Category | Variables | Notes |
|----------|-----------|-------|
| Identity | `{opponent}`, `{opponent_abbrev}`, `{opponent_short}` | Abbreviation is 3-letter; short name falls back to the full name (no separate short name in the API) |
| Scores | `{home_team_score}`, `{away_team_score}`, `{score}`, `{team_score}`, `{opponent_score}` | Populated for completed and live games |
| Outcome | `{result}`, `{result_text}` | W / L / T |
| Venue | `{venue}` | Venue name only |
| Playoffs | `{is_playoff}` condition | Finals games flagged as postseason |
| Records | `{team_record}`, `{opponent_record}` | Season W-L from ladder standings |
| Rankings | `{team_rank}`, `{opponent_rank}` | Ladder position (1 = top of table) |
| Statistics | `{team_ppg}`, `{opponent_ppg}` | Points per game |
| Logos | Team logos | Served from squiggle.com.au |

Not populated (no data source in the Squiggle API): venue city/state (`{venue_city}`, `{venue_state}`), broadcast variables, odds variables, and conference variables (AFL has no conferences).

## Caching

| Data | Cache TTL |
|------|-----------|
| Season schedule (216 games) | 1 hour |
| Team list (18 teams) | 24 hours |
| Ladder standings | 6 hours |

The full season schedule is fetched once per hour and filtered in-process for each date query. Together with the descriptive `User-Agent` header Teamarr sets automatically, this satisfies Squiggle's usage policy for bots (identify yourself, cache and reuse data, no bulk request spam).
