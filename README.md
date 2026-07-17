<p align="center">
  <img src="docs/assets/images/teamarr_electric_blue.png" alt="Teamarr — Sports Channel Management for Dispatcharr" width="420">
</p>

<p align="center"><strong>Sports Channel Management for <a href="https://github.com/Dispatcharr/Dispatcharr">Dispatcharr</a></strong></p>

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

## Image Tags

| Tag | Description |
|-----|-------------|
| `latest` | Stable release |
| `dev` | Development builds |

## Documentation

**Official Docs**: [pharaoh-labs.github.io/teamarr](https://pharaoh-labs.github.io/teamarr/) — User Guide, Technical Reference, Supported Leagues

**Community Guide**: https://teamarr-v2.jesmann.com/

## License

MIT
