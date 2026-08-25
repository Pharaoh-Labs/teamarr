---
title: Configuration
parent: Deployment
grand_parent: Technical Reference
nav_order: 2
---

# Configuration

Teamarr is configured via environment variables in your `docker-compose.yml` file. Most settings have sensible defaults and don't need to be changed.

## General Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `9195` | The port Teamarr listens on. `docker-compose.yml` maps `9195:9195` by default. |
| `TZ` | EPG timezone setting | UI timezone for date/time display. When unset, falls back to the EPG timezone configured in Settings (default `America/New_York`). `USER_TIMEZONE` is accepted as an alias. |
| `LOG_LEVEL` | `INFO` | Console log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `text` | Log format: `text` or `json` (for log aggregation systems like ELK, Loki, Splunk) |
| `LOG_DIR` | auto-detected | Override log directory path. See [Log Directory Detection](#log-directory-detection). |
| `SKIP_CACHE_REFRESH` | `false` | Skip team/league cache refresh on startup. Set to `true`, `yes`, or `1`. Useful for faster restarts during development. |
| `EPG_INDEX_FETCH_WORKERS` | `10` | Parallel workers for fetching Dispatcharr EPG programs during EPG matching. Lower it if your Dispatcharr instance struggles with concurrent requests. |
| `DATABASE_PATH` | `<project_root>/data/teamarr.db` | Path to the SQLite database (`/app/data/teamarr.db` in Docker). |
| `TEAMARR_CACHE_DIR` | auto-detected | Override the provider EPG cache directory (default `/app/data/epg_cache` in Docker). |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | Internal API config values; the actual listen address and port are `0.0.0.0` and `PORT`. |
| `ESPN_API_BASE` | `https://site.api.espn.com/apis/site/v2/sports` | Override the ESPN API base URL. |
| `GIT_BRANCH` / `GIT_SHA` | `unknown` | Build metadata shown in the UI. Baked in as build args by the Dockerfile — not normally set by users. |

## ESPN API Settings

These settings control how Teamarr communicates with ESPN's API. Most users don't need to change these defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `ESPN_MAX_WORKERS` | `100` / `50` / `24` | Maximum parallel workers for fetching data. Three defaults: 100 for team/event processing, 50 for cache refresh (which makes more API calls per league), 24 for the event-match prefetch. Setting the variable overrides all three. |
| `ESPN_MAX_CONNECTIONS` | `100` | HTTP connection pool size |
| `ESPN_TIMEOUT` | `10` | Request timeout in seconds |
| `ESPN_RETRY_COUNT` | `3` | Number of retry attempts on failure |

### When to Adjust ESPN Settings

If you experience timeouts or connection failures during cache refresh or EPG generation, you may be hitting **DNS throttling** from your network setup. This commonly affects users with:

- **PiHole** or **AdGuard** DNS filtering
- Custom DNS resolvers with rate limits
- Router-level DNS throttling

**Recommended settings for DNS-throttled environments:**

```yaml
environment:
  - ESPN_MAX_WORKERS=20
  - ESPN_MAX_CONNECTIONS=20
  - ESPN_TIMEOUT=15
```

These lower values reduce the number of parallel DNS lookups, giving your DNS resolver time to process requests without throttling.

{: .note }
ESPN's API has generous rate limits that are practically impossible to hit. Connection issues are almost always caused by local DNS or network constraints, not ESPN throttling.

## MLB Stats API Settings

Controls for the MLB Stats provider (MiLB leagues).

| Variable | Default | Description |
|----------|---------|-------------|
| `MLBSTATS_MAX_CONNECTIONS` | `20` | HTTP connection pool size |
| `MLBSTATS_TIMEOUT` | `15` | Request timeout in seconds |
| `MLBSTATS_RETRY_COUNT` | `3` | Number of retry attempts on failure |

## Supabase API Settings

Controls for the Supabase provider (Supabase-backed leagues such as the Canadian Baseball League). Credentials are normally discovered automatically from each league's website; the per-league variables let you supply them directly and skip that step.

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPABASE_TIMEOUT` | `10.0` | Request timeout in seconds |
| `SUPABASE_RETRY_COUNT` | `3` | Number of retry attempts on failure |
| `{LEAGUE_CODE}_SUPABASE_URL` | — | Supabase project URL for a specific league (e.g. `CBL_SUPABASE_URL`). Bypasses automatic credential discovery. |
| `{LEAGUE_CODE}_SUPABASE_API_KEY` | — | Supabase API key for a specific league (e.g. `CBL_SUPABASE_API_KEY`). |

## Logging

Teamarr writes to two rotating log files:

| File | Contents | Rotation |
|------|----------|----------|
| `teamarr.log` | All log messages (DEBUG and above) | 10 MB x 5 files |
| `teamarr_errors.log` | Errors only | 10 MB x 3 files |

The console log level is controlled by the `LOG_LEVEL` environment variable (default: `INFO`). File logs always capture `DEBUG` regardless of this setting.

### Log Directory Detection

The log directory is determined in this order:

1. `LOG_DIR` environment variable (if set)
2. `/app/data/logs` (if `/app/data` exists — Docker default)
3. `<project_root>/logs` (local development fallback)
4. `logs/` relative to the working directory (last resort, if no project root is found)

### Viewing Logs

```bash
# Docker container stdout
docker logs --tail 100 teamarr

# Log file (inside container or data volume)
docker exec teamarr cat /app/data/logs/teamarr.log | tail -100

# Or from data volume on host
tail -n 100 ./data/logs/teamarr.log
```

## Data Paths

| Path | Contents |
|------|----------|
| `/app/data/teamarr.db` | Database — all configuration, teams, templates, history |
| `/app/data/logs/` | Log files (auto-rotating) |
| `/app/data/teamarr.xml` | Generated XMLTV output (single file; path configurable in Settings, default `./data/teamarr.xml`) |
| `/app/data/epg_cache/` | Cached provider EPG files (Xtream EPG matching) |

{: .warning }
**Never delete `teamarr.db`** — it contains all your configuration. Schema upgrades are handled automatically via migrations on startup.
