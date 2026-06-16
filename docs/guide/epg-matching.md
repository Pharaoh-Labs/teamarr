---
title: EPG Program Matching
parent: User Guide
nav_order: 10
docs_version: "2.6.0"
---

# EPG Program Matching
{: .no_toc }

Match static-named linear channels (ESPN, FS1, NBA1) to events using Dispatcharr's program guide, and time-share one stream across many event channels near game time.

<details open markdown="block">
  <summary>Table of contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## The problem it solves

Teamarr normally matches a stream to an event by reading the **stream name** — `Cubs vs Cardinals` becomes the Cubs–Cardinals game. That works for event-named streams, but a traditional **linear channel** carries many different games across a day under one unchanging name:

> `Fox Sports 1` airs *Wales vs Ghana* at 1pm, an *MLB* game at 4pm, and *College Baseball* at 8pm — all under the single stream name "Fox Sports 1".

The stream name `Fox Sports 1` tells Teamarr nothing about which game is on, so name matching can't place it. **EPG program matching** solves this by reading the channel's **program guide** instead of its name, and attaching the linear stream to each event's channel only for that game's window.

The result: **one** linear stream serves **many** event channels — swapping in shortly before each game and out shortly after — while each event channel keeps its own stable identity, generated EPG, and filler.

---

## How it works

1. **Read the guide.** For each opted-in group, Teamarr asks Dispatcharr for the EPG **programs** airing on the group's streams (`GET /api/epg/programs/search/`).
2. **Match program titles, not stream names.** Each program's title + subtitle (`MLB Baseball` + `Cubs at Cardinals`) goes through the *same* team-matching pipeline Teamarr uses for stream names, and is matched to a real event.
3. **Time-share the stream.** A linear stream that airs many programs is attached to each matched event's channel only for that program's window (start − *attach before*, end + *detach after*), then detached when the window ends. Studio shows and replays are skipped.

### Where the EPG comes from — you don't map it

The program data comes from **Dispatcharr's own EPG sources** — the XMLTV guides you already configured in Dispatcharr. **You do not tell Teamarr which EPG belongs to which group.** Teamarr links each stream to its guide automatically using a precedence cascade (most authoritative first):

| # | Strategy | When it applies |
|---|----------|-----------------|
| 1 | **Channel mapping** | The stream is assigned to a Dispatcharr channel whose EPG is linked (`epg_data_id`). A *curated* mapping — the most trusted, so it wins outright. |
| 2 | **Direct tvg_id** | Your M3U stream's `tvg-id` already matches an **active** imported EPG channel id (namespace-aligned setups). |
| 3 | **Name match** | The stream's name matches an **active** imported EPG channel's name exactly after normalization (stripping `HD`/`FHD`/`(US)`, country prefixes like `US:`/`UK:`, etc.). **Strict:** ambiguous names are skipped, so `ESPN` never resolves to `ESPN2`. |
| 4 | **Xtream (XC) provider EPG** | *Opt-in fallback.* For streams the above leave unmatched, when the group's M3U account is an Xtream Codes panel, Teamarr fetches the provider's **own** `xmltv.php` and matches against it. See [Xtream fallback](#xtream-xc-provider-epg-fallback). |

Strategies 2–3 match against your **active** imported EPG sources only (disabled sources and Teamarr's own `_Teamarr` output are excluded). They mean EPG matching works on **raw stream groups** — you do **not** need to pre-build streams into Dispatcharr channels first.

### Xtream (XC) provider EPG fallback

Strategies 1–3 require a valid stream-to-EPG mapping **inside Dispatcharr**. Many providers' channels — especially **regional sports networks** — have no guide in your imported sources, so they never match.

As a backup, enable **Settings → Event Groups → "Fall back to Xtream (XC) provider EPG"**. When a group's M3U account is an Xtream Codes panel, Teamarr fetches that provider's own EPG (`{server}/xmltv.php`) directly and matches the still-unresolved streams against it. Because the provider's guide is **source-matched** to its own M3U, the stream `tvg-id` *is* the guide channel id — an exact match, no guessing.

- **Off by default** (opt-in). It downloads the provider's guide once per XC account and caches it on disk, re-fetching only when the cache is older than **Cache for (hours)** (default 24). Provider guides change slowly, so a long cache keeps generations fast.
- It only **fills gaps** — your curated Dispatcharr guide always takes priority.
- Provider guides vary in quality; some carry the generic network schedule rather than the live sports override.

### Dispatcharr channels as an EPG source

Normally each Event Group sources its candidate streams from an **M3U group** — so EPG matching considers *every* stream in that provider group. If you'd rather match only the channel versions you've **already curated in Dispatcharr**, enable **Settings → Event Groups → "Use Dispatcharr channels as an EPG source"**.

When on, Teamarr adds a second, **additive** source that:

- Enumerates the Dispatcharr **channels** you've mapped that carry an active, non-`_Teamarr` EPG link.
- Takes the **streams assigned to each channel** as candidates, tagged with that **channel's own EPG** (strategy 1 — the most authoritative mapping).
- Runs them through the same matching → channel-creation → time-window pipeline.

It runs **alongside** your per-group M3U matching (not instead of it); matches are consolidated onto the same event channels by event identity. Teamarr's **own generated channels are excluded** — they're output, not input. The source is managed for you as a hidden system group ("Dispatcharr Channels") that appears in stats but not in the Event Groups list; created channels use your global/per-league channel-group, profile, and template defaults.

**Scope it to specific groups.** When you enable the toggle, a **Dispatcharr groups to include** picker appears. Select the channel groups you actually want matched — Teamarr then scans only those, skipping the matching work for everything else (faster generation). Leave it empty to include all groups. Your selection also becomes a **Dispatcharr Group** option in [stream ordering](settings/channels.md#stream-ordering), so you can prioritize a group's streams within consolidated channels.

---

## Requirements

- **Dispatcharr with the program-search API** — `GET /api/epg/programs/search/`, **confirmed on Dispatcharr `0.24.0`**. Teamarr feature-detects this on connect; on older builds the feature simply stays off (the toggle has no effect), with no errors.
- **A configured EPG source in Dispatcharr** whose guide covers your linear channels.
- A stream resolvable to that guide by one of strategies 1–3 above — or, with the opt-in Xtream fallback, an XC provider whose own EPG covers it. Streams that resolve to nothing are left to normal name matching.

{: .note }
EPG matching is **opt-in and off by default** — enabled per event group. There is no global on/off switch.

---

## Enabling it

### 1. Per-group switch — Event Group settings

On each Event Group, enable **EPG program matching**. Only groups that opt in are scanned. This is the right switch for groups that contain linear channels (e.g. a "US \| Sports" group of ESPN/FS1/SEC Network feeds). There is **no global switch** — each group opts in on its own.

Enabling it on a group automatically **bypasses built-in stream filtering** for that group, because static linear names (`ESPN`, `NBA1`) have no `vs`/`@` separator and would otherwise be dropped before matching.

### 2. Buffers — Settings → Event Groups

Two global buffer fields tune the attach/detach window for every group that opts in:

| Setting | Default | Description |
|---------|---------|-------------|
| **Attach before (minutes)** | 60 | How long *before* a program's start the stream attaches to the event channel. |
| **Detach after (minutes)** | 60 | How long *after* a program's end the stream detaches. |

Buffers give viewers lead-in/lead-out time and absorb schedule slippage. They apply in full — the buffers you set drive the whole window. If a large buffer makes two adjacent programs on the same channel overlap, the stream is simply attached to **both** event channels during the overlap; nothing is trimmed. Buffer changes take effect on the next generation run, including for already-attached streams.

### Bulk enabling

The per-group toggle is also available in **bulk edit** (select multiple groups → Edit) and at **bulk import** time, so you can flip a whole batch of linear-channel groups at once.

---

## Seeing what matched

### The "EPG Matched" badge

Groups with EPG matching enabled show a violet **EPG Matched** badge in the Event Groups list, alongside the existing **Team Streams** / **Regex** badges.

### Preview

Use **Preview stream matches** on a group to see EPG matches before a real generation run — the preview exercises the same EPG path (it carries the stream `tvg_id` through to the matcher).

### Stream ordering — the "EPG matched stream" type

In **Settings → Channels → Stream Ordering**, add a **Stream Type** rule and choose **EPG matched stream** to prioritize streams that were attached via EPG matching. Use it to push time-shared linear streams ahead of — or behind — name-matched (event/team) streams within a consolidated channel. See [Channels settings](settings/channels.md#stream-ordering).

{: .note }
The ordering rule reads a `match_method` tag stored on each attached stream. Streams attached *before* this feature existed carry no tag until they're re-matched on the next generation run, so the rule applies going forward.

---

## Caveats & limits

- **Attach/detach precision is bounded by generation cadence.** A stream can only swap in/out when EPG generation runs (your scheduled cron). With hourly runs, expect roughly hourly granularity — the buffers exist partly to cover this.
- **Replays and studio shows are intentionally skipped.** Programs tagged *Classic Sport Event* (replays) or *Sports non-event* (studio/talk) don't match. A live channel showing offseason replays will legitimately match little or nothing.
- **A matched event must actually exist.** EPG matching pairs a program to a real event in your subscribed leagues. A guide entry for a game in a league you don't follow (or a finished game) won't match.
- **Strict name matching skips ambiguous names** to avoid wrong matches. Some channels may not resolve by name alone and will rely on the channel-mapping or direct-tvg_id strategies.

---

## Troubleshooting: "nothing matched"

Work down this list:

1. **Group opted in?** Enable **EPG program matching** on the Event Group (there is no global switch).
2. **Program-search supported?** It needs a Dispatcharr build with `/api/epg/programs/search/` (0.24.0+). On older builds the feature is silently off.
3. **Do the streams resolve to a guide?** They must match by a linked Dispatcharr channel, direct tvg_id, or an exact normalized name against an **active** imported EPG. Channels with no EPG coverage can't match — unless the provider is Xtream and you enable the **XC provider EPG fallback** (Settings → Event Groups).
4. **Is anything actually on?** Check the channel's guide — overnight/offseason slots are mostly replays and studio shows, which are skipped by design.
5. **Are the leagues subscribed?** The program's game must map to an event in a league you follow.

---

## Related

- [EPG Settings](settings/epg.md) — attach/detach buffers, channel-source, and XC fallback
- [Channels settings → Stream Ordering](settings/channels.md#stream-ordering) — the EPG matched stream ordering option
- [Consumer layer architecture](../reference/architecture/consumer-layer.md#epg-title-matching-matchingepg_matcherpy-matchingepg_indexpy) — internals
- [Dispatcharr layer architecture](../reference/architecture/dispatcharr-layer.md#program-data-search-epg-matching) — the program-search client
