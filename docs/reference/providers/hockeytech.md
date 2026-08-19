---
title: HockeyTech
parent: Providers
grand_parent: Technical Reference
nav_order: 5
---

# HockeyTech Provider

HockeyTech serves Canadian and US junior/minor hockey leagues via an undocumented API discovered from official league websites.

## API Details

| | |
|---|---|
| **Base URL** | `https://lscluster.hockeytech.com/feed/` |
| **Auth** | Public client keys (embedded in league websites) |
| **Priority** | 50 |
| **Rate Limit** | None observed (caching is used to be respectful) |

## Supported Leagues

### CHL & Member Leagues

| League | Client Code | Client Key |
|--------|-------------|------------|
| Canadian Hockey League | `chl` | `f1aa699db3d81487` |
| Ontario Hockey League | `ohl` | `f1aa699db3d81487` |
| Western Hockey League | `whl` | `f1aa699db3d81487` |
| Quebec Major Junior Hockey League | `lhjmq` | `f1aa699db3d81487` |

### Professional

| League | Client Code | Client Key |
|--------|-------------|------------|
| American Hockey League | `ahl` | `50c2cd9b5e18e390` |
| East Coast Hockey League | `echl` | `2c2b89ea7345cae8` |
| Professional Women's Hockey League | `pwhl` | `446521baf8c38984` |

### US Junior

| League | Client Code | Client Key |
|--------|-------------|------------|
| United States Hockey League | `ushl` | `e828f89b243dc43f` |

### Canadian Junior A

| League | Client Code | Client Key |
|--------|-------------|------------|
| Ontario Junior Hockey League | `ojhl` | `77a0bd73d9d363d3` |
| British Columbia Hockey League | `bchl` | `ca4e9e599d4dae55` |
| Saskatchewan Junior Hockey League | `sjhl` | `2fb5c2e84bf3e4a8` |
| Alberta Junior Hockey League | `ajhl` | `cbe60a1d91c44ade` |
| Manitoba Junior Hockey League | `mjhl` | `f894c324fe5fd8f0` |
| Maritime Junior Hockey League | `mhl` | `4a948e7faf5ee58d` |
| Greater Ontario Hockey League | `gojhl` | `34b10d4d34d7b59a` |

## API Request Format

All requests use the same base parameters:

```
feed=modulekit&key={client_key}&view={view}&client_code={league_code}&fmt=json&lang=en
```

| View | Description |
|------|-------------|
| `schedule` | Full season schedule |
| `scorebar` | Live scores |
| `teamsbyseason` | Teams in league |
| `seasons` | Season metadata (playoff flag, season names, dates) |

The `provider_league_id` in `schema.sql` is the `client_code` value (e.g., `ohl`, `ahl`, `lhjmq` for QMJHL).

## Cache TTLs

| Data | TTL |
|------|-----|
| Full season schedule | 30 minutes |
| Teams | 24 hours |
| Seasons metadata | 24 hours |
| Past games | 7 days |
| Today's games | 30 minutes |
| Tomorrow's games | 4 hours |
| 3-7 days out | 8 hours |
| 8+ days out | 24 hours |

## Special Behaviors

- **Full schedule caching**: `get_team_schedule()` fetches the entire season once, then filters locally
- **Lookback**: Scans 7 days back to resolve `.last` template variables
- **QMJHL client code**: Uses `lhjmq` (French: Ligue de hockey junior majeur du Québec)
- **Thread-safe**: Connection pooling with configurable limits
- **Season type via seasons view**: HockeyTech's `schedule` feed leaves `game_type` empty for every game, but each game has a `season_id`. The separate `seasons` view is joined in to map `season_id` → canonical season_type: `playoff == "1"` → `postseason`; `season_name` containing `preseason` / `pre-season` / `exhibition` → `preseason`; anything else → `regular`. Showcase/All-Star seasons (e.g. "AHL 2026 All-Star Challenge", "OHL Top Prospects") fall into `regular` since they have no playoff flag and no preseason keyword.

## File Locations

| File | Purpose |
|------|---------|
| `teamarr/providers/hockeytech/provider.py` | HockeyTechProvider class |
| `teamarr/providers/hockeytech/client.py` | HTTP client with client key management |
