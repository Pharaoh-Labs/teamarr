---
title: Dashboard
parent: User Guide
nav_order: 2
docs_version: "2.7.0"
---

# Dashboard

The dashboard is your landing page — a lean health-and-control panel. It answers "is my system healthy?" at a glance, surfaces recent generation runs, and gives you the managed-channel tables and EPG output without drilling into the feature sections. Composition detail (per-league, per-group, per-channel breakdowns) lives on its home tab, not here.

## Status Strip

A read-only strip across the top shows system health at a glance:

| Item | Shows |
|------|-------|
| **Dispatcharr** | Connection state — Connected (green), Disconnected (amber), Error (red, hover for the message), or Not configured |
| **Last generated** | When the last run finished (relative time) and its duration, color-coded by staleness: green under a day, amber 1–3 days, red if over 3 days, failed, or never run. Shows *Generating…* with a spinner during an active run |
| **Managed channels** | Live count of active Teamarr channels in Dispatcharr |
| **Matched** | Overall stream match rate, color-coded (only shown when match data exists) |
| **EPG URL** | The XMLTV URL with a one-click **Copy** button |

{: .note }
During a generation run, the channel and match-rate values show a spinner until fresh numbers land.

## Generation History

A table of recent full-pipeline runs (matching, channels, and EPG). Showing the five most recent by default — use **Show more** to expand.

| Column | Description |
|--------|-------------|
| **Status** | Completed, failed, cancelled, or running (spinner) |
| **Time** | When the run started |
| **Processed** | What was processed in the run |
| **Programmes** | Total programmes generated. Hover for the Events / Pregame / Postgame / Idle breakdown |
| **Matched** | Streams matched to events. Click to open a searchable drill-down of individual matched streams, filterable by group |
| **Channels** | Active channels after the run |
| **Duration** | How long the run took |

{: .tip }
From a run's failed/unmatched rows, use **Fix** to open the Event Matcher and manually correct a stream-to-event match.

## Managed Channels

A collapsible **Managed Channels** table lists the channels Teamarr currently maintains in Dispatcharr, with the channel name, the event it's tied to, sport, league, status, and scheduled delete time. You can delete individual channels here, and there are reset/cleanup actions for bulk operations.

A separate **Recently Deleted** section lists channels removed by event cleanup (channel, event, sport, league, and when they were deleted).

## EPG Output (XML Preview)

A collapsible **XML Preview** section contains:

- **EPG analysis** — coverage gaps and unreplaced-variable warnings, or an all-clear if the output is clean
- A searchable preview of the generated XMLTV file

The EPG URL itself lives in the status strip up top.

## All-Time Totals

A compact, de-emphasized footer shows lifetime totals: generations, programmes, streams matched, channels created, channels deleted, cache hits, and average run time.
