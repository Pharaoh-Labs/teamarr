---
title: Dispatcharr Output
parent: Channels
grand_parent: User Guide
nav_order: 5
docs_version: "2.7.0"
---

# Dispatcharr Output

How Teamarr writes its channels into Dispatcharr — which profiles they appear in, which stream profile processes them, and which channel group they land in. Set global defaults here, then override them per league where needed.

{: .note }
Dispatcharr **connection** (URL, credentials), the **EPG source**, and **logo cleanup** live in [Settings → Dispatcharr](../settings/dispatcharr) — those are connection and housekeeping concerns, not channel routing.

## Default Channel Profiles

Which Dispatcharr profiles new Teamarr channels are assigned to. These defaults apply to all groups unless overridden per league. Profile assignment is re-enforced on every EPG generation run.

You can also use dynamic profile placeholders — for example `[1, {sport}]` assigns every channel to profile 1 plus a dynamically created sport-specific profile.

## Default Stream Profile

The Dispatcharr stream profile applied to channel streams. The stream profile defines how streams are processed (ffmpeg, VLC, proxy, etc.). This default applies to all groups unless overridden.

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
| **Custom pattern** | Define a pattern using `{sport}` and `{league}` placeholders |

When **Custom pattern** is selected, a pattern field appears. For example, `{sport} | {league}` creates groups like "Hockey | NHL". Teamarr creates these dynamic groups in Dispatcharr automatically.

## Per-League Channel Config

Override channel profiles, channel groups, and group modes on a per-league basis. The table lists all leagues — click a league row to expand its configuration.

### Available Overrides

| Setting | Options | Description |
|---------|---------|-------------|
| **Channel Profiles** | Default, None, or specific profiles | Which Dispatcharr profiles this league's channels appear in |
| **Channel Group** | Default or specific group | Which Dispatcharr channel group to assign channels to |
| **Group Mode** | Default, Static, Dynamic by Sport, Dynamic by League, Custom | How the channel group is determined |

When Group Mode is set to **Custom**, a pattern field appears where you can enter a template like `{sport} - {league}` that dynamically creates groups.

{: .note }
Per-league overrides take precedence over the global defaults above. Use the **X** button to clear an override and revert to the default.

### Filtering

Use the search field to find specific leagues, and toggle **Subscribed only** to hide leagues you haven't enabled.
