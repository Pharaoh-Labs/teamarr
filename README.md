<p align="center">
  <img src="docs/assets/images/teamarr_electric_blue.png" alt="Teamarr — Sports Channel Management for Dispatcharr" width="420">
</p>

<p align="center"><strong>Dynamic EPG Generator for Sports Channels</strong></p>

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

## Upgrading from Legacy (1.x)

**There is no automatic migration path from legacy 1.x releases** due to significant architectural changes.

If you're upgrading from 1.x, you have two options:

1. **Start Fresh** - Archive your old database and begin with a clean setup. The app will detect your legacy database and guide you through the process, including downloading a backup of your data.

2. **Continue Using 1.x** - If you're not ready to migrate, use the archived image:
   ```yaml
   image: ghcr.io/pharaoh-labs/teamarr:1.4.9-archive
   ```
   Note: 1.x will continue to function but will not receive future updates.

## Image Tags

| Tag | Description |
|-----|-------------|
| `latest` | Stable release |
| `dev` | Development builds |
| `1.4.9-archive` | Final 1.x release (no longer maintained) |

## Documentation

**Official Docs**: [pharaoh-labs.github.io/teamarr](https://pharaoh-labs.github.io/teamarr/) — User Guide, Technical Reference, Supported Leagues

**Community Guide**: https://teamarr-v2.jesmann.com/

## License

MIT
