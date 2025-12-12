# Sport Pattern Definitions

> Canonical definitions for each sport pattern. Single source of truth.

## Overview

**5 patterns cover ~99% of all sports broadcasts.**

| # | Pattern | Description | Example Sports |
|---|---------|-------------|----------------|
| 1 | **team_vs_team** | 2 teams compete | Football, Basketball, Hockey, Soccer, Baseball, Rugby, Cricket, Esports |
| 2 | **individual** | 2 individuals compete | Tennis matches (if API returns match-level), Olympic bracket matches |
| 3 | **tournament** | Field + scoring/leaderboard | Golf, Tennis broadcasts, Diving, Gymnastics, Poker, Darts, Bull Riding |
| 4 | **card** | Multi-bout event | UFC, Boxing PPV, WWE, Bellator, PFL |
| 5 | **race** | Field + positional finish | F1, NASCAR, IndyCar, Swimming, Track, Cycling, Horse Racing |

### Coverage Analysis

| Sport Category | Pattern | Notes |
|----------------|---------|-------|
| Team ball sports | team_vs_team | All leagues |
| Combat sports (full cards) | card | UFC, Boxing PPV, WWE |
| Combat sports (single bout TBD) | individual | Reserved for API unknowns |
| Golf | tournament | Stroke play, leaderboard |
| Tennis (broadcast level) | tournament | "Wimbledon Day 5" |
| Tennis (match level) | individual | "Djokovic vs Alcaraz" - TBD based on API |
| Motorsports | race | All series |
| Olympic races | race | Swimming, track, cycling |
| Olympic judged | tournament | Gymnastics, diving, skating (leaderboard) |
| Olympic team sports | team_vs_team | Basketball, soccer, hockey |
| Poker/Darts | tournament | Eliminations, chip counts |
| Bull Riding/Rodeo | tournament | Ride scores, leaderboard |
| College dual meets | team_vs_team | "Michigan vs Ohio State" |
| Esports | team_vs_team | Teams of 5, still 2-sided |

### Why Individual Pattern Exists

**individual** is insurance for API unknowns. May never be used, but:
- Tennis match-level data might return participant details
- Some combat sport APIs might return single bouts
- Cost of keeping: minimal (one dataclass)
- Risk of removing: potential future refactor

If API data fits team_vs_team or card, use those instead.

---

## Pattern 1: TeamVsTeam

**Sports:** NFL, NBA, NHL, MLB, Soccer, College sports, Rugby, Cricket

### Event Dataclass

```python
@dataclass
class TeamVsTeamEvent(BaseEvent):
    home_team: Team
    away_team: Team
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    period: Optional[str] = None          # "Q4", "3rd", "Final"
    clock: Optional[str] = None           # "2:34"
    possession: Optional[str] = None      # "home" | "away"
    situation: Optional[str] = None       # "1st & 10 at DET 25"
```

### Template Variables

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `{home_team}` | str | Home team name | "Detroit Lions" |
| `{home_team_abbrev}` | str | Home team abbreviation | "DET" |
| `{home_team_logo}` | str | Home team logo URL | "https://..." |
| `{home_team_color}` | str | Home team primary color | "#0076B6" |
| `{home_score}` | int | Home team score | 27 |
| `{away_team}` | str | Away team name | "Chicago Bears" |
| `{away_team_abbrev}` | str | Away team abbreviation | "CHI" |
| `{away_team_logo}` | str | Away team logo URL | "https://..." |
| `{away_team_color}` | str | Away team primary color | "#0B162A" |
| `{away_score}` | int | Away team score | 24 |
| `{period}` | str | Current period | "4th Quarter" |
| `{clock}` | str | Game clock | "2:34" |
| `{situation}` | str | Current situation (football) | "1st & 10" |

### Duration Defaults

| Sport | Default Duration |
|-------|------------------|
| NFL | 3.5 hours |
| NBA | 2.5 hours |
| NHL | 2.5 hours |
| MLB | 3.5 hours |
| Soccer | 2 hours |
| College Football | 3.5 hours |
| College Basketball | 2.5 hours |

### Normalization (ESPN)

```python
def normalize_team_vs_team(raw: dict) -> TeamVsTeamEvent:
    competition = raw["competitions"][0]
    home = next(c for c in competition["competitors"] if c["homeAway"] == "home")
    away = next(c for c in competition["competitors"] if c["homeAway"] == "away")

    return TeamVsTeamEvent(
        id=raw["id"],
        provider="espn",
        name=raw["name"],
        short_name=raw["shortName"],
        start_time=parse_espn_date(raw["date"]),
        status=map_status(raw["status"]["type"]["name"]),
        league=league,
        sport=sport,
        venue=extract_venue(competition),
        broadcasts=extract_broadcasts(competition),
        home_team=normalize_team(home),
        away_team=normalize_team(away),
        home_score=parse_score(home.get("score")),
        away_score=parse_score(away.get("score")),
    )
```

---

## Pattern 2: Individual

**Sports:** Tennis (matches), Boxing (single bout), Wrestling, Badminton, Table Tennis

### Event Dataclass

```python
@dataclass
class Participant:
    id: str
    provider: str
    name: str
    short_name: Optional[str] = None
    country: Optional[str] = None
    ranking: Optional[int] = None
    seed: Optional[int] = None
    image_url: Optional[str] = None

@dataclass
class IndividualEvent(BaseEvent):
    participant_1: Participant          # Often higher seed / home
    participant_2: Participant
    score_1: Optional[str] = None       # "6-4, 6-3" or "KO R3"
    score_2: Optional[str] = None
    current_set: Optional[int] = None   # Tennis
    round_name: Optional[str] = None    # "Quarterfinal", "Round of 16"
```

### Template Variables

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `{participant_1}` | str | First participant name | "Novak Djokovic" |
| `{participant_1_country}` | str | Country code | "SRB" |
| `{participant_1_ranking}` | int | World ranking | 1 |
| `{participant_1_seed}` | int | Tournament seed | 1 |
| `{participant_2}` | str | Second participant name | "Carlos Alcaraz" |
| `{participant_2_country}` | str | Country code | "ESP" |
| `{participant_2_ranking}` | int | World ranking | 2 |
| `{participant_2_seed}` | int | Tournament seed | 2 |
| `{score_1}` | str | P1 score | "6-4, 6-3" |
| `{score_2}` | str | P2 score | "4-6, 3-6" |
| `{round_name}` | str | Tournament round | "Semifinal" |
| `{matchup}` | str | Formatted matchup | "Djokovic vs Alcaraz" |

### Duration Defaults

| Sport | Default Duration |
|-------|------------------|
| Tennis (best of 3) | 2 hours |
| Tennis (best of 5) | 3.5 hours |
| Boxing (single bout) | 1 hour |

### Normalization Notes

- ESPN tennis uses `competitors` array with `athlete` nested object
- Rankings/seeds in `competitor.curatedRank` or similar
- Score format varies wildly by sport

---

## Pattern 3: Tournament

**Sports:** Golf (PGA, LPGA), Tennis majors (the tournament itself, not matches)

### Event Dataclass

```python
@dataclass
class TournamentParticipant:
    id: str
    provider: str
    name: str
    position: Optional[int] = None      # Current leaderboard position
    score: Optional[str] = None         # "-12", "E", "+3"
    today: Optional[str] = None         # Today's round score
    thru: Optional[str] = None          # "F", "12", "—"

@dataclass
class TournamentEvent(BaseEvent):
    participants: list[TournamentParticipant]
    current_round: Optional[int] = None
    total_rounds: int = 4
    purse: Optional[str] = None
    defending_champion: Optional[str] = None
    cut_line: Optional[str] = None      # "E", "+2"
    course_par: Optional[int] = None
```

### Template Variables

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `{event_name}` | str | Tournament name | "The Masters" |
| `{round}` | int | Current round | 3 |
| `{total_rounds}` | int | Total rounds | 4 |
| `{round_name}` | str | Round name | "Third Round" |
| `{leader}` | str | Current leader | "Scottie Scheffler" |
| `{leader_score}` | str | Leader's score | "-12" |
| `{cut_line}` | str | Cut line | "+2" |
| `{purse}` | str | Prize purse | "$20,000,000" |
| `{defending_champion}` | str | Last year's winner | "Jon Rahm" |
| `{field_size}` | int | Number of participants | 156 |

### Duration Defaults

| Sport | Default Duration |
|-------|------------------|
| Golf (daily coverage) | 8 hours |
| Golf (featured groups) | 4 hours |

### Multi-Day Handling

Tournaments span multiple days. EPG options:
1. **One programme per day** - "The Masters - Round 3"
2. **Coverage blocks** - "Masters Morning Coverage", "Masters Afternoon Coverage"
3. **Featured content** - "Featured Groups", "Amen Corner Coverage"

Template config determines which approach.

---

## Pattern 4: Card

**Sports:** MMA (UFC, PFL, Bellator), Boxing cards, Wrestling (WWE events)

### Event Dataclass

```python
@dataclass
class Fighter:
    id: str
    provider: str
    name: str
    nickname: Optional[str] = None
    record: Optional[str] = None        # "23-1-0"
    weight_class: Optional[str] = None
    ranking: Optional[int] = None       # Division ranking
    country: Optional[str] = None
    image_url: Optional[str] = None

@dataclass
class Bout:
    bout_order: int                     # 1 = first, higher = later
    fighter_1: Fighter
    fighter_2: Fighter
    weight_class: str
    is_main_event: bool = False
    is_title_fight: bool = False
    scheduled_rounds: int = 3           # 3 or 5
    result: Optional[str] = None        # "KO", "SUB", "DEC"
    winner: Optional[str] = None        # fighter_1.id or fighter_2.id

@dataclass
class CardEvent(BaseEvent):
    bouts: list[Bout]
    main_event: Optional[Bout] = None
    co_main_event: Optional[Bout] = None
    card_type: Optional[str] = None     # "PPV", "Fight Night", "Prelims"
    early_prelims_start: Optional[datetime] = None
    prelims_start: Optional[datetime] = None
    main_card_start: Optional[datetime] = None
```

### Template Variables

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `{event_name}` | str | Card name | "UFC 300" |
| `{card_type}` | str | Card type | "Pay-Per-View" |
| `{main_event}` | str | Main event matchup | "Pereira vs Hill" |
| `{main_event_fighter_1}` | str | Main event fighter 1 | "Alex Pereira" |
| `{main_event_fighter_2}` | str | Main event fighter 2 | "Jamahal Hill" |
| `{main_event_weight_class}` | str | Weight class | "Light Heavyweight" |
| `{main_event_title_fight}` | bool | Is title fight | true |
| `{co_main_event}` | str | Co-main matchup | "Holloway vs Gaethje" |
| `{bout_count}` | int | Total bouts | 14 |
| `{title_fights}` | int | Number of title fights | 3 |

### Duration Defaults

| Card Type | Default Duration |
|-----------|------------------|
| UFC PPV (full card) | 6 hours |
| UFC Main Card only | 3 hours |
| UFC Prelims | 2 hours |
| UFC Early Prelims | 1.5 hours |
| Boxing PPV | 4 hours |

### Multi-Segment Handling

MMA cards have segments (early prelims → prelims → main card). EPG options:
1. **One programme for full card** - 6 hour block
2. **Separate programmes per segment** - 3 programmes
3. **Main card only** - ignore prelims

Template config determines which approach.

---

## Pattern 5: Race

**Sports:** F1, NASCAR, IndyCar, MotoGP, Horse Racing

### Event Dataclass

```python
@dataclass
class Driver:
    id: str
    provider: str
    name: str
    number: Optional[str] = None        # Car number
    team: Optional[str] = None          # Constructor/team name
    country: Optional[str] = None
    image_url: Optional[str] = None

@dataclass
class RaceParticipant:
    driver: Driver
    position: Optional[int] = None
    grid_position: Optional[int] = None # Starting position
    laps_completed: Optional[int] = None
    gap_to_leader: Optional[str] = None # "+5.234s", "+1 LAP"
    status: Optional[str] = None        # "Running", "DNF", "DNS"

@dataclass
class RaceEvent(BaseEvent):
    participants: list[RaceParticipant]
    laps: Optional[int] = None          # Total laps
    current_lap: Optional[int] = None
    race_type: Optional[str] = None     # "Race", "Qualifying", "Practice"
    track: Optional[str] = None         # Track name
    track_length: Optional[str] = None  # "5.412 km"
    weather: Optional[str] = None
    pole_position: Optional[Driver] = None
    fastest_lap: Optional[Driver] = None
```

### Template Variables

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `{event_name}` | str | Race name | "Monaco Grand Prix" |
| `{race_type}` | str | Session type | "Race" |
| `{track}` | str | Track name | "Circuit de Monaco" |
| `{laps}` | int | Total laps | 78 |
| `{current_lap}` | int | Current lap | 45 |
| `{leader}` | str | Current leader | "Max Verstappen" |
| `{leader_team}` | str | Leader's team | "Red Bull Racing" |
| `{pole_position}` | str | Pole sitter | "Charles Leclerc" |
| `{fastest_lap}` | str | Fastest lap holder | "Lewis Hamilton" |
| `{field_size}` | int | Number of cars | 20 |
| `{weather}` | str | Conditions | "Partly Cloudy" |

### Duration Defaults

| Session | Default Duration |
|---------|------------------|
| F1 Race | 2 hours |
| F1 Qualifying | 1 hour |
| F1 Practice | 1 hour |
| NASCAR Race | 3.5 hours |
| IndyCar Race | 2.5 hours |

### Multi-Session Handling

Race weekends have multiple sessions (Practice 1, 2, 3, Qualifying, Sprint, Race). Each is a separate event with `race_type` indicating session type.

---

## Common Fields (BaseEvent)

All patterns inherit these:

```python
@dataclass
class BaseEvent:
    # Identity
    id: str
    provider: str

    # Basic info
    name: str
    short_name: str
    start_time: datetime
    status: EventStatus
    league: str
    sport: str

    # Optional common
    venue: Optional[Venue] = None
    broadcasts: list[str] = field(default_factory=list)

    # Metadata
    season_year: Optional[int] = None
    season_type: Optional[str] = None   # "regular", "postseason"
    week: Optional[int] = None          # Week number if applicable
```

### Common Template Variables

Available for ALL patterns:

| Variable | Type | Description |
|----------|------|-------------|
| `{event_name}` | str | Event name |
| `{short_name}` | str | Short name |
| `{venue}` | str | Venue name |
| `{venue_city}` | str | Venue city |
| `{venue_full}` | str | Full venue string |
| `{start_time}` | datetime | Start time |
| `{start_date}` | str | Formatted date |
| `{start_time_local}` | str | Formatted time |
| `{league}` | str | League code |
| `{league_name}` | str | League name |
| `{sport}` | str | Sport |
| `{broadcasts}` | str | Broadcast networks |
| `{status}` | str | Event status |

---

## League → Pattern Mapping

```python
LEAGUE_PATTERNS = {
    # TeamVsTeam
    "nfl": "team_vs_team",
    "nba": "team_vs_team",
    "wnba": "team_vs_team",
    "nhl": "team_vs_team",
    "mlb": "team_vs_team",
    "mls": "team_vs_team",
    "eng.1": "team_vs_team",
    "esp.1": "team_vs_team",
    # ... all soccer leagues
    "college-football": "team_vs_team",
    "mens-college-basketball": "team_vs_team",

    # Individual
    "atp": "individual",
    "wta": "individual",

    # Tournament
    "pga": "tournament",
    "lpga": "tournament",
    "european-tour": "tournament",

    # Card
    "ufc": "card",
    "pfl": "card",
    "bellator": "card",
    "boxing": "card",
    "wwe": "card",

    # Race
    "f1": "race",
    "nascar": "race",
    "indycar": "race",
    "motogp": "race",
}

def get_pattern(league: str) -> str:
    """Get pattern for league. Defaults to team_vs_team."""
    return LEAGUE_PATTERNS.get(league, "team_vs_team")
```

---

## Template Structure

Single template with pattern-keyed sections:

```yaml
name: "My EPG Template"

title:
  team_vs_team: "{away_team} at {home_team}"
  individual: "{participant_1} vs {participant_2}"
  tournament: "{event_name} - {round_name}"
  card: "{event_name}"
  race: "{event_name} - {race_type}"
  default: "{event_name}"

subtitle:
  team_vs_team: "{venue_full}"
  individual: "{round_name}"
  tournament: "Round {round} of {total_rounds}"
  card: "{main_event}"
  race: "{track}"
  default: ""

description:
  team_vs_team: "{away_team} ({away_team_abbrev}) visits {home_team} ({home_team_abbrev}) at {venue}."
  individual: "{participant_1} ({participant_1_country}) faces {participant_2} ({participant_2_country}) in the {round_name}."
  tournament: "Coverage of {event_name}. Current leader: {leader} ({leader_score})."
  card: "{event_name} featuring {bout_count} bouts. Main event: {main_event}."
  race: "{event_name} at {track}. {laps} laps."
  default: "{event_name}"

duration:
  # Override defaults per league if needed
  nfl: 210  # 3.5 hours in minutes
  mlb: 210
  ufc: 360  # 6 hours for full card
```

---

## Adding a New Sport

Example: Adding Cricket

1. **Determine pattern** - Cricket is `team_vs_team` (mostly)
2. **Add to mapping:**
   ```python
   "ipl": "team_vs_team",
   "bbl": "team_vs_team",
   ```
3. **Add duration default:**
   ```python
   "ipl": 180,  # 3 hours for T20
   ```
4. **Done** - No new code, just config

Example: Adding a NEW pattern (esports with teams of 5)

1. **Create dataclass:**
   ```python
   @dataclass
   class EsportsEvent(BaseEvent):
       team_1: Team
       team_2: Team
       game: str  # "League of Legends", "CS2"
       map_score: Optional[str] = None  # "2-1"
   ```
2. **Define variables** - Add to this doc
3. **Add to mapping:**
   ```python
   "lol": "esports",
   "csgo": "esports",
   ```
4. **Update template engine** to handle new pattern
