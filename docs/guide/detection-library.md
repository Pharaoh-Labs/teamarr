---
title: Detection Library
parent: User Guide
nav_order: 8
docs_version: "2.3.1"
---

# Detection Library

The Detection Library manages how Teamarr classifies and identifies streams. It contains keywords, patterns, and team aliases that help the stream matcher understand what sport, league, and event a stream belongs to.

The library has five tabs, each handling a different aspect of stream classification.

## Team Aliases

Map alternate team names to their official names. IPTV providers often use shortened or unofficial team names (e.g., "Niners" instead of "San Francisco 49ers"). Aliases tell Teamarr to treat them as the same team.

### Table Columns

| Column | Description |
|--------|-------------|
| **Alias** | The alternate name that appears in stream names |
| **Maps To** | The official team name it resolves to |
| **League** | Which league the alias applies to |
| **Actions** | Delete button |

### Adding an Alias

1. Click **Add Alias**
2. Enter the **alias text** (the name your IPTV provider uses)
3. Select a **league** to filter the team list
4. Select the **team** the alias maps to
5. Click **Create**

{: .note }
To change an alias, delete it and create a new one. Aliases cannot be edited in place.

## Event Type Detection

Keywords that identify what type of event a stream represents. These help Teamarr distinguish between regular games, fight cards, tournaments, and other event formats.

### Table Columns

| Column | Description |
|--------|-------------|
| **Keyword/Pattern** | The keyword or regex pattern to match |
| **Type** | Text (literal match) or Regex (pattern match) |
| **Priority** | Higher numbers are checked first |
| **Status** | On/Off — disabled keywords are skipped |
| **Actions** | Toggle, Edit, Delete |

## League Hints

Keywords that identify which league a stream belongs to. When a stream name contains a league hint keyword, Teamarr narrows its event search to that league.

### Example

| Keyword | Target | Effect |
|---------|--------|--------|
| `UCL` | `uefa.champions` | Streams with "UCL" match Champions League events |
| `La Liga` | `esp.1` | Streams with "La Liga" match Spanish Primera Division |
| `CFL` | `cfl` | Streams with "CFL" match Canadian Football League |

### Table Columns

Same as Event Type Detection, plus a **Target** column showing the league code the keyword maps to.

## Sport Hints

Keywords that identify which sport a stream belongs to. Sport hints are checked when no league hint is found, providing a broader classification.

### Multi-Sport Hints

Some keywords are ambiguous across sports. For example, "football" could mean American Football or Soccer depending on context. Sport hints support **comma-separated targets** to map one keyword to multiple sports:

| Keyword | Target | Effect |
|---------|--------|--------|
| `football` | `Soccer, Football` | Tries matching against both Soccer and Football events |
| `footy` | `Soccer` | Only matches Soccer events |
| `hoops` | `Basketball` | Only matches Basketball events |

When entering multiple sports, separate them with commas. They display as individual badges in the table.

### Table Columns

Same as Event Type Detection, plus a **Target** column showing sport name(s) as badges.

## Separators

Matchup delimiters that split a stream name into two teams. Teamarr ships with built-in separators (`vs`, `@`, `at`, `x`, `contra`, and others), and this tab lets you add locale-specific ones your provider uses.

The most common reason to add one is the **hyphen** used by Spanish and other European EPGs:

| Stream name | Needs separator | Result |
|-------------|-----------------|--------|
| `España - Inglaterra` | ` - ` | Splits into `España` vs `Inglaterra` |

{: .warning }
Keep the surrounding spaces (`" - "`, not `"-"`) and add hyphen-style separators sparingly. A bare hyphen with no spaces matches inside ordinary words and hyphenated names, causing streams to be split incorrectly. Teamarr preserves the exact spacing you type for separators.

Separators have no **Target Value** — the field is hidden on this tab.

{: .note }
Live-broadcast prefixes such as `DIRECTO`, `EN DIRECTO`, `EN VIVO`, `AO VIVO`, `DIRETTA`, and `DIREKT` are stripped automatically during matching, so a stream like `DIRECTO España - Inglaterra` is read as `España - Inglaterra`. You don't need to configure these.

## Keyword Fields

All keyword tabs (Event Type, League Hints, Sport Hints, Separators) share the same create/edit form:

| Field | Description |
|-------|-------------|
| **Keyword/Pattern** | The text or regex to match in stream names |
| **Regular expression** | Toggle between literal text matching and regex |
| **Enabled** | Whether this keyword is active |
| **Target Value** | What the keyword maps to (league code or sport name). Not used for Event Type or Separators. |
| **Priority** | Numeric priority — higher values are checked first |
| **Description** | Optional notes about the keyword |

### Enable/Disable

Click the toggle icon in the Actions column to enable or disable a keyword without deleting it. Disabled keywords appear dimmed and are skipped during stream classification.

{: .note }
Team aliases don't have an enable/disable toggle — they're always active until deleted.

## Import & Export

Both aliases and keywords can be exported and imported as JSON files. This is useful for sharing configurations or backing up your detection rules.

### Export

Click **Export** to download the current tab's data as a JSON file.

### Import

Click **Import** and select a JSON file. The import results show how many items were created, updated, or skipped.

{: .tip }
Export your detection library before making major changes. If something goes wrong with matching after editing keywords, you can re-import the backup.
