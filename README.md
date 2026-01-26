# Teamarr

Dynamic EPG Generator for Sports Channels

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

Formal documentation coming soon.

## License

MIT
