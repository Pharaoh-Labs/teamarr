# Teamarr v2 - Architecture

> System design, layer responsibilities, and data flow.

## Implementation Status

| Layer | Component | Status |
|-------|-----------|--------|
| **Consumer** | Orchestrator | ✅ Basic (team EPG only) |
| **Consumer** | TeamEPGGenerator | ✅ Implemented |
| **Consumer** | EventEPGConsumer | ⏳ Planned |
| **Consumer** | ChannelLifecycle | ⏳ Planned |
| **Service** | SportsDataService | ✅ Basic routing (no caching yet) |
| **Provider** | ESPNProvider | ✅ Implemented (NFL tested) |
| **Provider** | TSDBProvider | ⏳ Planned |
| **Client** | ESPNClient | ✅ Implemented |
| **Utilities** | XMLTV | ✅ Implemented |
| **Utilities** | TemplateEngine | ⏳ Planned |
| **Database** | Schema | ✅ Implemented |
| **Database** | Connection | ✅ Implemented |
| **API** | FastAPI app | ✅ Implemented |
| **API** | Teams CRUD | ✅ Implemented |
| **API** | Templates CRUD | ✅ Implemented |
| **API** | EPG endpoints | ✅ Implemented |
| **API** | Dependency Injection | ✅ Implemented (lru_cache singleton) |
| **API** | Input Validation | ✅ Implemented |

---

## Overview

Teamarr v2 uses a layered architecture with clean boundaries between concerns:

```
═══════════════════════════════════════════════════════════════════
                         CONSUMER LAYER
     (Works with dataclasses only. No knowledge of providers.)
═══════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │
│  │  Matching   │ │     EPG     │ │  Channel    │ │  Flask    │ │
│  │   Engine    │ │   Engine    │ │  Lifecycle  │ │  Routes   │ │
│  │             │ │             │ │             │ │           │ │
│  │ Stream →    │ │ Team-based  │ │ Create/     │ │ UI & API  │ │
│  │ Event       │ │ XMLTV gen   │ │ update/del  │ │ endpoints │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │
│                                                                  │
│  Input:  Event, Team, TeamStats (dataclasses)                   │
│  Output: EPG XML, channel operations, API responses             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ service.get_events(league, date)
                              │ service.get_team(team_id, league)
                              ▼
═══════════════════════════════════════════════════════════════════
                         SERVICE LAYER
       (Routing, caching, ID translation. Provider-agnostic.)
═══════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────┐
│                      SportsDataService                           │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Provider Discovery                                       │    │
│  │ "nfl" → ESPN     "ahl" → TSDB     (cached after first)  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ ID Translation                                           │    │
│  │ team_id=1 → espn:"8"  │  team_id=1 → tsdb:"134934"      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Caching (TTL-based, provider-agnostic)                   │    │
│  │ Fallback orchestration (ESPN fails → try TSDB)          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  Knows:  Canonical IDs, provider interface, cache strategy      │
│  Hidden: ESPN endpoints, TSDB quirks, raw responses             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ provider.get_events(league, date)
                              │ provider.get_team(provider_team_id, league)
                              ▼
═══════════════════════════════════════════════════════════════════
                       ABSTRACTION LAYER
           (SportsProvider ABC - the contract all providers sign)
═══════════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────┐
│                      SportsProvider ABC                          │
│                                                                  │
│  @abstractmethod get_events(league, date) → List[Event]         │
│  @abstractmethod get_team_schedule(team_id, league) → List[Event]
│  @abstractmethod get_team(team_id, league) → Optional[Team]     │
│  @abstractmethod get_event(event_id, league) → Optional[Event]  │
│  @abstractmethod supports_league(league) → bool                 │
│                                                                  │
│  Optional:  get_team_stats, get_league_teams, search_teams      │
│  Composite: get_team_events (default impl, scoreboard→schedule) │
│                                                                  │
│  Contract: Always return dataclasses. Hide all provider quirks. │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
═══════════════════════════════════════════════════════════════════
                       PROVIDER LAYER
            (Implements ABC. Orchestrates client + normalizer.)
═══════════════════════════════════════════════════════════════════

┌───────────────────────┐ ┌───────────────────────┐ ┌─────────────┐
│    ESPNProvider       │ │    TSDBProvider       │ │   Future    │
│    (implements ABC)   │ │    (implements ABC)   │ │  Providers  │
│                       │ │                       │ │             │
│ def get_events():     │ │ def get_events():     │ │             │
│   raw = client.get()  │ │   raw = client.get()  │ │             │
│   return normalize()  │ │   return normalize()  │ │             │
│                       │ │                       │ │             │
│ Fetches own metadata  │ │ Fetches own metadata  │ │             │
│ from DB (slug, etc)   │ │ from DB               │ │             │
└───────────────────────┘ └───────────────────────┘ └─────────────┘
          │                         │
          ▼                         ▼
═══════════════════════════════════════════════════════════════════
                       NORMALIZER LAYER
              (Provider-specific. dict → dataclass.)
═══════════════════════════════════════════════════════════════════

┌───────────────────────┐ ┌───────────────────────┐
│    ESPNNormalizer     │ │    TSDBNormalizer     │
│                       │ │                       │
│ normalize_event()     │ │ normalize_event()     │
│ normalize_team()      │ │ normalize_team()      │
│ normalize_stats()     │ │ normalize_stats()     │
│                       │ │                       │
│ Handles:              │ │ Handles:              │
│ - ESPN date formats   │ │ - TSDB date formats   │
│ - Nested competitors  │ │ - Flat structure      │
│ - Status quirks       │ │ - Status mapping      │
│ - Missing fields      │ │ - Missing fields      │
│                       │ │                       │
│ Testable with JSON    │ │ Testable with JSON    │
│ fixtures (no HTTP)    │ │ fixtures (no HTTP)    │
└───────────────────────┘ └───────────────────────┘
          │                         │
          ▼                         ▼
═══════════════════════════════════════════════════════════════════
                         CLIENT LAYER
                (Provider-specific. Raw HTTP only.)
═══════════════════════════════════════════════════════════════════

┌───────────────────────┐ ┌───────────────────────┐
│      ESPNClient       │ │      TSDBClient       │
│                       │ │                       │
│ get_scoreboard()      │ │ get_events_day()      │
│ get_schedule()        │ │ get_events_next()     │
│ get_team_info()       │ │ get_team()            │
│ get_event_summary()   │ │ get_event()           │
│                       │ │                       │
│ Returns: raw dict     │ │ Returns: raw dict     │
│ No processing         │ │ No processing         │
│ Just HTTP + JSON      │ │ Just HTTP + JSON      │
└───────────────────────┘ └───────────────────────┘
          │                         │
          ▼                         ▼
    ┌───────────┐             ┌───────────┐
    │  ESPN     │             │   TSDB    │
    │  API      │             │   API     │
    └───────────┘             └───────────┘
```

---

## Layer Summary

| Layer | Responsibility | Knows | Doesn't Know |
|-------|---------------|-------|--------------|
| **Consumer** | Business logic (EPG, matching, channels) | Dataclasses, service methods | Providers exist |
| **Service** | Routing, caching, ID translation | Provider interface, canonical IDs | API endpoints, response formats |
| **Abstraction** | Contract definition | Method signatures, return types | Implementation details |
| **Provider** | Orchestration | Its client, normalizer, metadata | Other providers |
| **Normalizer** | Data transformation (dict → dataclass) | Response structure, dataclass fields | HTTP, caching |
| **Client** | HTTP communication | Endpoints, auth, request format | Data meaning |

---

## Data Flow Example: "Get today's NFL games"

```
Consumer:     events = service.get_events("nfl", today)
                │
Service:      provider = discover_provider("nfl")  → ESPNProvider
              cache_key = ("espn", "nfl", today)
              if cached: return cache[cache_key]
              events = provider.get_events("nfl", today)
              cache[cache_key] = events
              return events
                │
Provider:     sport, league = map_league("nfl")  → ("football", "nfl")
              raw = client.get_scoreboard(sport, league, today)
              return [normalizer.normalize_event(e) for e in raw['events']]
                │
Normalizer:   Event(
                id=raw['id'],
                provider='espn',
                name=raw['name'],
                start_time=parse_date(raw['date']),
                home_team=normalize_team(raw['competitions'][0]...),
                ...
              )
                │
Client:       requests.get("https://site.api.espn.com/...scoreboard")
              return response.json()
```

---

## Consumer Architecture

EPG generation involves multiple distinct operations. Each consumer has a single responsibility:

```
┌─────────────────────────────────────────────────────────────────┐
│                      CONSUMER LAYER                              │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  EPG Orchestrator                        │    │
│  │         (Composite - runs consumers in sequence)         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│      ┌───────────────────────┼───────────────────────┐          │
│      ▼                       ▼                       ▼          │
│  ┌──────────┐         ┌──────────────┐        ┌─────────────┐   │
│  │ Team EPG │         │  Event EPG   │        │  Channel    │   │
│  │ Consumer │         │  Consumer    │        │  Lifecycle  │   │
│  │          │         │              │        │  Consumer   │   │
│  │ teams →  │         │ streams →    │        │             │   │
│  │ programmes│        │ programmes   │        │ Create/     │   │
│  │          │         │              │        │ update/     │   │
│  │ (static  │         │ (matched     │        │ delete      │   │
│  │ channels)│         │ events)      │        │ channels    │   │
│  └──────────┘         └──────────────┘        └─────────────┘   │
│       │                      │                       │          │
│       ▼                      ▼                       ▼          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   Shared Utilities                        │   │
│  │                                                           │   │
│  │  TemplateEngine    FillerGenerator    XMLTVWriter        │   │
│  │  LeagueDetector    TeamMatcher        EventMatcher       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              Reconciliation Consumer                     │    │
│  │     (Detects drift, orphans, fixes inconsistencies)      │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     INTEGRATION LAYER                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                Dispatcharr Integration                   │    │
│  │                                                          │    │
│  │  - Push EPG XML to Dispatcharr                          │    │
│  │  - Sync channel state (create/update/delete)            │    │
│  │  - Upload logos                                          │    │
│  │  - Refresh M3U accounts                                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  (Future integrations would live here too)                      │
└─────────────────────────────────────────────────────────────────┘
```

### Consumer Responsibilities

| Consumer | Input | Output | Single Responsibility |
|----------|-------|--------|----------------------|
| **TeamEPGConsumer** | `teams` table | List[Programme] | Generate schedule for static team channels |
| **EventEPGConsumer** | Streams + `event_epg_groups` | List[Programme] + matched events | Match streams → events, generate programmes |
| **ChannelLifecycleConsumer** | Matched events | Channel operations | Create/update/delete dynamic channels |
| **ReconciliationConsumer** | Expected vs actual state | Corrections | Detect drift, orphans, fix inconsistencies |

### Shared Utilities (Not Consumers)

| Utility | Purpose |
|---------|---------|
| **TemplateEngine** | Resolve {variables} in title/description templates |
| **FillerGenerator** | Generate pregame/postgame/idle programmes |
| **XMLTVWriter** | Serialize programmes to XMLTV format |
| **LeagueDetector** | Tier 1-4 league detection for ambiguous teams |
| **TeamMatcher** | Extract team identifiers from stream names |
| **EventMatcher** | Match stream to specific event |

---

## Directory Structure

```
teamarrv2/
├── CLAUDE.md                 # Index to all documentation
├── docs/                     # Detailed documentation
│   ├── architecture.md       # This file
│   ├── decisions.md          # All architectural decisions
│   ├── types.md              # Dataclass definitions
│   ├── providers.md          # Provider interface and implementations
│   ├── testing.md            # Test strategy
│   └── research/             # API research
│       ├── espn-api.md
│       ├── thesportsdb-api.md
│       └── soccer-multi-league.md
│
├── teamarr/
│   ├── core/                 # Foundation - types and interfaces
│   ├── providers/            # Provider implementations
│   │   ├── espn/
│   │   ├── thesportsdb/
│   │   └── soccer/           # Soccer composite provider
│   ├── services/             # Service layer
│   ├── consumers/            # EPG consumers
│   ├── integrations/         # External system integrations
│   ├── utilities/            # Shared utilities
│   ├── database/             # Database layer
│   ├── config/               # Configuration
│   └── utils/                # Low-level utilities
│
├── templates/                # Flask UI templates
├── static/                   # CSS, JS
└── tests/
    ├── fixtures/             # Captured API responses
    ├── unit/
    ├── integration/
    └── e2e/
```

---

## Key Design Properties

1. **Clean Boundaries** - Each layer only knows about the layer directly below it
2. **Provider Isolation** - Adding a new provider requires no changes to consumers
3. **Type Safety** - All data flows through dataclasses, never raw dicts
4. **Testability** - Each component can be tested in isolation with mocks
5. **Single Responsibility** - Each consumer/utility does one thing well
