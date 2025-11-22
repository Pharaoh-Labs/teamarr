# Teamarr - Dynamic Sports Team EPG Generator

**Transform ESPN's sports schedules into professional XMLTV EPG files for your IPTV system.**

Self-hosted dynamic sports EPG generator with support for 15 major leagues (NBA, NFL, MLB, NHL, MLS, NWSL, EPL, EFL Championship, La Liga, Bundesliga, Serie A, Ligue 1, NCAA Football, NCAA Men's/Women's Basketball) and 117 base template variables (252 with suffixes).

---

## ⚠️ BREAKING CHANGE: v0.x → v1.0.0

**TeamArr v1.0.0 is a complete architectural rewrite. No database migration is available.**

### If You're Upgrading from v0.x:

**YOU MUST START FRESH.** The database schema is fundamentally different.

**Migration Steps:**
1. **Stop your current TeamArr instance**
2. **Delete the old database**:
   ```bash
   rm teamarr.db
   ```
3. **Update to v1.0.0** (pull latest, rebuild container, etc.)
4. **Start TeamArr** - fresh database will be created automatically
5. **Reconfigure from scratch**:
   - Create templates (new concept - reusable across teams)
   - Import your teams from ESPN
   - Assign templates to teams
   - Configure settings

### What's New in v1.0.0:

✨ **Template-Based Architecture**: Formatting rules are now reusable across multiple teams
✨ **Variable Suffix System**: 117 base variables with `.next` and `.last` suffix support (252 total)
✨ **Organized Variables**: 5 logical categories (Teams, Games, Team Stats, Roster & Players, Betting & Odds)
✨ **Streamlined Conditionals**: 15 focused condition types
✨ **TZ Environment Sync**: Timezone automatically synced from Docker `TZ` environment variable
✨ **Better UI**: Color-coded variables, reorganized categories, improved variable helper

### What Changed:

- **Templates**: Formatting rules (title, description, filler) are now separate from teams
- **Variables**: Increased from 188 to 252 (with suffix system)
- **Organization**: Variables grouped into 5 categories instead of 15
- **Conditionals**: Simplified from 15+ to 15 focused types
- **Timezone**: Single global timezone (no per-team timezones)

**Why No Migration?** The old team-centric model stored all settings per-team. The new template-based model separates formatting (templates) from team identity. These are incompatible schemas.

**Need the old version?** It remains available on the `old-team-centric-v0.x` branch.

---

## Quick Start with Docker

```bash
docker run -d \
  --name teamarr \
  -p 9195:9195 \
  -v ./data:/app/data \
  -e TZ=America/New_York \
  ghcr.io/egyptiangio/teamarr:latest
```

Access the web interface at **http://localhost:9195**

### Docker Compose

```yaml
services:
  teamarr:
    image: ghcr.io/egyptiangio/teamarr:latest
    container_name: teamarr
    restart: unless-stopped
    ports:
      - 9195:9195
    volumes:
      - ./data:/app/data
    environment:
      - TZ=America/New_York
```

---

## Features

- **15 Major Leagues**: NBA, NFL, MLB, NHL, MLS, NWSL, EPL, EFL Championship, La Liga, Bundesliga, Serie A, Ligue 1, NCAA Football, NCAA Men's/Women's Basketball
- **252 Template Variables**: 117 base variables with `.next` and `.last` suffix support
- **Template-Based**: Create reusable templates and assign to multiple teams
- **Variable Suffix System**: Access current, next, and last game context (e.g., `{opponent}`, `{opponent.next}`, `{opponent.last}`)
- **Conditional Descriptions**: Dynamic content based on streaks, playoffs, rankings, and more
- **Gracenote-Standard EPG**: Professional quality XMLTV following industry best practices
- **Web-Based Configuration**: Simple, intuitive interface
- **Automatic Updates**: Scheduled EPG generation (hourly or daily)
- **ESPN API Integration**: Real-time data from ESPN's public API
- **IPTV Compatible**: Works with Plex, Jellyfin, TVHeadend, TiviMate, and more

---

## Usage

### 1. Create a Template

Templates define how your EPG entries will be formatted. Create reusable templates for different use cases:

1. Go to **Templates** → **Create Template**
2. Set basic info (name, sport, league)
3. Configure templates:
   - **Title**: `{league} {sport}`
   - **Subtitle**: `{venue_city}, {venue_state}`
   - **Description**: `{team_name} ({team_record}) vs {opponent} ({opponent_record})`
4. Add conditional descriptions for special cases
5. Configure filler content (pregame, postgame, idle)
6. Set XMLTV options

### 2. Import Teams

1. Go to **Teams** → **Import Teams**
2. Browse by league or search
3. Select teams to import
4. Teams are added to your roster

### 3. Assign Templates

1. Go to **Teams**
2. Select teams (multi-select with checkboxes)
3. Use **Bulk Actions** → **Assign Template**
4. Choose template from dropdown

### 4. Generate EPG

1. Click **Generate EPG** from dashboard
2. EPG is generated with all active teams
3. Download XMLTV file or use EPG URL in your IPTV app

---

## Variable Suffix System

**NEW in v1.0.0**: Access multiple game contexts with suffix notation

### Syntax

- `{variable}` - Current game
- `{variable.next}` - Next scheduled game
- `{variable.last}` - Last completed game

### Examples

**Pregame Filler**:
```
Up next: {opponent.next} on {game_date.next} at {game_time.next}
```

**Postgame Filler**:
```
Final: {team_name} {score.last} - {opponent.last} {opponent_score.last}
```

**Idle Filler**:
```
Last game: {opponent.last} ({result.last})
Next game: {opponent.next} on {game_date.next}
```

### Variable Categories

Variables are organized into 5 categories:

1. **🏈 Teams** (30 vars) - Team/opponent identity, venue, league, conferences
2. **📅 Games** (19 vars) - Date, time, status, broadcasts, season context
3. **📊 Team Stats** (52 vars) - Records, standings, streaks, performance, h2h
4. **👥 Roster & Players** (9 vars) - Head coach, player leaders
5. **💰 Betting & Odds** (7 vars) - Spreads, moneylines, over/under

**Color coding** in the UI indicates suffix availability:
- 🔵 **Blue** = All contexts (base, .next, .last)
- 🔘 **Gray** = No suffix (BASE only)
- 🟢 **Green** = Base + .next only
- 🔴 **Red** = .last only

---

## Conditional Descriptions

Create dynamic descriptions based on game context:

### Available Conditions

- **Is home** / **Is away**
- **Streak (win) ≥ N** / **Streak (loss) ≥ N**
- **Home Streak (win) ≥ N** / **Home Streak (loss) ≥ N**
- **Away Streak (win) ≥ N** / **Away Streak (loss) ≥ N**
- **Is playoff** / **Is preseason**
- **Has odds**
- **Ranked opponent** (opponent ranked top 25)
- **Top 10 matchup** (both teams ranked top 10)
- **Opponent name contains** [text]
- **Is National Broadcast**

### Example

**Priority 10**: If win streak ≥ 3
```
{team_name} looks to extend their {win_streak} game winning streak vs {opponent}
```

**Priority 20**: If loss streak ≥ 3
```
Can {team_name} snap their {loss_streak} game losing streak against {opponent}?
```

**Priority 100 (fallback)**:
```
{team_name} ({team_record}) vs {opponent} ({opponent_record}) at {venue}
```

---

## Template Variables

### Most Popular

| Variable | Example | Suffix Support |
|----------|---------|----------------|
| `{team_name}` | Detroit Pistons | BASE |
| `{team_abbrev}` | DET | BASE |
| `{opponent}` | Atlanta Hawks | ALL |
| `{opponent_abbrev}` | ATL | ALL |
| `{team_record}` | 12-2 | BASE |
| `{opponent_record}` | 8-6 | ALL |
| `{venue}` | State Farm Arena | ALL |
| `{game_date}` | November 19, 2025 | ALL |
| `{game_time}` | 7:30 PM EST | ALL |
| `{win_streak}` | 5 | BASE |
| `{loss_streak}` | 3 | BASE |
| `{season_series_record}` | 2-1 | ALL |
| `{team_rank}` | #8 | BASE |
| `{head_coach}` | Monty Williams | BASE |
| `{odds_spread}` | -5.5 | BASE + .next |
| `{score}` | 112 | .last |
| `{final_score}` | 112-98 | .last |

**[View all 117 variables in the app's variable helper]**

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `9195` | Web interface port |
| `TZ` | `America/New_York` | Timezone (synced to database on init) |

---

## Volumes

| Path | Description |
|------|-------------|
| `/app/data` | SQLite database and generated XMLTV files |

---

## Ports

| Port | Description |
|------|-------------|
| `9195` | Web interface |

---

## XMLTV Output

```xml
<programme start="20251119003000 +0000" stop="20251119033000 +0000" channel="pistons.nba">
  <title lang="en">NBA Basketball</title>
  <sub-title lang="en">DET @ ATL - State Farm Arena</sub-title>
  <desc lang="en">Detroit Pistons (12-2) look to extend their 5 game winning streak against Atlanta Hawks (8-6).</desc>
  <category lang="en">Sports</category>
  <category lang="en">Basketball</category>
  <new/>
  <live/>
</programme>
```

---

## Architecture

### Template-Based Model

**Templates** define formatting rules:
- Title/subtitle/description templates
- Conditional descriptions with priority
- Pregame/postgame/idle filler content
- XMLTV flags and categories

**Teams** are lightweight identity records:
- ESPN team ID
- League and sport
- Channel ID
- Template assignment (nullable)

**Benefits**:
- Create one template, reuse for all teams in a league
- Easy to update formatting across multiple teams
- Cleaner separation of concerns
- More flexible and maintainable

---

## Support

- **Issues**: [GitHub Issues](https://github.com/egyptiangio/teamarr/issues)
- **Discussions**: [GitHub Discussions](https://github.com/egyptiangio/teamarr/discussions)

---

## License

MIT License - see [LICENSE](LICENSE) file for details

---

## Changelog

### v1.0.0 (2025-11-23) - BREAKING CHANGE

**Complete architectural rewrite - no migration path**

**Added**:
- Template-based architecture
- Variable suffix system (.next, .last)
- 117 base variables (252 with suffixes)
- 5 opponent conference/division variables
- TZ environment variable sync
- Reorganized variable categories (5 instead of 15)
- Streamlined conditional types (15 focused conditions)
- Scheduled EPG generation (hourly/daily)
- Better UI with color-coded variables
- Improved variable helper with suffix guidance

**Changed**:
- Templates are now separate from teams
- Variables increased from 188 to 252
- Single global timezone (no per-team timezones)
- Conditional descriptions simplified

**Breaking**:
- Database schema incompatible with v0.x
- Users must delete old database and start fresh
- No migration path available

---

**Web Interface**: http://localhost:9195
**Docker Image**: `ghcr.io/egyptiangio/teamarr:latest`
**Version**: 1.0.0
