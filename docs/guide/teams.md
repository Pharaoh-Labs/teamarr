---
title: Teams
parent: User Guide
nav_order: 5
docs_version: "2.3.0"
---

# Teams

Team-based EPG creates one persistent channel per team. Each channel stays in your guide 24/7 and gets populated with the team's schedule — upcoming games, live events, and recent results.

## How It Works

1. Import teams from the league cache
2. Assign a **team template** to each team
3. Teamarr looks up each team's schedule and generates EPG programmes

Each team channel shows:
- **Pregame** filler before the game starts
- **Live event** programme during the game
- **Postgame** filler after the game ends
- **Idle** filler on days with no games

## Importing Teams

Go to **Teams > Import** to browse the league cache by sport.

1. Click a sport to expand its leagues
2. Click a league to see available teams
3. Select teams individually or use **Select All**
4. Click **Import Selected**

Teams are grouped by sport in the sidebar. The badge next to each sport shows how many leagues have cached teams. Leagues with 0 teams haven't had their cache refreshed yet — use the cache refresh button in Settings > System.

## Managing Teams

The Teams table shows all imported teams with:

| Column | Description |
|--------|-------------|
| **Team** | Team name with logo |
| **League** | League the team belongs to |
| **Template** | Assigned template (click to change) |
| **Channel** | Dispatcharr channel ID if synced |
| **Status** | Active (has upcoming games) or inactive |

### Assigning Templates

Each team needs a **team template** assigned. Click the template dropdown in the team's row to select one. You can also bulk-assign templates by selecting multiple teams.

Team templates are different from event templates — they support `.next` and `.last` suffixes for referencing upcoming and previous games, and include idle/pregame/postgame filler content.

### Schedule Days

Configure how many days of schedule to fetch per team in **Settings > Teams**. More days means more programmes in the EPG but longer generation times.

## Team Channels in Dispatcharr

When Dispatcharr integration is configured, Teamarr creates and manages channels for each team:

- Channel names use the team template's channel name format
- Channel logos are set from the team's logo URL
- Channels are assigned to the configured channel group and profiles
- Channel numbers follow the configured numbering mode (auto or manual)

Channels persist even when no game is scheduled — they show idle filler content instead.

### Competition Filtering

By default, soccer team channels include fixtures from all competitions the team plays in (domestic league, cups, continental tournaments). If your team channels are backed by league-specific streams, you can enable the **League fixtures only** toggle in [Settings > Channels > Per-League Channel Config](settings/channels#league-fixtures-only-soccer) to restrict EPG to the team's primary league only.
