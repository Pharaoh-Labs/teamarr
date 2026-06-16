---
title: Dashboard
parent: User Guide
nav_order: 2
docs_version: "2.3.0"
---

# Dashboard

The dashboard provides an at-a-glance overview of your Teamarr setup, statistics, and EPG generation history.

## Quick Actions

Located in the top-right corner, these buttons provide shortcuts to common tasks:

| Action | Description |
|--------|-------------|
| **Create Template** | Jump to the template creation form |
| **Import Teams** | Import teams from the league cache |
| **Import Event Group** | Import a stream group from Dispatcharr |
| **Generate EPG** | Manually trigger EPG generation |

## Statistics Quadrants

The dashboard displays four quadrants with detailed statistics. Some stats have tooltips with additional breakdowns - hover to view.

### Teams

| Stat | Description | Tooltip |
|------|-------------|---------|
| **Total** | Number of teams configured | None |
| **Leagues** | Number of unique leagues | League breakdown with logos |
| **Active** | Teams with upcoming or recent games | None |
| **Assigned** | Teams assigned to a Dispatcharr channel | None |

### Event Groups

| Stat | Description | Tooltip |
|------|-------------|---------|
| **Groups** | Number of event groups configured | Per-group match rates |
| **Leagues** | Unique leagues across all groups | League breakdown with logos |
| **Streams** | Total streams across all groups | None |
| **Matched** | Streams matched to real events | Match rate by group |

### EPG

| Stat | Description | Tooltip |
|------|-------------|---------|
| **Channels** | Total channels in EPG | Team vs event breakdown |
| **Events** | Number of game programmes | Team vs event breakdown |
| **Filler** | Filler programmes | Pregame/postgame/idle breakdown |
| **Total** | Total programmes in the EPG | None |

### Channels

| Stat | Description | Tooltip |
|------|-------------|---------|
| **Active** | Channels currently active in Dispatcharr | None |
| **Logos** | Channels with logo URLs | None |
| **Groups** | Channel groups in use | Group breakdown |
| **Deleted 24h** | Channels deleted in the last 24 hours (event cleanup) | None |

## EPG Generation History

A table showing recent EPG generation runs with:

| Column | Description |
|--------|-------------|
| **Status** | Completed (✓), failed (✗), cancelled (⊘), or running (spinner) |
| **Time** | Timestamp of the run |
| **Processed** | Teams / Event Groups processed in this run |
| **Programmes** | Total programmes generated. Hover for breakdown: Events, Pregame, Postgame, Idle |
| **Matched** | Streams successfully matched to events. Click for drill-down with search/filter |
| **Failed** | Streams that could not be matched. Click to see details and use the Fix button to open the event matcher |
| **Channels** | Active channels after this run |
| **Duration** | How long the generation took |
| **Size** | XMLTV file size |

{: .tip }
Click the **Matched** or **Failed** numbers to open a drill-down modal showing individual stream details, grouped by event group. Use the search bar to filter by group name or stream.

## Getting Started Guide

When no teams or templates are configured, the dashboard displays a getting started guide with four steps:

1. **Configure Settings** - Connect to Dispatcharr, set EPG output path and timezone
2. **Create Templates** - Define title/description formats using variables
3. **Add Teams** - Import teams for team-based EPG (one XMLTV channel per team — wire it to one of your existing Dispatcharr channels)
4. **Create Event Groups** - Import stream groups from Dispatcharr for event-based EPG (Teamarr creates dynamic channels per matched game)

Each step links directly to the relevant page. Once you have at least one template and either teams or event groups configured, the getting started guide is replaced by the statistics quadrants and generation history.