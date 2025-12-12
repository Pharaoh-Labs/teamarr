# Soccer Multi-League Research

> Analysis of soccer's multi-league complexity and the SoccerCompositeProvider design.

## The Problem

Club soccer teams play in multiple competitions simultaneously:

```
Manchester United plays in:
├── eng.1 (Premier League) ─────── Domestic league
├── eng.fa (FA Cup) ────────────── Domestic cup
├── eng.league_cup (EFL Cup) ───── Domestic cup
├── uefa.europa (Europa League) ── Continental
└── potentially more...

To find "today's Man United game", we must check ALL of these.
```

**This is different from other sports:**
- NFL team plays only in NFL
- NBA team plays only in NBA
- NHL team plays only in NHL
- College team plays in one conference

---

## Competition Types

### Domestic Leagues
- **Primary competition** - determines season success
- Weekly games throughout season
- Known schedule far in advance
- Examples: eng.1, esp.1, ger.1, ita.1, fra.1

### Domestic Cups
- **Knockout tournaments** - games scheduled as rounds progress
- Less predictable scheduling
- Teams may be eliminated
- Examples: eng.fa, eng.league_cup, esp.copa

### Continental Competitions
- **European club competitions** - based on league finish
- Group stage → knockouts
- Qualifying rounds for smaller leagues
- Examples: uefa.champions, uefa.europa, uefa.conference

### International
- **National team competitions** - different pool entirely
- World Cup, Euros, Nations League, friendlies
- **Not mixed with club competitions**

---

## Provider Coverage (244 soccer leagues)

### ESPN Covers (~80 leagues)

Major leagues:
- eng.1, eng.2, eng.3, eng.4 (English football pyramid)
- esp.1, esp.2 (La Liga, Segunda)
- ger.1, ger.2 (Bundesliga, 2. Bundesliga)
- ita.1, ita.2 (Serie A, Serie B)
- fra.1, fra.2 (Ligue 1, Ligue 2)
- uefa.champions, uefa.europa, uefa.conference

Cups:
- eng.fa, eng.league_cup
- esp.copa
- ger.dfb_pokal
- ita.coppa
- fra.coupe_de_france

### TheSportsDB Covers

ESPN gaps:
- eng.5+ (National League and below)
- ger.3+ (3. Liga and below)
- Many international leagues
- Smaller European leagues

---

## Solution: SoccerCompositeProvider

### Design Goals

1. **Transparency** - Service layer sees soccer as just another provider
2. **League routing** - Each league routes to correct base provider
3. **Team aggregation** - Get all events for a team across leagues
4. **Country detection** - Know which country's competitions to check

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      SERVICE LAYER                               │
│                                                                  │
│   service.get_team_events("man-utd", "soccer", ...)             │
│                                                                  │
│   Sees soccer as just another provider                          │
│   Doesn't know about multi-league complexity                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              SoccerCompositeProvider                             │
│              (implements SportsProvider)                         │
│                                                                  │
│   1. Determine team's country (from primary league)             │
│   2. Get all relevant competitions for that country             │
│   3. Check each competition for team's events                   │
│   4. Aggregate and dedupe results                               │
│                                                                  │
│   Returns: Clean List[Event]                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
         ESPNProvider                   TSDBProvider
         (eng.1, uefa.*)                (eng.5+, etc)
```

### Database Schema

```sql
-- League → Provider routing
CREATE TABLE soccer_league_providers (
    league_code TEXT PRIMARY KEY,       -- "eng.1", "ger.3"
    provider TEXT NOT NULL,             -- "espn" | "thesportsdb"
    provider_league_id TEXT NOT NULL,   -- ESPN: "eng.1", TSDB: "4328"
    country TEXT,                       -- "england", "germany", NULL for UEFA
    competition_type TEXT,              -- "domestic_league" | "domestic_cup" | "continental"
    tier INT,                           -- 1 = top flight
    display_name TEXT,
    active BOOLEAN DEFAULT TRUE
);

-- Team → Leagues mapping (discovered)
CREATE TABLE soccer_team_leagues (
    team_id TEXT NOT NULL,
    team_provider TEXT NOT NULL,
    league_code TEXT NOT NULL,
    last_seen_at TIMESTAMP,
    PRIMARY KEY (team_id, team_provider, league_code)
);
```

### Country → Competitions Mapping

```python
COUNTRY_COMPETITIONS = {
    "england": {
        "domestic_leagues": ["eng.1", "eng.2", "eng.3", "eng.4", "eng.5"],
        "domestic_cups": ["eng.fa", "eng.league_cup"],
        "continental": ["uefa.champions", "uefa.europa", "uefa.conference"],
    },
    "germany": {
        "domestic_leagues": ["ger.1", "ger.2", "ger.3"],
        "domestic_cups": ["ger.dfb_pokal"],
        "continental": ["uefa.champions", "uefa.europa", "uefa.conference"],
    },
    # ... etc
}
```

### Team Country Detection

Derived from ESPN API's primary league:

```python
def get_team_country(self, team_id: str, provider: str) -> Optional[str]:
    """Get team's country from their primary league."""
    team = self.base_providers[provider].get_team(team_id, "soccer")
    if not team or not team.league:
        return None

    # Look up country from league table
    row = self.db.fetch_one(
        "SELECT country FROM soccer_league_providers WHERE league_code = ?",
        (team.league,)
    )
    return row['country'] if row else None
```

**Example:**
```
Team: Liverpool
ESPN returns: primary league = eng.1
Lookup: eng.1 → country = "england"
Check: eng.1, eng.fa, eng.league_cup, uefa.* for Liverpool's games
```

---

## League Discovery

### TSDB Multi-League Fields

TheSportsDB teams include up to 7 league associations:

```json
{
  "idTeam": "133612",
  "strTeam": "Manchester United",
  "strLeague": "English Premier League",
  "idLeague": "4328",
  "strLeague2": "FA Cup",
  "idLeague2": "4482",
  "strLeague3": "UEFA Europa League",
  "idLeague3": "4481",
  "strLeague4": "EFL Cup",
  "idLeague4": "4570"
}
```

### Discovery Job

```python
class SoccerLeagueDiscoveryJob:
    """Nightly job to refresh team → leagues mappings."""

    def run(self):
        for team in self._get_active_soccer_teams():
            # Try TSDB first (has multi-league fields)
            tsdb_leagues = self._discover_from_tsdb(team)

            # Also check ESPN schedule for competitions
            espn_leagues = self._discover_from_schedule(team)

            # Merge and save
            all_leagues = set(tsdb_leagues) | set(espn_leagues)
            self._update_team_leagues(team, all_leagues)

        # Purge stale entries
        self._purge_stale_entries(max_age_days=30)

    def _discover_from_tsdb(self, team) -> List[str]:
        """Get leagues from TSDB team record."""
        data = self.tsdb_client.lookup_team(team.tsdb_id)
        leagues = []
        for i in range(1, 8):
            suffix = '' if i == 1 else str(i)
            league_id = data.get(f'idLeague{suffix}')
            if league_id:
                canonical = self._map_tsdb_league(league_id)
                if canonical:
                    leagues.append(canonical)
        return leagues

    def _discover_from_schedule(self, team) -> List[str]:
        """Discover leagues from team's schedule."""
        schedule = self.espn_client.get_team_schedule(team.espn_id, "soccer")
        leagues = set()
        for event in schedule.get('events', []):
            league = event.get('league', {}).get('slug')
            if league:
                leagues.add(league)
        return list(leagues)
```

---

## Event Aggregation

### Algorithm

```python
def get_team_events(self, team_id: str, league: str,
                    start_date: date, end_date: date) -> List[Event]:
    """Get all events for a soccer team across competitions."""

    # 1. Get team's country
    country = self._get_team_country(team_id)
    if not country:
        return []

    # 2. Get all competitions to check
    competitions = self._get_country_competitions(country)

    # 3. Check each competition
    all_events = []
    for comp_league in competitions:
        provider = self._get_provider_for_league(comp_league)
        if not provider:
            continue

        events = provider.get_events(comp_league, start_date)
        team_events = [
            e for e in events
            if team_id in (e.home_team.id, e.away_team.id)
        ]
        all_events.extend(team_events)

    # 4. Dedupe (same event might appear in multiple lookups)
    return self._dedupe_events(all_events)

def _dedupe_events(self, events: List[Event]) -> List[Event]:
    """Remove duplicate events (same id + provider)."""
    seen = set()
    unique = []
    for event in events:
        key = (event.id, event.provider)
        if key not in seen:
            seen.add(key)
            unique.append(event)
    return unique
```

---

## Open Questions

### 1. International Teams

National teams have different competition pools:
- World Cup qualifying
- Euro/AFCON/etc. qualifying
- Nations League
- Friendlies

**Options:**
1. Same pattern with "international" competition pool
2. Separate handling for national teams
3. Skip international teams (focus on clubs)

**Recommendation:** Start with clubs only. International teams are lower priority.

### 2. Provider Failover

If ESPN is down for eng.1, do we try TSDB?

**Current decision:** No cross-provider fallback (Decision #2).
- eng.1 is ESPN-only (better data quality)
- TSDB has eng.1 but may be less fresh
- Keep it simple: if provider fails, return empty

### 3. Performance

Checking 6+ leagues per team could be slow.

**Mitigations:**
1. **Parallel requests** - Check leagues concurrently
2. **Cache team→leagues** - Only discover occasionally
3. **Cache scoreboard** - Same scoreboard serves all teams in league
4. **Limit competitions** - Only check likely ones based on team tier

```python
# Parallel league checking
from concurrent.futures import ThreadPoolExecutor

def get_team_events_parallel(self, team_id: str, leagues: List[str], date: date) -> List[Event]:
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(self._check_league, team_id, league, date): league
            for league in leagues
        }
        all_events = []
        for future in futures:
            events = future.result()
            all_events.extend(events)
    return self._dedupe_events(all_events)
```

### 4. New League Onboarding

How to add new leagues to routing?

**Options:**
1. **Admin UI** - Add/edit soccer_league_providers
2. **Code changes** - Require redeploy
3. **Auto-discovery** - Detect from schedule data

**Recommendation:** Database-driven with UI. Code has defaults for common leagues.

---

## College Soccer: Normal Path

College soccer does NOT have multi-league complexity:
- Teams play in one conference
- No cups, no continental competition
- Route directly to ESPN, bypass composite

```python
def get_provider(self, league: str) -> SportsProvider:
    # College soccer → ESPN directly
    if league in ("mens-college-soccer", "womens-college-soccer"):
        return self.base_providers["espn"]

    # Club/international soccer → composite
    if self._is_pro_soccer_league(league):
        return self.soccer_composite

    # Everything else
    return self._discover_provider(league)
```

---

## v1 Implementation Reference

v1 has `soccer_multi_league.py` (31KB) that handles this:

Key concepts to port:
1. Team → leagues cache with scheduled refresh
2. Parallel league checking
3. Country-based competition pools
4. Stale entry purging

Review: `../teamarr/epg/soccer_multi_league.py`

---

## Testing Strategy

### Unit Tests

- Test league routing (eng.1 → ESPN, eng.5 → TSDB)
- Test country detection
- Test event deduplication
- Test competition pool lookup

### Integration Tests

- Test full aggregation flow with mocked providers
- Test cache behavior
- Test parallel execution

### Fixtures Needed

- ESPN scoreboard for eng.1, eng.fa, uefa.champions
- TSDB team lookup with multi-league fields
- Mixed events from multiple competitions

---

## Implementation Order

1. **Schema** - Create soccer_league_providers, soccer_team_leagues tables
2. **Data** - Populate with major leagues (eng.*, ger.*, esp.*, etc.)
3. **Composite** - Implement basic SoccerCompositeProvider
4. **Routing** - Implement league → provider routing
5. **Discovery** - Implement team → leagues discovery
6. **Aggregation** - Implement multi-league event aggregation
7. **Caching** - Add performance optimizations
8. **Testing** - Comprehensive test coverage
