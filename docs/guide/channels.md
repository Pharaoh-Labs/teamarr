---
title: Channels
parent: User Guide
nav_order: 9
docs_version: "2.3.1"
---

# Channels

The Channels page shows all event-based channels currently managed by Teamarr. These are ephemeral channels created for sporting events and automatically deleted when events end.

Team-based channels are managed separately on the [Teams](teams) page.

## Channels Table

Each row represents a channel synced (or pending sync) to your configured integration target.

| Column | Description |
|--------|-------------|
| **Channel** | Channel name, logo, number (#), and TVG ID |
| **Event** | Away @ Home matchup with event date and time |
| **Sport** | Sport display name (e.g., Basketball, Soccer) |
| **League** | League name badge |
| **Status** | Sync status with Headendarr or Dispatcharr |
| **Delete At** | Scheduled deletion time (relative, e.g., "in 2h") |
| **Actions** | Manual delete button |

## Filters

Use the filter bar to narrow the table:

- **Name** — text search on channel name
- **Sport** — filter by sport
- **League** — filter by league
- **Status** — filter by sync status
- **Show deleted** — include soft-deleted channels

## Sync Status

The Status column shows whether each channel is correctly synced to Headendarr or Dispatcharr.

| Status | Color | Meaning |
|--------|-------|---------|
| **In Sync** | Green | Channel matches the target platform — streams and settings are aligned |
| **Pending** | Gray | Channel created locally, awaiting first sync to Headendarr or Dispatcharr |
| **Created** | Blue | Just created in Headendarr or Dispatcharr, not yet verified |
| **Drifted** | Yellow | Configuration mismatch detected — profiles, streams, or settings differ from what Teamarr expects. Re-synced on next generation run. |
| **Orphaned** | Red | Tracked locally but missing from Headendarr or Dispatcharr |
| **Error** | Red | Sync encountered an error |

{: .note }
Drifted channels self-heal automatically. The lifecycle sync compares the target platform's actual state against Teamarr's expected state and corrects any differences on the next EPG generation.

## Pending Deletions

A banner at the top shows how many channels are scheduled for deletion and when the next one expires. Channels are deleted automatically by the lifecycle scheduler based on the [delete timing](settings/channels#channel-lifecycle) configured in Settings.

## Bulk Operations

Select multiple channels using the checkboxes to enable bulk delete. A fixed bar appears at the bottom of the page with the selection count and delete button.

## Find Orphans

The **Find Orphans** button scans your configured integration target for channels that exist there but aren't tracked by Teamarr. This can happen if:

- Teamarr was restarted or restored from backup
- Channels were created manually in Headendarr or Dispatcharr with Teamarr-style IDs
- A sync error left channels behind

Each orphan can be deleted individually or all at once from the modal.

## Reset All

The **Reset All** button removes all Teamarr-managed event channels from the active integration target. This is a destructive operation that:

1. Shows a preview of all channels that will be deleted
2. Requires confirmation before proceeding
3. Deletes channels from Headendarr or Dispatcharr entirely

Channels will be recreated on the next EPG generation run based on current streams and settings.

{: .warning }
Reset All deletes all event channels immediately. Team channels are not affected. Use this when you want a clean slate — for example, after major configuration changes.

## Recently Deleted

A collapsible section at the bottom shows the last 50 deleted channels with their event, sport, league, and deletion timestamp. This helps verify that lifecycle cleanup is working correctly.
