---
title: Media Servers
parent: Settings
grand_parent: User Guide
nav_order: 3
docs_version: "2.11.1"
---

# Media Servers

Connect media servers so their live TV guides refresh automatically after each EPG generation. Configure under **Settings → Media Servers**.

All three integrations support **any number of servers**, and every configured server across all three refreshes **in parallel** after generation — one slow or offline server never delays the others.

## Emby / Jellyfin

Each server entry takes a URL and either an API key (recommended — generate in the server dashboard) or username/password. Click **Add Server** for additional servers; an optional name keeps logs readable. After each generation Teamarr triggers a guide refresh on every entry so new programmes appear without waiting for the server's own scheduled refresh.

Saved secrets display as `********` — leave them as-is to keep the stored value, or type over them to replace.

## Channels DVR

Channels DVR splits channel-list and guide data into two providers, so Teamarr refreshes both:

1. **M3U Source** — the custom channels source that pulls from Dispatcharr (`POST /providers/m3u/sources/<name>/refresh`)
2. **XMLTV Lineup** — the guide data source for those channels (`PUT /dvr/lineups/<id>`). Without this the channels update but the guide stays stale. If you don't pick a lineup, Teamarr derives `XMLTV-<source name>` automatically.

Both dropdowns are discovered live from the server once a URL is set. The local Channels DVR API is unauthenticated by design — no credentials needed.

### Multiple servers

Useful when several households or locations share one Dispatcharr: click **Add Server** and give each entry its URL, M3U source, and lineup. Every listed server receives the same channel set and EPG. The east/west or per-household split (which channels each DVR actually shows) lives in Dispatcharr profiles, not in Teamarr.

{: .note }
Times shown inside programme titles/descriptions come from your templates and render in Teamarr's EPG timezone. Guide *grid* times always render in each client's local timezone automatically — XMLTV timestamps carry offsets. If your servers span timezones, avoid time-of-day template variables rather than looking for per-server EPGs.
