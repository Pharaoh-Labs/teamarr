---
title: Detection Keyword Service
parent: Architecture
grand_parent: Technical Reference
nav_order: 4
---

# Detection Keyword Service

The `DetectionKeywordService` provides centralized pattern-based detection for stream classification. It abstracts the source of detection patterns: built-in constants from `teamarr/utilities/constants.py` merged with user-defined patterns from the `detection_keywords` database table (managed via the Detection Library UI).

Consumers (`classifier.py`, `stream_filter.py`) call the service instead of importing pattern constants. The service exposes:

- **Pattern accessors** — `get_combat_keywords()`, `get_league_hints()`, `get_sport_hints()`, `get_placeholder_patterns()`, `get_card_segment_patterns()`, `get_exclusion_patterns()`, `get_separators()`
- **Detection methods** — `is_combat_sport()`, `detect_league()`, `detect_sport()`, `is_placeholder()`, `detect_card_segment()`, `is_excluded()`, `find_separator()`
- **Cache management** — `invalidate_cache()`, `warm_cache()`

## Design Principles

### 1. Layer Separation

**Classifier and filter modules should NOT:**
- Import pattern constants directly
- Compile regex patterns themselves
- Have hardcoded detection logic

**Classifier and filter modules SHOULD:**
- Call DetectionKeywordService methods
- Handle orchestration logic only
- Remain unaware of pattern sources

### 2. Pattern Sources

Built-in patterns come from `teamarr/utilities/constants.py`:

- EVENT_TYPE_KEYWORDS (keywords per event type: `EVENT_CARD`, `TEAM_VS_TEAM`, `FIELD_EVENT`; combat keywords are derived via `get_event_type_keywords().get("EVENT_CARD")` — there is no separate combat constant)
- LEAGUE_HINT_PATTERNS (59 patterns, including multi-league umbrellas)
- SPORT_HINT_PATTERNS (33 patterns, including multi-sport hints)
- PLACEHOLDER_PATTERNS (15 patterns)
- CARD_SEGMENT_PATTERNS (12 patterns)
- COMBAT_SPORTS_EXCLUDE_PATTERNS (14 patterns)
- GAME_SEPARATORS (10 separators: `vs.`, `vs`, `v.`, `v`, `@`, `at`, `x`, `contre`, `gegen`, `contra`)

User-defined patterns (league hints, sport hints, event type keywords) are stored in the `detection_keywords` table and managed through **Detection Library** in the UI. The service merges them with the built-in patterns at runtime — no restart required.

### 3. Pattern Caching

Patterns are compiled once and cached at class level:
- Lazy initialization on first access
- No recompilation overhead
- `invalidate_cache()` for testing or DB updates

### 4. Word Boundary Matching

Combat sports keywords use word boundary matching (`\b`) to avoid false positives:
- "wbo" matches "WBO Championship" but NOT "Cowboys"
- "pbc" matches "PBC Boxing" but NOT embedded substrings

## Stream Classification Flow

```
Stream Name
     │
     ▼
┌─────────────────────┐
│ 1. Placeholder?     │──Yes──▶ Skip (no event info)
└─────────────────────┘
     │ No
     ▼
┌─────────────────────┐
│ 2. Combat Sports?   │──Yes──▶ EVENT_CARD category
└─────────────────────┘         (UFC, Boxing, MMA)
     │ No
     ▼
┌─────────────────────┐
│ 3. Has Separator?   │──Yes──▶ TEAM_VS_TEAM category
└─────────────────────┘         (NFL, NBA, Soccer)
     │ No
     ▼
    Fallback logic

Note: skip_builtin_filter bypasses steps 1-2 in stream_filter.py
```

## skip_builtin_filter Option

Groups can set `skip_builtin_filter=True` to bypass built-in filtering:
- Placeholder detection skipped
- Unsupported sport detection skipped
- Custom regex still applies

This allows users to match streams that would normally be filtered (e.g., individual sports like golf or tennis that Teamarr can't schedule-match but user wants in EPG).

## Multi-Sport Hints

Some keywords are ambiguous across sports. Sport hints support multi-sport targets:

```python
# Single sport
"hockey" → "Hockey"

# Multiple sports (bare "football" is ambiguous)
"football" → ["Soccer", "Football"]
```

When a multi-sport hint matches, the matcher tries all listed sports. In stream filtering, a stream is only excluded if **all** its hinted sports are unsupported.

Multi-sport targets are stored as JSON arrays in the database (`'["Soccer", "Football"]'`) and parsed back to lists. Single-element arrays are collapsed to plain strings.

## Multi-League Hints

League hints can map to multiple leagues for umbrella brands:

| Keyword | Maps To |
|---------|---------|
| `EFL` | `eng.2`, `eng.3`, `eng.4`, `eng.fa` |
| `Bundesliga` | `ger.1`, `ger.2` |
| `CHL` | `ohl`, `whl`, `qmjhl` |
| `NCAAB` | `mens-college-basketball`, `womens-college-basketball` |

When a stream matches a multi-league hint, the matcher tries events from all listed leagues.

## Usage Examples

```python
from teamarr.services.detection_keywords import DetectionKeywordService

# Check if stream is combat sports
if DetectionKeywordService.is_combat_sport("UFC 315: Main Card"):
    # Handle EVENT_CARD classification

# Detect league from stream name
league = DetectionKeywordService.detect_league("NFL: Cowboys vs Eagles")
# Returns: "nfl"

# Umbrella brands return lists
league = DetectionKeywordService.detect_league("EFL: Team A vs Team B")
# Returns: ["eng.2", "eng.3", "eng.4", "eng.fa"]

# Pre-warm cache on startup
stats = DetectionKeywordService.warm_cache()
# Returns per-category pattern counts, e.g. {'combat_keywords': ..., 'league_hints': ..., ...}
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/detection-keywords` | List all keywords |
| GET | `/api/v1/detection-keywords/categories` | Describe available categories |
| GET | `/api/v1/detection-keywords/{category}` | Filter by category |
| GET | `/api/v1/detection-keywords/id/{id}` | Get single keyword by id |
| POST | `/api/v1/detection-keywords` | Create keyword |
| PUT | `/api/v1/detection-keywords/id/{id}` | Update keyword |
| DELETE | `/api/v1/detection-keywords/id/{id}` | Delete keyword |
| POST | `/api/v1/detection-keywords/import` | Bulk import (upsert) |
| GET | `/api/v1/detection-keywords/export` | Export keywords as JSON |

## File Locations

| Component | Location |
|-----------|----------|
| Service | `teamarr/services/detection_keywords.py` |
| Classifier | `teamarr/consumers/matching/classifier.py` |
| Stream Filter | `teamarr/services/stream_filter.py` |
| Constants | `teamarr/utilities/constants.py` |
| DB CRUD | `teamarr/database/detection_keywords.py` |
| API Routes | `teamarr/api/routes/detection_keywords.py` |
