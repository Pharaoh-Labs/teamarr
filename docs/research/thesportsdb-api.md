# TheSportsDB API Research

> TheSportsDB endpoints, response formats, rate limits, and implementation notes.

## Overview

TheSportsDB provides a freemium sports data API. Free tier uses API key `3` (demo key). Premium tier ($9/month) provides dedicated key and enhanced features.

**Base URL:** `https://www.thesportsdb.com/api/v1/json/{api_key}`

**Free API Key:** `3` (demo/public key)

---

## Rate Limits

### Free Tier (API Key: 3)

- No official rate limit documentation
- Community reports suggest ~10-20 requests/minute is safe
- Recommend: 1 request per 3-5 seconds
- Cache aggressively to minimize calls

### Premium Tier ($9/month)

- Dedicated API key
- Higher rate limits (unspecified)
- V2 API access with 2-minute livescores
- Video highlights

### Implementation Strategy

```python
import time
from functools import wraps

MIN_REQUEST_INTERVAL = 3.0  # seconds between requests
_last_request_time = 0

def rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global _last_request_time
        elapsed = time.time() - _last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.time()
        return func(*args, **kwargs)
    return wrapper
```

---

## Core Endpoints

### Events by Day

**Endpoint:** `/eventsday.php`

**Parameters:**
| Param | Description | Example |
|-------|-------------|---------|
| `d` | Date in YYYY-MM-DD format | `2024-12-08` |
| `l` | League ID | `4328` (Premier League) |

**Example:**
```
GET https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d=2024-12-08&l=4328
```

**Response:**
```json
{
  "events": [
    {
      "idEvent": "2274850",
      "strEvent": "Arsenal vs Manchester United",
      "strEventAlternate": "Manchester United @ Arsenal",
      "strSport": "Soccer",
      "idLeague": "4328",
      "strLeague": "English Premier League",
      "strSeason": "2024-2025",
      "strHomeTeam": "Arsenal",
      "strAwayTeam": "Manchester United",
      "intHomeScore": "2",
      "intAwayScore": "1",
      "strTimestamp": "2024-12-08T16:30:00",
      "dateEvent": "2024-12-08",
      "strTime": "16:30:00",
      "idHomeTeam": "133604",
      "idAwayTeam": "133612",
      "strHomeTeamBadge": "https://...",
      "strAwayTeamBadge": "https://...",
      "idVenue": "15086",
      "strVenue": "Emirates Stadium",
      "strCountry": "England",
      "strStatus": "FT",
      "strPostponed": "no"
    }
  ]
}
```

**Note:** Returns `{"events": null}` when no events.

### Next Events by League

**Endpoint:** `/eventsnextleague.php`

**Parameters:**
| Param | Description | Example |
|-------|-------------|---------|
| `id` | League ID | `4328` |

**Example:**
```
GET https://www.thesportsdb.com/api/v1/json/3/eventsnextleague.php?id=4328
```

Returns next 15 upcoming events for the league.

### Next Events by Team

**Endpoint:** `/eventsnext.php`

**Parameters:**
| Param | Description | Example |
|-------|-------------|---------|
| `id` | Team ID | `133604` |

**Example:**
```
GET https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id=133604
```

Returns next 5 upcoming events for the team.

### Event Lookup (by ID)

**Endpoint:** `/lookupevent.php`

**Parameters:**
| Param | Description | Example |
|-------|-------------|---------|
| `id` | Event ID | `2274850` |

**Example:**
```
GET https://www.thesportsdb.com/api/v1/json/3/lookupevent.php?id=2274850
```

### Team Lookup

**Endpoint:** `/lookupteam.php`

**Parameters:**
| Param | Description | Example |
|-------|-------------|---------|
| `id` | Team ID | `133604` |

**Example:**
```
GET https://www.thesportsdb.com/api/v1/json/3/lookupteam.php?id=133604
```

**Response (47 fields):**
```json
{
  "teams": [
    {
      "idTeam": "133604",
      "strTeam": "Arsenal",
      "strTeamShort": "ARS",
      "strTeamAlternate": "Arsenal FC, The Gunners",
      "intFormedYear": "1886",
      "strSport": "Soccer",
      "strLeague": "English Premier League",
      "idLeague": "4328",
      "strLeague2": "FA Cup",
      "idLeague2": "4482",
      "strStadium": "Emirates Stadium",
      "intStadiumCapacity": "60260",
      "strLocation": "London, England",
      "strCountry": "England",
      "strBadge": "https://...",
      "strLogo": "https://...",
      "strColour1": "#EF0107",
      "strColour2": "#FFFFFF",
      "strDescriptionEN": "Arsenal Football Club..."
    }
  ]
}
```

### Search Teams

**Endpoint:** `/searchteams.php`

**Parameters:**
| Param | Description | Example |
|-------|-------------|---------|
| `t` | Team name query | `Arsenal` |

**Example:**
```
GET https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t=Arsenal
```

### All Leagues

**Endpoint:** `/all_leagues.php`

Returns all available leagues.

```json
{
  "leagues": [
    {
      "idLeague": "4328",
      "strLeague": "English Premier League",
      "strSport": "Soccer",
      "strLeagueAlternate": "Premier League, EPL"
    }
  ]
}
```

### Teams in League

**Endpoint:** `/lookup_all_teams.php`

**Parameters:**
| Param | Description | Example |
|-------|-------------|---------|
| `id` | League ID | `4328` |

**Example:**
```
GET https://www.thesportsdb.com/api/v1/json/3/lookup_all_teams.php?id=4328
```

---

## Event Status Mapping

| TSDB Status | Meaning | Our State |
|-------------|---------|-----------|
| `NS` | Not Started | `scheduled` |
| `1H` | First Half | `live` |
| `HT` | Half Time | `live` |
| `2H` | Second Half | `live` |
| `FT` | Full Time | `final` |
| `AET` | After Extra Time | `final` |
| `PEN` | Penalties | `final` |
| `PST` | Postponed | `postponed` |
| `CANC` | Cancelled | `cancelled` |
| `ABD` | Abandoned | `cancelled` |
| `AWD` | Awarded | `final` |
| `WO` | Walkover | `final` |

**Note:** `strPostponed` field also indicates `"yes"` or `"no"`.

---

## Key League IDs

### Major Leagues

| League | ID | Notes |
|--------|-----|-------|
| Premier League | 4328 | |
| La Liga | 4335 | |
| Bundesliga | 4331 | |
| Serie A | 4332 | |
| Ligue 1 | 4334 | |
| Champions League | 4480 | |
| NFL | 4391 | |
| NBA | 4387 | |
| NHL | 4380 | |
| MLB | 4424 | |

### Leagues ESPN Doesn't Cover

| League | ID | Notes |
|--------|-----|-------|
| AHL | 4380 | ESPN gap |
| English League 1 | 4396 | Third tier |
| English League 2 | 4397 | Fourth tier |
| Scottish Premiership | 4330 | |
| Eredivisie | 4337 | Netherlands |
| MLS | 4346 | |
| Australian A-League | 4356 | |

---

## Response Normalization

### Event Normalization

```python
def normalize_event(raw: dict, league: str) -> Optional[Event]:
    """Convert TheSportsDB event to our Event dataclass."""
    return Event(
        id=raw['idEvent'],
        provider='thesportsdb',
        name=raw.get('strEvent', ''),
        short_name=raw.get('strEventAlternate', ''),
        start_time=parse_timestamp(raw.get('strTimestamp')),
        home_team=Team(
            id=raw['idHomeTeam'],
            provider='thesportsdb',
            name=raw['strHomeTeam'],
            short_name=raw['strHomeTeam'][:3].upper(),
            abbreviation=raw['strHomeTeam'][:3].upper(),
            league=league,
            logo_url=raw.get('strHomeTeamBadge'),
        ),
        away_team=Team(
            id=raw['idAwayTeam'],
            provider='thesportsdb',
            name=raw['strAwayTeam'],
            short_name=raw['strAwayTeam'][:3].upper(),
            abbreviation=raw['strAwayTeam'][:3].upper(),
            league=league,
            logo_url=raw.get('strAwayTeamBadge'),
        ),
        status=normalize_status(raw.get('strStatus', 'NS')),
        league=league,
        home_score=parse_score(raw.get('intHomeScore')),
        away_score=parse_score(raw.get('intAwayScore')),
        venue=Venue(name=raw.get('strVenue', ''))
    )

def parse_score(score: Optional[str]) -> Optional[int]:
    """Parse TSDB score (string or null) to int."""
    if score is None or score == '':
        return None
    try:
        return int(score)
    except ValueError:
        return None
```

### Team Normalization

```python
def normalize_team(raw: dict, league: str) -> Team:
    """Convert TheSportsDB team to our Team dataclass."""
    return Team(
        id=raw['idTeam'],
        provider='thesportsdb',
        name=raw['strTeam'],
        short_name=raw.get('strTeamShort', raw['strTeam'][:3].upper()),
        abbreviation=raw.get('strTeamShort', raw['strTeam'][:3].upper()),
        league=league,
        logo_url=raw.get('strBadge'),
        color=raw.get('strColour1', '').replace('#', ''),
    )
```

---

## Differences from ESPN

| Aspect | ESPN | TheSportsDB |
|--------|------|-------------|
| IDs | Numeric strings | Numeric strings |
| Dates | ISO 8601 with Z | Separate date/time fields |
| Scores | Nested in competitor | Flat fields |
| Status | Nested object | Single string code |
| Abbreviations | Always provided | Sometimes missing |
| Team colors | Without # | With # prefix |
| Rate limits | Generous | Must rate limit |

---

## Team Multi-League Discovery

TheSportsDB teams can belong to multiple leagues:

```json
{
  "strLeague": "English Premier League",
  "idLeague": "4328",
  "strLeague2": "FA Cup",
  "idLeague2": "4482",
  "strLeague3": "EFL Cup",
  "idLeague3": "4570",
  "strLeague4": "Champions League",
  "idLeague4": "4480"
}
```

This helps solve the soccer multi-league problem:

```python
def get_team_leagues(team_id: str) -> List[str]:
    """Get all leagues a team plays in."""
    data = client.lookup_team(team_id)
    if not data or 'teams' not in data:
        return []

    team = data['teams'][0]
    leagues = []

    for i in range(1, 8):
        suffix = '' if i == 1 else str(i)
        league_id = team.get(f'idLeague{suffix}')
        if league_id:
            leagues.append(league_id)

    return leagues
```

---

## Limitations

### Free Tier

- Limited to 5 next events per team
- Limited to 15 next events per league
- No historical events beyond recent
- No livescores (only status updates)

### Data Quality

- Abbreviations sometimes missing (generate from name)
- Colors include # prefix (strip for consistency)
- Some leagues have incomplete data
- Schedule updates may lag behind ESPN

### Coverage Gaps

TSDB covers ESPN gaps but has its own gaps:
- Some minor leagues incomplete
- Newer leagues may lack teams
- Stadium/venue data often missing

---

## Caching Recommendations

```python
CACHE_DURATIONS = {
    'team': 24 * 60 * 60,      # 24 hours - team info rarely changes
    'league_teams': 7 * 24 * 60 * 60,  # 1 week
    'events_day': 5 * 60,      # 5 minutes - scores update
    'events_next': 60 * 60,    # 1 hour - schedule mostly stable
}
```

---

## Error Handling

```python
def _request(self, endpoint: str, params: dict = None) -> Optional[dict]:
    url = f"{self.base_url}/{endpoint}"

    try:
        response = self._session.get(url, params=params, timeout=10)

        if response.status_code == 429:
            log.warn("RATE_LIMITED", "TheSportsDB rate limit hit")
            time.sleep(60)  # Back off for 1 minute
            return None

        if response.status_code != 200:
            log.error("HTTP_ERROR", f"Status {response.status_code}")
            return None

        data = response.json()

        # TSDB returns null for "no results" instead of empty array
        if data.get('events') is None:
            return {'events': []}
        if data.get('teams') is None:
            return {'teams': []}

        return data

    except requests.exceptions.RequestException as e:
        log.error("REQUEST_FAILED", str(e))
        return None
```

---

## When to Use TheSportsDB

Use TSDB when:
1. ESPN doesn't cover the league (AHL, lower European tiers)
2. Need team multi-league discovery for soccer
3. ESPN is down (fallback)

Prefer ESPN when:
1. Both cover the league (ESPN is fresher)
2. Need detailed stats (TSDB stats are limited)
3. Need livescores (TSDB free tier doesn't have them)
