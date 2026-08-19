---
title: Consolidation
parent: Channels
grand_parent: User Guide
nav_order: 2
---

# Consolidation

When an event has multiple streams (different providers, qualities, or feeds), Consolidation decides whether those streams merge into a single channel or split into separate ones.

## Default Mode

| Mode | Description |
|------|-------------|
| **Consolidate** | Merge multiple streams for the same event into a single channel with multiple sources. Exception keywords can override this per-stream. |
| **Separate** | Each stream gets its own channel, even if they're for the same event. More channels, no merging. |

In Consolidate mode, [Stream Priority](stream-priority) rules decide which stream is listed first within the merged channel.

## Exception Keywords

Exception keywords let certain streams break out of the default behavior — useful for keeping, say, a 4K or alternate-language feed on its own channel.

![Channels → Consolidation — default mode and the exception keywords table](../../assets/images/channels-consolidation.png)

Each keyword has:

- **Label** — the display name. It's appended to the variant channel's name, resolves the `{exception_keyword}` template variable, and is part of the channel's tvg-id.
- **Match Terms** — comma-separated terms matched against stream names.
- **Behavior** — one of three:

| Behavior | Description |
|----------|-------------|
| **Sub-Consolidate** | Group matching streams together on their own channel, separate from the main channel |
| **Separate** | Each matching stream gets its own channel |
| **Ignore** | Matching streams are dropped entirely — no channel |

- **Enabled** — an API-only flag (there's no UI toggle); keywords disabled via the API disappear from the card.

A fresh install ships with eight language keywords seeded (Spanish, French, German, Portuguese, Italian, Japanese, Korean, Chinese — all Sub-Consolidate), so alternate-language feeds split out of the box.

{: .note }
The Exception Keywords card is only *shown* in Consolidate mode, but stored keywords are checked on every run regardless of mode — a keyword's behavior overrides the global mode per-stream (an **Ignore** keyword drops its streams even in Separate mode).

Keyword placement is **enforced every generation**: if a stream should move between a main channel and its keyword variant (because keywords or stream names changed), it's moved, and the main channel is always kept on the lower channel number than its variants.

## Feed Separation

When multiple IPTV providers carry separate home and away broadcast feeds for the same event, Feed Separation detects them and creates distinct channels for each.

### How It Works

1. **Literal token detection** — streams containing terms like "HOME" or "AWAY" are detected before team matching. The token is stripped so it doesn't interfere with team-name parsing.
2. **Team streams** — a stream matched as a team's own channel (the whole stream name is one team, e.g. `MLB | Miami Marlins`) *is* that team's feed: with **Detect Team Names** on, it goes to that team's feed channel instead of the shared one.
3. **Broadcast-market detection** — the stream is matched against the event's actual broadcast listings from the provider (ESPN reports each network's market: national, home, or away). This is how team-branded channels ("Brewers.TV") and regional networks that don't carry the team's name at all ("YES", "Marquee Sports Network") resolve to the right feed. Matching tolerates the usual drift — punctuation, casing, run-together and abbreviated forms. National networks never count as a team feed, a stream matching *both* sides stays a normal channel, and very short names are skipped.
4. **Team-name detection** — if enabled, streams are scanned for team names in a feed context (e.g., "Orioles Feed", "Orioles.TV", "Orioles.US") and matched against the event's home and away teams. A matchup title alone ("Pirates vs Marlins") is a shared feed and never splits.
5. **Channel discrimination** — streams resolved to different teams get separate channels, even for the same event. Unlabeled streams go to their own channel as usual. Each feed channel gets its own tvg-id (`…-feed-<team>`), which is why each carries distinct EPG.

Detection checks the stream **name, tvg-id, and tvg-name** — a stream whose tvg-id is `Brewers.TV` resolves even when its display name says nothing.

### Settings

Feed **identification** always runs — every stream's resolved feed team *and* which side it is (home, away, or unknown) are stored, driving the [Specific Team's Feed and Feed Side stream-priority rules](stream-priority#rule-types) even with the feature off. The master **Feed Separation** toggle gates only the channel *splitting*: whether resolved feeds get their own channels.

| Setting | Default | Description |
|---------|---------|-------------|
| **Feed Separation** | Off | Master toggle for the feature |
| **Home Feed Terms** | `HOME` | Comma-separated terms that indicate a home feed |
| **Away Feed Terms** | `AWAY` | Comma-separated terms that indicate an away feed |
| **Detect Team Names** | On | Also match team names in stream names (e.g., "Orioles Feed") |
| **Feed Label Style** | Team Name | How feed channels are labeled — see below |

### Label Styles

Controls the label appended to channel names when a feed team is detected (always in the form `(<label> Feed)`):

| Style | Example |
|-------|---------|
| **Team Name** | `NYY @ BAL (Orioles Feed)` |
| **Short Name** | `NYY @ BAL (BAL Feed)` |
| **Home/Away** | `NYY @ BAL (Home Feed)` / `(Away Feed)` |

{: .note }
If your channel-name template already places the feed team itself (any feed variable — `{feed_team*}`, `{broadcast_feed*}`, or `{feed_home_away}`), the automatic `(… Feed)` suffix is suppressed — the template wins.

### Example

Given an event "NYY @ BAL" with streams (default Team Name style):

- `MLB: NYY @ BAL HOME` → detected as home feed → channel: `NYY @ BAL (Orioles Feed)`
- `MLB: NYY @ BAL AWAY` → detected as away feed → channel: `NYY @ BAL (Yankees Feed)`
- `MLB: NYY @ BAL` → no feed detected → channel: `NYY @ BAL`

This creates three separate channels, each consolidating their respective streams.
