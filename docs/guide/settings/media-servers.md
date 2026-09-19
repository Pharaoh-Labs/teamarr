---
title: Media Servers
parent: Settings
grand_parent: User Guide
nav_order: 3
---

# Media Servers

Connect media servers so their live TV guides refresh automatically after each EPG generation. Configure under **Settings → Media Servers**.

![Settings → Media Servers — per-integration toggles and server rows](../../assets/images/settings-media-servers.png)

All four integrations support **any number of servers**, and every configured server across all four refreshes **in parallel** after generation — one slow or offline server never delays the others.

Each integration has its own **Enable** toggle — a configured-but-disabled integration is silently skipped, so if a server never refreshes, check the toggle first. Every server row has a **Test** button that reports the connected server and version. Rows added without a URL are dropped on save.

## Emby / Jellyfin

Each server entry takes a URL and either an API key (recommended — generate in the server dashboard) or username/password. Click **Add Server** for additional servers; an optional name keeps logs readable. After each generation Teamarr triggers a guide refresh on every entry so new programmes appear without waiting for the server's own scheduled refresh.

The refresh triggers the server's own **Refresh Guide** scheduled task and waits for it to complete (with live progress, up to 5 minutes) — that's why a generation run can sit near the end while a slow server churns.

Jellyfin 10.x and 12+ are both supported: Teamarr authenticates to Jellyfin with the standard `Authorization: MediaBrowser …` header rather than the legacy `X-Emby-Token` header that Jellyfin 12 removed.

Saved secrets display as `********` — leave them as-is to keep the stored value, or type over them to replace.

A failed refresh never fails the generation — but it is recorded. Each run stores every server's outcome (success, duration, error) with its run stats, and once a server has failed three consecutive runs the Dashboard status strip shows a **Media servers … not refreshing** warning (hover for the error) and the support bundle raises a `media_server_refresh_failing` signal. If you see it, check the URL first: a server that moved hosts fails instantly on every run and is otherwise invisible.

## Channels DVR

Channels DVR splits channel-list and guide data into two providers, so Teamarr refreshes both — sequenced, each step confirmed against the server's log before the next:

1. **M3U Source** — the custom channels source that pulls from Dispatcharr (`POST /providers/m3u/sources/<name>/refresh`); Teamarr waits for the server to confirm the lineup refreshed
2. **XMLTV Lineup** — the guide data source for those channels (`PUT /dvr/lineups/<id>`); Teamarr waits for the guide fetch and airing re-index to complete. Without this the channels update but the guide stays stale. If you don't pick a lineup, Teamarr derives `XMLTV-<source name>` automatically.

Both dropdowns are discovered live from the server once a URL is set (a saved selection that no longer exists on the server is flagged "not found on server"). The local Channels DVR API is unauthenticated by design — no credentials needed.

### Multiple servers

Useful when several households or locations share one Dispatcharr: click **Add Server** and give each entry its URL, M3U source, and lineup. Every listed server receives the same channel set and EPG. The east/west or per-household split (which channels each DVR actually shows) lives in Dispatcharr profiles, not in Teamarr.

{: .note }
Times shown inside programme titles/descriptions come from your templates and render in Teamarr's EPG timezone. Guide *grid* times always render in each client's local timezone automatically — XMLTV timestamps carry offsets. If your servers span timezones, avoid time-of-day template variables rather than looking for per-server EPGs.

## Plex

Plex's Live TV & DVR feature (pointed at Dispatcharr's HDHomeRun emulation) doesn't notice new or removed channels on its own — after each generation Teamarr updates the channel map (`PUT /media/grabbers/devices/<key>/channelmap`): it enables/disables channels on the matched device and binds each to its EPG data. This call is a **full-state-replace** — and not just for which channels are enabled: Teamarr first reads the device's current state (`GET /livetv/dvrs`), then writes back every currently-enabled channel's binding, including ones that aren't Teamarr's own (so other tools or manually-added channels sharing the same device keep their EPG data — a channel merely left out of the write gets disabled anyway), plus Teamarr's current channel set. This single call is also what refreshes Plex's guide data — it's the same request Plex's own UI sends when you open a tuner's Channel Matching screen and hit Save.

### Setup

Each server entry needs a **URL**, a **Plex Token** ([finding your token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)), and a **DVR / Device** selection. Once the URL and token are set, Teamarr discovers every DVR and its HDHomeRun devices from the server and lists them in the dropdown — pick the one whose URI matches the Dispatcharr HDHomeRun instance/profile this server should track. A device whose URI has no profile suffix (e.g. plain `/hdhr`) pulls channels from *every* Dispatcharr profile on that instance; only pick it if that's actually what you want, since the channel-map merge then has to distinguish Teamarr's channels from everyone else's on a much larger shared set.

If the device is scoped to one Dispatcharr profile, also pick that profile from the **Dispatcharr Channel Profile** dropdown — this limits which of Teamarr's managed channels get pushed to that device instead of pushing every profile's channels to it.

{: .note }
Teamarr assumes Dispatcharr/XMLTV numbering is aligned — that a tuner channel number and its XMLTV channel id match (Teamarr's documented default setup). Under that assumption no extra EPG-identifier lookup is needed; each of Teamarr's channels binds to itself in the channel map.

Saved tokens display as `********` — leave them as-is to keep the stored value, or type over them to replace.

Plex does not need explicit channel removal from Teamarr: channels that drop out of Dispatcharr's HDHomeRun lineup are pruned by Plex itself on its own polling cadence.
