---
title: Stream Priority
parent: Channels
grand_parent: User Guide
nav_order: 4
docs_version: "2.9.1"
---

# Stream Priority

Configure rules for ordering streams within consolidated channels. When multiple streams are merged into a single channel (see [Consolidation](consolidation)), these rules determine which stream is listed first — the "primary" stream.

This is distinct from [channel ordering](numbering#channel-ordering), which controls a channel's position in the lineup.

## Two ways to rank: Scoring and Priority

Every rule belongs to one of two classes. Both use the same [rule types](#rule-types) — the difference is *how* a match affects ordering.

| Class | How it ranks | When to use |
|-------|--------------|-------------|
| **Scoring** *(default for new rules)* | Additive. Each matching rule adds its signed **points**; a stream's points are summed and the highest total sorts first. Negative points push a stream down. | The everyday case — nudge streams up or down by several attributes at once (preferred provider, HD, right feed) and let the totals decide. |
| **Priority** *(hard order)* | The first Priority rule a stream matches sets its **band**. Bands always outrank scoring, so a Priority match is a hard "must always win / must always lose". Lower number = higher priority. | Escape hatch for absolutes: "streams from this account always come first," "EPG-matched streams always come last." |

**How the two combine.** A stream is ranked by its hard band first, then by its total score *within* that band, then by the order it was added. Because bands are strict, no amount of score moves a stream out of its band — scoring only reorders streams that share a band. Streams that match no Priority rule fall into the baseline band (see [Everything Else](#the-everything-else-baseline)) and are ranked purely by score.

{: .note }
**Upgrading from an earlier version?** Your existing rules are preserved exactly as **Priority** rules, in the same order, so ordering is unchanged until you deliberately add Scoring rules. Exported rule files from older versions also import cleanly.

### Example: push EPG-matched streams to the back

A common goal is *"prefer my premium provider, but always keep EPG-matched (time-shared linear) streams last — even when they come from that provider."* Scoring handles this directly:

- **Scoring** rule — *M3U Account* = "Premium IPTV" → **+100**
- **Scoring** rule — *Stream Type* = EPG matched stream → **−100000**

A premium stream scores +100 and floats up; a premium stream that is *also* EPG-matched nets −99900 and sinks below everything. The large negative simply outweighs the provider bonus — no special compound rule needed. (You could equally make the EPG rule a **Priority** rule at the worst band for the same effect.)

## Rule Types

Any rule type can be used as a Scoring rule or a Priority rule.

| Type | Description | Example |
|------|-------------|---------|
| **M3U Account** | Match streams from a specific M3U account | "Premium IPTV" → +100 |
| **Event Group** | Match streams from a specific event group | "ESPN+ Group" → +20 |
| **Regex Pattern** | Match streams whose name matches a regex | `(?i)1080p` → +15 |
| **Stream Type** | Match by how the stream was recognized: **event stream**, **team stream**, or **EPG matched stream**. Optionally narrow a team-stream rule to specific teams. *EPG matched stream* covers streams attached via [EPG program-data matching](../matching/program-matching) — i.e. time-shared linear channels (ESPN, FS1) matched to events through Dispatcharr's program guide. The three types are mutually exclusive: an EPG-matched stream only ever matches the *EPG matched stream* option, never *event* or *team* — regardless of rule order. | Team stream → +10 |
| **Home/Away Feed** | Match streams that look like a team's own broadcast (its home or away feed), detected from the stream name. Pick one or more teams. **Invert** flips it to match feeds that are *not* your selected teams (useful for pushing other teams' feeds down). | Selected teams → +30 |
| **Dispatcharr Group** | Match channel-source streams by their Dispatcharr channel group. The dropdown lists the groups you selected under [Use Dispatcharr channels as an EPG source](../matching/program-matching#dispatcharr-channels-as-an-epg-source). Only channel-source streams carry a Dispatcharr group; regular matched streams are unaffected. | "US \| Sports" → +5 |
| **Stream Stats** | Match streams whose quality meets numeric thresholds — **resolution width/height**, **source FPS**, **output/audio bitrate**, or **sample rate** — using `>`, `<`, `>=`, `<=`, `=`. Combine several conditions (all must pass). Use it to float HD / high-bitrate streams ahead of lower-quality ones. | `resolution_height >= 1080` and `source_fps >= 50` → +25 |
| **Everything Else** | Optional catch-all baseline for any stream not matched by a Priority rule. Only meaningful as a **Priority** rule — it sets the band unmatched streams land in. | Everything else → priority 99 |

{: .note }
**Stream Stats** values come from Dispatcharr's external stream probe and are cached per stream (refreshed when older than an hour). A freshly added stream has no stats until Dispatcharr has probed it, so a Stream Stats rule won't match it until then — a stream with no value for the metric is treated as not matching.

### Points

Scoring rules take a **signed integer** in the Points column (the ± field). New scoring rules start at **+10**. Positive points promote a stream, negative points demote it, and totals accumulate across every scoring rule a stream matches. There is no need to space values out — points only ever compete *within* a band, so `+1`/`+2`/`+3` ranks the same as `+10`/`+20`/`+30`.

### The "Everything Else" baseline

Unlike earlier versions, a catch-all is **no longer added automatically**. Streams that match no Priority rule already fall to a default baseline band, so you only need an explicit **Everything Else** row when you want to place that baseline at a specific priority relative to your other Priority bands. Add one with the **Add baseline (Everything Else)** button in the Priority section; there can only be one.

### Team filters

Both **Stream Type** (team streams) and **Home/Away Feed** rules let you pick specific teams. Leaving the team selection empty makes the rule a no-op — a Stream Type rule with no teams matches *all* team streams, while a Home/Away Feed rule with no teams matches nothing. Use the **Default** button to load your configured team-filter include list, or **Clear** to start fresh.

### How Home/Away Feed detection works

Teamarr builds a name-matching pattern from your selected teams' names and abbreviations, then looks for feed indicators in the stream name — a matchup (`vs`, `at`, `@`), a side (`home`/`away`), a camera label (`cam 01`/`cam 02`), or a `(Team feed)` marker. A stream like `Cubs vs Pirates (Home)` is recognized as the Pirates' home feed. Generic streams with no feed markers (for example a plain `Pirates vs Cubs` with no side) are left for other rules to handle. Because detection relies on the stream name, results depend on your provider's naming conventions.

## Live events keep their #1 stream

While an event is airing, scheduled generation runs won't displace the channel's top stream — the one a viewer is most likely watching. Rule changes still take effect in the background (priorities are recomputed and stored), and new streams that match mid-event are added **below** the current #1, but the top slot itself stays put until the event ends. The first run after the event restores full rule ordering.

A **manually triggered** generation run bypasses this pin — that's your escape hatch if the pinned stream is the wrong one: fix your rules (or remove the bad stream) and hit Generate.

## Why is a stream ordered this way?

On the **Channels** page, click a stream's priority number to open a popover that explains its ordering against your current rules: the hard **band** it landed in (and which Priority rule, if any, set it), plus each **Scoring** contribution with its points. If the stored number was computed under rules you've since changed, the popover marks it stale so you know a regeneration will re-rank it.

## Export & Import

Use the **Export** and **Import** buttons in the Stream Priority header to back up your rules or move them between instances.

- **Export** downloads your last **saved** rules — including each rule's class (Scoring/Priority) and points — as a `stream-ordering-rules.json` file. If you have unsaved edits in the editor, Teamarr warns you first — save before exporting if you want those edits included.
- **Import** reads a rules file and **replaces** your entire current rule set. Rules with an invalid type, value, or priority are skipped. Older files that predate scoring import fine: rules with no class default to **Priority**. No catch-all is force-added.

Rules that reference an M3U account, event group, or Dispatcharr group match by **name**, so they carry over cleanly to another instance as long as the same names exist there. Team-based rules (Stream Type and Home/Away Feed) reference provider team IDs and only apply to teams present on the target instance.
