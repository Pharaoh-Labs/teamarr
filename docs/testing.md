# Teamarr v2 - Testing Strategy

> Test pyramid, fixtures, and test organization.

## Test Pyramid

```
                    ┌───────────────┐
                    │  E2E Tests    │  Few, slow, high confidence
                    └───────────────┘
                   ┌─────────────────────┐
                   │  Integration Tests   │  Some, medium speed
                   └─────────────────────┘
              ┌───────────────────────────────┐
              │         Unit Tests            │  Many, fast, focused
              └───────────────────────────────┘
```

| Level | Components | Speed | Count |
|-------|------------|-------|-------|
| **Unit** | Normalizers, types, cache, mappings | Fast (<1s each) | Many |
| **Integration** | Provider flows, service + cache | Medium (1-5s) | Some |
| **E2E** | Full EPG generation, v1 parity | Slow (10-30s) | Few |

---

## Test Organization

```
tests/
├── conftest.py              # Shared fixtures, MockProvider
├── fixtures/                # Captured API responses
│   ├── espn/
│   │   ├── nfl_scoreboard.json
│   │   ├── nfl_scoreboard_no_games.json
│   │   ├── nfl_schedule_lions.json
│   │   ├── nfl_team_lions.json
│   │   ├── nba_scoreboard.json
│   │   ├── malformed_response.json
│   │   └── edge_cases/
│   │       ├── postponed_game.json
│   │       ├── doubleheader.json
│   │       └── tbd_opponent.json
│   └── thesportsdb/
│       ├── events_day.json
│       ├── team_lookup.json
│       └── events_next.json
├── unit/                    # Fast, focused tests
│   ├── test_types.py
│   ├── test_espn_normalizer.py
│   ├── test_tsdb_normalizer.py
│   ├── test_cache.py
│   ├── test_league_mapping.py
│   ├── test_template_engine.py
│   └── test_filler.py
├── integration/             # Multi-component tests
│   ├── test_espn_provider.py
│   ├── test_tsdb_provider.py
│   ├── test_sports_service.py
│   ├── test_soccer_composite.py
│   ├── test_team_epg_consumer.py
│   └── test_event_epg_consumer.py
└── e2e/                     # Full system tests
    ├── test_epg_generation.py
    └── test_feature_parity.py  # Compare v2 output to v1
```

---

## Unit Tests

### What to Test

| Component | Test Focus |
|-----------|------------|
| **Normalizers** | Field extraction, edge cases, malformed data |
| **Types** | Dataclass construction, validation, serialization |
| **Cache** | Hit/miss, TTL, thread safety |
| **Mappings** | League → provider routing |
| **Template Engine** | Variable substitution, conditionals |
| **Filler Generator** | Pregame/postgame programme creation |

### Normalizer Tests

```python
# tests/unit/test_espn_normalizer.py

import json
import pytest
from pathlib import Path
from teamarr.providers.espn.normalizer import ESPNNormalizer
from teamarr.core.types import Event, Team, EventStatus

FIXTURES = Path(__file__).parent.parent / "fixtures" / "espn"

class TestESPNNormalizer:
    def setup_method(self):
        self.normalizer = ESPNNormalizer()

    def test_normalize_event_basic(self):
        """Test normalizing a standard NFL event."""
        with open(FIXTURES / "nfl_scoreboard.json") as f:
            data = json.load(f)

        raw_event = data["events"][0]
        event = self.normalizer.normalize_event(raw_event, "nfl")

        assert event is not None
        assert event.provider == "espn"
        assert event.league == "nfl"
        assert isinstance(event.home_team, Team)
        assert isinstance(event.away_team, Team)
        assert isinstance(event.status, EventStatus)

    def test_normalize_event_missing_venue(self):
        """Test handling event without venue data."""
        raw_event = {
            "id": "12345",
            "name": "Test Game",
            "date": "2024-12-08T18:00Z",
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"id": "1", "name": "Home Team"}},
                    {"homeAway": "away", "team": {"id": "2", "name": "Away Team"}},
                ]
                # No venue field
            }],
            "status": {"type": {"state": "pre"}}
        }

        event = self.normalizer.normalize_event(raw_event, "nfl")

        assert event is not None
        assert event.venue is None  # Gracefully handles missing venue

    def test_normalize_event_malformed_returns_none(self):
        """Test that malformed data returns None, not exception."""
        with open(FIXTURES / "malformed_response.json") as f:
            data = json.load(f)

        event = self.normalizer.normalize_event(data, "nfl")
        assert event is None

    def test_normalize_team_extracts_all_fields(self):
        """Test team normalization extracts all available fields."""
        raw_team = {
            "id": "8",
            "displayName": "Detroit Lions",
            "shortDisplayName": "Lions",
            "abbreviation": "DET",
            "logo": "https://example.com/logo.png",
            "color": "0076B6"
        }

        team = self.normalizer.normalize_team(raw_team, "nfl")

        assert team.id == "8"
        assert team.provider == "espn"
        assert team.name == "Detroit Lions"
        assert team.short_name == "Lions"
        assert team.abbreviation == "DET"
        assert team.logo_url == "https://example.com/logo.png"
        assert team.color == "0076B6"

    @pytest.mark.parametrize("status_state,expected", [
        ("pre", "scheduled"),
        ("in", "live"),
        ("post", "final"),
        ("postponed", "postponed"),
        ("canceled", "cancelled"),
    ])
    def test_normalize_status_mapping(self, status_state, expected):
        """Test status state mapping."""
        raw_status = {"type": {"state": status_state}}
        status = self.normalizer._normalize_status(raw_status)
        assert status.state == expected
```

### Cache Tests

```python
# tests/unit/test_cache.py

import pytest
from threading import Thread
from teamarr.services.cache import SportsDataCache

class TestSportsDataCache:
    def test_get_miss_returns_none(self):
        cache = SportsDataCache()
        result = cache.get(("events", "espn", "nfl", "2024-12-08"))
        assert result is None
        assert cache.misses == 1

    def test_set_and_get(self):
        cache = SportsDataCache()
        key = ("events", "espn", "nfl", "2024-12-08")
        value = [{"id": "123"}]

        cache.set(key, value)
        result = cache.get(key)

        assert result == value
        assert cache.hits == 1

    def test_clear_returns_stats(self):
        cache = SportsDataCache()
        cache.set(("a",), 1)
        cache.set(("b",), 2)
        cache.get(("a",))  # Hit
        cache.get(("c",))  # Miss

        stats = cache.clear()

        assert stats["size"] == 2
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_thread_safety(self):
        """Test cache is thread-safe."""
        cache = SportsDataCache()
        errors = []

        def writer():
            for i in range(100):
                cache.set((f"key-{i}",), i)

        def reader():
            for i in range(100):
                try:
                    cache.get((f"key-{i}",))
                except Exception as e:
                    errors.append(e)

        threads = [
            Thread(target=writer),
            Thread(target=reader),
            Thread(target=writer),
            Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
```

---

## Integration Tests

### What to Test

| Component | Test Focus |
|-----------|------------|
| **Provider** | Full flow: client → normalizer → dataclass |
| **Service** | Routing, caching, fallback |
| **Consumers** | Full generation with mock service |

### Provider Integration Tests

```python
# tests/integration/test_espn_provider.py

import pytest
from datetime import date
from unittest.mock import Mock, patch
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.core.types import Event, Team

class TestESPNProvider:
    def setup_method(self):
        self.provider = ESPNProvider()

    def test_supports_nfl(self):
        assert self.provider.supports_league("nfl") is True

    def test_does_not_support_unknown(self):
        assert self.provider.supports_league("unknown-league") is False

    @patch.object(ESPNProvider, '_client')
    def test_get_events_returns_events(self, mock_client):
        """Test get_events with mocked HTTP."""
        # Load fixture
        with open("tests/fixtures/espn/nfl_scoreboard.json") as f:
            mock_client.get_scoreboard.return_value = json.load(f)

        events = self.provider.get_events("nfl", date(2024, 12, 8))

        assert len(events) > 0
        assert all(isinstance(e, Event) for e in events)
        assert all(e.provider == "espn" for e in events)
        assert all(e.league == "nfl" for e in events)

    @patch.object(ESPNProvider, '_client')
    def test_get_events_empty_on_no_games(self, mock_client):
        """Test get_events returns empty list when no games."""
        mock_client.get_scoreboard.return_value = {"events": []}

        events = self.provider.get_events("nfl", date(2024, 7, 15))

        assert events == []

    @patch.object(ESPNProvider, '_client')
    def test_get_events_handles_api_failure(self, mock_client):
        """Test get_events returns empty list on API failure."""
        mock_client.get_scoreboard.return_value = None

        events = self.provider.get_events("nfl", date(2024, 12, 8))

        assert events == []  # Graceful degradation
```

### Service Integration Tests

```python
# tests/integration/test_sports_service.py

import pytest
from datetime import date
from teamarr.services.sports_data import SportsDataService
from tests.conftest import MockProvider

class TestSportsDataService:
    def test_routes_to_correct_provider(self):
        """Test that NFL routes to ESPN, AHL to TSDB."""
        espn = MockProvider("espn").add_league("nfl")
        tsdb = MockProvider("thesportsdb").add_league("ahl")

        service = SportsDataService(providers=[espn, tsdb])

        # Should route to ESPN
        service.get_events("nfl", date(2024, 12, 8))
        assert espn.get_events_called
        assert not tsdb.get_events_called

        espn.reset()
        tsdb.reset()

        # Should route to TSDB
        service.get_events("ahl", date(2024, 12, 8))
        assert not espn.get_events_called
        assert tsdb.get_events_called

    def test_caches_results(self):
        """Test that repeated calls use cache."""
        provider = MockProvider("espn").add_league("nfl")
        service = SportsDataService(providers=[provider])

        # First call
        service.get_events("nfl", date(2024, 12, 8))
        assert provider.call_count == 1

        # Second call - should use cache
        service.get_events("nfl", date(2024, 12, 8))
        assert provider.call_count == 1  # No additional calls

    def test_fallback_on_primary_failure(self):
        """Test fallback when primary provider fails."""
        espn = MockProvider("espn").add_league("nfl").set_failure(True)
        tsdb = MockProvider("thesportsdb").add_league("nfl")

        service = SportsDataService(providers=[espn, tsdb])
        events = service.get_events("nfl", date(2024, 12, 8))

        # Should have tried ESPN, fallen back to TSDB
        assert espn.get_events_called
        assert tsdb.get_events_called
```

---

## E2E Tests

### Feature Parity Test

```python
# tests/e2e/test_feature_parity.py

import pytest
from teamarr.consumers.orchestrator import EPGOrchestrator
from teamarr.config import GenerationConfig

class TestFeatureParity:
    """Compare v2 output to v1 for same inputs."""

    @pytest.fixture
    def v1_output(self):
        """Load v1's generated XMLTV for comparison."""
        with open("tests/fixtures/v1_teams.xml") as f:
            return f.read()

    def test_team_epg_matches_v1(self, v1_output):
        """Test that v2 team EPG output matches v1."""
        config = GenerationConfig(
            team_epg_enabled=True,
            event_epg_enabled=False,
            push_to_dispatcharr=False,
        )

        orchestrator = EPGOrchestrator(config)
        result = orchestrator.run()

        # Parse both XMLs and compare programmes
        v1_programmes = parse_xmltv(v1_output)
        v2_programmes = result.programmes

        # Compare key attributes
        for v1_prog, v2_prog in zip(v1_programmes, v2_programmes):
            assert v1_prog.channel_id == v2_prog.channel_id
            assert v1_prog.title == v2_prog.title
            assert abs((v1_prog.start - v2_prog.start).seconds) < 60
```

---

## Test Fixtures

### Capturing Fixtures

```bash
# Capture ESPN scoreboard
curl "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=20241208" \
    > tests/fixtures/espn/nfl_scoreboard.json

# Capture ESPN team schedule
curl "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/8/schedule" \
    > tests/fixtures/espn/nfl_schedule_lions.json

# Capture TheSportsDB events
curl "https://www.thesportsdb.com/api/v1/json/3/eventsday.php?d=2024-12-08&l=4391" \
    > tests/fixtures/thesportsdb/events_day.json
```

### Fixture Guidelines

1. **Real responses** - Capture actual API responses, not hand-crafted
2. **Edge cases** - Include postponed games, doubleheaders, TBD opponents
3. **Minimal** - Remove unnecessary fields to keep fixtures readable
4. **Versioned** - Update when API changes

---

## Mock Provider

```python
# tests/conftest.py

from teamarr.core.interfaces import SportsProvider
from teamarr.core.types import Event, Team, TeamStats

class MockProvider(SportsProvider):
    """Configurable mock for testing."""

    def __init__(self, name: str = "mock"):
        self._name = name
        self._events: Dict[Tuple[str, date], List[Event]] = {}
        self._teams: Dict[str, Team] = {}
        self._supported_leagues: Set[str] = set()
        self._should_fail = False

        # Call tracking
        self.get_events_called = False
        self.call_count = 0

    # Fluent configuration
    def add_league(self, league: str) -> "MockProvider":
        self._supported_leagues.add(league)
        return self

    def add_events(self, league: str, dt: date, events: List[Event]) -> "MockProvider":
        self._events[(league, dt)] = events
        return self

    def set_failure(self, should_fail: bool) -> "MockProvider":
        self._should_fail = should_fail
        return self

    def reset(self):
        self.get_events_called = False
        self.call_count = 0

    # SportsProvider implementation
    @property
    def name(self) -> str:
        return self._name

    def supports_league(self, league: str) -> bool:
        return league in self._supported_leagues

    def get_events(self, league: str, date: date) -> List[Event]:
        self.get_events_called = True
        self.call_count += 1

        if self._should_fail:
            return []

        return self._events.get((league, date), [])

    def get_team_schedule(self, team_id: str, league: str,
                          days_ahead: int = 14) -> List[Event]:
        return []

    def get_team(self, team_id: str, league: str) -> Optional[Team]:
        return self._teams.get(team_id)

    def get_event(self, event_id: str, league: str) -> Optional[Event]:
        return None
```

---

## Running Tests

```bash
# Run all tests
pytest

# Run unit tests only (fast)
pytest tests/unit/

# Run integration tests
pytest tests/integration/

# Run with coverage
pytest --cov=teamarr --cov-report=html

# Run specific test file
pytest tests/unit/test_espn_normalizer.py

# Run specific test
pytest tests/unit/test_espn_normalizer.py::TestESPNNormalizer::test_normalize_event_basic

# Run tests matching pattern
pytest -k "normalizer"

# Verbose output
pytest -v
```

---

## CI Integration

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pip install pytest pytest-cov
      - run: pytest --cov=teamarr --cov-report=xml
      - uses: codecov/codecov-action@v3
```
