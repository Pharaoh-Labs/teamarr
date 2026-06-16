---
title: EPG
parent: Settings
grand_parent: User Guide
nav_order: 4
docs_version: "2.3.0"
---

# EPG Settings

Configure EPG output, scheduling, channel reset, and default game durations.

## Output Settings

### Output Path

Where to write the generated XMLTV file. Default: `./data/teamarr.xml`

### Output Days Ahead

How many days of EPG data to include in the output. Default: 14 days.

### EPG Start (Hours Ago)

Include events that started up to this many hours ago. Useful for catching games still in progress. Default: 6 hours.

### Include Final Events

Toggle whether to include completed/final events in the EPG output.

## Scheduled Generation

Enable automatic EPG generation on a schedule.

### Cron Expression

Standard cron format for scheduling. Common presets are available:

| Preset | Expression | Description |
|--------|------------|-------------|
| Every Hour | `0 * * * *` | Run at the top of every hour |
| Every 2 Hours | `0 */2 * * *` | Run every 2 hours |
| Every 4 Hours | `0 */4 * * *` | Run every 4 hours |
| Every 6 Hours | `0 */6 * * *` | Run every 6 hours |
| Daily at Midnight | `0 0 * * *` | Run once daily at midnight |
| Daily at 6 AM | `0 6 * * *` | Run once daily at 6 AM |

### Run Now

Manually trigger an EPG generation run.

## Scheduled Channel Reset

For users experiencing stale channel logos in Jellyfin. Schedule a periodic purge of all Teamarr channels before your media server's guide refresh. Leave disabled if you're not having issues.

### Enable Scheduled Channel Reset

Toggle whether to enable periodic channel reset.

### Reset Schedule (Cron Expression)

Standard cron format for scheduling the reset. Common presets are available:

| Preset | Expression |
|--------|------------|
| Daily 2:30 AM | `30 2 * * *` |
| Daily 3:30 AM | `30 3 * * *` |
| Daily 4:30 AM | `30 4 * * *` |
| Daily 5:30 AM | `30 5 * * *` |

{: .note }
Set this to run shortly before your media server's scheduled guide refresh. Channels will be recreated on the next EPG generation.

## Default Durations

Set default event durations (in hours) for each sport. These are used when the actual event duration is unknown.

| Sport | Default |
|-------|---------|
| Basketball | 3.0 |
| Football | 3.5 |
| Hockey | 3.0 |
| Baseball | 3.5 |
| Soccer | 2.5 |
| MMA | 5.0 |
| Boxing | 4.0 |
| Tennis | 3.0 |
| Golf | 6.0 |
| Racing | 3.0 |
| Cricket | 4.0 |

## EPG Program-Data Matching

EPG program-data matching settings now live on the **Event Groups** settings tab — see [Event Group Settings → EPG Program Matching](event-groups.md#epg-program-matching). They moved there because matching is enabled per event group. The full how-it-works walkthrough is in the [EPG Program Matching guide](../epg-matching.md).
