---
title: Headendarr Integration
parent: Settings
grand_parent: User Guide
nav_order: 6
docs_version: "2.3.1"
---

# Headendarr Integration

Configure connection to Headendarr for automatic event-channel management.

## Connection Settings

| Field | Description |
|-------|-------------|
| **Enable** | Toggle Headendarr integration on or off |
| **URL** | Headendarr server URL (for example `http://localhost:9985`) |
| **Username** | Headendarr admin username |
| **Password** | Headendarr admin password |
| **Teamarr Host** | Hostname or IP:port that Headendarr should use to reach Teamarr's XMLTV endpoint |

Use the **Test** button to verify your connection.

### Connection Status

A status badge shows the current connection state:

| Status | Description |
|--------|-------------|
| **Connected** | Successfully communicating with Headendarr |
| **Disconnected** | Configured but unable to connect |
| **Error** | Connection failed (hover for error details) |
| **Not Configured** | Integration not yet set up |

## XMLTV Provisioning

Teamarr can provision a fixed `Teamarr` XMLTV source in Headendarr automatically.

- Teamarr builds the XMLTV URL from the **Teamarr Host** field
- The URL used is `http://<teamarr-host>/api/v1/epg/xmltv`
- The source name is fixed to `Teamarr`
- The refresh schedule is fixed to hourly

Use the provisioning action after saving settings, or any time the Teamarr host changes.

## Playlists

When connected, Teamarr can list available Headendarr playlists and use them as the source inventory for event groups.

- Playlists are the Headendarr equivalent of source accounts
- Stream groups inside those playlists can be imported into Teamarr event groups
- Teamarr performs the actual fuzzy matching and event selection locally

See [Headendarr Integration Guide](../headendarr-integration) for the full setup flow.
