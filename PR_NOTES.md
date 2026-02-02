# European Football & Combat Sports Matching Improvements

> ⚠️ **Draft PR** - AI-assisted development with Claude (Anthropic) via Cursor IDE

## Summary

This PR improves stream-to-event matching for European football (soccer), UFC, and boxing streams. The changes address parsing issues with common IPTV provider stream name formats that were causing match failures. Additionally, it adds professional EPG filler content with program artwork and game times.

## Changes

### Stream Matching Improvements (`teamarr/consumers/matching/`)

#### `normalizer.py`
- **Added DATE_MASK_WITH_YEAR patterns** - Captures full European-style dates like `23 August 2025` instead of leaving the year behind
- **Added TIME_PATTERN for unusual formats** - Handles `9:pm` format (colon before am/pm) common in some IPTV providers

#### `classifier.py`
- **Enhanced pipe handling** - Strips datetime suffix from team names when format is `Team | Day, Date Time`
  - Before: `FC Barcelona | Saturday, DATE_MASK 2025` → Team2 = broken
  - After: `FC Barcelona` → Team2 = correct
- **Improved fighter name cleaning** - Strips trailing time, fight/rematch numbers, BACKUP/SD tags, and provider suffixes from UFC/boxing streams

### EPG Filler Improvements

#### `database/templates.py`
- **Default channel name format** - When template fields are NULL, use `{away_team} @ {home_team}` instead of empty string
- **Prevents empty display-name tags** in XMLTV output

#### Database Templates (via SQL)
- **All templates updated** with `program_art_url` using jesmann.com sports logos
- **Pregame filler** now shows: "Game Starting at 7:30 PM EST" (includes actual game time!)
- **Postgame filler** shows: "Game Complete" with final score
- **Idle filler** shows upcoming game info with artwork
- **Team aliases** added for major European soccer teams (PSG, Inter, Juventus, Barcelona, Bayern Munich, etc.)

### Configuration
- **docker-compose.yml** - Configured for local development builds
- **Default timezone** - Set to America/New_York

## Test Results

### After Fix
- **Bundesliga**: 17 streams matched ✅
- **Serie A**: 12 streams matched ✅
- **La Liga**: 12 streams matched ✅
- **Premier League**: 23 streams matched ✅
- **Ligue 1**: 9 streams matched ✅
- **UEFA Champions League**: 8 streams matched ✅

### UFC/Boxing
- Fighter names now cleanly extracted: Volkanovski vs Lopes
- Shakur Stevenson vs Teofimo Lopez (fully clean)

## XMLTV Output Validation
- ✅ Valid XML per xmllint
- ✅ UTF-8 encoded
- ✅ Times in UTC with explicit +0000 offset
- ✅ Compatible with Jellyfin, TVHeadend, NextPVR, Plex, Kodi

## Jellyfin Integration Notes

**Important:** When setting up the EPG source in Jellyfin, use the URL with the tvg_id_source parameter:

    http://YOUR_DISPATCHARR_IP:9191/output/epg?tvg_id_source=tvg_id

Without this parameter, Teamarr event channels won't get proper EPG data.

## Filler Content Examples

### Pregame (before game starts)
- **Title**: "Game Starting at 3:00 PM EST"
- **Subtitle**: "New Orleans Pelicans at Charlotte Hornets"
- **Description**: Full venue info with tip-off time
- **Artwork**: Professional matchup cover from jesmann.com

### Postgame (after game ends)
- **Title**: "Game Complete"
- **Subtitle**: Teams that played
- **Description**: Final score included
- **Artwork**: Professional matchup cover

## Development Notes

This PR was developed with AI assistance (Claude/Anthropic via Cursor IDE) for:
- Debugging regex patterns
- Database analysis via MCP SQLite integration
- Testing stream parsing with live data
- XMLTV validation
- Deep dive debugging across Teamarr → Dispatcharr → Jellyfin pipeline

## How to Test

1. Clone this branch
2. Run docker compose up -d --build
3. Trigger EPG generation via UI or API
4. Check match results in the Stats page
5. Verify Jellyfin shows "Game Starting at X:XX PM" instead of generic "Game Starting Soon"
