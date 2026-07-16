---
title: Media Servers
parent: Settings
grand_parent: User Guide
nav_order: 3
docs_version: "2.11.1"
---

# Media Servers

Connect media servers so their live TV guides refresh automatically after each EPG generation. Configure under **Settings → Media Servers**.

## Emby / Jellyfin

Both take the same fields: URL, and either an API key (recommended — generate in the server dashboard) or username/password. After each generation Teamarr triggers a guide refresh so new programmes appear without waiting for the server's own scheduled refresh.

## Channels DVR

Channels DVR splits channel-list and guide data into two providers, so Teamarr refreshes both:

1. **M3U Source** — the custom channels source that pulls from Dispatcharr (`POST /providers/m3u/sources/<name>/refresh`)
2. **XMLTV Lineup** — the guide data source for those channels (`PUT /dvr/lineups/<id>`). Without this the channels update but the guide stays stale. If you don't pick a lineup, Teamarr derives `XMLTV-<source name>` automatically.

Both dropdowns are discovered live from the server once a URL is set. The local Channels DVR API is unauthenticated by design — no credentials needed.

### Multiple servers

Teamarr can push to any number of Channels DVR servers — useful when several households or locations share one Dispatcharr. Click **Add Server** and give each entry its URL, M3U source, and lineup (an optional name keeps logs readable). Every listed server receives the same channel set and EPG, and each is refreshed independently after generation — one server being offline never blocks the others.

The east/west or per-household split (which channels each DVR actually shows) lives in Dispatcharr profiles, not in Teamarr.

{: .note }
Times shown inside programme titles/descriptions come from your templates and render in Teamarr's EPG timezone. Guide *grid* times always render in each client's local timezone automatically — XMLTV timestamps carry offsets. If your servers span timezones, avoid time-of-day template variables rather than looking for per-server EPGs.
