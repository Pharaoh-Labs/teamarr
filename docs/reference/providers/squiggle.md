---
title: Squiggle
parent: Providers
grand_parent: Technical Reference
nav_order: 4
docs_version: "2.5.5"
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
| Identity | `{opponent}`, `{opponent.abbrev}` | Full name and 3-letter abbreviation |
| Identity | `{opponent.short}` | Same as full name (no separate short name in API) |
| Scores | `{home_score}`, `{away_score}`, `{score}`, `{team_score}`, `{opp_score}` | Populated for completed and live games |
| Result | `{result}` | win / loss / tie |
| Status | `{status}` | scheduled / live / final |
| Venue | `{venue}` | Venue name only |
| Season | `{is_playoff}`, `{season_type}` | Finals games flagged as postseason |
| Record | `{record}`, `{opp_record}` | Season W-L from ladder standings |
| Ranking | `{rank}`, `{opp_rank}` | Ladder position (1 = top of table) |
| Stats | `{ppg}`, `{papg}` | Points scored/conceded per game |
| Logos | Team logos | Served from squiggle.com.au |

Variables not available (no data source):

| Variable | Reason |
|----------|--------|
| `{venue.city}`, `{venue.state}` | API returns venue name only |
| `{broadcasts}` | Not in Squiggle API |
| `{odds}` | Not in Squiggle API |
| `{home.color}`, `{away.color}` | No color data |
| Conference/division variables | AFL has no conferences |

## Caching

| Data | Cache TTL |
|------|-----------|
| Season schedule (216 games) | 1 hour |
| Team list (18 teams) | 24 hours |
| Ladder standings | 6 hours |

The full season schedule is fetched once per hour and filtered in-process for each date query. This satisfies Squiggle's requirement to cache and reuse data rather than polling per-date.

## Usage Policy

Squiggle requires bots to:

- Set a descriptive `User-Agent` header identifying the application (Teamarr does this automatically)
- Cache data and avoid repeated identical requests
- Not spam the API with simultaneous bulk requests

Teamarr's in-process caching satisfies all of these requirements.
