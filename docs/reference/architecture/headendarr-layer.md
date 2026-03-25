---
title: Headendarr Integration Layer
parent: Architecture
grand_parent: Technical Reference
nav_order: 4
docs_version: "2.3.1"
---

# Headendarr Integration Layer

The `teamarr/headendarr/` package provides Teamarr's Headendarr-specific client and manager layer. It is responsible for connection management, playlist discovery, XMLTV source provisioning, and channel operations against Headendarr's API.

## Responsibilities

- Authenticate to Headendarr with the configured admin credentials
- Discover playlists and playlist stream groups for Teamarr event groups
- Provision the fixed `Teamarr` XMLTV source in Headendarr
- Create, update, and delete Teamarr-managed channels in Headendarr
- Map Headendarr's channel and source model into Teamarr's lifecycle service

## Main Components

```text
HeadendarrFactory (singleton)
  ↓
HeadendarrConnection
  ├── HeadendarrClient     (HTTP + auth + retry)
  ├── PlaylistManager      (playlists + streams)
  ├── EPGManager           (XMLTV source provisioning + refresh)
  └── ChannelManager       (channel CRUD + source priority mapping)
```

## Key Differences from Dispatcharr

- Headendarr uses playlists as the source inventory for event groups
- Teamarr provisions a fixed `Teamarr` XMLTV source automatically
- The user only configures the Headendarr URL, credentials, and the Teamarr host value
- Dispatcharr-only concepts such as channel profiles, stream profiles, and logo cleanup do not apply here

## File Locations

| File | Purpose |
|------|---------|
| `headendarr/client.py` | HTTP client |
| `headendarr/auth.py` | Session/auth helpers |
| `headendarr/factory.py` | Connection factory |
| `headendarr/types.py` | Typed integration models |
| `headendarr/managers/playlists.py` | Playlist and stream discovery |
| `headendarr/managers/epg.py` | XMLTV source provisioning and refresh |
| `headendarr/managers/channels.py` | Channel CRUD and lifecycle mapping |
