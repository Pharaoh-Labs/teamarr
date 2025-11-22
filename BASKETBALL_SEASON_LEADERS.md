# Basketball Season Leaders - ESPN Core API

## Overview
Season leader statistics (top scorer PPG) are fetched from ESPN's Core API for reliable, up-to-date data.

## API Endpoint
```
http://sports.core.api.espn.com/v2/sports/basketball/leagues/{league}/seasons/{year}/types/2/teams/{team_id}/leaders
```

### Parameters
- `{sport}`: `basketball`
- `{league}`: `nba`, `mens-college-basketball`, `womens-college-basketball`, `wnba`
- `{year}`: Current season year (e.g., 2026 for 2025-26 NBA season)
  - NBA/WNBA: Use current year + 1
  - NCAA: Use current year
- `{team_id}`: ESPN team ID

### Response Structure
```json
{
  "categories": [
    {
      "name": "pointsPerGame",
      "displayName": "Points Per Game",
      "leaders": [
        {
          "displayValue": "27.4",
          "value": 27.4375,
          "athlete": {
            "$ref": "http://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/2026/athletes/3917376"
          }
        }
      ]
    },
    {
      "name": "reboundsPerGame",
      "...": "..."
    },
    {
      "name": "assistsPerGame",
      "...": "..."
    }
  ]
}
```

## Implementation

### Method: `_get_season_leaders_from_core_api()`
Location: `epg/orchestrator.py:1421-1472`

**Process**:
1. Call Core API leaders endpoint
2. Find `pointsPerGame` category
3. Get first leader from leaders array
4. Fetch athlete details from `$ref` URL
5. Extract name, position, PPG

**Data Flow**:
```
Core API Leaders Endpoint
    ↓
Get pointsPerGame category
    ↓
Fetch athlete.$ref (name, position)
    ↓
Build result dict
    ↓
Return basketball_top_scorer_* variables
```

### Variables Populated
- `basketball_top_scorer_name` - Player display name (e.g., "Jaylen Brown")
- `basketball_top_scorer_position` - Position abbreviation (e.g., "G", "F")
- `basketball_top_scorer_ppg` - Points per game (e.g., "27.4")
- `basketball_top_scorer_total` - **Empty string** (see Limitations below)

## Integration

### When Core API is Used
The Core API is called for **scheduled/future basketball games**:
- Game status is NOT `STATUS_FINAL` or `STATUS_FULL_TIME`
- Ensures season stats for upcoming games

### Fallback Behavior
If Core API fails or returns no data:
1. Falls back to competition data (schedule events)
2. Uses game leaders for completed games
3. May return empty dict if no leaders available

### Code Location
`epg/orchestrator.py:1635-1684` - `_extract_player_leaders()`

```python
# For basketball, try Core API for season leaders
if 'basketball' in league:
    game_status = competition.get('status', {}).get('type', {}).get('name', '')

    # For scheduled games, use Core API for accurate season stats
    if game_status not in ['STATUS_FINAL', 'STATUS_FULL_TIME']:
        season_leaders = self._get_season_leaders_from_core_api(sport, league, team_id)
        if season_leaders:
            return season_leaders
```

## Limitations

### 1. `basketball_top_scorer_total` is Empty
**Reason**: Core API doesn't provide individual player games played (GP) in a straightforward way.

**Why Total is Unreliable**:
- Calculating `total = PPG * games_played` requires player's GP, not team GP
- Using team GP would be inaccurate if player missed games
- ESPN Core API requires additional athlete statistics call to get GP
- Adding extra API calls for estimate isn't worth the cost

**Alternative**: Users can use `{basketball_top_scorer_ppg}` in templates instead of total.

### 2. Season Year Calculation
**Current Implementation**: `current_year = datetime.now().year + 1`

**Assumption**: Works for NBA (2025-26 season = year 2026)

**Edge Cases**:
- Early January games might be in previous season
- NCAA basketball uses different year format
- WNBA season spans single year

**Future Improvement**: Parse season year from team stats or schedule data instead of calculating.

## Testing

### Manual Test
```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from epg.orchestrator import EPGOrchestrator

orch = EPGOrchestrator()
result = orch._get_season_leaders_from_core_api('basketball', 'nba', '2')
print('Top scorer:', result.get('basketball_top_scorer_name'))
print('PPG:', result.get('basketball_top_scorer_ppg'))
"
```

**Expected Output**:
```
Top scorer: Jaylen Brown
PPG: 27.4
```

### Test with Audit Script
```bash
python3 variable_audit_live.py 9
```

Should now show populated `basketball_top_scorer_*` variables instead of empty strings.

## Example Template Usage

### Using PPG Only
```
{team} is led by {basketball_top_scorer_name} ({basketball_top_scorer_position}), averaging {basketball_top_scorer_ppg} points per game.
```

**Output**:
```
Boston Celtics is led by Jaylen Brown (G), averaging 27.4 points per game.
```

### Avoid Using Total
❌ **Don't use** (will be empty):
```
{basketball_top_scorer_name} has scored {basketball_top_scorer_total} points this season.
```

✅ **Use instead**:
```
{basketball_top_scorer_name} is averaging {basketball_top_scorer_ppg} PPG this season.
```

## Future Enhancements

### Potential Additions
1. **Rebounds and Assists Leaders**: Add `reboundsPerGame` and `assistsPerGame` categories
2. **Player GP Fetch**: Make additional API call to get accurate totals
3. **Caching**: Cache season leaders to reduce API calls (updates daily)
4. **Multiple Leaders**: Support top 3 scorers instead of just #1

### Additional Categories Available
The Core API provides many categories:
- `reboundsPerGame`
- `assistsPerGame`
- `blocksPerGame`
- `stealsPerGame`
- `fieldGoalPct`
- `threePointFieldGoalPct`
- `freeThrowPct`

All follow the same `$ref` pattern for athlete lookup.

---

**Last Updated**: 2025-11-22
**Status**: Production Ready ✅
**API Calls**: 2 per team (leaders + athlete details)
