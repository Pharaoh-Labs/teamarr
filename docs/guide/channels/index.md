---
title: Channels
parent: User Guide
nav_order: 8
has_children: true
redirect_from:
  # Do NOT add /guide/channels/ here — that is this page's own URL, so
  # jekyll-redirect-from writes the stub over guide/channels/index.html and
  # the page redirects to itself forever. Only genuinely different legacy
  # paths belong in this list.
  - /guide/channels.html
  - /guide/settings/channels/
  - /guide/settings/channels.html
---

# Channels

The Channels area is where you control everything about the channels Teamarr creates in Dispatcharr for sporting events — when they exist, how streams map onto them, what numbers they get, which stream plays first, and where they land in Dispatcharr.

Event channels are ephemeral: they're created around each event and removed when it's over — by the delete timing you configure, and by several automatic cleanup paths (vanished streams, disabled sources, unsubscribed leagues, orphan detection) described under [Lifecycle](lifecycle#how-channels-get-deleted). Team-based channels are managed separately on the [Teams](../epg/teams) page.

The channels themselves are inspected on the **Dashboard**'s [Managed Channels table](../dashboard#managed-channels) — sync status, per-stream detail and priority explainer, Find Orphans, and bulk deletes all live there. These pages configure the behavior; the Dashboard shows the result.

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
