# Teamarr v2 - Architectural Decisions

> All major decisions with rationale and implementation details.

## Decision Log Summary

| # | Topic | Decision | Status |
|---|-------|----------|--------|
| 1 | Type System | Dataclasses | Decided |
| 2 | ID Strategy | Provider-scoped IDs | Decided |
| 3 | Directory Structure | Nested package (`teamarr/`) | Decided |
| 4 | Provider Interface | 4 required + 1 composite + 3 optional methods | Decided |
| 5 | Provider Priority | ESPN primary, others fallback | Decided |
| 6 | Build Order | Vertical slices | Decided |
| 7 | Data Source Priority | Scoreboard primary, schedule fallback | Decided |
| 8 | Team ID Storage | Multi-provider mapping + metadata blobs | Decided |
| 9 | League Identifiers | Canonical codes (ESPN-style) + DB overrides | Decided |
| 10 | Provider Discovery | Dynamic, priority-ordered, cached | Decided |
| 11 | Null Handling | Graceful at service layer | Decided |
| 12 | Caching Strategy | Three-tier caching | Decided |
| 13 | Soccer Multi-League | Consumer-level aggregation | Decided |
| 14 | Provider Registry | Centralized with auto-wiring | Decided |
| 15 | Error Handling | Fail gracefully, never crash | Decided |
| 16 | Testing Strategy | Test pyramid | Decided |
| 17 | Logging | Structured with clear levels | Decided |
| 18 | Consumer Architecture | Discrete consumers + composite orchestrator | Decided |
| 19 | Dispatcharr Integration | Integration Layer (not consumer) | Decided |
| 20 | Database Schema | Breaking change, no backward compat | Decided |
| 21 | Configuration | Separate concerns (.env vs DB) | Decided |
| 22 | Soccer Team Matching | TSDB→ESPN cross-reference via `idESPN` | Decided |
| 23 | Sport Patterns | Pattern registry for sport-specific event structures | Decided |

---

## Decision #1: Type System

**Decision:** Use Python dataclasses for all data structures.

**Rationale:**
- Clean attribute access: `event.home_team.name` not `event['home_team']['name']`
- IDE support (autocomplete, type checking)
- Can add methods to dataclasses
- Proper Python objects with equality, repr, etc.

---

## Decision #2: Provider-Scoped IDs

**Decision:** Events and teams carry both their ID and provider name. No cross-provider ID mapping.

### Implementation

```python
@dataclass
class Event:
    id: str              # "401547679"
    provider: str        # "espn"

# Database
event_id = "401547679"
event_provider = "espn"
tvg_id = "teamarr-event-espn-401547679"

# Lookup always uses originating provider
provider = get_provider(event.provider)
provider.get_event(event.id, league)
```

### Why Not Cross-Provider Mapping?

Options B (Canonical IDs) and C (Multi-Provider Catalog) require solving: "Is ESPN event 401547679 the same as TSDB event 1234567?"

This is hard:
- Fuzzy team name matching across naming conventions
- Time window tolerance (kickoff times vary)
- Venue normalization

**When would cross-provider fallback actually help?**

| Scenario | Frequency | Does fallback help? |
|----------|-----------|---------------------|
| ESPN down for minutes | Rare | Cached data is fine |
| ESPN down for hours | Very rare | Channel lifetime is ~4 hours anyway |
| ESPN doesn't cover league | Common | Different provider from start, not fallback |
| ESPN missing an event | Rare | Schedule fallback (same provider) catches it |

The common case isn't "ESPN failed mid-event" - it's "ESPN doesn't cover this league." That's solved by provider selection at match time.

### Contract

- Event belongs to one provider
- We always ask that provider for updates
- If provider unavailable, gracefully degrade (use cached data)
- No cross-provider magic that could cause inconsistencies

---

## Decision #4: Provider Interface Methods

**Decision:** 4 required methods, 1 composite with default implementation, 3 optional.

```
┌─────────────────────────────────────────────────────────────────┐
│                     SportsProvider ABC                           │
├─────────────────────────────────────────────────────────────────┤
│  IDENTITY                                                        │
│    name                        "espn", "thesportsdb"             │
│                                                                  │
│  LEAGUE SUPPORT                                                  │
│    supports_league(league)     Local check, no API call          │
│                                                                  │
│  REQUIRED                                                        │
│    get_events(league, date)        PRIMARY - scoreboard          │
│    get_team_schedule(team, league) FALLBACK - team schedule      │
│    get_team(team, league)          Team identity                 │
│    get_event(event, league)        Refresh known events          │
│                                                                  │
│  COMPOSITE (default impl)                                        │
│    get_team_events(...)            Scoreboard→schedule dance     │
│                                                                  │
│  OPTIONAL (return None/empty)                                    │
│    get_team_stats(team, league)    Template variables            │
│    get_league_teams(league)        Team import UI                │
│    search_teams(query, league)     Team search UI                │
└─────────────────────────────────────────────────────────────────┘
```

### Change Safety

| Change Type | Difficulty | Example |
|-------------|------------|---------|
| Add optional method | Easy | `get_venue()` with `return None` |
| Add optional param | Easy | `get_events(..., include_odds=False)` |
| Add optional dataclass field | Easy | `Event.weather: Optional = None` |
| Add new provider | Easy | `class NHLProvider(SportsProvider)` |
| Add required method | Medium | Must update all providers |
| Change signature | Medium | Must update all providers |
| Remove/rename method | Hard | Breaks all callers |

See [providers.md](providers.md) for the full interface definition.

---

## Decision #7: Data Source Priority

**Decision:** Scoreboard (daily events) is primary, team schedule is fallback.

**Rationale:**
- Scoreboard: 1 API call per league per day, gets all events
- Schedule: 1 API call per team, more expensive
- Scoreboard is more reliable and fresher (live scores)

**Behavior:**
1. Try scoreboard first for the requested date
2. If team not found in scoreboard, fall back to team schedule
3. Schedule provides extended lookahead (30+ days)

---

## Decision #8: Team ID Storage

**Decision:** Multi-provider mapping table with JSONB metadata blobs.

```sql
CREATE TABLE team_provider_ids (
    team_id INTEGER REFERENCES teams(id),
    provider TEXT NOT NULL,              -- "espn" | "thesportsdb"
    provider_team_id TEXT NOT NULL,      -- "8" | "134934"
    provider_metadata JSONB DEFAULT '{}', -- Provider-specific extras
    last_verified_at TIMESTAMP,
    PRIMARY KEY (team_id, provider)
);
```

**Example data:**
```
team_id | provider    | provider_team_id | provider_metadata
--------|-------------|------------------|------------------------------------------
1       | espn        | 8                | {"slug": "det/lions", "sport": "football"}
1       | thesportsdb | 134934           | {}
47      | espn        | 360              | {"slug": "man-united", "sport": "soccer"}
```

### Key Properties

| Property | How It Works |
|----------|--------------|
| Provider isolation | Each provider only reads its own metadata row |
| Clean abstraction | Service layer never sees slugs, sports, etc. |
| Extensibility | New provider needs X? Store in metadata, no schema change |

---

## Decision #9: League Identifiers

**Decision:** ESPN-style canonical codes with DB extension capability.

```python
# Built-in defaults (covers 90% of cases)
DEFAULT_LEAGUE_MAPPINGS = {
    "nfl": {"espn": ("football", "nfl"), "thesportsdb": 4391},
    "nba": {"espn": ("basketball", "nba"), "thesportsdb": 4387},
    "premier-league": {"espn": ("soccer", "eng.1"), "thesportsdb": 4328},
}
```

**DB can extend/override:**
```sql
CREATE TABLE league_provider_mappings (
    canonical_code TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_league_id TEXT NOT NULL,
    provider_sport TEXT,
    PRIMARY KEY (canonical_code, provider)
);
```

---

## Decision #10: Provider Discovery

**Decision:** Priority-ordered discovery with caching.

```python
def get_provider_for_league(self, league: str) -> Optional[SportsProvider]:
    # Use cached if available
    if league in self._league_provider_cache:
        return self.get_provider(self._league_provider_cache[league])

    # Try providers in priority order
    for provider in self.providers:
        if provider.supports_league(league):
            self._league_provider_cache[league] = provider.name
            return provider

    return None
```

**Key insight:** `supports_league()` is a cheap local check (set membership), not an API call.

---

## Decision #12: Caching Strategy

**Decision:** Three-tier caching architecture.

```
TIER 1: EPHEMERAL (In-Memory)
─────────────────────────────
  Location:  Service Layer (SportsDataCache)
  Lifecycle: Per EPG generation
  Purge:     Clear on generation start
  Contents:  Scoreboard events, team schedules, team identity, stats

TIER 2: SEMI-PERMANENT (Database, Scheduled Refresh)
────────────────────────────────────────────────────
  Location:  Database tables
  Lifecycle: Persists across restarts
  Purge:     Scheduled refresh (daily/weekly)
  Contents:  League teams cache, soccer team→leagues mapping

TIER 3: PERMANENT (Database, Observability-Based Purge)
───────────────────────────────────────────────────────
  Location:  Database tables
  Lifecycle: Persists until stale
  Purge:     Based on "last seen" generation counter
  Contents:  Stream fingerprints (stream → event mapping)
```

### Cache Key Structure

```python
# Pattern: (data_type, provider, *identifiers)
("events", "espn", "nfl", "2024-12-08")
("schedule", "espn", "8", "nfl")
("team", "espn", "8", "nfl")
("event", "espn", "401547679", "nfl")
("stats", "espn", "8", "nfl")
```

---

## Decision #13: Soccer Multi-League Handling

**Status:** Decided (revised after v1 analysis)

**Problem:** Club soccer teams play in multiple leagues simultaneously:
```
Manchester United plays in:
├── eng.1 (Premier League)
├── eng.fa (FA Cup)
├── eng.league_cup (EFL Cup)
├── uefa.champions (Champions League)
└── ... potentially more
```

**Decision:** Consumer-level aggregation via SoccerLeagueCache, NOT a composite provider.

### Architecture

```
TeamEPGConsumer
    ├── detects soccer team (is_soccer_league())
    ├── queries SoccerLeagueCache.get_team_leagues(team_id)
    ├── calls service.get_team_events() for EACH league
    └── merges events by ID, tracks source_league

SoccerLeagueCache (Service Utility)
    ├── reverse-lookup cache: team_id → [league_slugs]
    ├── built from ESPN's 244 soccer leagues
    └── refreshed weekly (~5 seconds with parallel fetching)

ESPNProvider
    └── single-league operations only (unchanged)
```

### Why NOT a Composite Provider?

1. **v1 pattern works** - Battle-tested in production
2. **Simpler provider interface** - Providers stay single-league
3. **Easier testing** - No mock orchestration in provider layer
4. **Clear responsibility** - Aggregation is consumer/orchestrator concern

### Key Components

| Component | Location | Responsibility |
|-----------|----------|---------------|
| `SoccerLeagueCache` | `services/` | Team→leagues cache, tag detection |
| `soccer_team_leagues` | Database | Reverse index (3400+ teams, 244 leagues) |
| `soccer_leagues` | Database | League metadata with JSON tags |
| `TeamEPGConsumer._fetch_soccer_multi_league()` | `consumers/` | Multi-league event aggregation |

### League Tags (Multi-Value)

Leagues have multiple tags, not single categories:
```python
# eng.1 → ["domestic", "club", "league", "mens"]
# uefa.champions → ["continental", "club", "cup", "mens"]
# fifa.world → ["world", "national", "cup", "mens"]
```

77 regex/substring patterns auto-detect tags from slug.

### Source League Tracking

Events preserve source competition:
```python
event.source_league = "uefa.champions"
event.source_league_name = "UEFA Champions League"
event.source_league_logo = "https://..."
```

Enables template variables: `{competition_name}`, `{competition_logo}`

### Resolved Questions

| Question | Answer |
|----------|--------|
| International teams? | Same cache, filter by `team_type='national'` |
| Provider failover? | No. ESPN-only for soccer. Cache + graceful degradation. |
| New league onboarding? | Automatic. Cache refresh discovers all ESPN leagues. |
| Performance? | Parallel fetching, scoreboard caching, ~5-10 leagues per team |

See [research/soccer-architecture.md](research/soccer-architecture.md) for full design.

---

## Decision #14: Provider Registry

**Decision:** Centralized registry with auto-wiring for soccer composite.

```python
class ProviderRegistry:
    def register(self, provider: SportsProvider) -> None:
        """Register a provider. Soccer composite auto-rebuilds."""
        self._base_providers[provider.name] = provider
        self._rebuild_soccer_composite()
        self._league_provider_cache.clear()
```

**Adding a new provider:**
```python
# Just register it
self.registry.register(NHLProvider())

# Add DB entries if covers soccer
INSERT INTO soccer_league_providers ...

# Done. Soccer composite auto-discovers.
```

---

## Decision #15: Error Handling

**Decision:** Never crash the EPG generation. Return empty/None, log, continue.

```
CLIENT LAYER
├── Retry transient errors (timeout, 5xx, 429)
├── Exponential backoff (1s, 2s, 4s)
├── Max 3 retries
├── Log all errors with context
└── Return None on failure (never raise)

NORMALIZER LAYER
├── Skip malformed records (log warning)
├── Use defaults for optional fields
└── Return None/empty list (never raise)

PROVIDER LAYER
├── Handle None from client gracefully
├── Try fallback endpoints if available
└── Return None/empty list (never raise)

SERVICE LAYER
├── Try fallback providers if primary fails
├── Cache empty results (prevent retry spam)
└── Return empty list to consumers (never raise)
```

---

## Decision #17: Logging Standards

**Decision:** Structured logging with clear levels.

**Format:** `[TIMESTAMP] [LEVEL] [COMPONENT] [ACTION] message | key=value`

| Level | When to Use | Example |
|-------|-------------|---------|
| DEBUG | Detailed diagnostics | API request/response details |
| INFO | Normal operations | "EPG generation complete" |
| WARN | Degraded but continuing | "Retry on 503", "Missing field" |
| ERROR | Failures needing attention | "All retries exhausted" |

See [CLAUDE.md](../CLAUDE.md#decision-17-logging-standards) for full implementation.

---

## Decision #20: Database Schema

**Decision:** Clean break from v1, no backward compatibility.

**Rationale:**
1. Provider abstraction is fundamental
2. Users expect breaking changes in a "v2"
3. Clean slate for multi-provider from day one
4. Migration script is one-time cost

### Key Changes

**New tables:**
- `team_provider_ids` - Multi-provider team mapping
- `league_provider_mappings` - League routing

**Replaced tables:**
- `schedule_cache`, `team_stats_cache` → `provider_cache` (unified)
- 3 soccer tables → 1 `soccer_team_leagues`

**Updated tables:**
- `teams` - Remove `espn_team_id`, `sport`
- `managed_channels` - Add `event_provider`

---

## Decision #21: Configuration

**Decision:** Separate concerns between .env and database.

| Store in .env | Store in DB |
|--------------|-------------|
| Infrastructure (ports, paths) | User preferences |
| Secrets (API keys) | Feature flags |
| Deployment-specific | Runtime configuration |
| Timezone | EPG settings |

```bash
# .env - Infrastructure
DATABASE_PATH=/data/teamarr.db
DISPATCHARR_URL=http://dispatcharr:5000
DEFAULT_TIMEZONE=America/Detroit
```

```sql
-- DB - User preferences
epg_days_ahead=14
channel_create_timing=day_before
auto_generate_schedule=0 6 * * *
```

---

## Decision #22: Soccer Team Matching via TSDB Cross-Reference

**Decision:** Use TheSportsDB's `idESPN` field to directly map soccer teams to ESPN IDs, eliminating fuzzy matching.

**Status:** New - discovered during API research.

### Discovery

TheSportsDB includes an `idESPN` field on team records that directly corresponds to ESPN's team IDs. This was verified against live APIs:

| TSDB Team | idESPN | ESPN Verification |
|-----------|--------|-------------------|
| Liverpool | 364 | ✅ `/soccer/eng.1/teams/364` → Liverpool |
| Manchester United | 360 | ✅ `/soccer/eng.1/teams/360` → Manchester United |
| Barcelona | 83 | ✅ `/soccer/esp.1/teams/83` → Barcelona |
| Bayern Munich | 132 | ✅ `/soccer/ger.1/teams/132` → Bayern Munich |
| Juventus | 111 | ✅ `/soccer/ita.1/teams/111` → Juventus |

### Coverage

| Sport | idESPN Available? |
|-------|-------------------|
| Soccer (all major leagues) | ✅ Yes |
| NFL | ❌ No (null) |
| NBA | ❌ No (null) |
| MLB | ❌ No (null) |
| NHL | ❌ No (returns "0") |

### Impact on Architecture

**Before:** Required fuzzy name matching between providers
```
TSDB: "Arsenal" → ESPN: "Arsenal FC" → fuzzy match → hope for the best
```

**After:** Direct ID lookup
```
TSDB: idESPN=359 → ESPN: /teams/359 → guaranteed match
```

### Implementation

```python
def resolve_soccer_team_espn_id(team_name: str) -> Optional[str]:
    """Get ESPN team ID via TheSportsDB cross-reference."""
    tsdb_result = thesportsdb.search_team(team_name)
    if tsdb_result and tsdb_result.get('idESPN'):
        espn_id = tsdb_result['idESPN']
        if espn_id and espn_id != '0':  # '0' is placeholder
            return espn_id
    return None  # Fallback to name matching
```

### Changes to Decision #13 (Soccer Sub-Abstraction)

This simplifies the soccer composite provider:

1. **No mapping table needed** for soccer - TSDB provides the cross-reference
2. **League discovery simplified** - TSDB's `idLeague` through `idLeague7` lists all competitions
3. **Provider priority** - Use TSDB for discovery, ESPN for data (best of both)

### Workflow

```
User adds "Arsenal" channel
  1. Search TSDB: "Arsenal" → idTeam=133604, idESPN=359
  2. Get leagues from TSDB: idLeague=4328 (EPL), idLeague2=4482 (FA Cup), ...
  3. Map to ESPN slugs: 4328→eng.1, 4482→eng.fa, ...
  4. Fetch schedules from ESPN using team ID 359
  5. No fuzzy matching anywhere
```

### Caveats

1. **Soccer only** - American sports require fallback to name/abbreviation matching
2. **League context required** - ESPN needs league slug (`eng.1`), not just team ID
3. **Small clubs** - Some lower-league teams may lack `idESPN`
4. **TSDB caching** - API has aggressive caching; may return stale data

### Related Documentation

- Full field mappings: [research/api-field-mappings.md](research/api-field-mappings.md#critical-discovery-thesportsdb--espn-cross-reference)
- Soccer provider design: [research/soccer-multi-league.md](research/soccer-multi-league.md)

---

## Decision #23: Sport Pattern Registry

**Decision:** Define sport patterns as a registry that normalizes event structures, template variables, and duration behavior per sport type.

**Status:** Decided

### Problem

Different sports have fundamentally different event structures:

| Pattern | Sports | Structure |
|---------|--------|-----------|
| Team vs Team | Football, Basketball, Hockey, Soccer | 2 teams, single venue |
| Individual vs Individual | Tennis, Boxing (single bout) | 2 participants |
| Tournament | Golf, Tennis majors | Multi-day, many participants |
| Card/Multi-bout | MMA, Boxing cards | Multiple bouts, main event |
| Race | F1, NASCAR | Many participants, positions |

Our current `Event` dataclass assumes `home_team` / `away_team`, which breaks for 30%+ of sports.

### Solution: Sport Pattern Registry

**Same principle as providers:** Define once, plug in everywhere.

```
Consumer asks for data
        │
        ▼
Service routes to provider
        │
        ▼
Provider looks up pattern for sport
        │
        ▼
Pattern defines:
  - Event dataclass (TeamVsTeamEvent, TournamentEvent, etc.)
  - Required/optional fields
  - Template variables available
  - Duration calculation
  - Validation rules
        │
        ▼
Provider normalizes raw API data INTO pattern-specific dataclass
        │
        ▼
Consumer receives typed, validated event
```

### Key Design Principles

1. **Single place to add a sport** - Define pattern once, all layers respect it
2. **Type safety** - Pattern-specific dataclasses, not optional fields everywhere
3. **Template variable scoping** - `{home_team}` only available for TeamVsTeam pattern
4. **Provider isolation** - Providers use patterns to know HOW to normalize
5. **Consumer ignorance** - Consumers work with typed events, don't care about patterns

### Event Class Hierarchy

```python
@dataclass
class BaseEvent:
    """Common fields ALL events have."""
    id: str
    provider: str
    name: str
    short_name: str
    start_time: datetime
    status: EventStatus
    league: str
    sport: str
    venue: Optional[Venue] = None
    broadcasts: list[str] = field(default_factory=list)

@dataclass
class TeamVsTeamEvent(BaseEvent):
    """Football, basketball, hockey, soccer, baseball."""
    home_team: Team
    away_team: Team
    home_score: Optional[int] = None
    away_score: Optional[int] = None

@dataclass
class TournamentEvent(BaseEvent):
    """Golf, tennis majors."""
    participants: list[TournamentParticipant]
    current_round: Optional[int] = None
    total_rounds: int = 4

@dataclass
class CardEvent(BaseEvent):
    """MMA, boxing cards."""
    bouts: list[Bout]
    main_event: Optional[Bout] = None
```

### Pattern Interface

```python
class SportPattern(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Pattern identifier: 'team_vs_team', 'tournament', etc."""

    @property
    @abstractmethod
    def event_class(self) -> type[BaseEvent]:
        """The dataclass for events of this pattern."""

    @abstractmethod
    def get_template_variables(self, event: BaseEvent) -> dict[str, Any]:
        """Extract available template variables from an event."""

    @abstractmethod
    def get_duration(self, event: BaseEvent, league: str) -> timedelta:
        """Calculate expected duration for EPG."""

    @abstractmethod
    def validate(self, event: BaseEvent) -> bool:
        """Ensure event has required fields for this pattern."""
```

### League-to-Pattern Registry

```python
SPORT_PATTERNS = {
    # Team vs Team
    "nfl": "team_vs_team",
    "nba": "team_vs_team",
    "nhl": "team_vs_team",
    "mlb": "team_vs_team",
    "eng.1": "team_vs_team",  # Soccer

    # Tournament
    "pga": "tournament",
    "lpga": "tournament",

    # Card
    "ufc": "card",
    "pfl": "card",

    # Race
    "f1": "race",
    "nascar": "race",

    # Individual vs Individual
    "atp": "individual",
    "wta": "individual",
}

def get_pattern(league: str) -> SportPattern:
    pattern_name = SPORT_PATTERNS.get(league, "team_vs_team")  # Default
    return PATTERN_REGISTRY[pattern_name]
```

### Adding a New Sport

To add cricket:

1. **Determine pattern** - Cricket is TeamVsTeam (mostly)
2. **Add to registry** - `"ipl": "team_vs_team"`
3. **If new pattern needed:**
   - Create `CricketMatchEvent(BaseEvent)` dataclass
   - Create `CricketPattern(SportPattern)` class
   - Register in `PATTERN_REGISTRY`
4. **Done** - Providers and consumers auto-discover

### Template Variable Availability

Each pattern exposes different variables:

| Variable | TeamVsTeam | Tournament | Card | Race |
|----------|------------|------------|------|------|
| `{home_team}` | ✅ | ❌ | ❌ | ❌ |
| `{away_team}` | ✅ | ❌ | ❌ | ❌ |
| `{leader}` | ❌ | ✅ | ❌ | ✅ |
| `{main_event}` | ❌ | ❌ | ✅ | ❌ |
| `{venue}` | ✅ | ✅ | ✅ | ✅ |

Templates that reference unavailable variables get empty string (not crash).

### Implementation Priority

1. **Phase 1 (Now):** Refactor `Event` → `BaseEvent` + `TeamVsTeamEvent`
2. **Phase 2:** Add Tournament pattern (golf)
3. **Phase 3:** Add Card pattern (MMA)
4. **Phase 4:** Add Race pattern (motorsports)
5. **Phase 5:** Add Individual pattern (tennis)

### Impact on Existing Code

**types.py:**
- `Event` → `BaseEvent` (common fields)
- New `TeamVsTeamEvent` with home/away teams
- Type alias: `Event = TeamVsTeamEvent` for backward compat during transition

**providers:**
- Use `get_pattern(league)` to know which dataclass to create
- Pattern tells provider which fields to extract

**consumers:**
- Work with typed events
- Use pattern's `get_template_variables()` instead of direct field access

### Full Design

See [sport-patterns.md](sport-patterns.md) for complete design document.
