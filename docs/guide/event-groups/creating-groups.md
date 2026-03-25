---
title: Creating Groups
parent: Event Groups
grand_parent: User Guide
nav_order: 1
docs_version: "2.3.0"
---

# Creating Event Groups

Event groups connect IPTV stream sources to Teamarr's sports data. Each group pulls streams from a Headendarr playlist or a Dispatcharr M3U account and matches them to real sporting events.

## The Subscription Model

Event groups use a **global subscription** to determine which sports and leagues to scan. This is configured in **Event Groups > Global Defaults**, not per-group.

**Global Defaults** include:
- **League subscriptions** — which non-soccer leagues to scan (e.g., NFL, NBA, NHL)
- **Soccer mode** — how to handle soccer leagues (follow teams, select leagues, or all)
- **Template assignments** — which template to use by sport or league
- **Team filter** — include/exclude specific teams from matching

All event groups inherit these defaults. Individual groups can override the subscription if needed (see Per-Group Overrides below).

## Basic Settings

When creating or editing a group:

### Name

A descriptive name for the group (e.g., "ESPN+ Sports", "NHL Backup").

### Source Account

Select which source account to pull streams from. In Dispatcharr this is an M3U account. In Headendarr this is a playlist.

### Stream Group

Select which stream group within the source account to use, or "All Groups" to include all streams from that account.

## Channel Configuration

### Channel Assignment Mode

| Mode | Description |
|------|-------------|
| **Auto** | Teamarr assigns channel numbers sequentially from the configured range |
| **Manual** | You specify a fixed starting channel number for this group |

### Channel Group

How channels are assigned in the target platform:

- **Use Default** — inherit from the platform defaults in Settings
- **Static** — assign all channels to a specific group where supported
- **Dynamic** — use patterns like `{sport}` or `{league}` to auto-create groups where supported

### Channel Profiles

Override the global default channel profiles for this group when using Dispatcharr:

- **Use Default** — inherit from Settings > Dispatcharr
- **Custom** — choose specific profiles for this group

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
| Teams | Extract team names | `(?P<home>.*)\s*vs\s*(?P<away>.*)` |
| Date | Extract date | `\d{1,2}/\d{1,2}/\d{4}` |
| Time | Extract time | `\d{1,2}:\d{2}\s*(?:AM\|PM)?` |
| League | Extract league hint | `(?:NFL\|NBA\|NHL):` |
| Fighters | Extract fighter names (MMA/Boxing) | `(?P<fighter1>.*)\s*vs\s*(?P<fighter2>.*)` |
| Event name | Extract event name | — |

Each extractor has an enable toggle. Leave disabled to use the built-in parser.

## Team Filter

Override the global default team filter for this group:

- **Use Default** — inherit from Global Defaults
- **Custom Filter** — define include/exclude teams specific to this group
- **Bypass for playoffs** — auto-include all playoff games regardless of team filter

## Per-Group Subscription Overrides

By default, groups inherit the global league subscription. To override:

1. Edit the group
2. Under "Subscription Override", toggle on custom leagues
3. Select the specific leagues this group should scan

This is useful when a stream source only covers certain sports (e.g., a hockey-only IPTV group that shouldn't waste time scanning for NFL events).

## Channel Sort Order

Controls how channels within this group are ordered:

| Mode | Description |
|------|-------------|
| **Time** | Sort by event start time |
| **Sport, then time** | Group by sport, then sort by time within each sport |
| **League, then time** | Group by league, then sort by time within each league |

## Advanced Options

### Enabled

Toggle the group on/off without deleting it. Disabled groups are skipped during EPG generation.

### Priority

When multiple groups could match the same stream, higher priority groups are checked first. Lower numbers = higher priority.
