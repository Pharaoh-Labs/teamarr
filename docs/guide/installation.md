---
title: Installation
parent: User Guide
nav_order: 1
docs_version: "2.3.1"
---

# Installation

Docker Compose is the recommended method for installation.

## Prerequisites

- Docker
- [Headendarr](https://github.com/Pharaoh-Labs/headendarr) or [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) (recommended - Teamarr is designed to integrate with either platform)
- [Game-Thumbs](game-thumbs.md) (optional - sports matchup thumbnail and logo generation)

## Docker

**Image tags:**
- `latest` - Stable release (recommended)
- `dev` - Development branch, may contain experimental features

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

      # Override log directory path (default: /app/data/logs)
      # - LOG_DIR=/custom/log/path
```

### Unraid

An Unraid Docker template is available in the Community Applications store. Search for "Teamarr" to install directly from the Unraid UI.

Open Teamarr at `http://<your-server>:9195`

## Data Persistence

All Teamarr data is stored in the `./data` volume mount:

| Path | Contents |
|------|----------|
| `data/teamarr.db` | Database — teams, templates, settings, event groups, run history |
| `data/logs/` | Log files (rotating, auto-managed) |
| `data/epg/` | Generated XMLTV output |

{: .warning }
**Never delete `teamarr.db`** — it contains all your configuration. Schema upgrades are handled automatically via migrations on startup.

## First Run

On first startup, Teamarr will:

1. Create the database and run all migrations
2. Refresh the league and team cache from providers (~2-3 minutes)
3. Start the web UI on port 9195

The dashboard will show a **Getting Started** guide walking you through initial setup: connect to Headendarr or Dispatcharr, create templates, add teams or event groups.

## Updating

Pull the latest image and recreate the container:

```bash
docker compose pull teamarr
docker compose up -d teamarr
```

Teamarr handles database migrations automatically — no manual steps needed between versions.

{: .note }
Advanced users familiar with Python may run Teamarr locally without Docker. Clone the repository and run `python app.py`.
