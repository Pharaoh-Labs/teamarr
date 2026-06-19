---
title: Stream Priority
parent: Channels
grand_parent: User Guide
nav_order: 4
docs_version: "2.7.0"
---

# Stream Priority

Configure priority rules for ordering streams within consolidated channels. When multiple streams are merged into a single channel (see [Consolidation](consolidation)), these rules determine which stream is listed first — the "primary" stream.

This is distinct from [channel ordering](numbering#channel-ordering), which controls a channel's position in the lineup.

## Rule Types

| Type | Description | Example |
|------|-------------|---------|
| **M3U Account** | Prioritize streams from a specific M3U account | "Premium IPTV" = priority 1 |
| **Event Group** | Prioritize streams from a specific event group | "ESPN+ Group" = priority 2 |
| **Regex Pattern** | Prioritize streams matching a regex | `(?i)1080p` = priority 1 |
| **Stream Type** | Match by how the stream was recognized: **event stream**, **team stream**, or **EPG matched stream**. Optionally narrow a team-stream rule to specific teams. *EPG matched stream* covers streams attached via [EPG program-data matching](../matching/program-matching) — i.e. time-shared linear channels (ESPN, FS1) matched to events through Dispatcharr's program guide. | "Team stream" → priority 3 |
| **Home/Away Feed** | Match streams that look like a team's own broadcast (its home or away feed), detected from the stream name. Pick one or more teams. **Invert** flips it to match feeds that are *not* your selected teams (useful for pushing other teams' feeds to the back). | Selected teams → priority 1 |
| **Dispatcharr Group** | Match channel-source streams by their Dispatcharr channel group. The dropdown lists the groups you selected under [Use Dispatcharr channels as an EPG source](../matching/program-matching#dispatcharr-channels-as-an-epg-source). Only channel-source streams carry a Dispatcharr group; regular matched streams are unaffected. | "US \| Sports" → priority 2 |
| **Stream Stats** | Match streams whose quality meets numeric thresholds — **resolution width/height**, **source FPS**, **output/audio bitrate**, or **sample rate** — using `>`, `<`, `>=`, `<=`, `=`. Combine several conditions (all must pass). Use it to float HD / high-bitrate streams ahead of lower-quality ones. | `resolution_height >= 1080` and `source_fps >= 50` → priority 1 |
| **Everything Else** | Catch-all fallback applied to any stream not matched by the rules above. Always present and cannot be removed; set its priority to control where unmatched streams land. | Everything else → priority 99 |

{: .note }
**Stream Stats** values come from Dispatcharr's external stream probe and are cached per stream (refreshed when older than an hour). A freshly added stream has no stats until Dispatcharr has probed it, so a Stream Stats rule won't match it until then — a stream with no value for the metric is treated as not matching.

Lower priority numbers = higher priority. Rules are evaluated in order — the first matching rule determines the stream's priority.

### Team filters

Both **Stream Type** (team streams) and **Home/Away Feed** rules let you pick specific teams. Leaving the team selection empty makes the rule a no-op — a Stream Type rule with no teams matches *all* team streams, while a Home/Away Feed rule with no teams matches nothing. Use the **Default** button to load your configured team-filter include list, or **Clear** to start fresh.

### How Home/Away Feed detection works

Teamarr builds a name-matching pattern from your selected teams' names and abbreviations, then looks for feed indicators in the stream name — a matchup (`vs`, `at`, `@`), a side (`home`/`away`), a camera label (`cam 01`/`cam 02`), or a `(Team feed)` marker. A stream like `Cubs vs Pirates (Home)` is recognized as the Pirates' home feed. Generic streams with no feed markers (for example a plain `Pirates vs Cubs` with no side) are left for other rules to handle. Because detection relies on the stream name, results depend on your provider's naming conventions.

## Export & Import

Use the **Export** and **Import** buttons in the Stream Priority header to back up your rules or move them between instances.

- **Export** downloads your last **saved** rules (including the catch-all) as a `stream-ordering-rules.json` file. If you have unsaved edits in the editor, Teamarr warns you first — save before exporting if you want those edits included.
- **Import** reads a rules file and **replaces** your entire current rule set. Rules with an invalid type, value, or priority are skipped, and a catch-all is added automatically if the file doesn't include one.

Rules that reference an M3U account, event group, or Dispatcharr group match by **name**, so they carry over cleanly to another instance as long as the same names exist there. Team-based rules (Stream Type and Home/Away Feed) reference provider team IDs and only apply to teams present on the target instance.
