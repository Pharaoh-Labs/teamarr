---
title: EPG
parent: User Guide
nav_order: 10
docs_version: "2.3.0"
---

# EPG

The EPG page is where you generate, download, and monitor your XMLTV output. It provides controls for on-demand generation, a preview of the XML, and a history of past runs.

## Actions Bar

The top bar contains the primary EPG controls:

| Action | Description |
|--------|-------------|
| **Generate** | Manually triggers EPG generation. Disabled while a run is already in progress. A progress toast appears showing the current phase (Teams, Event Groups, Finalizing) and percentage |
| **Cancel** | Appears while a run is in progress. Cancels the current generation |
| **Download** | Downloads the latest XMLTV file to your browser |
| **XMLTV URL** | Copyable URL (e.g., `http://host:9195/api/v1/epg/xmltv`) for pointing media players, Headendarr, or Dispatcharr at the live EPG output |

## Statistics Cards

Six cards across the top summarize the current EPG content:

| Card | Description |
|------|-------------|
| **Channels** | Total channels in the current EPG |
| **Events** | Game and match programmes |
| **Pregame** | Pregame filler programmes |
| **Postgame** | Postgame filler programmes |
| **Idle** | Idle filler programmes for team channels with no game scheduled |
| **Total** | Sum of all programmes (events + pregame + postgame + idle) |

## XML Preview

An expandable section showing the raw XMLTV output. A search bar at the top lets you find specific channels or programmes by name. This is useful for verifying template output and debugging formatting issues.

## Recent Runs

A table of recent EPG generation runs. This is the same RunHistoryTable shown on the Dashboard.

| Column | Description |
|--------|-------------|
| **Status** | Completed, failed, cancelled, or running |
| **Time** | Timestamp of the run |
| **Processed** | Teams / Event Groups processed |
| **Programmes** | Total programmes generated |
| **Matched** | Streams successfully matched to events |
| **Failed** | Streams that could not be matched |
| **Channels** | Active channels after this run |
| **Duration** | How long the generation took |
| **Size** | XMLTV file size |

{: .tip }
Click the **Matched** or **Failed** numbers to open a drill-down modal showing per-stream details grouped by event group. The Failed drill-down includes a **Fix** button that opens the event matcher so you can manually link unmatched streams.

## All-Time Totals

Cumulative statistics across all generation runs, giving a long-term view of your EPG output.

## Generation Workflow

1. Click **Generate** (or wait for the scheduled cron to trigger automatically).
2. A progress toast appears showing phases: processing teams, then event groups, then finalizing.
3. On completion, the statistics cards update and the run appears in Recent Runs.
4. If you click **Cancel** during generation, the run appears with a cancelled status.

## Scheduling

EPG generation runs automatically on a configurable cron schedule set in **Settings > EPG**. The default schedule is hourly. You can always trigger an additional run manually using the Generate button.
