---
title: Detection Library Design
parent: Architecture
grand_parent: Technical Reference
nav_order: 7
docs_version: "2.7.0"
---

# Detection Library Architecture Design

Design document for the Detection Library (epic `teamarrv2-b8h`). Phase 1 has
shipped — see [Detection Keyword Service](detection-keywords) for the
implemented service. This page preserves the original top-down design and the
remaining phased plan.

## Overview

The Detection Library centralizes all pattern-based detection configuration, making hardcoded lists in `constants.py` user-configurable while preserving sensible defaults.

## Key Architecture Decision: Separate Flows Per Event Type

```
Stream → Detect Event Type → Route to specific flow

TEAM_VS_TEAM:
  custom_regex_teams → extract team1/team2

EVENT_CARD (combat sports):
  custom_regex_fighters → extract fighter1/fighter2

FIELD_EVENT (golf, tennis, racing):
  custom_regex_competitors → extract competitor(s)
```

**Rationale**: Using `team1/team2` for fighters is semantically sloppy. Each sport category has distinct patterns and the UI can show relevant fields per event type.

## Implementation Phases (Top-Down)

### Phase 1: Detection Logic (No DB Yet)

Build the abstraction layer first, using constants.py as the data source.

1. **b8h.8**: Unify COMBAT_SPORTS_KEYWORDS
   - Merge UFC and boxing keywords into single list
   - Add MMA, Bellator, PFL, ONE FC keywords

2. **b8h.19**: Create DetectionKeywordService
   - New file: `teamarr/services/detection_keywords.py`
   - Loads from constants.py (later: DB with constants fallback)
   - Caches compiled regex patterns
   - Provides typed accessors per category

3. **b8h.20**: Refactor classifier to use service
   - Replace direct constant imports with service calls
   - Decouples classifier from data source

4. **b8h.4**: Add separate custom regex fields
   - `custom_regex_teams` → TEAM_VS_TEAM only
   - `custom_regex_fighters` → EVENT_CARD only
   - Future: `custom_regex_competitors` → FIELD_EVENT

### Phase 2: Persistence

Add database storage for user customization.

5. **b8h.9**: Create detection_keywords DB table
6. **b8h.10**: API endpoints (CRUD, reset, import/export)
7. **b8h.11**: Service reads DB + constants (user overrides built-in)

### Phase 3: User Interface

8. **b8h.12**: Detection Library tab in Settings
   - Consolidated view alongside Team Aliases
   - Category-based editing

### Phase 4: New Sports (Blocked by League Enablement)

- **b8h.14/16/17**: Enable golf/motorsports leagues in schema
- Research stream formats
- Implement FIELD_EVENT detection

## DetectionKeywordService Design

```python
# teamarr/services/detection_keywords.py

class DetectionKeywordService:
    """Service for detection patterns - abstracts data source."""

    _cache: dict[str, Any] = {}

    # Phase 1: Load from constants
    # Phase 2: Load from DB with constants fallback

    @classmethod
    def get_combat_keywords(cls) -> list[str]:
        """Get unified combat sports keywords."""
        ...

    @classmethod
    def get_league_hints(cls) -> list[tuple[Pattern, str | list[str]]]:
        """Get compiled league hint patterns."""
        ...

    @classmethod
    def is_combat_sport(cls, text: str) -> bool:
        """Check if text matches combat sport keywords."""
        ...

    @classmethod
    def detect_league(cls, text: str) -> str | list[str] | None:
        """Detect league from text using hint patterns."""
        ...

    @classmethod
    def invalidate_cache(cls):
        """Clear cache (call after DB changes)."""
        cls._cache.clear()
```

## Database Schema (Phase 2)

```sql
CREATE TABLE IF NOT EXISTS detection_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    category TEXT NOT NULL,      -- combat_sports, league_hints, etc.
    pattern TEXT NOT NULL,       -- keyword or regex pattern
    is_regex BOOLEAN DEFAULT FALSE,
    maps_to TEXT,                -- for hints: league code, sport name, etc.
    is_builtin BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    description TEXT,

    UNIQUE(category, pattern)
);
```

## Categories

| Category | Source Constant | `is_regex` | `maps_to` |
|----------|-----------------|------------|-----------|
| `combat_sports` | EVENT_CARD_KEYWORDS (unified) | No | None |
| `league_hints` | LEAGUE_HINT_PATTERNS | Yes | League code(s) |
| `sport_hints` | SPORT_HINT_PATTERNS | Yes | Sport name |
| `placeholders` | PLACEHOLDER_PATTERNS | Yes | None |
| `card_segments` | CARD_SEGMENT_PATTERNS | Yes | Segment name |
| `exclusions` | UFC_EXCLUDE_PATTERNS | Yes | Category |
| `separators` | GAME_SEPARATORS | No | None |

## Custom Regex Fields Per Event Type

### Schema Changes (event_epg_groups)

```sql
-- Existing (TEAM_VS_TEAM)
custom_regex_teams TEXT,
custom_regex_teams_enabled BOOLEAN DEFAULT FALSE,

-- New (EVENT_CARD)
custom_regex_fighters TEXT,
custom_regex_fighters_enabled BOOLEAN DEFAULT FALSE,

-- Future (FIELD_EVENT)
custom_regex_competitors TEXT,
custom_regex_competitors_enabled BOOLEAN DEFAULT FALSE,
```

### CustomRegexConfig Updates

```python
@dataclass
class CustomRegexConfig:
    # TEAM_VS_TEAM
    teams_pattern: str | None = None
    teams_enabled: bool = False

    # EVENT_CARD (new)
    fighters_pattern: str | None = None
    fighters_enabled: bool = False

    # FIELD_EVENT (future)
    competitors_pattern: str | None = None
    competitors_enabled: bool = False

    # Shared
    date_pattern: str | None = None
    date_enabled: bool = False
    time_pattern: str | None = None
    time_enabled: bool = False
    league_pattern: str | None = None
    league_enabled: bool = False
```

### Classifier Flow

```python
def classify_stream(...):
    # 1. Detect event type
    if is_event_card(text):
        # 2a. EVENT_CARD flow
        if custom_regex.fighters_enabled:
            fighter1, fighter2 = extract_with_custom_regex(custom_regex.fighters_pattern)
        else:
            fighter1, fighter2 = extract_fighters_from_event_card(text)
        return ClassifiedStream(category=EVENT_CARD, fighter1=fighter1, ...)

    # 2b. TEAM_VS_TEAM flow
    if custom_regex.teams_enabled:
        team1, team2 = extract_with_custom_regex(custom_regex.teams_pattern)
    else:
        team1, team2 = extract_teams_from_separator(text)
    return ClassifiedStream(category=TEAM_VS_TEAM, team1=team1, ...)
```

## Dependency Chain

```
b8h.8 (Unify keywords)
  ↓
b8h.19 (Detection service)
  ↓
b8h.20 (Classifier uses service)
  ↓
├── b8h.4 (Separate custom regex fields)
└── b8h.9 (DB table)
      ↓
    b8h.10 (API)
      ↓
    ├── b8h.11 (Service reads DB)
    └── b8h.12 (UI)
```

## Benefits of Top-Down Approach

1. **Ships incremental value** - Cleaner classifier before UI exists
2. **Understand patterns first** - Before building the editor
3. **Same code path** - Constants become built-in defaults, no special cases
4. **Easy to test** - Service can be unit tested with constants
5. **Smooth migration** - Swap data source without changing consumers
