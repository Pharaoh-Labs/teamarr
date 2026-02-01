# European Football & Combat Sports Matching Improvements

> ⚠️ **Draft PR** - AI-assisted development with Claude (Anthropic) via Cursor IDE

## Summary

This PR improves stream-to-event matching for European football (soccer), UFC, and boxing streams. The changes address parsing issues with common IPTV provider stream name formats that were causing match failures.

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

### Configuration
- **`docker-compose.yml`** - Configured for local development builds (can be switched back to published image for production)
- **Default timezone** - Set to `America/New_York`

## Test Results

### Before Fix
European football streams like:
```
Bundesliga 06: Werder Bremen vs. Borussia Monchengladbach | Saturday, 31 January 2026 14:30
```
Would parse Team2 as `Borussia Monchengladbach | Saturday, 2025` (broken) and fail to match.

### After Fix
- **Bundesliga**: 17 streams matched ✅
- **Serie A**: 12 streams matched ✅
- **La Liga**: 12 streams matched ✅
- **Premier League**: 23 streams matched ✅
- **Ligue 1**: 9 streams matched ✅
- **UEFA Champions League**: 8 streams matched ✅

### UFC/Boxing
- Fighter names now cleanly extracted: `Volkanovski` vs `Lopes` (time and fight numbers stripped)
- `Shakur Stevenson` vs `Teofimo Lopez` (fully clean)

## XMLTV Output Validation
- ✅ Valid XML per `xmllint`
- ✅ UTF-8 encoded
- ✅ Times in UTC with explicit `+0000` offset (standard XMLTV format)
- ✅ Compatible with Jellyfin, TVHeadend, NextPVR, Plex, Kodi

## Development Notes

This PR was developed with AI assistance (Claude/Anthropic via Cursor IDE) for:
- Debugging regex patterns
- Database analysis via MCP SQLite integration
- Testing stream parsing with live data
- XMLTV validation

## How to Test

1. Clone this branch
2. Run `docker compose up -d --build`
3. Trigger EPG generation via UI or API
4. Check match results in the Stats page

## Commits

- `89b9055` - chore(dev): configure docker-compose for local development builds
- `ba2f744` - fix(config): correct default timezone to America/New_York
- `463b624` - fix(matching): improve European football and UFC/Boxing stream parsing
- `0be0d2c` - Expose stream filter settings in UI
- `35485b8` - Improve team extraction for provider suffixes
- `167a797` - Classify time-separated team streams
- `41695ca` - Fix Dispatcharr EPG assignment and XMLTV fallback
