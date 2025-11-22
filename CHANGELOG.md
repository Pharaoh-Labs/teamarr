# Changelog

All notable changes to TeamArr will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-11-23

### ⚠️ BREAKING CHANGES

**Complete architectural rewrite - no database migration available**

Users on v0.x MUST delete their existing database and start fresh. The database schema is fundamentally different and incompatible.

**Migration Steps**:
1. Stop your current TeamArr instance
2. Delete `teamarr.db`
3. Update to v1.0.0
4. Start TeamArr (fresh database auto-created)
5. Reconfigure from scratch (create templates, import teams, assign templates)

### Added

#### Template-Based Architecture
- **Templates**: Reusable formatting rules separate from teams
- Create one template, assign to multiple teams
- Templates include: title/subtitle/description formats, conditional descriptions, filler content, XMLTV settings
- Template library: Export/import templates as JSON for sharing

#### Variable Suffix System
- **117 base variables** (up from ~90 in v0.x)
- **252 total variables** with `.next` and `.last` suffix support
- Syntax: `{variable}`, `{variable.next}`, `{variable.last}`
- Access current game, next game, and last game contexts
- All 59 game-specific variables support all three contexts
- 36 team identity variables (BASE only - no suffix)
- 10 result variables (.last only)
- 7 odds variables (BASE + .next)

#### New Variables (v1.0.0)
- `opponent_college_conference` - Opponent's college conference name
- `opponent_college_conference_abbrev` - Opponent's college conference abbreviation
- `opponent_pro_conference` - Opponent's pro conference name
- `opponent_pro_conference_abbrev` - Opponent's pro conference abbreviation
- `opponent_pro_division` - Opponent's pro division name

#### Variable Organization
- Reorganized from 15 categories to 5 logical groups:
  - 🏈 **Teams** (30 vars) - Team/opponent identity, venue, league, conferences, divisions
  - 📅 **Games** (19 vars) - Date, time, status, broadcasts, season context
  - 📊 **Team Stats** (52 vars) - Records, standings, streaks, performance, h2h
  - 👥 **Roster & Players** (9 vars) - Head coach, player leaders
  - 💰 **Betting & Odds** (7 vars) - Spreads, moneylines, over/under

#### Conditional Descriptions
- Streamlined to 15 focused condition types:
  - Is home / Is away
  - Streak (win) ≥ N / Streak (loss) ≥ N
  - Home Streak (win) ≥ N / Home Streak (loss) ≥ N
  - Away Streak (win) ≥ N / Away Streak (loss) ≥ N
  - Is playoff / Is preseason
  - Has odds
  - Ranked opponent (top 25)
  - Top 10 matchup
  - Opponent name contains [text]
  - Is National Broadcast
- Priority-based matching (1-100, lower = higher priority)
- Fallback descriptions (priority 100)
- Preset library for saving/reusing conditions

#### User Interface
- **Variable Helper**: Color-coded variables showing suffix availability
  - Blue = All contexts (base, .next, .last)
  - Gray = No suffix (BASE only)
  - Green = Base + .next
  - Red = .last only
- **Suffix Guide**: Compact guidance at top of variable helper
- **Variable Search**: Real-time filtering
- **Recently Used**: Track frequently used variables
- **Live Preview**: Real-time template preview with sample data
- **5 Tabbed Sections**: Basic Info, Templates, Conditions, Fillers, XMLTV Settings

#### Features
- **Scheduled EPG Generation**: Automatic hourly or daily regeneration
- **TZ Environment Sync**: Timezone automatically synced from Docker `TZ` variable on database init
- **Team Import System**: Browse/search teams by league, conference-based for college sports
- **Bulk Operations**: Assign template, activate/deactivate, delete multiple teams
- **Template Export/Import**: Share templates via JSON
- **EPG Management Page**: Full EPG preview, analysis, search, download
- **Settings Page**: Organized into 6 sections with improved layout

### Changed

#### Architecture
- **From**: Team-centric model (all settings stored per-team)
- **To**: Template-based model (formatting separate from team identity)
- Templates are reusable across multiple teams
- Teams are lightweight identity records with template assignment

#### Variables
- **Count**: 188 → 252 (with suffix system)
- **Organization**: 15 categories → 5 logical groups
- **Naming**: Renamed 6 variables for consistency:
  - `matchup` → `matchup_abbrev`
  - `moneyline` → `odds_moneyline`
  - `opponent_moneyline` → `odds_opponent_moneyline`
  - `over_under` → `odds_over_under`
  - `spread` → `odds_spread`
  - `opponent_spread_odds` → `odds_opponent_spread`

#### Timezone
- **From**: Per-team timezone settings
- **To**: Single global timezone (synced from `TZ` environment variable)
- Simplified configuration
- Matches typical use case (one timezone for all teams)

#### Database Schema
- Complete redesign: `templates` + simplified `teams` tables
- Template ID is nullable foreign key on teams (allows unassigned teams)
- ON DELETE SET NULL for template deletion (teams become unassigned)
- No migration path from v0.x

### Removed

#### Variables (v0.x → v1.0.0)
- Deleted 52 variables during audit:
  - Redundant/unused variables
  - Legacy context variables (old next_*, last_* implementation)
  - Old player leader variables (replaced with new implementation)
- See `VARIABLE_SUFFIX_AUDIT_LOG.md` for full details

#### Features
- Per-team timezone settings (now single global timezone)
- Team-level filler configuration (now template-level)
- Per-team XMLTV settings (now template-level)
- Some conditional types (streamlined from 15+ to 15 focused types)

### Fixed
- Midnight crossover handling for games that span midnight
- EPG page redirect (returns to EPG tab instead of dashboard)
- Variable population logic for deleted variables
- JSON parsing for template fields (categories, flags, description_options)
- Light mode badge visibility with borders
- Dropdown sizing consistency

### Technical Details

#### Files Changed (v0.x → v1.0.0)
- `database/schema.sql`: Complete rewrite for template-based model
- `epg/orchestrator.py`: Updated for template merging (1,741 lines)
- `epg/template_engine.py`: Added suffix system, updated variables (1,193 lines)
- `templates/*.html`: All UI pages rebuilt for template-based workflow
- `static/css/style.css`: Added suffix guidance styling
- `config/variables.json`: Updated to 117 variables with suffix documentation

#### API Endpoints Added
- `/api/variables` - Returns all template variables
- `/api/condition-presets` - Preset library
- `/api/templates` - Template list for dropdowns
- `/api/leagues/<league>/conferences` - College sports conferences
- `/api/teams/bulk-import` - Bulk team import

#### Dependencies
- Python 3.8+
- Flask
- SQLite3
- Requests (ESPN API)

### Migration Notes

**For Users on v0.x**:
1. Backup your current `teamarr.db` (for reference only - not usable)
2. Stop TeamArr
3. Delete `teamarr.db`
4. Update to v1.0.0 (pull/rebuild)
5. Start TeamArr (fresh DB created)
6. Create templates
7. Import teams from ESPN
8. Assign templates to teams

**Why No Migration?**
The database schema is fundamentally incompatible. The old model stored all formatting per-team. The new model separates templates from teams. Automatic migration would require:
- Creating templates from each unique team configuration
- Handling partial matches (teams with similar but not identical settings)
- Migrating conditional descriptions to new priority system
- Converting per-team timezones to global timezone

This complexity, combined with the small user base, makes manual reconfiguration the safest approach.

**Old Version Available**: The v0.x codebase is preserved on the `old-team-centric-v0.x` branch.

---

## [0.x.x] - Pre-1.0.0

See `old-team-centric-v0.x` branch for changelog of earlier versions.

Major features in v0.x:
- Team-centric architecture
- 188 template variables
- 15+ conditional description types
- ESPN API integration
- Web-based configuration
- XMLTV generation
- Dark mode UI
- Docker support

---

[1.0.0]: https://github.com/egyptiangio/teamarr/releases/tag/v1.0.0
