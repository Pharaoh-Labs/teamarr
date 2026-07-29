---
title: Installation
parent: User Guide
nav_order: 1
---

# Installation

Docker Compose is the recommended method for installation.

## Prerequisites

- Docker
- [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) (highly recommended — Teamarr is designed for tight integration with Dispatcharr)
- [Game-Thumbs](epg/game-thumbs) (optional — sports matchup thumbnail and logo generation)

## Docker

**Image tags:**
- `latest` — Stable release (recommended)
- `dev` — Development branch, may contain experimental features

```yaml
services:
  teamarr:
    image: ghcr.io/pharaoh-labs/teamarr:latest
    container_name: teamarr
    restart: unless-stopped
    ports:
      - 9195:9195
    volumes:
      - ./data:/app/data
    environment:
      # UI timezone - controls time display in the Teamarr web interface
      # EPG output timezone is configured separately in Settings
      - TZ=America/New_York

      # Console log level: DEBUG, INFO, WARNING, ERROR (default: INFO)
      # Note: File logging (data/logs/) always captures DEBUG regardless of this setting
      # - LOG_LEVEL=INFO

      # Log format: "text" or "json" (default: text)
      # Use "json" for log aggregation systems (ELK, Loki, Splunk)
      # - LOG_FORMAT=text

      # Skip team/league cache refresh on startup (default: false)
      # Useful during development to speed up restarts. Cache can still
      # be refreshed manually via the UI or by the daily scheduled task.
      # - SKIP_CACHE_REFRESH=true

      # ESPN connection tuning — useful if a local DNS filter (Pi-hole,
      # AdGuard) throttles the many parallel ESPN lookups
      # - ESPN_MAX_WORKERS=25
      # - ESPN_MAX_CONNECTIONS=25
```

The full list of supported environment variables (logging, ports, provider tuning) is in the [Configuration reference](../reference/deployment/configuration).

### Unraid

An Unraid Docker template is available in the Community Applications store. Search for "Teamarr" to install directly from the Unraid UI.

Open Teamarr at `http://<your-server>:9195`

## Data Persistence

All Teamarr data is stored in the `./data` volume mount:

| Path | Contents |
|------|----------|
| `data/teamarr.db` | Database — teams, templates, settings, sources, subscriptions, run history |
| `data/teamarr.xml` | Generated XMLTV output |
| `data/logs/` | Log files (rotating, auto-managed) |
| `data/backups/` | Manual and scheduled database backups |

{: .warning }
**Never delete `teamarr.db`** — it contains all your configuration. Schema upgrades are handled automatically via migrations on startup.

## First Run

On first startup, Teamarr will:

1. Create the database and run all migrations
2. Refresh the league and team directory from providers (a startup overlay shows progress — usually well under a minute)
3. Start the web UI on port 9195

The navigation bar numbers the setup flow: **Settings (0) → Sources (1) → Subscriptions (2) → Matching (3) → EPG (4) → Channels (5)**, with the **Generate** button at the end. Work left to right; the [User Guide index](./) mirrors the same order. Start with [Dispatcharr Integration](dispatcharr-integration).

## Updating

Pull the latest image and recreate the container:

```bash
docker compose pull teamarr
docker compose up -d teamarr
```

Teamarr handles database migrations automatically — no manual steps needed between versions.

{: .note }
Advanced users familiar with Python may run Teamarr locally without Docker. Clone the repository and run `python app.py`.
