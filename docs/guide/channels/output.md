---
title: Dispatcharr Output
parent: Channels
grand_parent: User Guide
nav_order: 5
---

# Dispatcharr Output

How Teamarr writes its channels into Dispatcharr — which profiles they appear in, which stream profile processes them, and which channel group they land in. Set global defaults here, then override them per league where needed.

![Channels → Dispatcharr Output — profile, stream-profile, and channel-group cards](../../assets/images/channels-output.png)

{: .note }
Dispatcharr **connection** (URL, credentials), the **EPG source**, and **logo cleanup** live in [Settings → Dispatcharr](../settings/dispatcharr) — those are connection and housekeeping concerns, not channel routing.

## Default Channel Profiles

Which Dispatcharr profiles new Teamarr channels are assigned to. These defaults apply to all sources unless overridden per league. Profile assignment is re-enforced on every EPG generation run.

The selector lists your existing profiles as checkboxes, plus two **dynamic profile** entries — `{sport}` and `{league}` — and an **Add custom pattern…** input for combined patterns (a custom pattern must contain `{sport}` or `{league}`). Dynamic profiles are created in Dispatcharr on demand: check `{sport}` and every channel is also added to a profile named for its sport.

## Default Stream Profile

The Dispatcharr stream profile applied to channel streams. The stream profile defines how streams are processed (ffmpeg, VLC, proxy, etc.). This default applies everywhere — there is **no per-league stream-profile override**.

## Default Channel Group

The Dispatcharr channel group new channels are assigned to, plus how that group is chosen.

### Channel Group

Pick a static group from the dropdown. By default the list hides M3U-sourced groups; toggle **Show M3U-sourced channel groups** to assign a group that originated from an M3U account.

### Group Mode

| Mode | Description |
|------|-------------|
| **Static** | All channels go to the selected group above |
| **Dynamic by Sport** | Auto-creates and assigns groups named by sport |
| **Dynamic by League** | Auto-creates and assigns groups named by league |
| **Custom pattern** | Define a pattern using `{sport}`, `{league}`, and `{conference}` placeholders |

When **Custom pattern** is selected, a pattern field appears. For example, `{sport} | {league}` creates groups like "Hockey | NHL". Teamarr creates these dynamic groups in Dispatcharr automatically.

In group patterns, `{sport}` resolves to the sport's display name ("Hockey"), and `{league}` to the league's **short alias** — "EPL", not "English Premier League". `{conference}` resolves to the home team's conference name for NCAA football/basketball events ("Southeastern Conference"); events without conference data fall back to the static group.

A few failure modes are handled gracefully: a pattern whose wildcard can't resolve for an event falls back to the static group; and if a configured static group has been deleted in Dispatcharr, the channels are created **ungrouped** with a log warning telling you to re-select a group.

## Per-League Channel Config

Override channel profiles, channel groups, and group modes on a per-league basis. The **Subscribed only** toggle is on by default, so the table opens with just your subscribed leagues (turn it off to see all; the search field filters within whatever's visible). Click a league row to expand its configuration.

### Available Overrides

| Setting | Options | Description |
|---------|---------|-------------|
| **Channel Profiles** | Default or specific profiles | Which Dispatcharr profiles this league's channels appear in |
| **Channel Group** | Default or specific group | Which Dispatcharr channel group to assign channels to |
| **Channel Group Mode** | Default, Static, Dynamic by Sport, Dynamic by League, Custom | How the channel group is determined |

When Channel Group Mode is set to **Custom**, a pattern field appears where you can enter a template like `{sport} - {league}` that dynamically creates groups.

{: .note }
Per-league overrides take precedence over the global defaults above. Use the **X** button to clear an override and revert to the default.
