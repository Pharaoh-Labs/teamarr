---
title: Headendarr Integration
parent: User Guide
nav_order: 4
docs_version: "2.3.1"
---

# Headendarr Integration

Teamarr can use Headendarr as its event-channel target. Teamarr handles the sports matching and XMLTV generation locally, then uses Headendarr for playlist discovery, channel creation, and channel cleanup.

If you are using Dispatcharr instead, see [Dispatcharr Integration](dispatcharr-integration).

## Initial Setup

### 1. Connect to Headendarr

1. Go to **Settings > Headendarr**
2. Enable the integration toggle
3. Enter your Headendarr URL (for example `http://headendarr:9985`)
4. Enter your Headendarr admin username and password
5. Enter the **Teamarr Host** as Headendarr can see it (for example `teamarr:9195` or `192.168.1.50:9195`)
6. Click **Test** to verify the connection shows "Connected"
7. Click **Save**

### 2. Provision the Teamarr XMLTV Source

1. Stay in **Settings > Headendarr**
2. Use the provisioning action to create or update the built-in `Teamarr` XMLTV source in Headendarr
3. Teamarr points that source to `http://<teamarr-host>/api/v1/epg/xmltv`
4. Teamarr configures the source to refresh hourly

After the initial provisioning, Headendarr keeps refreshing Teamarr's XMLTV feed on its own schedule.

### 3. Import Event Groups

1. Go to **Event Groups**
2. Click **Import**
3. Select a Headendarr playlist and stream group
4. Save the event group and assign a template

Teamarr uses Headendarr playlists as the stream inventory for event matching.

## How It Works

Once connected, Teamarr manages the event-channel lifecycle in Headendarr:

1. **EPG Generation** runs manually or on schedule
2. Teamarr fetches candidate streams from Headendarr playlists
3. Teamarr matches streams to real-world sports events
4. Teamarr creates or updates Headendarr channels for matched events
5. Headendarr refreshes the Teamarr XMLTV source and links the guide data
6. Teamarr removes channels again after the configured lifecycle window expires

## Network Configuration

Teamarr and Headendarr need to be able to reach each other over the network.

### Docker Compose (Same Host)

If both containers are on the same Docker network, use the container names:

```yaml
# Teamarr Settings > Headendarr URL:
http://headendarr:9985

# Teamarr Settings > Headendarr > Teamarr Host:
teamarr:9195
```

### Separate Hosts

Use the IP address or hostname that each application can reach:

```text
# Teamarr → Headendarr
http://192.168.1.100:9985

# Headendarr → Teamarr XMLTV
192.168.1.101:9195
```

## Notes

- Headendarr setup is intentionally minimal: URL, username, password, and the Teamarr host value.
- Teamarr does the event matching itself. Headendarr only needs to expose playlists and accept channel-management API calls.
- Event channels still depend on the usual matching rules. If stream names are too vague, Teamarr may not be able to identify the correct event.
