# API Field Mappings Reference

> Captured live API responses with exact field paths for normalizer implementation.

## ESPN API

### Scoreboard Response (Primary)

**Endpoint:** `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard`

```json
{
  "leagues": [...],
  "season": {"type": 2, "year": 2025},
  "week": {"number": 14, "teamsOnBye": [...]},
  "events": [
    {
      "id": "401772947",                           // → Event.id
      "uid": "s:20~l:28~e:401772947",
      "date": "2025-12-05T01:15Z",                 // → Event.start_time (UTC ISO 8601)
      "name": "Dallas Cowboys at Detroit Lions",   // → Event.name
      "shortName": "DAL @ DET",                    // → Event.short_name
      "season": {"year": 2025, "type": 2, "slug": "regular-season"},
      "week": {"number": 14},
      "competitions": [
        {
          "id": "401772947",
          "date": "2025-12-05T01:15Z",
          "attendance": 64028,
          "venue": {                               // → Event.venue
            "id": "3727",
            "fullName": "Ford Field",              // → Venue.name
            "address": {
              "city": "Detroit",                   // → Venue.city
              "state": "MI",                       // → Venue.state
              "country": "USA"                     // → Venue.country
            },
            "indoor": true
          },
          "competitors": [
            {
              "id": "8",
              "homeAway": "home",                  // Determine home vs away
              "winner": true,
              "team": {
                "id": "8",                         // → Team.id
                "location": "Detroit",
                "name": "Lions",
                "abbreviation": "DET",             // → Team.abbreviation
                "displayName": "Detroit Lions",    // → Team.name
                "shortDisplayName": "Lions",       // → Team.short_name
                "color": "0076b6",                 // → Team.color (no # prefix)
                "alternateColor": "bbbbbb",
                "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/scoreboard/det.png"
                                                   // → Team.logo_url
              },
              "score": "44",                       // → Event.home_score (string!)
              "linescores": [{"value": 10.0, "period": 1}, ...],
              "records": [
                {"type": "total", "summary": "8-5"},   // → TeamStats.record
                {"type": "home", "summary": "5-2"},    // → TeamStats.home_record
                {"type": "road", "summary": "3-3"}    // → TeamStats.away_record
              ]
            },
            {
              "id": "6",
              "homeAway": "away",                  // This is the away team
              "winner": false,
              "team": {...},
              "score": "30",                       // → Event.away_score
              "records": [...]
            }
          ],
          "broadcasts": [
            {"market": "national", "names": ["Prime Video"]}
                                                   // → Event.broadcasts
          ],
          "status": {
            "clock": 0.0,
            "displayClock": "0:00",                // → EventStatus.clock
            "period": 4,                           // → EventStatus.period
            "type": {
              "id": "3",
              "name": "STATUS_FINAL",
              "state": "post",                     // → EventStatus.state mapping
              "completed": true,
              "description": "Final",              // → EventStatus.detail
              "detail": "Final",
              "shortDetail": "Final"
            }
          },
          "notes": [],
          "leaders": [...]  // Player stats, not needed for EPG
        }
      ],
      "status": {...}  // Duplicate of competitions[0].status
    }
  ]
}
```

### Team Info Response

**Endpoint:** `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}`

```json
{
  "team": {
    "id": "8",                                     // → Team.id
    "uid": "s:20~l:28~t:8",
    "slug": "detroit-lions",                       // Store in provider_metadata
    "location": "Detroit",
    "name": "Lions",
    "nickname": "Lions",
    "abbreviation": "DET",                         // → Team.abbreviation
    "displayName": "Detroit Lions",                // → Team.name
    "shortDisplayName": "Lions",                   // → Team.short_name
    "color": "0076b6",                             // → Team.color
    "alternateColor": "bbbbbb",
    "logos": [
      {
        "href": "https://a.espncdn.com/i/teamlogos/nfl/500/det.png",
        "rel": ["full", "default"]                 // Use this one → Team.logo_url
      },
      {
        "href": "https://a.espncdn.com/i/teamlogos/nfl/500-dark/det.png",
        "rel": ["full", "dark"]
      },
      {
        "href": "https://a.espncdn.com/i/teamlogos/nfl/500/scoreboard/det.png",
        "rel": ["full", "scoreboard"]
      }
    ],
    "record": {
      "items": [
        {
          "type": "total",
          "summary": "8-5",                        // → TeamStats.record
          "stats": [
            {"name": "wins", "value": 8.0},
            {"name": "losses", "value": 5.0},
            {"name": "ties", "value": 0.0},
            {"name": "winPercent", "value": 0.615},
            {"name": "streak", "value": 1.0},      // → TeamStats.streak (need W/L prefix)
            {"name": "playoffSeed", "value": 8.0},
            {"name": "avgPointsFor", "value": 30.3},
            {"name": "avgPointsAgainst", "value": 23.4},
            {"name": "divisionWins", "value": 1.0},
            {"name": "divisionLosses", "value": 3.0}
          ]
        },
        {
          "type": "home",
          "summary": "5-2",                        // → TeamStats.home_record
          "stats": [...]
        },
        {
          "type": "road",
          "summary": "3-3",                        // → TeamStats.away_record
          "stats": [...]
        }
      ]
    },
    "groups": {
      "id": "10",                                  // Division ID
      "parent": {"id": "7"},                       // Conference ID
      "isConference": false                        // If true, no parent
    },
    "franchise": {
      "venue": {
        "id": "3727",
        "fullName": "Ford Field",
        "grass": false,
        "indoor": true
      }
    },
    "nextEvent": [...]  // Upcoming games
  }
}
```

### Team Schedule Response

**Endpoint:** `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{id}/schedule`

```json
{
  "timestamp": "2025-12-10T00:45:29Z",
  "status": "success",
  "season": {"year": 2025, "type": 2, "name": "Regular Season"},
  "team": {
    "id": "8",
    "abbreviation": "DET",
    "displayName": "Detroit Lions",
    "recordSummary": "8-5",
    "standingSummary": "3rd in NFC North",
    "groups": {"id": "10", "parent": {"id": "7"}}
  },
  "events": [
    {
      "id": "401772722",
      "date": "2025-09-07T20:25Z",
      "name": "Detroit Lions at Green Bay Packers",
      "shortName": "DET @ GB",
      "seasonType": {"id": "2", "type": 2, "name": "Regular Season"},
      "week": {"number": 1, "text": "Week 1"},
      "competitions": [
        {
          "date": "2025-09-07T20:25Z",
          "venue": {"fullName": "Lambeau Field", "address": {...}},
          "competitors": [
            {
              "id": "9",
              "homeAway": "home",
              "winner": true,
              "team": {
                "id": "9",
                "location": "Green Bay",
                "nickname": "Packers",      // Note: "nickname" not "name"
                "abbreviation": "GB",
                "displayName": "Green Bay Packers",
                "shortDisplayName": "Packers",
                "logos": [...]
              },
              "score": {"value": 27.0, "displayValue": "27"},
              "record": [
                {"type": "total", "displayValue": "1-0"},
                {"type": "home", "displayValue": "1-0"},
                {"type": "road", "displayValue": "0-0"}
              ]
            },
            {...}  // Away team
          ],
          "broadcasts": [{"type": {"shortName": "TV"}, "media": {"shortName": "CBS"}}],
          "status": {
            "type": {"state": "post", "description": "Final"}
          }
        }
      ]
    }
  ]
}
```

### Event Summary Response

**Endpoint:** `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={id}`

Different structure - needs transformation to match scoreboard:

```json
{
  "boxscore": {
    "teams": [
      {
        "team": {
          "id": "6",
          "slug": "dallas-cowboys",
          "displayName": "Dallas Cowboys",
          "abbreviation": "DAL",
          "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/dal.png"
        },
        "statistics": [...],  // Team stats
        "displayOrder": 1,
        "homeAway": "away"
      },
      {...}  // Home team
    ],
    "players": [...]  // Player stats
  },
  "header": {
    "competitions": [
      {
        "date": "2025-12-05T01:15Z",
        "competitors": [
          {
            "id": "8",
            "homeAway": "home",
            "winner": true,
            "score": "44",
            "team": {...}
          },
          {...}
        ],
        "status": {
          "type": {"state": "post", "description": "Final"}
        }
      }
    ]
  }
}
```

---

## TheSportsDB API

### Team Lookup Response

**Endpoint:** `https://www.thesportsdb.com/api/v1/json/3/lookupteam.php?id={id}`

```json
{
  "teams": [
    {
      "idTeam": "133604",                          // → Team.id
      "idESPN": "359",                             // ESPN cross-reference!
      "strTeam": "Arsenal",                        // → Team.name
      "strTeamAlternate": "Arsenal Football Club, AFC, Arsenal FC",
      "strTeamShort": "ARS",                       // → Team.abbreviation
      "intFormedYear": "1892",
      "strSport": "Soccer",
      "strLeague": "English Premier League",       // Primary league
      "idLeague": "4328",                          // → Team.league mapping
      "strLeague2": "FA Cup",                      // Secondary leagues!
      "idLeague2": "4482",
      "strLeague3": "EFL Cup",
      "idLeague3": "4570",
      "strLeague4": "UEFA Champions League",
      "idLeague4": "4480",
      "strLeague5": "Emirates Cup",
      "idLeague5": "5648",
      "strLeague6": "",
      "idLeague6": null,
      "strLeague7": "",
      "idLeague7": null,
      "strStadium": "Emirates Stadium",
      "strLocation": "Holloway, London, England",
      "intStadiumCapacity": "60338",
      "strCountry": "England",
      "strBadge": "https://r2.thesportsdb.com/images/media/team/badge/...",
                                                   // → Team.logo_url
      "strLogo": "https://r2.thesportsdb.com/images/media/team/logo/...",
      "strColour1": "#EF0107",                     // → Team.color (has # prefix!)
      "strColour2": "#fbffff",
      "strColour3": "#013373",
      "strGender": "Male",
      "strDescriptionEN": "Arsenal Football Club is...",
      "strWebsite": "www.arsenal.com",
      "strFacebook": "www.facebook.com/Arsenal",
      "strTwitter": "twitter.com/arsenal",
      "strInstagram": "instagram.com/arsenal"
    }
  ]
}
```

### Team Search Response

**Endpoint:** `https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t={query}`

```json
{
  "teams": [
    {
      "idTeam": "134939",                          // → Team.id
      "strTeam": "Detroit Lions",                  // → Team.name
      "strTeamAlternate": "Lions",
      "strTeamShort": "DET",                       // → Team.abbreviation
      "strSport": "American Football",
      "strLeague": "NFL",
      "idLeague": "4391",
      "strStadium": "Ford Field",
      "strLocation": "Detroit, Michigan",
      "strCountry": "United States",
      "strBadge": "https://r2.thesportsdb.com/images/media/team/badge/...",
      "strLogo": "https://r2.thesportsdb.com/images/media/team/logo/...",
      "strColour1": "#005A8B",                     // Note: different blue than ESPN
      "strColour2": "#B0B7BC",
      "strEquipment": "https://r2.thesportsdb.com/images/media/team/equipment/..."
    }
  ]
}
```

### Events Next Response (Team Schedule)

**Endpoint:** `https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id={team_id}`

Returns next 5 events. Note: Free tier only.

```json
{
  "events": [
    {
      "idEvent": "2274865",                        // → Event.id
      "idAPIfootball": "1387334",                  // API Football cross-reference
      "strEvent": "Bolton Wanderers vs Exeter City", // → Event.name
      "strEventAlternate": "Exeter City @ Bolton Wanderers",
                                                   // → Event.short_name
      "strFilename": "English League 1 2025-12-13 Bolton Wanderers vs Exeter City",
      "strSport": "Soccer",
      "idLeague": "4396",
      "strLeague": "English League 1",
      "strLeagueBadge": "https://r2.thesportsdb.com/images/media/league/badge/...",
      "strSeason": "2025-2026",
      "strHomeTeam": "Bolton Wanderers",           // → home_team lookup
      "strAwayTeam": "Exeter City",                // → away_team lookup
      "intHomeScore": null,                        // → Event.home_score (null if not started)
      "intRound": "20",
      "intAwayScore": null,                        // → Event.away_score
      "intSpectators": null,
      "strTimestamp": "2025-12-13T15:00:00",       // → Event.start_time (NO timezone!)
      "dateEvent": "2025-12-13",
      "strTime": "15:00:00",
      "idHomeTeam": "133606",                      // → Team ID for home
      "strHomeTeamBadge": "https://r2.thesportsdb.com/images/media/team/badge/...",
      "idAwayTeam": "134365",                      // → Team ID for away
      "strAwayTeamBadge": "https://r2.thesportsdb.com/images/media/team/badge/...",
      "idVenue": "28826",
      "strVenue": "Toughsheet Community Stadium",  // → Venue.name
      "strCountry": "England",                     // → Venue.country
      "strCity": null,                             // Often null
      "strStatus": "Not Started",                  // → EventStatus.state mapping
      "strPostponed": "no"                         // Check for "yes"
    }
  ]
}
```

### Events Day Response (League Scoreboard)

**Endpoint:** `https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d={date}&l={league_id}`

Same structure as Events Next, but for a specific date.

**Important:** Returns `{"events": null}` when no events (not empty array!)

### Event Lookup Response

**Endpoint:** `https://www.thesportsdb.com/api/v1/json/3/lookupevent.php?id={event_id}`

Same structure as events in other responses, wrapped in `{"events": [...]}`

---

## Field Mapping Summary

### Team Normalization

| Our Field | ESPN Source | TSDB Source |
|-----------|-------------|-------------|
| `id` | `team.id` | `idTeam` |
| `provider` | `"espn"` (constant) | `"thesportsdb"` (constant) |
| `name` | `team.displayName` | `strTeam` |
| `short_name` | `team.shortDisplayName` | `strTeamShort` or generate |
| `abbreviation` | `team.abbreviation` | `strTeamShort` |
| `league` | Inferred from request | `idLeague` → canonical |
| `logo_url` | `team.logo` or `logos[rel=default]` | `strBadge` |
| `color` | `team.color` (no #) | `strColour1` (has #, strip it) |

### Event Normalization

| Our Field | ESPN Source | TSDB Source |
|-----------|-------------|-------------|
| `id` | `event.id` | `idEvent` |
| `provider` | `"espn"` | `"thesportsdb"` |
| `name` | `event.name` | `strEvent` |
| `short_name` | `event.shortName` | `strEventAlternate` |
| `start_time` | `event.date` (ISO 8601) | `strTimestamp` (assume UTC) |
| `home_team` | `competitors[homeAway=home].team` | lookup `idHomeTeam` |
| `away_team` | `competitors[homeAway=away].team` | lookup `idAwayTeam` |
| `home_score` | `competitors[home].score` (string→int) | `intHomeScore` (can be null) |
| `away_score` | `competitors[away].score` | `intAwayScore` |
| `venue` | `competitions[0].venue` | `strVenue`, `strCountry` |
| `broadcasts` | `broadcasts[].names[]` | N/A (not available) |
| `status` | `status.type.state` → mapping | `strStatus` → mapping |
| `league` | Inferred from request | `idLeague` → canonical |

### Status Mapping

| ESPN state | TSDB status | Our state |
|------------|-------------|-----------|
| `pre` | `Not Started`, `NS` | `scheduled` |
| `in` | `1H`, `HT`, `2H`, live codes | `live` |
| `post` | `FT`, `AET`, `PEN` | `final` |
| `postponed` | `PST`, `strPostponed=yes` | `postponed` |
| `canceled` | `CANC`, `ABD` | `cancelled` |

### Venue Normalization

| Our Field | ESPN Source | TSDB Source |
|-----------|-------------|-------------|
| `name` | `venue.fullName` | `strVenue` |
| `city` | `venue.address.city` | `strCity` (often null) |
| `state` | `venue.address.state` | N/A |
| `country` | `venue.address.country` | `strCountry` |

---

## Key Differences to Handle

### ESPN
1. **Nested competitors** - Must find by `homeAway` field
2. **Scores as strings** - Must convert to int
3. **Colors without #** - Use directly
4. **Multiple logo variants** - Select `rel=default` or scoreboard
5. **Rich status object** - `type.state`, `type.description`, `period`, `displayClock`
6. **Records in competitor** - Access via `records[type=total].summary`

### TheSportsDB
1. **Flat team references** - `idHomeTeam`, `strHomeTeam` separate fields
2. **Team badges in event** - `strHomeTeamBadge`, `strAwayTeamBadge`
3. **Colors with #** - Strip prefix
4. **null vs empty** - `{"events": null}` not `{"events": []}`
5. **Timestamps without timezone** - Assume UTC
6. **Multi-league fields** - `idLeague`, `idLeague2`, ... `idLeague7`
7. **Limited abbreviations** - May need to generate from name
8. **No broadcasts** - Not available in free tier
9. **Team lookup required** - Events only have IDs, need separate call for full team data

### Cross-Provider
1. **ID namespacing** - Always pair `id` with `provider`
2. **League code mapping** - ESPN uses `eng.1`, TSDB uses `4328`
3. **Color inconsistency** - Same team may have different colors
4. **Name variations** - "Detroit Lions" vs "Lions"

---

## Critical Discovery: TheSportsDB → ESPN Cross-Reference

### The `idESPN` Field

TheSportsDB includes an `idESPN` field that directly maps to ESPN's team IDs. **This is verified to work.**

#### Verification Results

| TSDB Team | TSDB idESPN | ESPN Lookup | Result |
|-----------|-------------|-------------|--------|
| Liverpool | 364 | `/soccer/eng.1/teams/364` | ✅ Liverpool |
| Manchester United | 360 | `/soccer/eng.1/teams/360` | ✅ Manchester United |
| Arsenal | 359 | `/soccer/eng.1/teams/359` | ✅ Arsenal |
| Chelsea | 363 | `/soccer/eng.1/teams/363` | ✅ Chelsea |
| Barcelona | 83 | `/soccer/esp.1/teams/83` | ✅ Barcelona |
| Real Madrid | 86 | `/soccer/esp.1/teams/86` | ✅ Real Madrid |
| Bayern Munich | 132 | `/soccer/ger.1/teams/132` | ✅ Bayern Munich |
| Juventus | 111 | `/soccer/ita.1/teams/111` | ✅ Juventus |

#### Coverage by Sport

| Sport | Has idESPN? | Notes |
|-------|-------------|-------|
| Soccer (EPL) | ✅ **Yes** | All major teams verified |
| Soccer (La Liga) | ✅ **Yes** | Barcelona, Real Madrid verified |
| Soccer (Bundesliga) | ✅ **Yes** | Bayern verified |
| Soccer (Serie A) | ✅ **Yes** | Juventus verified |
| Soccer (Ligue 1) | ✅ **Likely** | Not tested but pattern holds |
| NFL | ❌ **No** | Returns `null` |
| NBA | ❌ **No** | Returns `null` |
| MLB | ❌ **No** | Returns `None` |
| NHL | ⚠️ **Falsy** | Returns `0` (not useful) |

### Implications for Architecture

This discovery **significantly simplifies soccer team matching**:

#### Before (Assumed Approach)
```
User wants "Arsenal" schedule
  → Search TSDB for "Arsenal" → get TSDB team ID
  → Search ESPN for "Arsenal" → get ESPN team ID
  → Fuzzy match names to correlate IDs
  → Hope names match across providers
  → Store mapping in database
```

#### After (With idESPN)
```
User wants "Arsenal" schedule
  → Search TSDB for "Arsenal" → get idESPN=359
  → Call ESPN directly: /soccer/eng.1/teams/359
  → Done. No fuzzy matching needed.
```

### Implementation Strategy

#### For Soccer Teams
1. **Primary lookup via TSDB** - Search by name, get `idESPN`
2. **Direct ESPN calls** - Use `idESPN` as ESPN team ID
3. **No mapping table needed** - Cross-reference is built-in
4. **Multi-league support** - TSDB knows all leagues a team plays in

#### For American Sports (NFL, NBA, MLB, NHL)
1. **Fallback to name matching** - No cross-reference available
2. **Use abbreviations** - More reliable than full names
3. **Store mappings** - Cache discovered mappings in `team_provider_ids` table

### Code Example

```python
def get_espn_team_id_for_soccer(team_name: str) -> Optional[str]:
    """Get ESPN team ID via TheSportsDB cross-reference."""
    # Search TSDB
    tsdb_team = thesportsdb_client.search_team(team_name)
    if not tsdb_team:
        return None

    # Check for ESPN cross-reference
    espn_id = tsdb_team.get('idESPN')
    if espn_id and espn_id != '0':  # '0' is falsy placeholder
        return espn_id

    # Fallback to name matching for teams without cross-ref
    return None
```

### Caveats

1. **Soccer only** - American sports don't have this field populated
2. **Not 100% coverage** - Some smaller soccer clubs may lack `idESPN`
3. **League context needed** - ESPN IDs require knowing the league slug (`eng.1`, `esp.1`, etc.)
4. **TSDB API caching** - Their API has aggressive caching; same endpoint may return stale data

### Related Fields

TSDB also includes:
- `idAPIfootball` - Cross-reference to API-Football (another provider)
- `strTeamAlternate` - Alternative names ("Arsenal Football Club, AFC, Arsenal FC")

These could be useful for additional provider integrations or fuzzy matching fallbacks.
