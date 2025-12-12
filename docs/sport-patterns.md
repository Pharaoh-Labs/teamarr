# Sport Pattern Registry

> Single place to define a sport's structure, data shape, and template variables.

## Summary

**5 patterns cover ~99% of all sports broadcasts.**

| # | Pattern | Description | Example Sports |
|---|---------|-------------|----------------|
| 1 | **team_vs_team** | 2 teams compete | Football, Basketball, Hockey, Soccer, Baseball, Rugby, Cricket, Esports |
| 2 | **individual** | 2 individuals compete | Tennis matches (API TBD), Olympic bracket matches |
| 3 | **tournament** | Field + scoring/leaderboard | Golf, Tennis broadcasts, Gymnastics, Diving, Poker, Darts, Bull Riding |
| 4 | **card** | Multi-bout event | UFC, Boxing PPV, WWE, Bellator, PFL |
| 5 | **race** | Field + positional finish | F1, NASCAR, IndyCar, Swimming, Track, Cycling, Horse Racing |

See [sport-pattern-definitions.md](sport-pattern-definitions.md) for full dataclass definitions and template variables.

## Problem

Different sports have fundamentally different structures. Without a pattern system, we'd have:
- Provider code littered with `if sport == "golf"` checks
- Consumer code guessing what fields exist
- Templates breaking when `{home_team}` doesn't exist for golf
- No way to add a new sport without touching multiple files

## Design Principle

**Same principle as providers:** Define once, plug in everywhere.

```
┌─────────────────────────────────────────────────────────────────┐
│                    SPORT PATTERN REGISTRY                        │
│                                                                  │
│  "nfl" → TeamVsTeamPattern                                      │
│  "golf" → TournamentPattern                                      │
│  "ufc" → CardPattern                                            │
│  "tennis" → IndividualVsIndividualPattern                       │
│                                                                  │
│  Each pattern defines:                                           │
│  - Event structure (what fields exist)                          │
│  - Participant model (Team, Individual, Driver, Fighter, etc.)  │
│  - Duration behavior (fixed, variable, multi-day)               │
│  - Available template variables                                  │
│  - EPG generation strategy                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## How It Plugs Into the Pipeline

```
═══════════════════════════════════════════════════════════════════
                        CONSUMER LAYER
═══════════════════════════════════════════════════════════════════
                              │
                              │ "Give me Lions events"
                              │ (doesn't care about sport structure)
                              ▼
═══════════════════════════════════════════════════════════════════
                        SERVICE LAYER
           Knows: which pattern applies to which league
═══════════════════════════════════════════════════════════════════
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │ TeamVsTeam   │  │ Tournament   │  │ Card         │
    │ Pattern      │  │ Pattern      │  │ Pattern      │
    │              │  │              │  │              │
    │ Validates:   │  │ Validates:   │  │ Validates:   │
    │ - home_team  │  │ - field      │  │ - bouts[]    │
    │ - away_team  │  │ - cut_line   │  │ - main_event │
    │ - venue      │  │ - players[]  │  │ - venue      │
    │              │  │ - rounds     │  │              │
    │ Variables:   │  │              │  │ Variables:   │
    │ {home_team}  │  │ Variables:   │  │ {main_event} │
    │ {away_team}  │  │ {leader}     │  │ {card_name}  │
    │ {venue}      │  │ {course}     │  │ {bout_count} │
    └──────────────┘  └──────────────┘  └──────────────┘
            │                 │                 │
            └─────────────────┼─────────────────┘
                              │
                              ▼
═══════════════════════════════════════════════════════════════════
                        PROVIDER LAYER
           Uses pattern to know HOW to normalize raw data
═══════════════════════════════════════════════════════════════════
                              │
    Provider receives raw ESPN/TSDB data
    Looks up pattern for the sport
    Normalizes into pattern-specific dataclass
                              │
                              ▼
    Returns: TeamVsTeamEvent | TournamentEvent | CardEvent
             (all share base Event interface)
```

---

## Pattern Definition (Conceptual)

Each sport pattern defines:

### 1. Event Structure

```python
class SportPattern(ABC):
    """Base pattern all sports implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Pattern name: 'team_vs_team', 'tournament', etc."""

    @property
    @abstractmethod
    def event_class(self) -> type:
        """The dataclass used for events of this pattern."""

    @property
    @abstractmethod
    def participant_class(self) -> type:
        """Team, Individual, Driver, Fighter, etc."""

    @abstractmethod
    def get_template_variables(self, event) -> dict:
        """Extract all available template variables from an event."""

    @abstractmethod
    def get_duration(self, event) -> timedelta:
        """Calculate expected duration for EPG."""

    @abstractmethod
    def validate_event(self, event) -> bool:
        """Ensure event has required fields for this pattern."""
```

### 2. League-to-Pattern Mapping

```python
LEAGUE_PATTERNS = {
    # Team vs Team
    "nfl": "team_vs_team",
    "nba": "team_vs_team",
    "nhl": "team_vs_team",
    "mlb": "team_vs_team",
    "epl": "team_vs_team",
    "mls": "team_vs_team",

    # Individual vs Individual
    "atp": "individual_vs_individual",
    "wta": "individual_vs_individual",

    # Tournament
    "pga": "tournament",
    "lpga": "tournament",

    # Card/Multi-bout
    "ufc": "card",
    "pfl": "card",
    "boxing": "card",

    # Race
    "f1": "race",
    "nascar": "race",
    "indycar": "race",
}
```

### 3. Pattern-Specific Event Classes

```python
@dataclass
class BaseEvent:
    """Fields ALL events have regardless of sport."""
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
    """Golf, tennis majors (the tournament itself, not individual matches)."""
    participants: list[TournamentParticipant]
    current_round: Optional[int] = None
    total_rounds: int = 4
    cut_line: Optional[int] = None
    purse: Optional[str] = None


@dataclass
class CardEvent(BaseEvent):
    """MMA, boxing cards."""
    bouts: list[Bout]
    main_event: Optional[Bout] = None
    co_main_event: Optional[Bout] = None


@dataclass
class RaceEvent(BaseEvent):
    """F1, NASCAR, IndyCar."""
    participants: list[RaceParticipant]
    laps: Optional[int] = None
    track: Optional[Track] = None
```

---

## Template Variable Availability

Each pattern exposes different variables:

| Variable | TeamVsTeam | Tournament | Card | Race |
|----------|------------|------------|------|------|
| `{home_team}` | ✅ | ❌ | ❌ | ❌ |
| `{away_team}` | ✅ | ❌ | ❌ | ❌ |
| `{home_score}` | ✅ | ❌ | ❌ | ❌ |
| `{away_score}` | ✅ | ❌ | ❌ | ❌ |
| `{leader}` | ❌ | ✅ | ❌ | ✅ |
| `{main_event}` | ❌ | ❌ | ✅ | ❌ |
| `{bout_count}` | ❌ | ❌ | ✅ | ❌ |
| `{round}` | ❌ | ✅ | ❌ | ❌ |
| `{lap}` | ❌ | ❌ | ❌ | ✅ |
| `{pole_position}` | ❌ | ❌ | ❌ | ✅ |
| `{venue}` | ✅ | ✅ | ✅ | ✅ |
| `{event_name}` | ✅ | ✅ | ✅ | ✅ |
| `{start_time}` | ✅ | ✅ | ✅ | ✅ |

Templates reference variables. Pattern determines which are available. Template engine validates at runtime.

---

## Duration Behavior

| Pattern | Duration Strategy |
|---------|------------------|
| TeamVsTeam | Sport-specific default (NFL: 3.5h, NBA: 2.5h, NHL: 2.5h) |
| Tournament | Multi-day (4 days for golf, variable for tennis) |
| Card | Total card duration (UFC: ~5h including prelims) |
| Race | Race duration + pre/post (F1: ~2h race, NASCAR: ~3-4h) |

---

## Adding a New Sport

To add a new sport (e.g., cricket):

1. **Determine pattern** - Cricket is team vs team (mostly)
2. **Add league mapping** - `"ipl": "team_vs_team"`
3. **If new pattern needed** - Create `CricketMatchEvent` dataclass and `CricketPattern` class
4. **Provider normalization** - ESPN/TSDB providers use pattern to know how to normalize
5. **Template variables** - Cricket pattern defines available variables

All in ONE place (the pattern definition). Consumers don't change. Providers just look up the pattern.

---

## Integration Points

### Provider Layer
```python
class ESPNProvider:
    def normalize_event(self, raw: dict, league: str) -> BaseEvent:
        pattern = get_pattern_for_league(league)
        # Pattern tells us which dataclass to create
        # and which fields to extract
        return pattern.normalize(raw, self.name)
```

### Service Layer
```python
class SportsDataService:
    def get_events(self, league: str, date: date) -> list[BaseEvent]:
        # Service doesn't care about pattern
        # Just routes to provider, returns typed events
        provider = self._get_provider(league)
        return provider.get_events(league, date)
```

### Consumer Layer
```python
class TeamEPGGenerator:
    def generate(self, event: BaseEvent) -> Programme:
        pattern = get_pattern_for_event(event)
        variables = pattern.get_template_variables(event)
        duration = pattern.get_duration(event)
        # Generate programme using pattern-provided data
```

---

## Open Questions

1. **Inheritance vs Composition** - Should patterns use inheritance (TeamVsTeamEvent extends BaseEvent) or composition (Event has a PatternData field)?

2. **Multi-pattern sports** - Tennis has both tournaments AND individual matches. Golf has stroke play AND match play. How to handle?

3. **Provider quirks** - ESPN models UFC differently than TSDB. Pattern normalization needs to handle this.

4. **Partial data** - What if a provider doesn't have all fields for a pattern? Graceful degradation?

---

## Implementation Priority

1. **Phase 1 (Current)** - TeamVsTeam pattern only (covers NFL, NBA, NHL, MLB, soccer)
2. **Phase 2** - Add Tournament pattern (golf)
3. **Phase 3** - Add Card pattern (MMA)
4. **Phase 4** - Add Race pattern (motorsports)
5. **Phase 5** - Add IndividualVsIndividual pattern (tennis matches)

For now, we build the registry infrastructure with TeamVsTeam, then expand.
