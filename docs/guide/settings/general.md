---
title: General
parent: Settings
grand_parent: User Guide
nav_order: 1
docs_version: "2.7.0"
---

# General Settings

System-level configuration: time, scheduled generation, the TheSportsDB API key, and update notifications.

## Time / Localization

Teamarr uses two timezones:

| Timezone | What it controls | Where it's set |
|----------|------------------|----------------|
| **UI Display** | How times appear in this web interface | The `TZ` environment variable (read-only in the UI) |
| **EPG Output** | The timezone written into generated EPG/XMLTV and template variables like `{game_time}` | Editable here |

```yaml
# docker-compose.yml example
environment:
  - TZ=America/New_York
```

{: .note }
The two can differ on purpose — browse in your local time while your media server expects EPG in its own timezone.

### Time Formatting

- **Time format** — 12-hour (`3:45 PM`) or 24-hour (`15:45`). Applies to both the UI and EPG output.
- **Show timezone abbreviation** — toggle whether abbreviations (EST, PST, …) appear alongside times.

## Schedule

Enable automatic EPG generation on a cron schedule. A status badge shows whether the scheduler is **Running** or **Stopped**, along with the last run time.

### Cron Expression

Standard cron format. Presets are one click away:

| Preset | Expression |
|--------|------------|
| Every Hour | `0 * * * *` |
| Every 2 Hours | `0 */2 * * *` |
| Every 4 Hours | `0 */4 * * *` |
| Every 6 Hours | `0 */6 * * *` |
| Daily at Midnight | `0 0 * * *` |
| Daily at 6 AM | `0 6 * * *` |

A preview shows the next few run times for the expression you enter.

### Run Now

Manually trigger a full generation run without waiting for the schedule.

## TheSportsDB API Key

Optional premium API key for TheSportsDB. The card header shows your current tier.

| Tier | Rate Limit | Coverage | Cost |
|------|------------|----------|------|
| **Free** | 30 req/min | Limited (a few events per league per day) | Free |
| **Premium** | 100 req/min | Full event coverage | ~$9/mo |

Some TSDB leagues (CFL, Unrivaled, boxing, Norwegian hockey) work fine on the free tier. Premium leagues — AFL, cricket (IPL, BBL, SA20), and Svenska Cupen — need a premium key for full event coverage. The league picker shows a crown icon on premium leagues.

Use the **Validate** button to test your key before saving. Get a key at [thesportsdb.com/pricing](https://www.thesportsdb.com/pricing).

See [TSDB Provider](../../reference/providers/tsdb.md) for technical details.

## Update Notifications

Teamarr can check for new versions and notify you when updates are available.

- **Current Version** — shows your running version and the latest available version. Dev builds show commit hashes; stable builds show version numbers. The release date is shown in your configured timezone.
- **Enable automatic update checks** — toggle update checking on/off.
- **Notify about stable releases** — get notified about new stable versions.
- **Notify about dev builds** — get notified about new dev commits (if you're running a dev build).
- **Check Now** — manually trigger a check. Results are cached for one hour.
