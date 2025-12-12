# Teamarr v2 - Project Constitution

## Vision

Teamarr v2 is a complete rewrite of the data layer with a provider-agnostic architecture. The system fetches sports data from multiple sources (ESPN, TheSportsDB, future providers), normalizes it into a unified format, and presents it to consumers (EPG generation, channel management, UI) in a source-agnostic way.

**Users don't know or care where data comes from. They see teams, events, and EPG.**

---

## Terminology

| Term | Definition |
|------|------------|
| **Data Provider** | ESPN, TheSportsDB - provides sports data (schedules, teams, scores) |
| **M3U Provider** | IPTV provider - provides streams organized into groups |
| **Event Group** | A group of streams from an M3U provider (e.g., "ESPN+" package) |
| **League** | A sports competition (NFL, NBA, eng.1, etc.) |
| **Event** | A single game/match from a data provider |

**Key distinction:** Data providers give us sports data. M3U providers give us streams. We match streams to events.

---

## Core EPG Flows

Two equally important, first-class EPG generation modes:

### Team-Based EPG
"Show me Lions games on the Lions channel"
- User configures a team channel (e.g., "Detroit Lions")
- System fetches that team's schedule
- Generates EPG for all games involving that team
- **Use case:** Dedicated channel per favorite team

### Event-Based EPG
"Show me all NFL games today, each on its own channel"
- System scans league scoreboard for events
- Dynamically creates/removes channels per event
- Matches streams to events
- **Use case:** Full league coverage, game-day channels

Both flows share the same provider layer and data types. Neither is secondary.

---

## Core Principles

1. **Single Source of Truth** - Each piece of logic exists in ONE place
2. **Type-Driven Design** - All data structures are dataclasses with attribute access
3. **Clean Boundaries** - Providers → Service → Consumers
4. **Testability** - Mock providers, captured API responses, no live-only logic
5. **No Premature Optimization** - Simple code > clever code
6. **Maintainability Over Cleverness** - Code will be read 100x more than written. Prioritize:
   - Clear naming over comments
   - Explicit over implicit
   - Small, focused functions (< 50 lines)
   - Small, focused files (< 200 lines) - if a file exceeds this, evaluate splitting
   - No bandaid fixes - fix the root cause or document technical debt
   - Delete dead code immediately - no commented-out blocks
   - If a pattern repeats 3x, refactor it once (not before)
7. **Future Over Past** - Design for where we're going, not where we've been:
   - No v1 migration path required - clean slate DB is acceptable
   - Don't add compatibility shims for v1 patterns
   - **Exception: Templates** - Full v1 template feature parity required:
     - Users are accustomed to template capabilities (pregame/postgame periods, conditionals, etc.)
     - v1 → v2 template export/import must work
     - May optimize structure (column names, JSON consolidation) but not eliminate features
   - If v1 compatibility would compromise v2 design, drop v1 compatibility (except templates)
8. **API-First Design** - All functionality exposed via documented REST API:
   - OpenAPI/Swagger docs auto-generated from code
   - UI is just another API consumer
   - Clear, consistent endpoint naming
   - Proper HTTP status codes and error responses
9. **Docs Stay Current** - Documentation is updated after each implementation step:
   - CLAUDE.md tracks build progress (checkboxes, status markers)
   - Architecture docs reflect what's actually built vs planned
   - New sessions can bootstrap from docs alone
   - If code and docs disagree, update docs immediately
10. **Single Point of Change** - Adding new capabilities requires changes in ONE place:
    - New provider → create provider file, register in registry, done
    - New sport (existing pattern) → add to LEAGUE_PATTERNS mapping, done
    - New sport pattern → create event dataclass + add to registry, done
    - New template variable → add to pattern's variable extractor, done
    - No shotgun surgery across multiple files

---

## Documentation Index

### Architecture & Design
- **[Architecture](docs/architecture.md)** - System design, layer diagrams, data flow
- **[Decisions](docs/decisions.md)** - All 23 architectural decisions with rationale
- **[Types](docs/types.md)** - Dataclass definitions (Event, Team, Programme, etc.)
- **[Providers](docs/providers.md)** - Provider interface and implementations

### Development
- **[DEVELOPMENT.md](DEVELOPMENT.md)** - Local setup, venv, IDE config, daily workflow
- **[Testing](docs/testing.md)** - Test pyramid, fixtures, mock providers
- **[v1 Patterns](docs/v1-patterns.md)** - Connection pooling, caching, retry logic from v1
- **[API Design](docs/api-design.md)** - REST endpoints, OpenAPI spec, error handling

### Sport Patterns
- **[Sport Patterns Overview](docs/sport-patterns.md)** - Design and architecture
- **[Sport Pattern Definitions](docs/sport-pattern-definitions.md)** - Canonical definitions for all 5 patterns

### API Research
- **[ESPN API](docs/research/espn-api.md)** - Endpoints, response formats, quirks
- **[TheSportsDB API](docs/research/thesportsdb-api.md)** - Endpoints, rate limits, normalization
- **[Soccer Architecture](docs/research/soccer-architecture.md)** - Multi-league cache and aggregation design
- **[Soccer Multi-League](docs/research/soccer-multi-league.md)** - Original research (see soccer-architecture.md for final design)

---

## Quick Reference

### Layer Responsibilities

| Layer | Responsibility |
|-------|---------------|
| **Consumer** | Business logic (EPG, matching, channels) |
| **Service** | Routing, caching, ID translation |
| **Provider** | Fetch + normalize → dataclasses |
| **Client** | Raw HTTP only |

### Key Decisions

| Decision | Choice |
|----------|--------|
| Type System | Dataclasses |
| ID Strategy | Provider-scoped (id + provider) |
| Provider Priority | ESPN primary, TSDB fallback |
| Caching | Three-tier (memory, DB scheduled, DB observability) |
| Error Handling | Never crash, return empty, log |
| Soccer Multi-League | Consumer-level aggregation via SoccerLeagueCache |
| Sport Patterns | 5 patterns cover ~99% of sports (team_vs_team, individual, tournament, card, race) |
| Stream Matching | Events → Streams (generate patterns from known events, scan stream names) |

### Key Numbers (from v1)

| Metric | Value |
|--------|-------|
| Template variables | ~227 |
| ESPN soccer leagues | 244 |
| Soccer teams indexed | 3,400+ |
| Stats cache TTL | 6 hours |
| Retry attempts | 3 |
| Thread pool workers | 100 |
| Connection pools | 10 per host |

### Provider Interface

```python
class SportsProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def supports_league(self, league: str) -> bool: ...

    @abstractmethod
    def get_events(self, league: str, date: date) -> List[Event]: ...

    @abstractmethod
    def get_team_schedule(self, team_id: str, league: str,
                          days_ahead: int = 14) -> List[Event]: ...

    @abstractmethod
    def get_team(self, team_id: str, league: str) -> Optional[Team]: ...

    @abstractmethod
    def get_event(self, event_id: str, league: str) -> Optional[Event]: ...
```

---

## Build Strategy: Vertical Slices

### Slice 1: "Detroit Lions team-based EPG works" ✅ COMPLETE
- [x] Team, Event, Venue dataclasses (minimal fields)
- [x] ESPNProvider.get_team_schedule() for NFL only
- [x] SportsDataService basic routing
- [x] Orchestrator generates XMLTV for one team
- [x] **Verify:** XML output generated (4 programmes for Lions)

**Gaps to address later:**
- [ ] ESPN provider caching (v1 had multi-level cache - critical for perf)
- [ ] TeamStats population (needed for template variables like `{team.record}`)
- [ ] Unit tests for ESPN provider
- [ ] Test other leagues (soccer/college may have quirks)

### Sport Pattern Registry (Decision #23) ✅ DESIGNED
5 patterns cover ~99% of all sports:
1. **team_vs_team** - Football, Basketball, Hockey, Soccer, Baseball, Rugby, Cricket, Esports
2. **individual** - Tennis matches (API TBD), Olympic bracket matches (insurance pattern)
3. **tournament** - Golf, Tennis broadcasts, Gymnastics, Diving, Poker, Darts, Bull Riding
4. **card** - UFC, Boxing PPV, WWE, Bellator, PFL
5. **race** - F1, NASCAR, IndyCar, Swimming, Track, Cycling, Horse Racing

Implementation tasks:
- [ ] Refactor `Event` → `BaseEvent` + `TeamVsTeamEvent`
- [ ] Create `SportPattern` ABC and pattern implementations
- [ ] Add league-to-pattern registry (LEAGUE_PATTERNS dict)
- [ ] Update ESPN provider to use patterns for normalization
- [ ] Add remaining patterns as needed (tournament, card, race, individual)

### Infrastructure: Database + API ✅ COMPLETE
- [x] Database schema designed (templates, teams, settings, event_epg_groups, managed_channels)
- [x] Database connection layer (init_db, get_db, reset_db)
- [x] FastAPI app skeleton
- [x] Teams CRUD endpoints (GET, POST, PUT, DELETE)
- [x] Templates CRUD endpoints (GET, POST, PUT, DELETE with full JSON field support)
- [x] EPG generation endpoint (POST /api/v1/epg/generate)
- [x] XMLTV output endpoint (GET /api/v1/epg/xmltv with input validation)
- [x] Swagger docs at /docs
- [x] Dependency injection (SportsDataService singleton via lru_cache)
- [x] Input validation (team_ids parsing, days_ahead bounds)

### Slice 2: "Event-based EPG works" ✅ COMPLETE
- [x] ESPNProvider.get_events() (scoreboard)
- [x] EventMatcher (by team IDs and names)
- [x] EventEPGGenerator.generate_for_leagues()
- [x] Orchestrator.generate_for_events() method
- [x] API: POST /epg/events/generate, GET /epg/events/xmltv, POST /epg/events/match
- [x] **Verified:** 7 NBA events → 7 programmes with correct XMLTV

### Stream Matching Pipeline ✅ COMPLETE
Events → Streams approach with fuzzy matching:
- [x] `FuzzyMatcher` utility using `rapidfuzz` (zero-maintenance fuzzy matching)
- [x] Pattern generation with mascot stripping ("Florida Atlantic Owls" → "Florida Atlantic")
- [x] `SingleLeagueMatcher` - match streams for a known league
- [x] `MultiLeagueMatcher` - match across leagues with whitelist filtering
- [x] **Verified:** 82.8% match rate vs v1's 76.6% (outperforms v1!)

**Supported leagues:**
- NFL, NBA, NHL, MLB, WNBA, MLS
- College: football, mens/womens basketball, mens/womens hockey
- Soccer: All ESPN leagues via `sport.league` format (e.g., `ger.1`, `esp.1`)

**Remaining:** Date range handling (NFL game on Dec 11 vs stream showing Dec 12)

### Slice 3: "Multiple leagues work" ✅ MOSTLY COMPLETE
- [x] College basketball (mens + womens)
- [x] College hockey (mens + womens)
- [x] Soccer (German, Spanish, Australian via league codes)
- [ ] Test all soccer leagues systematically

### Slice 4: "Full feature parity"
- [ ] League detection tiers
- [ ] Channel lifecycle
- [ ] All template variables (~227 in v1)
- [ ] **Verify:** Matches v1 output exactly

### Slice 5: "TheSportsDB provider"
- [ ] New provider for gap leagues (AHL, etc.)
- [ ] Test fallback behavior

---

## Directory Structure

```
teamarrv2/
├── CLAUDE.md                 # This file - project constitution
├── DEVELOPMENT.md            # Dev setup guide
├── README.md                 # Quick start
├── pyproject.toml            # Package config
├── .gitignore
├── .venv/                    # Virtual environment
│
├── docs/                     # Detailed documentation
│   ├── architecture.md
│   ├── decisions.md
│   ├── types.md
│   ├── providers.md
│   ├── testing.md
│   ├── v1-patterns.md
│   ├── api-design.md         # REST API spec
│   └── research/
│       ├── espn-api.md
│       ├── thesportsdb-api.md
│       ├── soccer-architecture.md
│       └── soccer-multi-league.md
│
├── teamarr/
│   ├── core/
│   │   ├── types.py          # ✅ Team, Event, Venue, Programme, etc.
│   │   └── interfaces.py     # ✅ SportsProvider ABC
│   ├── providers/            # Data providers (ESPN, TheSportsDB)
│   │   └── espn/
│   │       ├── client.py     # ✅ HTTP client
│   │       └── provider.py   # ✅ ESPNProvider
│   ├── services/
│   │   └── sports_data.py    # ✅ SportsDataService (routing)
│   ├── consumers/
│   │   ├── orchestrator.py        # ✅ EPG generation coordinator
│   │   ├── team_epg.py            # ✅ Team-based EPG generator
│   │   ├── event_epg.py           # ✅ Event-based EPG generator
│   │   ├── event_matcher.py       # ✅ Match queries to events
│   │   ├── single_league_matcher.py  # ✅ Stream matching for single league
│   │   └── multi_league_matcher.py   # ✅ Stream matching across leagues
│   ├── utilities/
│   │   ├── xmltv.py           # ✅ XMLTV output
│   │   └── fuzzy_match.py     # ✅ FuzzyMatcher using rapidfuzz
│   ├── database/
│   │   ├── schema.sql        # ✅ Full schema
│   │   └── connection.py     # ✅ Connection management
│   ├── api/
│   │   ├── app.py            # ✅ FastAPI application
│   │   ├── models.py         # ✅ Pydantic request/response models
│   │   ├── dependencies.py   # ✅ DI (singleton SportsDataService)
│   │   └── routes/
│   │       ├── health.py     # ✅ Health check
│   │       ├── teams.py      # ✅ Teams CRUD
│   │       ├── templates.py  # ✅ Templates CRUD (full JSON fields)
│   │       └── epg.py        # ✅ EPG generation (team + event modes, matching)
│   ├── integrations/         # (planned)
│   ├── config/               # (planned)
│   └── utils/                # (planned)
│
└── tests/
    ├── test_matching_pipeline.py  # ✅ Stream matching tests with real data
    ├── test_v1_comparison.py      # ✅ v1 vs v2 performance comparison
    ├── fixtures/espn/             # (planned)
    ├── unit/                      # (planned)
    └── integration/               # (planned)
```

**Legend:** ✅ = implemented, (planned) = not yet built

---

## Success Criteria

v2 is ready when:

1. **Feature parity** - Everything v1 does, v2 does
2. **All tests pass** - Unit and integration
3. **ESPN works identically** - Same EPG output for same inputs
4. **TheSportsDB works** - At least one league functional
5. **No v1 code patterns** - No scattered field extraction, no fallback chains
6. **Documentation complete** - README, API docs updated

---

## Codebase Stats

**Total: ~9,700 lines across 56 files**

### Code Files (~2,000 lines)
| File | Lines |
|------|-------|
| `teamarr/providers/espn/provider.py` | 267 |
| `teamarr/api/models.py` | 253 |
| `teamarr/api/routes/epg.py` | 239 |
| `teamarr/api/routes/templates.py` | 157 |
| `teamarr/providers/espn/client.py` | 156 |
| `teamarr/consumers/event_matcher.py` | 136 |
| `teamarr/consumers/event_epg.py` | 127 |
| `teamarr/consumers/orchestrator.py` | 109 |
| `teamarr/consumers/team_epg.py` | 111 |
| `teamarr/utilities/xmltv.py` | 101 |
| `teamarr/api/routes/teams.py` | 97 |
| `teamarr/core/types.py` | 92 |
| `teamarr/core/interfaces.py` | 87 |
| `teamarr/database/connection.py` | 81 |
| `teamarr/services/sports_data.py` | 69 |
| Other (app, routes, __init__) | ~140 |

### Documentation (7,351 lines)
| File | Lines |
|------|-------|
| `docs/decisions.md` | 786 |
| `docs/research/api-field-mappings.md` | 620 |
| `docs/sport-pattern-definitions.md` | 567 |
| `docs/testing.md` | 565 |
| `docs/providers.md` | 523 |
| `docs/research/thesportsdb-api.md` | 500 |
| `docs/v1-patterns.md` | 473 |
| `docs/research/soccer-multi-league.md` | 447 |
| `docs/research/soccer-architecture.md` | 434 |
| `docs/research/espn-api.md` | 411 |
| `docs/types.md` | 386 |
| `docs/architecture.md` | 347 |
| `docs/sport-patterns.md` | 330 |
| `CLAUDE.md` | 316 |
| `docs/api-design.md` | 309 |
| `DEVELOPMENT.md` | 296 |
| `README.md` | 24 |

### Database (258 lines)
| File | Lines |
|------|-------|
| `teamarr/database/schema.sql` | 258 |

---

## Reference

v1 codebase available at `../teamarr/` for reference.

Key v1 files:
- `api/espn_client.py` - ESPN API patterns
- `epg/orchestrator.py` - Team EPG generation
- `epg/event_matcher.py` - Event matching logic
- `epg/league_detector.py` - Tier 1-4 detection
- `epg/template_engine.py` - Variable substitution
- `epg/channel_lifecycle.py` - Channel CRUD
- `database/__init__.py` - Database functions
