---
title: Dispatcharr
parent: Settings
grand_parent: User Guide
nav_order: 2
docs_version: "2.7.0"
---

# Dispatcharr Integration

Configure connection to Dispatcharr for automatic channel management.

## Connection Settings

Server URL and credentials for connecting to Dispatcharr.

| Field | Description |
|-------|-------------|
| **Enable** | Toggle Dispatcharr integration on/off |
| **URL** | Dispatcharr server URL (e.g., `http://localhost:9191`) |
| **Username** | Dispatcharr login username |
| **Password** | Dispatcharr login password |

Use the **Test** button to verify your connection.

### Connection Status

A status badge shows the current connection state:

| Status | Description |
|--------|-------------|
| **Connected** | Successfully communicating with Dispatcharr |
| **Disconnected** | Configured but unable to connect |
| **Error** | Connection failed (hover for error details) |
| **Not Configured** | Integration not yet set up |

## EPG Source

Select which EPG source in Dispatcharr to associate with Teamarr-managed channels. This links your channels to the correct guide data.

If you haven't created an EPG source in Dispatcharr yet, you'll need to do that first. See [Dispatcharr Integration Guide](../dispatcharr-integration) for setup details.

## Default Channel Profiles

Select which channel profiles to assign to Teamarr-managed channels by default. Individual sources can override this setting (see [Sources](../sources/)), and per-league config under [Channels](../channels/) can override per league.

- **All profiles selected** — Channels appear in all profiles
- **None selected** — Channels don't appear in any profile
- **Specific profiles** — Channels appear only in selected profiles

### Dynamic Wildcards

In addition to selecting specific profiles, you can use wildcards that dynamically create and assign profiles based on the event:

| Wildcard | Description | Example |
|----------|-------------|---------|
| `{sport}` | Creates/assigns profile named after the sport | `football`, `basketball` |
| `{league}` | Creates/assigns profile named after the league | `nfl`, `nba`, `epl` |

For example, selecting profiles `[1, {sport}]` would assign all channels to profile 1, plus dynamically create and assign to a sport-specific profile.

{: .note }
Profile assignment is enforced on every EPG generation run. Wildcard profiles are created in Dispatcharr automatically if they don't exist.

## Default Stream Profile

Select which stream profile to assign to streams on Teamarr-managed channels. Stream profiles in Dispatcharr control transcoding and quality settings.

If no stream profile is selected, streams are added without a profile assignment.

## Default Channel Group

Configure which Dispatcharr channel group to assign Teamarr-managed channels to by default.

### Channel Group

Select a specific channel group, or leave as "None" to not assign a group.

### Group Mode

| Mode | Description | Example |
|------|-------------|---------|
| **Static** | All channels go to the selected group | All in "Sports" |
| **Dynamic by Sport** | Auto-create groups per sport | "Football", "Basketball", "Hockey" |
| **Dynamic by League** | Auto-create groups per league | "NFL", "NBA", "NHL" |
| **Custom** | Use a template pattern to create groups | `{sport} - {league}` → "Football - NFL" |

When **Custom** is selected, a pattern field appears. Use `{sport}` and `{league}` variables in your pattern. Groups are created automatically in Dispatcharr if they don't exist.

{: .note }
Per-league overrides under [Channels](../channels/) take precedence over these defaults.

## Logo Cleanup

When enabled, removes **all** unused logos from Dispatcharr after EPG generation.

{: .warning }
This affects all unused logos in Dispatcharr, not just ones uploaded by Teamarr. Use with caution if you have manually uploaded logos that are not actively assigned to channels.

See [Dispatcharr Integration Guide](../dispatcharr-integration) for complete setup details.
