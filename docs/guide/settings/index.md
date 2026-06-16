---
title: Settings
parent: User Guide
nav_order: 9
has_children: true
docs_version: "2.7.0"
---

# Settings

As of v2.7.0, **Settings** holds only system and integration configuration. Per-feature settings now live inside the section they belong to, so you tune them where you use them:

| Looking for… | It now lives in… |
|--------------|------------------|
| Event group / source matching defaults | [Sources](../sources/) |
| Team-based stream settings | [EPG → Teams](../epg/teams/) |
| Channel lifecycle, numbering, stream ordering | [Channels](../channels/) |
| EPG-match attach/detach buffers and tuning | [Matching](../matching/) |
| EPG output path, window, durations, XMLTV metadata | [EPG → Output](../epg/output) |

What remains under Settings:

- **[General](general)** — timezone, time format, scheduled generation, TheSportsDB API key, and update notifications
- **[Dispatcharr](dispatcharr)** — connection, EPG source, default profiles/groups, and logo cleanup
- **Media Servers** — Emby, Jellyfin, and Channels DVR integration
- **[Advanced](advanced)** — backup/restore and the data caches (directory, game data, match cache, run history)

{: .note }
If a setting you remember from an earlier version isn't here, it was moved into its feature area — check the table above.
