# Soccer Multi-League Architecture (v2)

> Comprehensive design for handling soccer's multi-competition complexity.

## The Core Problem

Club soccer teams play in multiple competitions simultaneously:

```
Liverpool (ESPN ID: 364) plays in:
├── eng.1 ─────────── English Premier League (domestic league)
├── eng.fa ────────── FA Cup (domestic cup)
├── eng.league_cup ── EFL Cup (domestic cup)
├── uefa.champions ── UEFA Champions League (continental)
└── fifa.cwc ──────── FIFA Club World Cup (world)

To find "today's Liverpool game", we must check ALL of these.
```

This is **unique to soccer**. NFL/NBA/NHL teams play in exactly one league.

---

## v1 Solution Analysis

v1 solves this with three components:

### 1. Reverse-Lookup Cache (Database)

```sql
-- Team → Leagues mapping (built from ESPN)
CREATE TABLE soccer_team_leagues (
    espn_team_id TEXT,           -- "364"
    league_slug TEXT,            -- "eng.1", "uefa.champions"
    team_name TEXT,              -- "Liverpool"
    team_type TEXT,              -- "club" | "national"
    team_abbrev TEXT,            -- "LIV"
    last_seen TIMESTAMP,
    UNIQUE(espn_team_id, league_slug)
);

-- League metadata
CREATE TABLE soccer_leagues_cache (
    league_slug TEXT PRIMARY KEY, -- "eng.1"
    league_name TEXT,             -- "English Premier League"
    league_abbrev TEXT,           -- "EPL"
    league_tags JSON,             -- ["domestic", "club", "league", "mens"]
    league_logo_url TEXT,
    team_count INTEGER,
    last_seen TIMESTAMP
);
```

**Key insight:** This is a **reverse index**. Given team_id, find all leagues. ESPN's API is organized league→teams, so we invert it.

### 2. Cache Population (Weekly Job)

```python
def refresh_cache():
    """~5 seconds with 100 threads, covers 244 leagues, 3400+ teams"""

    # 1. Fetch all league slugs from ESPN Core API
    league_slugs = fetch_from("https://sports.core.api.espn.com/v2/sports/soccer/leagues?limit=500")

    # 2. For each league, fetch teams (parallel)
    for slug in league_slugs:  # 244 leagues
        teams = fetch_from(f"https://site.api.espn.com/.../soccer/{slug}/teams")
        for team in teams:
            # Build reverse index
            team_to_leagues[team.id].append(slug)

    # 3. Save to database
    save_to_db(team_to_leagues)
```

### 3. Multi-League Schedule Fetching (Per Team EPG)

```python
def fetch_soccer_schedules(team):
    """Orchestrator calls this for soccer teams"""

    # 1. Get all leagues from cache
    leagues = get_team_leagues(team.espn_id)  # ["eng.1", "uefa.champions", ...]

    # 2. Fetch schedule from each league
    events_by_id = {}
    for league in leagues:
        schedule = espn.get_team_schedule("soccer", league, team.espn_id)
        for event in schedule:
            if event.id not in events_by_id:
                event._source_league = league
                event._source_league_name = get_league_name(league)
                events_by_id[event.id] = event

    # 3. Return merged, deduplicated events
    return list(events_by_id.values())
```

---

## v2 Architecture Decision

### Option A: SoccerCompositeProvider (Original v2 Plan)

```
SportsDataService
    └── SoccerCompositeProvider (implements SportsProvider)
            ├── knows all leagues per team
            ├── aggregates events from multiple leagues
            └── hides complexity from service layer
```

**Pros:** Clean abstraction, provider-agnostic
**Cons:** Provider now has orchestration logic, harder to test

### Option B: Orchestrator-Level Logic (v1 Pattern) ✓ RECOMMENDED

```
EPGOrchestrator
    ├── detects soccer team
    ├── queries SoccerLeagueCache for team's leagues
    ├── calls SportsDataService.get_events() per league
    └── merges events with source tracking

SportsDataService
    └── ESPNProvider (single-league operations only)
```

**Pros:** Matches v1, simpler provider interface, easier to test
**Cons:** Soccer logic in consumer layer

### Decision: Option B

The provider interface stays simple (single-league operations). Soccer multi-league aggregation happens in the **TeamEPGConsumer** or a dedicated **SoccerScheduleFetcher** utility.

---

## v2 Implementation Design

### Component 1: SoccerLeagueCache (Service Layer)

Manages the reverse-lookup cache. Not a provider—a **service utility**.

```python
class SoccerLeagueCache:
    """
    Manages the soccer team → leagues reverse lookup cache.

    Populated by crawling ESPN's 244 soccer leagues.
    Refreshed weekly (or on-demand from admin UI).
    """

    def get_team_leagues(self, espn_team_id: str) -> List[str]:
        """Get all league slugs for a team."""
        # Returns: ["eng.1", "uefa.champions", "eng.fa", ...]

    def get_league_info(self, league_slug: str) -> Optional[LeagueInfo]:
        """Get league metadata (name, tags, logo)."""

    def get_team_info(self, espn_team_id: str) -> Optional[TeamInfo]:
        """Get team metadata including type (club/national)."""

    def refresh(self, progress_callback=None) -> RefreshResult:
        """Rebuild entire cache from ESPN (~5 seconds)."""

    def is_stale(self, max_age_days: int = 7) -> bool:
        """Check if cache needs refresh."""
```

### Component 2: LeagueInfo Dataclass

```python
@dataclass
class LeagueInfo:
    """Soccer league metadata."""
    slug: str                    # "eng.1"
    name: str                    # "English Premier League"
    abbreviation: str            # "EPL"
    tags: List[str]              # ["domestic", "club", "league", "mens"]
    logo_url: Optional[str]
    team_count: int

    @property
    def is_domestic(self) -> bool:
        return "domestic" in self.tags

    @property
    def is_club_competition(self) -> bool:
        return "club" in self.tags

    @property
    def is_national_team(self) -> bool:
        return "national" in self.tags
```

### Component 3: League Tag Detection

```python
# Pattern-based tag detection (77 patterns from v1)
LEAGUE_TAG_PATTERNS = {
    'womens': ['.w.', 'women', 'wchampions', 'weuro', ...],
    'youth': ['u17', 'u19', 'u20', 'u21', 'u23', ...],
    'domestic': [r'^[a-z]{3}\.[1-9]$', r'^[a-z]{3}\.fa$', ...],
    'continental': ['uefa.', 'conmebol.', 'concacaf.', 'afc.', 'caf.'],
    'world': [r'^fifa\.world', r'^fifa\.cwc', ...],
    'cup': [r'\.fa$', r'\.cup$', 'pokal', 'coupe', 'coppa', ...],
    'league': [r'^[a-z]{3}\.[1-9]', 'serie', 'bundesliga', ...],
    'club': ['uefa.champions', 'conmebol.libertadores', r'^[a-z]{3}\.[1-9]', ...],
    'national': ['uefa.euro', 'uefa.nations', 'concacaf.gold', r'^fifa\.world', ...],
}

def get_league_tags(slug: str) -> List[str]:
    """Detect all applicable tags for a league slug."""
    tags = []
    for tag, patterns in LEAGUE_TAG_PATTERNS.items():
        for pattern in patterns:
            if matches(slug, pattern):
                tags.append(tag)
                break

    # Defaults
    if 'womens' not in tags and 'youth' not in tags:
        tags.append('mens')
    if 'domestic' in tags and 'club' not in tags and 'national' not in tags:
        tags.append('club')

    return tags
```

### Component 4: TeamEPGConsumer Soccer Logic

```python
class TeamEPGConsumer:
    """Generates EPG programmes for team-based channels."""

    def __init__(self, service: SportsDataService, soccer_cache: SoccerLeagueCache):
        self.service = service
        self.soccer_cache = soccer_cache

    def generate_team_programmes(self, team: Team, days_ahead: int) -> List[Programme]:
        if self._is_soccer_team(team):
            events = self._fetch_soccer_multi_league(team, days_ahead)
        else:
            events = self.service.get_team_schedule(team.id, team.league, days_ahead)

        return self._events_to_programmes(events, team)

    def _fetch_soccer_multi_league(self, team: Team, days_ahead: int) -> List[Event]:
        """Aggregate events from all leagues a soccer team plays in."""
        leagues = self.soccer_cache.get_team_leagues(team.provider_id)

        if not leagues:
            # Fallback to primary league only
            return self.service.get_team_schedule(team.id, team.league, days_ahead)

        events_by_id = {}
        for league_slug in leagues:
            try:
                league_events = self.service.get_team_events(
                    team.provider_id,
                    league_slug,
                    days_ahead
                )
                for event in league_events:
                    if event.id not in events_by_id:
                        # Enrich with source league metadata
                        event.source_league = league_slug
                        event.source_league_name = self.soccer_cache.get_league_name(league_slug)
                        event.source_league_logo = self.soccer_cache.get_league_logo(league_slug)
                        events_by_id[event.id] = event
            except Exception as e:
                log.warn("SOCCER_LEAGUE_FETCH_FAILED", league=league_slug, error=str(e))

        return sorted(events_by_id.values(), key=lambda e: e.start_time)
```

---

## Database Schema (v2)

```sql
-- Replaces v1's soccer_team_leagues, soccer_leagues_cache, soccer_cache_meta

-- Team → Leagues reverse index
CREATE TABLE soccer_team_leagues (
    id INTEGER PRIMARY KEY,
    espn_team_id TEXT NOT NULL,
    league_slug TEXT NOT NULL,
    team_name TEXT,
    team_abbreviation TEXT,
    team_type TEXT CHECK (team_type IN ('club', 'national')),
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(espn_team_id, league_slug)
);

CREATE INDEX idx_soccer_team_leagues_team ON soccer_team_leagues(espn_team_id);

-- League metadata
CREATE TABLE soccer_leagues (
    league_slug TEXT PRIMARY KEY,
    league_name TEXT NOT NULL,
    league_abbreviation TEXT,
    league_tags JSON DEFAULT '[]',  -- ["domestic", "club", "league", "mens"]
    league_logo_url TEXT,
    team_count INTEGER DEFAULT 0,
    last_refreshed_at TIMESTAMP
);

-- Cache refresh metadata
CREATE TABLE soccer_cache_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Single row
    last_full_refresh TIMESTAMP,
    leagues_processed INTEGER DEFAULT 0,
    teams_indexed INTEGER DEFAULT 0,
    refresh_duration_seconds REAL DEFAULT 0
);

-- Initialize meta row
INSERT INTO soccer_cache_meta (id) VALUES (1);
```

---

## Team Type Detection

Club vs National team detection (needed for competition pool filtering):

```python
def detect_team_type(name: str, location: str) -> str:
    """
    Detect if team is club or national.

    Logic: If location equals name, it's likely a national team.
    Examples:
        - name="England", location="England" → national
        - name="Manchester United", location="Manchester" → club
        - name="Liverpool", location="Liverpool" → club (exception list)
    """
    name_lower = name.lower().strip()
    location_lower = location.lower().strip()

    # City names that are also club names (exceptions)
    CLUB_CITY_NAMES = {
        'liverpool', 'chelsea', 'arsenal', 'everton',
        'brighton', 'fulham', 'brentford',
    }

    if name_lower == location_lower:
        if name_lower in CLUB_CITY_NAMES:
            return 'club'
        return 'national'

    return 'club'
```

---

## TheSportsDB Role (Clarification)

**TheSportsDB is NOT the primary source for soccer data.** Its role:

1. **Team Discovery:** When adding a new team, search TSDB by name to find `idESPN` for cross-reference
2. **Gap Leagues:** For leagues ESPN doesn't cover (lower tiers, some international)
3. **Fallback:** If ESPN is down (rare)

The multi-league cache is built **entirely from ESPN**. TSDB's `idLeague` through `idLeague7` fields are NOT used because:
- ESPN already tells us which leagues a team plays in
- ESPN's coverage is broader for top-tier leagues
- Single source of truth is simpler

---

## Source League Tracking

Events preserve their source competition for template variables:

```python
@dataclass
class Event:
    # ... existing fields ...

    # Soccer-specific source tracking
    source_league: Optional[str] = None          # "uefa.champions"
    source_league_name: Optional[str] = None     # "UEFA Champions League"
    source_league_logo: Optional[str] = None     # URL
```

**Template usage:**
```
{competition_name} - available for soccer events
{competition_logo} - available for soccer events

Example: "Liverpool vs Real Madrid" (UEFA Champions League)
```

---

## Open Questions Resolved

### Q1: International Teams?
**A:** Same cache structure, different competition pool. Detect via `team_type='national'` and filter to international competitions (uefa.euro, fifa.world, etc.).

### Q2: Provider Failover for Soccer?
**A:** No. ESPN is sole source. If ESPN fails, return empty/cached data. TSDB doesn't have same league coverage.

### Q3: Performance with Multiple Leagues?
**A:**
- Cache lookup is O(1) database query
- Parallel league fetching (ThreadPoolExecutor)
- Scoreboard caching means same scoreboard serves all teams in that league
- ~5-10 leagues per team, each call is cached

### Q4: New League Onboarding?
**A:** Automatic. Cache refresh discovers all 244 leagues from ESPN. No manual configuration needed unless filtering specific leagues out.

---

## Implementation Order

1. **Schema** - Create soccer_team_leagues, soccer_leagues, soccer_cache_meta tables
2. **SoccerLeagueCache** - Port v1's SoccerMultiLeague class with cleaner interface
3. **Tag Detection** - Port the 77 pattern rules
4. **TeamEPGConsumer** - Add _fetch_soccer_multi_league() method
5. **Cache Refresh Job** - Admin UI + scheduled refresh
6. **Testing** - Fixtures for multi-league scenarios

---

## Files to Reference

v1 implementation:
- `teamarr/epg/soccer_multi_league.py` (905 lines) - Core cache logic
- `teamarr/epg/orchestrator.py:755` - Multi-league schedule fetching
- `teamarr/database/schema.sql` - Table definitions
