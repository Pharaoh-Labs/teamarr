# Teamarr

Dynamic EPG Generator for Sports Channels

## Features

- **Automatic EPG Generation** - Dynamic TV guide for sports events
- **Multi-Provider Support** - ESPN, The Sports DB, and more
- **Stream Matching** - Intelligent matching of IPTV streams to events
- **Dispatcharr Integration** - Automated channel management
- **Update Notifications** - Optional notifications for stable releases and dev builds

## Quick Start

```yaml
services:
  teamarr:
    image: ghcr.io/pharaoh-labs/teamarr:latest
    container_name: teamarr
    restart: unless-stopped
    ports:
      - 9195:9195
    volumes:
      - ./data:/app/data
    environment:
      - TZ=America/Detroit
```

```bash
docker compose up -d
```

## Upgrading from V1

**There is no automatic migration path from V1 to V2** due to significant architectural changes.

If you're upgrading from V1, you have two options:

1. **Start Fresh with V2** - Archive your V1 database and begin with a clean setup. The app will detect your V1 database and guide you through the process, including downloading a backup of your V1 data.

2. **Continue Using V1** - If you're not ready to migrate, use the archived V1 image:
   ```yaml
   image: ghcr.io/pharaoh-labs/teamarr:1.4.9-archive
   ```
   Note: V1 will continue to function but will not receive future updates.

## Image Tags

| Tag | Description |
|-----|-------------|
| `latest` | Stable release (V2) |
| `dev` | Development builds |
| `1.4.9-archive` | Final V1 release (no longer maintained) |

## Documentation

**User Guide**: https://teamarr-v2.jesmann.com/

**Update Notification Testing**: See [docs/UPDATE_NOTIFICATION_TESTING.md](docs/UPDATE_NOTIFICATION_TESTING.md) for details on testing update checks for stable and dev builds.

Formal documentation coming soon.

## Update Notifications

Teamarr can optionally check for updates and notify you when new versions are available:

- **Stable Releases**: Checks GitHub Releases for new stable versions
- **Dev Builds**: Checks GitHub Container Registry for new development builds
- **Configurable**: Works with forks - configure your own repository URLs
- **Cached**: Smart caching to avoid excessive API calls

Update checking is enabled by default but can be configured via the API:

```bash
# Check for updates
curl http://localhost:9195/api/v1/updates/status

# Configure update checking
curl -X PATCH http://localhost:9195/api/v1/updates/settings \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "check_interval_hours": 24}'
```

See the [Update Notification Testing Guide](docs/UPDATE_NOTIFICATION_TESTING.md) for complete documentation.

## License

MIT
