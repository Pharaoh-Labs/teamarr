# Teamarr v2 - Core Types

> Dataclass definitions for all data structures.

## Design Principles

1. **Attribute access** - `event.home_team.name` not `event['home_team']['name']`
2. **Provider-scoped IDs** - Every entity carries its `id` and `provider`
3. **Optional fields with defaults** - Graceful handling of missing data
4. **Immutable where possible** - Data flows through system unchanged

---

## Team

```python
@dataclass
class Team:
    """Team identity - logo, colors, names."""

    id: str                    # Raw provider ID ("133604")
    provider: str              # "espn" | "thesportsdb"
    name: str                  # Display name ("Detroit Pistons")
    short_name: str            # Short name ("Pistons")
    abbreviation: str          # Abbreviation ("DET")
    league: str                # League identifier ("nba")
    logo_url: Optional[str] = None
    color: Optional[str] = None  # Hex color without # ("0C2340")
```

**Usage:**
```python
team = Team(
    id="8",
    provider="espn",
    name="Detroit Lions",
    short_name="Lions",
    abbreviation="DET",
    league="nfl",
    logo_url="https://a.espncdn.com/i/teamlogos/nfl/500/det.png",
    color="0076B6"
)

# Attribute access
print(f"{team.name} ({team.abbreviation})")  # "Detroit Lions (DET)"
```

---

## Venue

```python
@dataclass
class Venue:
    """Event location."""

    name: str                           # "Ford Field"
    city: Optional[str] = None          # "Detroit"
    state: Optional[str] = None         # "MI"
    country: Optional[str] = None       # "USA"
```

---

## EventStatus

```python
@dataclass
class EventStatus:
    """Current state of an event."""

    state: str                          # "scheduled" | "live" | "final" | "postponed" | "cancelled"
    detail: Optional[str] = None        # "1st Quarter", "Final", "Postponed - Weather"
    period: Optional[int] = None        # Current period/quarter/half
    clock: Optional[str] = None         # Game clock if live ("12:34")
```

**State values:**
| State | Meaning |
|-------|---------|
| `scheduled` | Game hasn't started |
| `live` | Game in progress |
| `final` | Game completed |
| `postponed` | Delayed to future date |
| `cancelled` | Will not be played |

---

## Event

```python
@dataclass
class Event:
    """A single sporting event (game/match)."""

    # Required - Identity
    id: str                    # Raw provider ID ("401547679")
    provider: str              # "espn" | "thesportsdb"
    name: str                  # "Detroit Pistons at Indiana Pacers"
    short_name: str            # "DET @ IND"
    start_time: datetime       # UTC datetime
    home_team: Team
    away_team: Team
    status: EventStatus
    league: str                # Canonical league code ("nba")

    # Optional - Scores
    home_score: Optional[int] = None
    away_score: Optional[int] = None

    # Optional - Context
    venue: Optional[Venue] = None
    broadcasts: List[str] = None       # ["ESPN", "ABC"]
    season_year: Optional[int] = None
    season_type: Optional[str] = None  # "regular" | "postseason" | "preseason"

    def __post_init__(self):
        if self.broadcasts is None:
            self.broadcasts = []
```

**Key properties:**
- `id` + `provider` uniquely identifies an event
- `start_time` is always UTC
- `home_team` and `away_team` are full Team objects, not IDs
- `broadcasts` defaults to empty list, never None

**Usage:**
```python
# Check if team is playing
if team_id in (event.home_team.id, event.away_team.id):
    print(f"Found {team.name} game: {event.name}")

# Check game state
if event.status.state == "live":
    print(f"Score: {event.home_score} - {event.away_score}")
    print(f"Period: {event.status.period}, Clock: {event.status.clock}")

# Get tvg_id for XMLTV
tvg_id = f"teamarr-event-{event.provider}-{event.id}"
```

---

## TeamStats

```python
@dataclass
class TeamStats:
    """Team statistics for template variables."""

    record: str                         # "10-5" or "6-2-4" (W-D-L for soccer)
    home_record: Optional[str] = None   # "6-2"
    away_record: Optional[str] = None   # "4-3"
    streak: Optional[str] = None        # "W3", "L2"
    rank: Optional[int] = None          # For college sports
    conference: Optional[str] = None    # "NFC North"
    division: Optional[str] = None      # "North"
```

**Template usage:**
```python
# Template: "{team_name} ({record}) vs {opponent_name}"
# Result:  "Detroit Lions (10-5) vs Chicago Bears"

if stats.streak:
    print(f"Current streak: {stats.streak}")  # "W3"
```

---

## Programme

```python
@dataclass
class Programme:
    """An XMLTV programme entry."""

    channel_id: str            # tvg-id
    title: str                 # Programme title
    start: datetime            # Start time (UTC)
    stop: datetime             # End time (UTC)

    # Optional
    description: Optional[str] = None
    category: Optional[str] = None     # "Sports"
    icon: Optional[str] = None         # Logo URL
    episode_num: Optional[str] = None  # For series
```

**Generated from Event:**
```python
programme = Programme(
    channel_id=f"teamarr-event-{event.provider}-{event.id}",
    title=f"{event.away_team.abbreviation} @ {event.home_team.abbreviation}",
    start=event.start_time - timedelta(minutes=30),  # Pregame
    stop=event.start_time + timedelta(hours=3),
    description=f"{event.name} on {', '.join(event.broadcasts)}",
    category="Sports",
    icon=event.home_team.logo_url
)
```

---

## MatchResult

```python
@dataclass
class MatchResult:
    """Result of matching a stream to an event."""

    stream_name: str           # Original stream name
    event: Optional[Event]     # Matched event (None if no match)
    confidence: float          # 0.0 to 1.0
    match_method: str          # "exact" | "fuzzy" | "cache" | "schedule"

    # Debug info
    teams_found: List[str] = None      # Teams extracted from stream name
    league_detected: Optional[str] = None

    def __post_init__(self):
        if self.teams_found is None:
            self.teams_found = []
```

---

## ManagedChannel

```python
@dataclass
class ManagedChannel:
    """A dynamically managed channel in Dispatcharr."""

    id: int                    # Database ID
    event_epg_group_id: int    # Parent group
    event_id: str              # Provider's event ID
    event_provider: str        # "espn" | "thesportsdb"
    tvg_id: str                # Unique XMLTV ID
    channel_name: str          # Display name
    channel_number: Optional[str] = None
    logo_url: Optional[str] = None

    # Lifecycle
    created_at: datetime = None
    expires_at: Optional[datetime] = None
    dispatcharr_channel_id: Optional[int] = None
```

---

## GenerationConfig

```python
@dataclass
class GenerationConfig:
    """Configuration for an EPG generation run."""

    # What to generate
    team_epg_enabled: bool = True
    event_epg_enabled: bool = True

    # Time range
    days_ahead: int = 14

    # Behavior
    reconcile_on_generation: bool = True
    push_to_dispatcharr: bool = True

    # Debug
    dry_run: bool = False
    verbose: bool = False
```

---

## GenerationResult

```python
@dataclass
class GenerationResult:
    """Result of an EPG generation run."""

    # Counts
    programmes_generated: int
    teams_processed: int
    events_matched: int
    channels_created: int
    channels_deleted: int

    # Timing
    started_at: datetime
    completed_at: datetime
    duration_seconds: float

    # Cache stats
    cache_hits: int
    cache_misses: int

    # Errors (if any)
    errors: List[str] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
```

---

## Type Relationships

```
Event
├── home_team: Team
├── away_team: Team
├── status: EventStatus
└── venue: Venue

ManagedChannel
└── references Event via (event_id, event_provider)

Programme
└── generated from Event + template

MatchResult
├── event: Event (optional)
└── metadata about matching
```

---

## Serialization

All types can be serialized to JSON for caching:

```python
import json
from dataclasses import asdict
from datetime import datetime

def serialize_event(event: Event) -> str:
    """Serialize event to JSON for caching."""
    data = asdict(event)
    # Convert datetime to ISO format
    data['start_time'] = event.start_time.isoformat()
    return json.dumps(data)

def deserialize_event(json_str: str) -> Event:
    """Deserialize event from JSON."""
    data = json.loads(json_str)
    data['start_time'] = datetime.fromisoformat(data['start_time'])
    data['home_team'] = Team(**data['home_team'])
    data['away_team'] = Team(**data['away_team'])
    data['status'] = EventStatus(**data['status'])
    if data['venue']:
        data['venue'] = Venue(**data['venue'])
    return Event(**data)
```

---

## Validation

Types should validate on construction where practical:

```python
@dataclass
class Event:
    # ... fields ...

    def __post_init__(self):
        if self.broadcasts is None:
            self.broadcasts = []

        # Validate required fields
        if not self.id:
            raise ValueError("Event.id is required")
        if not self.provider:
            raise ValueError("Event.provider is required")
        if self.provider not in ("espn", "thesportsdb"):
            raise ValueError(f"Unknown provider: {self.provider}")
```
