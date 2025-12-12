# ESPN API Research

> ESPN API endpoints, response formats, and implementation notes.

## Overview

ESPN provides a free, undocumented public API. No authentication required. No official rate limits documented, but aggressive polling should be avoided.

**Base URL:** `https://site.api.espn.com/apis/site/v2/sports`

---

## Core Endpoints

### Scoreboard (Primary Data Source)

**Endpoint:** `/{sport}/{league}/scoreboard`

**Parameters:**
| Param | Description | Example |
|-------|-------------|---------|
| `dates` | Date in YYYYMMDD format | `20241208` |
| `groups` | Group ID for college (unlocks full D1) | `50` (basketball), `80` (football FBS) |

**Example:**
```
GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=20241208
```

**Response Structure:**
```json
{
  "events": [
    {
      "id": "401547679",
      "uid": "s:20~l:28~e:401547679",
      "date": "2024-12-08T18:00Z",
      "name": "Detroit Lions at Chicago Bears",
      "shortName": "DET @ CHI",
      "competitions": [
        {
          "id": "401547679",
          "date": "2024-12-08T18:00Z",
          "competitors": [
            {
              "id": "8",
              "homeAway": "home",
              "team": {
                "id": "8",
                "displayName": "Chicago Bears",
                "abbreviation": "CHI",
                "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/chi.png",
                "color": "0B162A"
              },
              "score": "20",
              "record": [{"type": "total", "summary": "4-9", "displayValue": "4-9"}]
            },
            {
              "id": "8",
              "homeAway": "away",
              "team": {...},
              "score": "23"
            }
          ],
          "venue": {
            "fullName": "Soldier Field",
            "address": {"city": "Chicago", "state": "IL"}
          },
          "broadcasts": [
            {"market": {"type": "National"}, "names": ["FOX"]}
          ],
          "status": {
            "type": {
              "id": "3",
              "name": "STATUS_FINAL",
              "state": "post",
              "completed": true,
              "description": "Final"
            },
            "period": 4,
            "displayClock": "0:00"
          }
        }
      ]
    }
  ]
}
```

### Team Schedule

**Endpoint:** `/{sport}/{league}/teams/{team_id}/schedule`

**Example:**
```
GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/8/schedule
```

**Response:** Same `events` structure as scoreboard.

**Use case:** Extended lookahead (30+ days), fallback when scoreboard doesn't have a game.

### Team Info

**Endpoint:** `/{sport}/{league}/teams/{team_id}`

**Example:**
```
GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/8
```

**Response:**
```json
{
  "team": {
    "id": "8",
    "uid": "s:20~l:28~t:8",
    "slug": "detroit-lions",
    "displayName": "Detroit Lions",
    "shortDisplayName": "Lions",
    "abbreviation": "DET",
    "color": "0076B6",
    "alternateColor": "B0B7BC",
    "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/det.png",
    "record": {
      "items": [
        {"type": "total", "summary": "12-1", "stats": [...]},
        {"type": "home", "summary": "6-0"},
        {"type": "road", "summary": "6-1"}
      ]
    },
    "groups": {
      "id": "10",
      "parent": {"id": "7"},
      "isConference": false
    }
  }
}
```

### Event Summary (Single Event)

**Endpoint:** `/{sport}/{league}/summary?event={event_id}`

**Example:**
```
GET https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=401547679
```

**Use case:** Refresh event status, get final scores after game ends.

**Note:** Response structure differs from scoreboard. Requires transformation:
```python
# Summary returns header/competitions structure
header = data.get('header', {})
competitions = header.get('competitions', [{}])
competition = competitions[0]

# Must reconstruct scoreboard-like event
event = {
    'id': event_id,
    'date': competition.get('date'),
    'competitions': [{
        'competitors': competition.get('competitors', []),
        'status': competition.get('status', {}),
        # etc
    }]
}
```

### Group Info (Conference/Division Names)

**Endpoint (Core API):** `http://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/groups/{group_id}`

**Example:**
```
GET http://sports.core.api.espn.com/v2/sports/football/nfl/groups/10
```

**Response:**
```json
{
  "id": "10",
  "name": "NFC North",
  "shortName": "NFC North",
  "abbreviation": "NFCN",
  "isConference": false
}
```

---

## Sport/League Mappings

| Canonical | Sport | League | Notes |
|-----------|-------|--------|-------|
| `nfl` | football | nfl | |
| `nba` | basketball | nba | |
| `mlb` | baseball | mlb | |
| `nhl` | hockey | nhl | |
| `wnba` | basketball | wnba | |
| `mls` | soccer | usa.1 | |
| `mens-college-basketball` | basketball | mens-college-basketball | Add `groups=50` |
| `womens-college-basketball` | basketball | womens-college-basketball | Add `groups=50` |
| `college-football` | football | college-football | Add `groups=80` |
| `eng.1` | soccer | eng.1 | Premier League |
| `esp.1` | soccer | esp.1 | La Liga |
| `ger.1` | soccer | ger.1 | Bundesliga |

### College Sports Group IDs

```python
COLLEGE_SCOREBOARD_GROUPS = {
    'mens-college-basketball': '50',      # D1
    'womens-college-basketball': '50',    # D1
    'college-football': '80',             # FBS
    'mens-college-hockey': '50',
    'womens-college-hockey': '50',
}
```

Without groups param: ~5-10 featured games
With groups param: ~48-61 all D1 games

---

## Status Mapping

| ESPN State | ESPN Name | Our State |
|------------|-----------|-----------|
| `pre` | STATUS_SCHEDULED | `scheduled` |
| `in` | STATUS_IN_PROGRESS | `live` |
| `post` | STATUS_FINAL | `final` |
| `postponed` | STATUS_POSTPONED | `postponed` |
| `canceled` | STATUS_CANCELED | `cancelled` |

Status also includes:
- `period`: Current period/quarter (integer)
- `displayClock`: Game clock string ("12:34")
- `type.description`: Human-readable ("1st Quarter", "Final")

---

## Record Extraction

Records are nested in competitor data:

```python
def extract_record(record_list: List) -> Dict:
    """Extract win-loss record from competitor record array."""
    for rec in record_list:
        if rec.get('type') == 'total':
            summary = rec.get('displayValue', '0-0')
            # Parse "9-5" or "9-5-1" format
            parts = summary.split('-')
            return {
                'summary': summary,
                'wins': int(parts[0]),
                'losses': int(parts[1]),
                'ties': int(parts[2]) if len(parts) == 3 else 0
            }
    return {'summary': '0-0', 'wins': 0, 'losses': 0, 'ties': 0}
```

---

## Team Stats Fields

From `/teams/{id}` response, `record.items` contains:

| Type | Description |
|------|-------------|
| `total` | Overall record with stats array |
| `home` | Home record |
| `road` | Away record |
| `division` | Division record (pro sports) |

Stats array contains:
- `wins`, `losses`, `ties`
- `winPercent`
- `streak` (current win/loss streak count)
- `avgPointsFor` (PPG)
- `avgPointsAgainst` (PAPG)
- `playoffSeed`
- `gamesBehind`
- `homeWins`, `homeLosses`, `homeTies`
- `awayWins`, `awayLosses`, `awayTies`

---

## Conference/Division Logic

```python
# Team groups structure
groups = team_data['team'].get('groups', {})
division_id = groups.get('id', '')           # Division or conference ID
conference_id = groups.get('parent', {}).get('id', '')  # Parent conference
is_conference = groups.get('isConference', False)

# If isConference=true: groups.id IS the conference (no parent)
# If isConference=false: groups.id is division, groups.parent.id is conference

# Lookup names via Core API
# GET http://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/groups/{id}
```

---

## Caching Strategy (from v1)

v1 uses class-level caches cleared per EPG generation:

```python
class ESPNClient:
    # Class-level caches (shared across instances)
    _scoreboard_cache: Dict[tuple, Optional[Dict]] = {}
    _schedule_cache: Dict[tuple, Optional[Dict]] = {}
    _team_info_cache: Dict[tuple, Optional[Dict]] = {}
    _roster_cache: Dict[tuple, Optional[Dict]] = {}
    _group_cache: Dict[tuple, tuple] = {}

    # Thread-safe with double-checked locking
    def get_scoreboard(self, sport, league, date):
        cache_key = (sport, league, date)
        if cache_key in self._scoreboard_cache:
            return self._scoreboard_cache[cache_key]

        with self._scoreboard_cache_lock:
            if cache_key in self._scoreboard_cache:
                return self._scoreboard_cache[cache_key]

            result = self._make_request(url)
            self._scoreboard_cache[cache_key] = result
            return result
```

**Cache benefits:** Reduced scoreboard calls from 1000+ to ~20 per EPG generation.

---

## Error Handling

```python
def _make_request(self, url: str) -> Optional[Dict]:
    for attempt in range(self.retry_count):  # Default: 3
        try:
            response = self._session.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < self.retry_count - 1:
                time.sleep(self.retry_delay * (attempt + 1))  # 1s, 2s, 3s
                continue
            return None
```

---

## Edge Cases

### Postponed Games
- `status.type.state` = `"postponed"`
- `status.type.description` = `"Postponed - Weather"`
- Original `date` still present, may have new date in `notes`

### TBD Opponents
- College tournaments may have `team.displayName` = `"TBD"`
- `team.id` may be absent or special value

### Doubleheaders
- Same teams, same date, different `id`
- Disambiguate by time or event number

### Missing Fields
- `logo`, `color` sometimes absent
- `venue` may be null
- `broadcasts` array may be empty

### Soccer Record Format
- Uses W-D-L format (draws in middle): "6-2-4"
- vs other sports W-L or W-L-T: "10-5" or "10-5-2"

---

## Connection Pooling

```python
from requests.adapters import HTTPAdapter

session = requests.Session()
adapter = HTTPAdapter(
    pool_connections=10,   # Connection pools (per host)
    pool_maxsize=100,      # Max connections per pool
    max_retries=0          # Handle retries manually
)
session.mount('http://', adapter)
session.mount('https://', adapter)
```

---

## Leagues NOT Covered by ESPN

ESPN does NOT cover:
- AHL (American Hockey League)
- OHL/WHL/QMJHL (Canadian junior hockey)
- Lower European soccer tiers (ger.3, eng.5, etc.)
- Australian leagues (AFL, NRL)
- Many international competitions

These require TheSportsDB or other providers.
