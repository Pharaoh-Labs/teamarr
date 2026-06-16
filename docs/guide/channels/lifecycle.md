---
title: Lifecycle
parent: Channels
grand_parent: User Guide
nav_order: 1
docs_version: "2.7.0"
---

# Lifecycle

Controls when event channels are created in and deleted from Dispatcharr.

## Create Timing

| Mode | Description |
|------|-------------|
| **Same day** | Create channels on the day of the event |
| **Before event + buffer** | Create channels a configurable number of hours before the event starts |

When **Before event + buffer** is selected, a **Pre-Event Buffer (hours)** field appears where you set how many hours before the event to create the channel (e.g., 6 hours before).

## Delete Timing

| Mode | Description |
|------|-------------|
| **Same day** | Delete channels at midnight on the day of the event |
| **After event + buffer** | Delete channels a configurable number of hours after the event ends |

The **Post-Event Buffer (hours)** sets how many hours after the event ends to keep the channel (e.g., 2 hours after for postgame coverage).

{: .note }
Events that cross midnight always use the post-event buffer for deletion, even in "Same day" mode, so a channel isn't pulled out from under a game in progress.

{: .note }
Create and delete timing work together with EPG generation. Channels are only actually created or deleted when a generation run executes — the timing determines *eligibility*, not the exact moment.
