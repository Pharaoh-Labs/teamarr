# v1 Patterns Reference

> Critical implementation patterns from the v1 codebase that should be carried forward to v2.

## Quick Reference

| Metric | Value |
|--------|-------|
| Template variables | ~227 |
| Soccer leagues (ESPN) | 244 |
| Soccer teams indexed | 3,400+ |
| Stats cache TTL | 6 hours |
| Retry attempts | 3 |
| Thread pool workers | 100 |
| Connection pools | 10 per host |

---

## 1. Connection Pooling

**File:** `api/espn_client.py`

Single shared session across all instances with thread-safe initialization:

```python
import threading
import requests
from requests.adapters import HTTPAdapter

# Module-level shared session
_espn_session: Optional[requests.Session] = None
_espn_session_lock = threading.Lock()

def _get_espn_session() -> requests.Session:
    """Get or create shared ESPN HTTP session."""
    global _espn_session
    if _espn_session is None:
        with _espn_session_lock:
            if _espn_session is None:  # Double-check after acquiring lock
                session = requests.Session()
                adapter = HTTPAdapter(
                    pool_connections=10,      # Per-host connection pools
                    pool_maxsize=100,         # Match ThreadPoolExecutor workers
                    max_retries=0             # We handle retries manually
                )
                session.mount('http://', adapter)
                session.mount('https://', adapter)
                _espn_session = session
    return _espn_session
```

**Why this matters:**
- Reuses TCP connections across requests
- Thread-safe without blocking on every access
- Reduces connection overhead significantly

---

## 2. Multi-Level Caching

**File:** `api/espn_client.py`

### Class-Level Caches (Shared, Per-Generation)

```python
# Shared across all ESPNClient instances, cleared each generation
_scoreboard_cache: Dict[tuple, Optional[Dict]] = {}   # (sport, league, date)
_schedule_cache: Dict[tuple, Optional[Dict]] = {}     # (sport, league, team_slug)
_team_info_cache: Dict[tuple, Optional[Dict]] = {}    # (sport, league, team_id)
_roster_cache: Dict[tuple, Optional[Dict]] = {}       # (league, team_id)
_group_cache: Dict[tuple, tuple] = {}                 # (sport, league, group_id)

# Lock for thread-safe access
_cache_lock = threading.Lock()
```

### Instance-Level Cache (Long-Lived)

```python
class ESPNClient:
    def __init__(self):
        # Stats cache persists across generations (6-hour TTL)
        self._stats_cache = {}
        self._stats_cache_times = {}
        self._stats_cache_instance_lock = threading.Lock()
        self._cache_duration = timedelta(hours=6)
```

### Cache Access Pattern (Double-Checked Locking)

```python
def get_scoreboard(self, sport: str, league: str, date: str) -> Optional[Dict]:
    cache_key = (sport, league, date)

    # Fast path: check without lock
    if cache_key in _scoreboard_cache:
        return _scoreboard_cache[cache_key]

    # Slow path: acquire lock, check again, then fetch
    with _cache_lock:
        if cache_key in _scoreboard_cache:
            return _scoreboard_cache[cache_key]

        # Fetch from API
        result = self._fetch_scoreboard(sport, league, date)
        _scoreboard_cache[cache_key] = result  # Cache even if None!
        return result
```

**Key insight:** Cache `None` results too - prevents re-fetching the same failed request.

### Cache Clearing

```python
@classmethod
def clear_caches(cls):
    """Call at start of each EPG generation."""
    global _scoreboard_cache, _schedule_cache, _team_info_cache
    with _cache_lock:
        _scoreboard_cache.clear()
        _schedule_cache.clear()
        _team_info_cache.clear()
        # Note: stats cache NOT cleared (has its own TTL)
```

---

## 3. Retry Logic with Exponential Backoff

**File:** `api/espn_client.py`

```python
def _make_request(self, url: str) -> Optional[Dict]:
    """Make HTTP request with retry logic."""
    for attempt in range(self.retry_count):  # Default: 3
        try:
            response = self._session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < self.retry_count - 1:
                delay = self.retry_delay * (attempt + 1)  # 1s, 2s, 3s
                logger.warning(f"Attempt {attempt + 1}/{self.retry_count} failed: {e}")
                time.sleep(delay)
                continue
            else:
                logger.error(f"All {self.retry_count} attempts failed for {url}: {e}")
                return None
    return None
```

### Dispatcharr Backoff (with Jitter)

**File:** `api/dispatcharr_client.py`

```python
def _calculate_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 32.0) -> float:
    """
    Exponential backoff with jitter.

    Attempt 0: 0.5-1.5s   (base * 1 * jitter)
    Attempt 1: 1-3s       (base * 2 * jitter)
    Attempt 2: 2-6s       (base * 4 * jitter)
    Attempt 3: 4-12s      (base * 8 * jitter)
    Attempt 4: 8-24s      (base * 16 * jitter)
    Attempt 5: 16-32s     (base * 32 * jitter, capped)
    """
    delay = min(max_delay, base_delay * (2 ** attempt))
    jitter = random.uniform(0.5, 1.5)
    return delay * jitter
```

**Retryable conditions:**
- Connection errors (ConnectionError, Timeout, ChunkedEncodingError)
- Server transient failures (502, 503, 504)

---

## 4. Error Handling Philosophy

**Pattern:** Never crash, return empty, log, continue.

```python
def get_team_stats(self, sport: str, league: str, team_id: str) -> Dict:
    """Get team statistics. Returns empty dict on failure."""
    try:
        data = self._fetch_team_stats(sport, league, team_id)
        if data is None:
            return {}
        return self._normalize_stats(data)
    except Exception as e:
        logger.error(f"Failed to fetch stats for {team_id}: {e}")
        return {}  # Never raise, return empty
```

**Applied everywhere:**
- API calls return `None` or `{}` on failure
- Normalization skips malformed records
- Orchestrator continues with partial data
- UI shows degraded state, not error page

---

## 5. ESPN API Quirks

### College Sports Require Group Parameter

```python
COLLEGE_SCOREBOARD_GROUPS = {
    'mens-college-basketball': '50',    # All Division I
    'womens-college-basketball': '50',
    'college-football': '80'            # FBS only
}

def get_scoreboard(self, sport: str, league: str, date: str) -> Optional[Dict]:
    url = f"{self.base_url}/{sport}/{league}/scoreboard"
    params = {'dates': date}

    # Without groups param: ~5-10 featured games
    # With groups param: ~48-61 all games
    if league in COLLEGE_SCOREBOARD_GROUPS:
        params['groups'] = COLLEGE_SCOREBOARD_GROUPS[league]

    return self._make_request(url, params)
```

### Team Record Extraction

```python
def _extract_record(self, competitor: Dict) -> Dict:
    """Extract W-L record from competitor data."""
    records = competitor.get('records', [])
    for record in records:
        if record.get('type') == 'total':
            summary = record.get('summary', '0-0')
            # Parse "9-5" or "9-5-1" (with ties)
            parts = summary.split('-')
            return {
                'summary': summary,
                'wins': int(parts[0]) if parts else 0,
                'losses': int(parts[1]) if len(parts) > 1 else 0,
                'ties': int(parts[2]) if len(parts) > 2 else 0
            }
    return {'summary': '0-0', 'wins': 0, 'losses': 0}
```

### Status Normalization

```python
STATUS_MAP = {
    'STATUS_SCHEDULED': 'scheduled',
    'STATUS_IN_PROGRESS': 'in_progress',
    'STATUS_HALFTIME': 'in_progress',
    'STATUS_FINAL': 'final',
    'STATUS_FINAL_OT': 'final',
    'STATUS_POSTPONED': 'postponed',
    'STATUS_CANCELED': 'canceled',
    'STATUS_DELAYED': 'delayed',
}

def _normalize_status(self, status: Dict) -> str:
    type_name = status.get('type', {}).get('name', '')
    return STATUS_MAP.get(type_name, 'unknown')
```

---

## 6. Parallel Processing

**File:** `epg/orchestrator.py`

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def generate_epg(self, teams: List[Dict], progress_callback=None) -> List[Programme]:
    programmes = []

    with ThreadPoolExecutor(max_workers=100) as executor:
        # Submit all teams for parallel processing
        future_to_team = {
            executor.submit(self._process_team, team): team
            for team in teams
        }

        # Collect results as they complete
        for i, future in enumerate(as_completed(future_to_team)):
            team = future_to_team[future]
            try:
                team_programmes = future.result()
                programmes.extend(team_programmes)
            except Exception as e:
                logger.error(f"Failed to process {team['team_name']}: {e}")

            # Progress callback for UI
            if progress_callback:
                progress_callback(
                    status='processing',
                    message=f"Processed {team['team_name']}",
                    percent=int((i + 1) / len(teams) * 100),
                    current=i + 1,
                    total=len(teams)
                )

    return programmes
```

---

## 7. Database Patterns

### JSON Columns for Flexibility

```sql
CREATE TABLE templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    -- Structured data as JSON
    flags JSON DEFAULT '{"new": false, "live": true}',
    categories JSON DEFAULT '["Sports"]',
    pregame_periods JSON DEFAULT '[]',
    postgame_periods JSON DEFAULT '[]',
    description_options JSON DEFAULT '[]'
);
```

### Auto-Updated Timestamps

```sql
CREATE TABLE teams (
    id INTEGER PRIMARY KEY,
    team_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trigger to auto-update
CREATE TRIGGER update_teams_timestamp
AFTER UPDATE ON teams
BEGIN
    UPDATE teams SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
```

### Views for Common Queries

```sql
CREATE VIEW v_active_teams AS
SELECT
    t.*,
    l.sport,
    l.league_name,
    l.logo_url as league_logo,
    tmpl.name as template_name
FROM teams t
LEFT JOIN league_config l ON t.league = l.league_code
LEFT JOIN templates tmpl ON t.template_id = tmpl.id
WHERE t.active = 1;
```

---

## 8. Template Variable Categories

### Basic Game Info
- `team_name`, `team_abbrev`, `opponent`, `opponent_abbrev`
- `matchup` (e.g., "Lakers @ Celtics")
- `venue_full`, `venue_city`, `venue_state`
- `game_time`, `game_day`, `game_date`

### Home/Away Context
- `is_home` (boolean)
- `vs_at` ("vs" or "@")
- `home_team`, `away_team`

### Scores & Status
- `home_score`, `away_score`, `our_score`
- `final_score` (e.g., "120-115")
- `status`, `result_text`, `overtime_text`

### Records & Standings
- `team_record`, `opponent_record`
- `home_record`, `away_record`, `division_record`
- `playoff_seed`, `games_back`

### Head-to-Head
- `h2h_series` (e.g., "3-1")
- `h2h_streak` (e.g., "won last 2")
- `last_matchup_date`, `last_matchup_score`

### Temporal (for fillers)
- `hours_until`, `days_until`
- `next_opponent`, `next_game_date`
- `last_opponent`, `last_result`

### Suffix Syntax
```
{variable}       # Current game
{variable.next}  # Next scheduled game
{variable.last}  # Last completed game
```

---

## 9. Progress Callback Pattern

**File:** `app.py`

```python
# Global status dict for polling
generation_status = {
    'in_progress': False,
    'status': 'idle',
    'message': '',
    'percent': 0,
    'extra': {}
}

def progress_callback(status, message, percent=None, **extra):
    """Update generation status for UI polling."""
    generation_status.update({
        'in_progress': status != 'complete',
        'status': status,
        'message': message,
        'percent': percent or 0,
        'extra': extra
    })

# API endpoint for polling
@app.route('/api/epg/status')
def epg_status():
    return jsonify(generation_status)
```

**UI polls every 500ms during generation.**

---

## 10. Key File Reference

| File | Lines | Purpose |
|------|-------|---------|
| `api/espn_client.py` | 1,378 | ESPN API with caching |
| `epg/orchestrator.py` | 2,436 | Main EPG workflow |
| `epg/template_engine.py` | 1,500+ | Variable resolution |
| `epg/channel_lifecycle.py` | 3,800+ | Channel automation |
| `epg/soccer_multi_league.py` | 905 | Multi-league cache |
| `app.py` | 7,834 | Flask web UI |
| `database/schema.sql` | 1,061 | Complete schema |
| `api/dispatcharr_client.py` | 400+ | Dispatcharr integration |

---

## 11. What v2 Changes

| v1 Pattern | v2 Approach | Reason |
|------------|-------------|--------|
| Raw dicts | Dataclasses | Type safety, IDE support |
| 2,400-line orchestrator | Discrete consumers | Single responsibility |
| ESPN code scattered | Provider abstraction | Pluggable providers |
| Monolithic app.py | Flask blueprints | Maintainability |
| Direct API in consumers | Service layer | Clean boundaries |
| League detection tiers | Provider handles own leagues | Simpler routing |

---

## 12. Anti-Patterns to Avoid

1. **Config in code** → Use database settings
2. **Magic strings** → Use enums/constants
3. **Deep nesting** → Keep functions focused
4. **Implicit state** → Pass context explicitly
5. **Provider code scattered** → Encapsulate in provider
6. **Direct API in consumers** → Go through service
