---
title: Channels
parent: User Guide
nav_order: 8
has_children: true
docs_version: "2.7.0"
redirect_from:
  - /guide/channels/
  - /guide/channels.html
  - /guide/settings/channels/
  - /guide/settings/channels.html
---

# Channels

The Channels area is where you control everything about the channels Teamarr creates in Dispatcharr for sporting events — when they exist, how streams map onto them, what numbers they get, which stream plays first, and where they land in Dispatcharr.

Event channels are ephemeral: they're created around each event and deleted when it ends. Team-based channels are managed separately on the [Teams](../epg/teams) page.

## Sub-pages

| Page | What it covers |
|------|----------------|
| **[Lifecycle](lifecycle)** | When event channels are created and deleted, and the pre/post-event buffers |
| **[Consolidation](consolidation)** | Whether multiple streams for one event merge into a single channel or split apart — plus exception keywords and feed separation |
| **[Numbering](numbering)** | Channel-number assignment (auto/manual), the channel range, and channel ordering in the lineup |
| **[Stream Priority](stream-priority)** | Rules that decide which stream plays first inside a consolidated channel |
| **[Dispatcharr Output](output)** | How channels are written to Dispatcharr — profiles, channel groups, group modes, and per-league overrides |

{: .note }
Most settings on these pages take effect on the **next EPG generation run** — the timing and rules determine eligibility and order, not the exact moment a channel changes.
