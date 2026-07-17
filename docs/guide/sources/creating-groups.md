---
title: Adding a Source
parent: Sources
grand_parent: User Guide
nav_order: 1
docs_version: "2.7.0"
redirect_from:
  - /guide/event-groups/creating-groups/
  - /guide/event-groups/creating-groups.html
---

# Adding a Source

Sources connect M3U stream groups to Teamarr's sports data. Each source pulls streams from a Dispatcharr M3U account and matches them to real sporting events.

## The Subscription Model

Sources use a **global subscription** to determine which sports and leagues to scan. This is configured in **Sources > Global Defaults**, not per-source.

**Global Defaults** include:
- **League subscriptions** — which non-soccer leagues to scan (e.g., NFL, NBA, NHL)
- **Soccer mode** — how to handle soccer leagues (follow teams, select leagues, or all)
- **Template assignments** — which template to use by sport or league
- **Team filter** — include/exclude specific teams from matching

All sources inherit these defaults. Individual sources can override the subscription if needed (see Per-Source Overrides below).

## Basic Settings

When creating or editing a source:

### Name

A descriptive name for the source (e.g., "ESPN+ Sports", "NHL Backup").

### M3U Account

Select which Dispatcharr M3U account to pull streams from.

### Stream Group

Select which stream group within the M3U account to use, or "All Groups" to include all streams from that account.

## Channel Configuration

### Channel Assignment Mode

| Mode | Description |
|------|-------------|
| **Auto** | Teamarr assigns channel numbers sequentially from the configured range |
| **Manual** | You specify a fixed starting channel number for this source |

### Channel Group

How channels are assigned to Dispatcharr channel groups:

- **Use Default** — inherit from Settings > Channels
- **Static** — assign all channels to a specific group
- **Dynamic** — use patterns like `{sport}` or `{league}` to auto-create groups

### Channel Profiles

Override the global default channel profiles for this source:

- **Use Default** — inherit from Settings > Dispatcharr
- **Custom** — choose specific profiles for this source

Dynamic wildcards like `{sport}` and `{league}` create profiles automatically in Dispatcharr.

## Stream Matching

### Stream Filters

Control which streams from the M3U group are processed:

- **Include regex** — only process streams matching this pattern
- **Exclude regex** — skip streams matching this pattern

### Custom Regex Extractors

Override how Teamarr parses stream names. By default, the built-in classifier handles most formats. Use custom regex when your IPTV provider uses unusual naming.

| Extractor | Purpose | Example Pattern |
|-----------|---------|-----------------|
| Teams | Extract team names | `(?P<team1>.*)\s*vs\s*(?P<team2>.*)` |
| Date | Extract date | `\d{1,2}/\d{1,2}/\d{4}` |
| Time | Extract time | `\d{1,2}:\d{2}\s*(?:AM\|PM)?` |
| League | Extract league hint | `(?:NFL\|NBA\|NHL):` |
| Fighters | Extract fighter names (MMA/Boxing) | `(?P<fighter1>.*)\s*vs\s*(?P<fighter2>.*)` |
| Event name | Extract event name | — |

Each extractor has an enable toggle. Leave disabled to use the built-in parser.

Named groups accept both `(?<name>...)` and Python's `(?P<name>...)` syntax. The recognized names are `team1`/`team2` (Teams), `fighter1`/`fighter2` (Fighters), `date` or `month`/`day`/`year` (Date), `time` or `hour`/`minute`/`ampm` (Time), `league` (League), and `event_name` (Event name). When the recognized named groups are present they take precedence, so extra unnamed groups — like a `(vs|v)` separator — are safe. Without named groups, the first capture group is used (first two for Teams/Fighters).

**Date patterns describe a format, not a literal date.** The best way to write one is with component groups that declare the format structurally — `(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{2,4})` says "day-first, then month, then year" and can never be misread. A single `(?P<date>...)` blob also works: Teamarr learns the source's format from the whole group before matching (one `16/07` in the list proves the source is day-first, so `05/07` parses as July 5). When the format can be verified this way, the date strictly gates candidate games (±1 day for provider-timezone boundaries) and a mismatch is reported as `date_mismatch`; when it can't be verified, the date only ranks candidates — it never blocks team matching outright.

**Pattern Tester** — the *Open Pattern Tester* button opens a workspace that runs your patterns against the group's real stream names. Highlighting is instant client-side JavaScript regex, and each stream also gets a **pipeline verdict badge** computed by the real Python extraction functions: green `✓ pipeline` means the pattern fully extracts (both teams captured, date/time actually parseable), amber `✗` lists the fields the pipeline would reject even if the regex visually matches. Invalid Python patterns and configuration pitfalls (e.g. month/day patterns without the date toggle) are called out in a banner. Hover a badge to see the extracted values.

**Tennis groups** use the **Teams** extractor for player pairs — the two named
groups become player 1 and player 2 (surname-based matching handles tournament
prefixes and extra tokens). The built-in parser also recognizes the
`Surname, First - Surname, First` provider format without any configuration.

## Team Filter

Override the global default team filter for this source:

- **Use Default** — inherit from Global Defaults
- **Custom Filter** — define include/exclude teams specific to this source
- **Bypass for playoffs** — auto-include all playoff games regardless of team filter

## Per-Source Subscription Overrides

By default, sources inherit the global league subscription. To override:

1. Edit the source
2. Under "Subscription Override", uncheck **Use global subscription**
3. The picker automatically seeds from your current global subscription
4. Deselect any leagues or sports you want to exclude, then save

Use **Match Global** at any time to reset the picker back to the current global subscription and start over.

This is useful when a stream source mixes sports and you need to exclude specific leagues from a source — for example, excluding MLB from a multi-sport source where the provider labels all streams with the same channel format regardless of sport.

## Channel Sort Order

Controls how channels within this source are ordered:

| Mode | Description |
|------|-------------|
| **Time** | Sort by event start time |
| **Sport, then time** | Group by sport, then sort by time within each sport |
| **League, then time** | Group by league, then sort by time within each league |

## Advanced Options

### Enabled

Toggle the source on/off without deleting it. Disabled sources are skipped during EPG generation.

### Priority

When multiple sources could match the same stream, higher priority sources are checked first. Lower numbers = higher priority.

### Team Stream Source

Allow team-branded streams (e.g. `NHL | Toronto Maple Leafs`) to match events where that team plays. Built-in stream filtering is automatically bypassed for this source.

### EPG Program Matching

Match static-named linear channels (e.g. `ESPN`, `FS1`, `NBA1`) in this source to events using Dispatcharr's program guide, and time-share one stream across many event channels near game time. Built-in filtering is bypassed for this source. See [EPG Program Matching](../matching/program-matching) for the full guide.
