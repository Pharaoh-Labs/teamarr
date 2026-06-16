---
title: Advanced
parent: Settings
grand_parent: User Guide
nav_order: 4
docs_version: "2.7.0"
---

# Advanced

Backup/restore, scheduled channel reset, and the data caches.

## Backup & Restore

### Download Backup

Download a complete backup of your Teamarr database, including:

- All teams and their configurations
- Templates and presets
- Sources and event groups
- Settings

### Restore Backup

Upload a `.db` backup file to restore. A backup of your current data is automatically created before restoring.

{: .warning }
Restoring a backup replaces ALL current data. Restart the application after a restore.

## Scheduled Channel Reset

For users experiencing stale channel logos in their media server (e.g. Jellyfin). Schedule a periodic purge of all Teamarr channels before your media server's guide refresh; the channels are recreated on the next EPG generation. Leave disabled unless you're seeing this problem.

| Field | Description |
|-------|-------------|
| **Enable Scheduled Channel Reset** | Toggle the periodic reset on/off |
| **Reset Schedule (Cron Expression)** | Standard cron format; presets like `30 2 * * *` (daily 2:30 AM) are available |

{: .note }
Set this to run shortly *before* your media server's scheduled guide refresh.

## Data Caches

Teamarr maintains several caches. Each tile shows live counts and a clear/refresh action.

| Cache | Contents | Action |
|-------|----------|--------|
| **Team & League Directory** | Cached teams and leagues from ESPN and TheSportsDB (enables offline matching) | **Refresh Directory** — pull the latest team/league data. A *Directory Stale* badge appears when a refresh is due. |
| **Game Data Cache** | Schedules, scores, and odds | **Clear Game Cache** |
| **Stream Match Cache** | Stream-to-event fingerprint matches | **Clear Match Cache** |
| **Run History** | Processing-run logs and statistics (auto-cleaned to 30 days after each run) | **Clear Run History** |

{: .note }
The Team & League Directory refreshes automatically on first startup. Manual refresh is useful after adding new leagues or when team rosters change significantly. Clearing the game-data or match caches forces fresh lookups on the next generation run.
