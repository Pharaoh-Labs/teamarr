# Teamarr v2 - Provider System

> Provider interface, implementations, and registration.

## SportsProvider ABC

The contract between Service Layer and Provider Layer. Every provider implements this interface.

```python
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Optional, List

class SportsProvider(ABC):
    """
    The contract between Service Layer and Provider Layer.

    Every provider (ESPN, TheSportsDB, future) implements this interface.
    Providers hide all their quirks behind this clean contract.
    What comes out is always clean dataclasses.
    """

    # =========================================================================
    # IDENTITY
    # =========================================================================

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Short, lowercase identifier: 'espn', 'thesportsdb'

        Used for: database storage, cache keys, logging.
        Must be stable - appears in database records.
        """

    # =========================================================================
    # LEAGUE SUPPORT
    # =========================================================================

    @abstractmethod
    def supports_league(self, league: str) -> bool:
        """
        Can this provider handle a given league?

        Must be LOCAL only - no API calls. Just check a set.
        Used by Service Layer for provider discovery.
        """

    # =========================================================================
    # REQUIRED METHODS - All providers must implement
    # =========================================================================

    @abstractmethod
    def get_events(self, league: str, date: date) -> List[Event]:
        """
        Get all events for a league on a date.

        PRIMARY DATA SOURCE - scoreboard/livescores.
        Cheap (1 call per league), fresh, reliable.
        """

    @abstractmethod
    def get_team_schedule(self, team_id: str, league: str,
                          days_ahead: int = 14) -> List[Event]:
        """
        Get upcoming events for a specific team.

        FALLBACK DATA SOURCE - used when scoreboard misses a game
        or when extended lookahead needed (30+ days).
        """

    @abstractmethod
    def get_team(self, team_id: str, league: str) -> Optional[Team]:
        """
        Get team identity: logo, colors, names.

        Typically cached aggressively - team identity rarely changes.
        """

    @abstractmethod
    def get_event(self, event_id: str, league: str) -> Optional[Event]:
        """
        Get a specific event by ID.

        Used to REFRESH events we already matched - get final scores,
        updated status, etc. Event ID must be from this provider.
        """

    # =========================================================================
    # COMPOSITE - Default implementation provided
    # =========================================================================

    def get_team_events(self, team_id: str, league: str,
                        start_date: date, end_date: date) -> List[Event]:
        """
        Get team's events in a date range.

        Default: tries scoreboard per day, falls back to schedule.
        Override if provider has a more efficient approach.
        """
        events = []
        schedule_events = None

        current = start_date
        while current <= end_date:
            day_events = self.get_events(league, current)
            team_events = [
                e for e in day_events
                if team_id in (e.home_team.id, e.away_team.id)
            ]

            if team_events:
                events.extend(team_events)
            else:
                if schedule_events is None:
                    days = (end_date - start_date).days + 1
                    schedule_events = self.get_team_schedule(
                        team_id, league, days_ahead=max(days, 14)
                    )
                events.extend(
                    e for e in schedule_events
                    if e.start_time.date() == current
                )

            current += timedelta(days=1)

        return events

    # =========================================================================
    # OPTIONAL - Return None/empty if unsupported
    # =========================================================================

    def get_team_stats(self, team_id: str, league: str) -> Optional[TeamStats]:
        """
        Team statistics for template variables: {record}, {streak}, etc.

        ESPN: full stats. TSDB: limited. Consumers handle None gracefully.
        """
        return None

    def get_league_teams(self, league: str) -> List[Team]:
        """All teams in a league. Used for team import UI."""
        return []

    def search_teams(self, query: str, league: Optional[str] = None) -> List[Team]:
        """Search teams by name. Used for team import UI."""
        return []
```

---

## Provider Architecture

Each provider has three internal components:

```
┌───────────────────────────────────────────────────────────────┐
│                      ESPNProvider                              │
│                   (implements SportsProvider)                  │
│                                                                │
│  ┌─────────────┐  ┌─────────────────┐  ┌─────────────────┐   │
│  │ ESPNClient  │  │ ESPNNormalizer  │  │ League Mappings │   │
│  │             │  │                 │  │                 │   │
│  │ HTTP calls  │→│ dict → dataclass│  │ nfl → (football,│   │
│  │ Raw JSON    │  │ Field mapping   │  │        nfl)     │   │
│  └─────────────┘  └─────────────────┘  └─────────────────┘   │
└───────────────────────────────────────────────────────────────┘
```

### Client Layer

Raw HTTP communication only:

```python
class ESPNClient:
    """Raw ESPN API calls. No data processing."""

    def get_scoreboard(self, sport: str, league: str, date: date) -> Optional[dict]:
        """Get scoreboard for a league on a date."""
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
        return self._request(url, params={"dates": date.strftime("%Y%m%d")})

    def get_schedule(self, sport: str, league: str, team_slug: str) -> Optional[dict]:
        """Get team schedule."""
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_slug}/schedule"
        return self._request(url)

    def get_team_info(self, sport: str, league: str, team_id: str) -> Optional[dict]:
        """Get team details."""
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}"
        return self._request(url)
```

### Normalizer Layer

Transform raw responses to dataclasses:

```python
class ESPNNormalizer:
    """Transform ESPN API responses to dataclasses."""

    def normalize_event(self, raw: dict, league: str) -> Optional[Event]:
        """Convert ESPN event dict to Event dataclass."""
        try:
            competition = raw.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])

            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})

            return Event(
                id=raw["id"],
                provider="espn",
                name=raw.get("name", ""),
                short_name=raw.get("shortName", ""),
                start_time=self._parse_date(raw.get("date")),
                home_team=self.normalize_team(home.get("team", {}), league),
                away_team=self.normalize_team(away.get("team", {}), league),
                status=self._normalize_status(raw.get("status", {})),
                league=league,
                home_score=self._parse_score(home.get("score")),
                away_score=self._parse_score(away.get("score")),
                venue=self._normalize_venue(competition.get("venue")),
                broadcasts=self._extract_broadcasts(competition),
            )
        except Exception as e:
            log.warn("NORMALIZE_FAILED", f"Could not normalize event", error=str(e))
            return None

    def normalize_team(self, raw: dict, league: str) -> Team:
        """Convert ESPN team dict to Team dataclass."""
        return Team(
            id=raw.get("id", ""),
            provider="espn",
            name=raw.get("displayName", raw.get("name", "")),
            short_name=raw.get("shortDisplayName", raw.get("name", "")),
            abbreviation=raw.get("abbreviation", ""),
            league=league,
            logo_url=raw.get("logo"),
            color=raw.get("color"),
        )
```

### Provider Layer

Orchestrates client + normalizer:

```python
class ESPNProvider(SportsProvider):
    """ESPN implementation of SportsProvider."""

    def __init__(self):
        self.client = ESPNClient()
        self.normalizer = ESPNNormalizer()
        self._supported_leagues = {
            "nfl", "nba", "mlb", "nhl", "wnba",
            "mens-college-basketball", "womens-college-basketball",
            "college-football", "eng.1", "esp.1", "ger.1", # etc
        }

    @property
    def name(self) -> str:
        return "espn"

    def supports_league(self, league: str) -> bool:
        return league in self._supported_leagues

    def get_events(self, league: str, date: date) -> List[Event]:
        sport, espn_league = self._map_league(league)
        raw = self.client.get_scoreboard(sport, espn_league, date)
        if not raw:
            return []

        events = []
        for event_data in raw.get("events", []):
            event = self.normalizer.normalize_event(event_data, league)
            if event:
                events.append(event)
        return events

    def _map_league(self, league: str) -> tuple[str, str]:
        """Map canonical league to ESPN (sport, league) tuple."""
        mappings = {
            "nfl": ("football", "nfl"),
            "nba": ("basketball", "nba"),
            "mlb": ("baseball", "mlb"),
            "nhl": ("hockey", "nhl"),
            "eng.1": ("soccer", "eng.1"),
            # ... more mappings
        }
        return mappings.get(league, ("", league))
```

---

## Provider Registry

Centralized registration with auto-wiring:

```python
class ProviderRegistry:
    """
    Central registry for all sports data providers.

    Adding a new provider:
    1. Implement SportsProvider
    2. Call registry.register(MyProvider())
    3. Done. Soccer composite auto-discovers if provider covers soccer.
    """

    def __init__(self, db):
        self.db = db
        self._base_providers: Dict[str, SportsProvider] = {}
        self._soccer_composite: Optional[SoccerCompositeProvider] = None
        self._league_provider_cache: Dict[str, str] = {}

    def register(self, provider: SportsProvider) -> None:
        """Register a provider. Soccer composite auto-rebuilds."""
        self._base_providers[provider.name] = provider
        self._rebuild_soccer_composite()
        self._league_provider_cache.clear()

    def get_provider(self, league: str) -> Optional[SportsProvider]:
        """Get appropriate provider for a league."""
        # Check cache
        if league in self._league_provider_cache:
            return self._get_provider_by_name(self._league_provider_cache[league])

        # Soccer leagues → composite
        if self._is_soccer_league(league) and self._soccer_composite:
            self._league_provider_cache[league] = "soccer_composite"
            return self._soccer_composite

        # Try base providers in priority order
        for provider in self._get_priority_ordered():
            if provider.supports_league(league):
                self._league_provider_cache[league] = provider.name
                return provider

        return None
```

---

## Provider Priority

ESPN is always primary. Others fill gaps.

```python
PROVIDER_PRIORITY = [
    ("espn", 1),           # Priority 1 - try first
    ("thesportsdb", 2),    # Priority 2 - fallback
]
```

**Behavior:**
- NFL request → ESPN supports → ESPN handles
- AHL request → ESPN doesn't support → TheSportsDB handles
- ESPN API fails → Falls through to TheSportsDB (if it supports that league)

---

## Adding a New Provider

### Step 1: Implement the Interface

```python
class MyNewProvider(SportsProvider):
    @property
    def name(self) -> str:
        return "mynewprovider"

    def supports_league(self, league: str) -> bool:
        return league in {"ahl", "echl", "sphl"}

    def get_events(self, league: str, date: date) -> List[Event]:
        # Implementation
        pass

    def get_team_schedule(self, team_id: str, league: str,
                          days_ahead: int = 14) -> List[Event]:
        # Implementation
        pass

    def get_team(self, team_id: str, league: str) -> Optional[Team]:
        # Implementation
        pass

    def get_event(self, event_id: str, league: str) -> Optional[Event]:
        # Implementation
        pass
```

### Step 2: Register the Provider

```python
# In app initialization
registry.register(MyNewProvider())
```

### Step 3: Add League Mappings (if needed)

```sql
INSERT INTO league_provider_mappings
    (canonical_code, provider, provider_league_id)
VALUES
    ('ahl', 'mynewprovider', 'AHL'),
    ('echl', 'mynewprovider', 'ECHL');
```

---

## ESPN Provider Details

### Supported Leagues

```python
ESPN_LEAGUES = {
    # US Major
    "nfl", "nba", "mlb", "nhl", "wnba", "mls",

    # US College
    "mens-college-basketball", "womens-college-basketball",
    "college-football", "mens-college-hockey",

    # Soccer (partial - see soccer composite for full list)
    "eng.1", "eng.2", "esp.1", "ger.1", "ita.1", "fra.1",
    "uefa.champions", "uefa.europa",

    # Other
    "pga", "lpga", "atp", "wta", "f1",
}
```

### API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/scoreboard` | Daily events for a league |
| `/teams/{id}/schedule` | Team's upcoming games |
| `/teams/{id}` | Team details |
| `/summary?event={id}` | Single event details |

### ESPN Quirks (Handled in Normalizer)

1. **Nested competitors** - Home/away in `competitions[0].competitors[]`
2. **Date format** - ISO 8601 with Z suffix
3. **Missing fields** - Logo, color sometimes absent
4. **Status codes** - Multiple fields for same concept

---

## TheSportsDB Provider Details

### Supported Leagues

Primarily covers leagues ESPN doesn't:
- AHL, OHL, WHL (minor hockey)
- Lower-tier European soccer
- Australian leagues
- Various international competitions

### API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/eventsday.php` | Events on a specific day |
| `/eventsnext.php` | Team's next N events |
| `/lookupteam.php` | Team details |
| `/lookupevent.php` | Single event |

### Rate Limits

TheSportsDB has rate limits. See [research/thesportsdb-api.md](research/thesportsdb-api.md) for details.

---

## Soccer Composite Provider

See [research/soccer-multi-league.md](research/soccer-multi-league.md) for the full design.

**Problem:** Club soccer teams play in multiple leagues simultaneously.

**Solution:** A composite provider that:
1. Discovers which leagues a team plays in
2. Aggregates events from all relevant leagues
3. Routes to the appropriate base provider per league

```python
class SoccerCompositeProvider(SportsProvider):
    """
    Handles soccer's multi-league complexity.

    Manchester United plays in eng.1, eng.fa, eng.league_cup, uefa.champions.
    This provider checks all relevant leagues for a team's events.
    """

    @property
    def name(self) -> str:
        return "soccer_composite"

    def get_events(self, league: str, date: date) -> List[Event]:
        # Route to appropriate base provider
        provider = self._get_provider_for_league(league)
        return provider.get_events(league, date)

    def get_team_events(self, team_id: str, league: str,
                        start_date: date, end_date: date) -> List[Event]:
        # Get all leagues this team plays in
        team_leagues = self._get_team_leagues(team_id)

        # Aggregate events from all leagues
        all_events = []
        for team_league in team_leagues:
            provider = self._get_provider_for_league(team_league)
            events = provider.get_events(team_league, start_date)
            team_events = [e for e in events
                          if team_id in (e.home_team.id, e.away_team.id)]
            all_events.extend(team_events)

        return all_events
```
