---
title: Settings
parent: User Guide
nav_order: 3
has_children: true
---

# Settings

**Settings** holds only system and integration configuration. Per-feature settings live inside the section they belong to, so you tune them where you use them:

| Looking for… | It now lives in… |
|--------------|------------------|
| Event group / source matching defaults | [Sources](../sources/) |
| Team-based stream settings | [EPG → Teams](../epg/teams/) |
| Channel lifecycle, numbering, stream ordering | [Channels](../channels/) |
| Dispatcharr default profiles, stream profile, channel group / group mode | [Channels → Dispatcharr Output](../channels/output) |
| EPG-match attach/detach buffers and tuning | [Matching](../matching/) |
| EPG output path, window, durations, XMLTV metadata | [EPG → Output](../epg/output) |

What remains under Settings:

- **[General](general)** — timezone, time format, scheduled generation, TheSportsDB API key, and update notifications
- **[Dispatcharr](dispatcharr)** — connection, EPG source, and logo cleanup
- **[Media Servers](media-servers)** — Emby, Jellyfin, and Channels DVR integration (multiple servers supported for each)
- **[Advanced](advanced)** — backup/restore (including scheduled backups), scheduled channel reset, Gracenote category overrides, and the data caches

{: .note }
If a setting you remember from an earlier version isn't here, it was moved into its feature area — check the table above.
