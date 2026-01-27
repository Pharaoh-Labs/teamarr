---
title: Game Thumbs
parent: Templates
grand_parent: User Guide
nav_order: 4
---

# Game Thumbs Integration

[Game Thumbs](https://github.com/sethwv/game-thumbs) is an optional external service that generates dynamic program artwork for sports events. It creates matchup images with team logos, scores, and broadcast network badges.

{: .note }
Game Thumbs is a separate project maintained by [@sethwv](https://github.com/sethwv). Teamarr does not require Game Thumbs, but it significantly enhances the visual experience.

## Features

- Dynamic matchup artwork with team logos
- Multiple art styles (cover, logo, badge variations)
- Broadcast network badges (ESPN, FOX, etc.)
- Fallback images when teams aren't found
- Support for all major leagues

## Documentation

For full documentation, visit: [game-thumbs-docs.swvn.io](https://game-thumbs-docs.swvn.io)

## Hosted Options

If you don't want to self-host, there are community-hosted instances available:

| Host | URL | Notes |
|------|-----|-------|
| **swvn.io** | `https://sportslogos.jesmann.com` | Primary hosted instance |

{: .important }
Hosted instances are provided as a community service and may have usage limits or availability constraints.

## Self-Hosting

To run your own instance:

```bash
docker run -d \
  --name game-thumbs \
  -p 3000:3000 \
  ghcr.io/sethwv/game-thumbs:latest
```

See the [GitHub repository](https://github.com/sethwv/game-thumbs) for detailed setup instructions.

## Using in Templates

### Program Art URL

Use in the `program_art_url` field:

```
<game-thumbs-url>/{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png?style=1&logo=true&fallback=true
```

### Channel Logo URL

Use in the `event_channel_logo_url` field:

```
<game-thumbs-url>/{league_id}/{away_team_pascal}/{home_team_pascal}/logo.png?style=1&logo=true&fallback=true&badge={broadcast_national_network}
```

### URL Parameters

| Parameter | Description |
|-----------|-------------|
| `style` | Art style variant (1-6) |
| `logo` | Include team logos (true/false) |
| `fallback` | Show fallback image if teams not found (true/false) |
| `badge` | Overlay text badge (e.g., broadcast network) |

### Template Variables

These Teamarr variables work well with game-thumbs URLs:

| Variable | Example | Description |
|----------|---------|-------------|
| `{league_id}` | `nfl`, `nba` | League identifier |
| `{away_team_pascal}` | `NewYorkGiants` | Away team in PascalCase |
| `{home_team_pascal}` | `DallasCowboys` | Home team in PascalCase |
| `{broadcast_national_network}` | `ESPN` | National broadcast network |
| `{exception_keyword}` | `Spanish` | Exception keyword label |

## Example Configurations

### Basic Cover Art

```
https://your-game-thumbs:3000/{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png
```

### With Broadcast Badge

```
https://your-game-thumbs:3000/{league_id}/{away_team_pascal}/{home_team_pascal}/logo.png?badge={broadcast_national_network}
```

### Pregame Art (Next Game)

```
https://your-game-thumbs:3000/{league_id}/{away_team_pascal.next}/{home_team_pascal.next}/cover.png?style=1
```

### Postgame Art (Last Game)

```
https://your-game-thumbs:3000/{league_id}/{away_team_pascal.last}/{home_team_pascal.last}/cover.png?style=5
```
