---
title: Teams
parent: User Guide
nav_order: 5
docs_version: "2.3.0"
---

# Teams

Team-based EPG produces one persistent **XMLTV channel** per team in the guide Teamarr writes. Teamarr does *not* create a Dispatcharr channel for each team — that's only done for event-based workflows. Instead, you point one of your existing Dispatcharr channels at the team's XMLTV channel id (via Dispatcharr's normal EPG association), and Teamarr keeps that XMLTV channel populated with the team's schedule — upcoming games, live events, and recent results.

## How It Works

1. Import teams from the league cache
2. Assign a **team template** to each team
3. Teamarr looks up each team's schedule and writes EPG programmes for that team's XMLTV channel

Each team's EPG includes:
- **Pregame** programmes before the game starts
- **Live event** programmes during the game
- **Postgame** programmes after the game ends
- **Idle** programmes on days with no games

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
| **Channel** | XMLTV channel id (e.g. `team.espn.nfl.123`) — point a Dispatcharr channel at this id to wire up the EPG |
| **Status** | Active (has upcoming games) or inactive |

### Assigning Templates

Each team needs a **team template** assigned. Click the template dropdown in the team's row to select one. You can also bulk-assign templates by selecting multiple teams.

Team templates are different from event templates — they support `.next` and `.last` suffixes for referencing upcoming and previous games, and include idle/pregame/postgame filler content.

### Schedule Days

Configure how many days of schedule to fetch per team in **Settings > Teams**. More days means more programmes in the EPG but longer generation times.
