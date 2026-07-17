"""TSDB provider tests — racing grouping, season fallback, reload, prewarm.

Merged from four per-concern files (iua3.5 step 4); original docstrings kept
as section comments.
"""

import contextlib
import sqlite3
import threading
from datetime import date
from unittest.mock import MagicMock

from teamarr.consumers.cache.refresh import CacheRefresher
from teamarr.providers.registry import ProviderConfig, ProviderRegistry
from teamarr.providers.tsdb.provider import TSDBProvider
from teamarr.providers.tsdb.racing import parse_racing_events
from tests.helpers import SCHEMA_PATH

# ===========================================================================
# Racing event grouping & session classification
# ===========================================================================
# Tests for TSDB racing event grouping (WEC, IMSA).
#
# TheSportsDB models a race weekend as several flat per-session events sharing
# a (strSeason, intRound). `parse_racing_events` groups these into a single
# multi-session `Event`, mirroring the ESPN racing pipeline's shape.


def _event(
    event_id, name, date_str, time_str, round_,
    season="2026", venue="Circuit de la Sarthe", country="France",
):
    return {
        "idEvent": event_id,
        "strEvent": name,
        "dateEvent": date_str,
        "strTime": time_str,
        "strTimestamp": None,
        "strSeason": season,
        "intRound": round_,
        "strVenue": venue,
        "strCity": None,
        "strCountry": country,
    }


# A WEC round with FP1-3, two class-specific Hyperpole Qualifying sessions,
# two class-specific Hyperpole sessions per class, and the race itself.
WEC_ROUND = [
    _event("1", "24 Hours of Le Mans Free Practice 1", "2026-06-10", "12:00:00", "3"),
    _event("2", "24 Hours of Le Mans Free Practice 2", "2026-06-10", "20:00:00", "3"),
    _event("3", "24 Hours of Le Mans Free Practice 3", "2026-06-11", "12:45:00", "3"),
    _event(
        "4", "24 Hours of Le Mans Hyperpole Qualifying – LMP2 & LMGT3",
        "2026-06-10", "16:45:00", "3",
    ),
    _event(
        "5", "24 Hours of Le Mans Hyperpole Qualifying – Hypercar",
        "2026-06-10", "17:30:00", "3",
    ),
    _event("6", "24 Hours of Le Mans Hyperpole 1 - LMP2 & LMGT3", "2026-06-11", "18:00:00", "3"),
    _event("7", "24 Hours of Le Mans Hyperpole 1 - Hypercar", "2026-06-11", "19:05:00", "3"),
    _event("8", "24 Hours of Le Mans", "2026-06-13", "10:00:00", "3"),
]

# A round-500 "Prologue" weekend with only Morning/Afternoon sessions - no
# event in the group qualifies as "the race".
WEC_PROLOGUE = [
    _event(
        "10", "Imola Prologue Morning Session", "2026-04-14", "07:00:00", "500",
        venue="Imola Circuit", country="Italy",
    ),
    _event(
        "11", "Imola Prologue Afternoon Session", "2026-04-14", "12:00:00", "500",
        venue="Imola Circuit", country="Italy",
    ),
]

# IMSA: one event per round, no session suffix.
IMSA_ROUND = [
    _event(
        "20", "Rolex 24 At DAYTONA", "2026-01-25", "00:00:00", "1",
        venue="Daytona International Speedway", country="USA",
    ),
]


def test_wec_round_session_codes_and_race_identification():
    events = parse_racing_events(WEC_ROUND, "wec", "racing", "tsdb")
    assert len(events) == 1

    event = events[0]
    assert event.id == "tsdb_wec_2026_3"
    assert event.name == "24 Hours of Le Mans"
    assert event.circuit_name == "Circuit de la Sarthe"

    sessions_by_code = {s.code: s for s in event.sessions}
    assert sessions_by_code["fp1"].name == "Practice 1"
    assert sessions_by_code["fp2"].name == "Practice 2"
    assert sessions_by_code["fp3"].name == "Practice 3"
    assert sessions_by_code["qualifying_lmp2_lmgt3"].name == "Qualifying - LMP2 & LMGT3"
    assert sessions_by_code["qualifying_hypercar"].name == "Qualifying - Hypercar"
    assert sessions_by_code["hyperpole_1_lmp2_lmgt3"].name == "Hyperpole 1 - LMP2 & LMGT3"
    assert sessions_by_code["hyperpole_1_hypercar"].name == "Hyperpole 1 - Hypercar"
    assert sessions_by_code["race"].name == "Race"

    # Sessions are ordered by start time, race last
    assert event.sessions[-1].code == "race"


def test_wec_prologue_round_with_no_race_event():
    events = parse_racing_events(WEC_PROLOGUE, "wec", "racing", "tsdb")
    assert len(events) == 1

    event = events[0]
    assert event.id == "tsdb_wec_2026_500"
    # No session matched "race" since neither event qualified
    codes = [s.code for s in event.sessions]
    assert "race" not in codes
    assert codes == ["prologue_am", "prologue_pm"]
    assert event.sessions[0].name == "Prologue (AM)"
    assert event.sessions[1].name == "Prologue (PM)"
    # Falls back to the chronologically-last event for name/venue
    assert event.name == "Imola Prologue Afternoon Session"
    assert event.circuit_name == "Imola Circuit"


def test_imsa_round_single_race_session():
    events = parse_racing_events(IMSA_ROUND, "imsa", "racing", "tsdb")
    assert len(events) == 1

    event = events[0]
    assert event.id == "tsdb_imsa_2026_1"
    assert event.name == "Rolex 24 At DAYTONA"
    assert len(event.sessions) == 1
    assert event.sessions[0].code == "race"
    assert event.sessions[0].name == "Race"


def test_get_events_filters_by_session_date():
    client = MagicMock()
    client.get_sport.return_value = "racing"
    client.get_events_by_season.return_value = {"events": WEC_ROUND}

    provider = TSDBProvider(client=client)

    # FP1/Hyperpole Qualifying sessions are on 2026-06-10
    events = provider.get_events("wec", date(2026, 6, 10))
    assert len(events) == 1
    assert events[0].id == "tsdb_wec_2026_3"

    # The race session is on 2026-06-13 - same Event returned for that date too
    events = provider.get_events("wec", date(2026, 6, 13))
    assert len(events) == 1
    assert events[0].id == "tsdb_wec_2026_3"

    # No sessions on this date
    events = provider.get_events("wec", date(2026, 7, 1))
    assert events == []


# ===========================================================================
# Season fallback when day endpoints are empty
# ===========================================================================
# Regression tests for GH #217 — TSDB season-fallback gating.
#
# The dead `eventsround.php` fallback fired for every league on every empty
# date, producing a 404 storm that hung the Event Group preview. The fallback
# is now `eventsseason.php`, gated to SEASON_FALLBACK_LEAGUES, so ordinary
# leagues (e.g. CFL) with empty individual dates short-circuit to [].


def _provider_with_empty_day_endpoints():
    """Provider whose day/next endpoints return no events."""
    client = MagicMock()
    client.get_events_by_date.return_value = {"events": []}
    client.get_league_next_events.return_value = {"events": []}
    client.get_events_by_season.return_value = {"events": []}
    return TSDBProvider(client=client), client


def test_non_fallback_league_does_not_hit_season_endpoint():
    """CFL (not in SEASON_FALLBACK_LEAGUES) must short-circuit, never calling
    the full-season endpoint — this is the #217 storm fix."""
    provider, client = _provider_with_empty_day_endpoints()

    events = provider.get_events("cfl", date(2026, 5, 30))

    assert events == []
    client.get_events_by_season.assert_not_called()


def test_fallback_league_uses_season_endpoint():
    """Unrivaled (sparse on day endpoints) still falls back to the season
    endpoint so its coverage is preserved."""
    provider, client = _provider_with_empty_day_endpoints()

    provider.get_events("unrivaled", date(2026, 5, 30))

    client.get_events_by_season.assert_called_once_with("unrivaled")


def test_unrivaled_is_gated():
    assert "unrivaled" in TSDBProvider.SEASON_FALLBACK_LEAGUES
    assert "cfl" not in TSDBProvider.SEASON_FALLBACK_LEAGUES


# ===========================================================================
# Provider reload on API-key rotation
# ===========================================================================
# Tests for TSDB provider hot-reload when API key changes (s9n.1).
#
# Verifies that ProviderRegistry.reinitialize_provider() causes the TSDB
# provider to be recreated with the updated API key from the database,
# without requiring a restart.


class TestReinitializeProvider:
    def test_reinitialize_resets_cached_instance(self):
        """reinitialize_provider should clear the cached instance."""
        mock_provider = MagicMock()
        factory = MagicMock(return_value=mock_provider)

        config = ProviderConfig(
            name="test_provider",
            provider_class=type(mock_provider),
            factory=factory,
            enabled=True,
            priority=100,
        )
        # Simulate a cached instance
        config._instance = MagicMock()
        old_instance = config._instance

        ProviderRegistry._providers["test_provider"] = config

        try:
            result = ProviderRegistry.reinitialize_provider("test_provider")
            assert result is True
            assert config._instance is None

            # Next get() call should recreate via factory
            new_instance = config.get_instance()
            assert new_instance is mock_provider
            assert new_instance is not old_instance
            factory.assert_called_once()
        finally:
            ProviderRegistry._providers.pop("test_provider", None)

    def test_reinitialize_unknown_provider(self):
        """reinitialize_provider with unknown name returns False."""
        result = ProviderRegistry.reinitialize_provider("nonexistent_provider")
        assert result is False

    def test_reinitialize_picks_up_new_api_key(self):
        """After reinitialize, TSDB factory re-reads key from DB."""
        call_count = 0
        keys = ["old_key", "new_premium_key"]

        def mock_factory():
            nonlocal call_count
            key = keys[min(call_count, len(keys) - 1)]
            call_count += 1
            provider = MagicMock()
            provider.is_premium = key != "123"
            provider._api_key = key
            return provider

        config = ProviderConfig(
            name="test_tsdb",
            provider_class=MagicMock,
            factory=mock_factory,
            enabled=True,
            priority=100,
        )
        ProviderRegistry._providers["test_tsdb"] = config

        try:
            # First access creates with old key
            instance1 = config.get_instance()
            assert instance1._api_key == "old_key"

            # Reinitialize
            ProviderRegistry.reinitialize_provider("test_tsdb")

            # Second access creates with new key
            instance2 = config.get_instance()
            assert instance2._api_key == "new_premium_key"
            assert instance2 is not instance1
            assert call_count == 2
        finally:
            ProviderRegistry._providers.pop("test_tsdb", None)


class TestDisplaySettingsReloadIntegration:
    """Verify the endpoint code calls reinitialize when tsdb_api_key is set."""

    def test_endpoint_source_contains_reinitialize_call(self):
        """The display settings endpoint should call reinitialize_provider for tsdb."""
        import inspect

        from teamarr.api.routes.settings.display import update_display_settings_endpoint

        source = inspect.getsource(update_display_settings_endpoint)
        assert 'reinitialize_provider("tsdb")' in source
        assert "unmask_or_skip(update.tsdb_api_key) is not None" in source


# ===========================================================================
# Premium-league cache prewarm gating
# ===========================================================================
# TSDB premium-league gating in the startup cache prewarm (epic 46y3).
#
# Without a TSDB premium key, the cache build must NOT roll premium-only TSDB
# leagues into the team/league directory — otherwise it wastes free-tier calls on
# data it can't fully fetch. Once a premium key is configured the provider reports
# is_premium and every league is fetched again.


SCHEMA = SCHEMA_PATH

# From schema.sql leagues table (tsdb_tier).
PREMIUM = ["ipl", "sa20", "uru.2"]
FREE = ["boxing", "cfl"]


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def _shared_factory(conn: sqlite3.Connection):
    @contextlib.contextmanager
    def factory():
        yield conn

    return factory


class _FakeTSDB:
    """Minimal TSDB provider stub that records which leagues were fetched."""

    name = "tsdb"

    def __init__(self, *, is_premium: bool, leagues: list[str]):
        self.is_premium = is_premium
        self._leagues = leagues
        self.fetched: set[str] = set()
        self._lock = threading.Lock()

    def get_supported_leagues(self) -> list[str]:
        return list(self._leagues)

    def supports_league(self, league: str) -> bool:
        return league in self._leagues

    def get_league_teams(self, league: str) -> list:
        with self._lock:
            self.fetched.add(league)
        return []


def test_premium_tsdb_leagues_skipped_without_key():
    conn = _db()  # schema default: no premium key
    refresher = CacheRefresher(db_factory=_shared_factory(conn))
    prov = _FakeTSDB(is_premium=False, leagues=PREMIUM + FREE)

    refresher._discover_from_provider(prov)

    for code in PREMIUM:
        assert code not in prov.fetched, f"premium league {code} should be skipped"
    for code in FREE:
        assert code in prov.fetched, f"free league {code} should be fetched"


def test_premium_tsdb_leagues_included_with_key():
    conn = _db()
    refresher = CacheRefresher(db_factory=_shared_factory(conn))
    prov = _FakeTSDB(is_premium=True, leagues=PREMIUM + FREE)

    refresher._discover_from_provider(prov)

    assert prov.fetched == set(PREMIUM + FREE)


def test_premium_tsdb_leagues_query():
    conn = _db()
    refresher = CacheRefresher(db_factory=_shared_factory(conn))
    premium = refresher._premium_tsdb_leagues()
    # The known premium-tier codes are present; free-tier ones are not.
    assert set(PREMIUM).issubset(premium)
    assert premium.isdisjoint(FREE)


# ---------------------------------------------------------------------------
# Season format candidates + retry-on-empty (#60, bead pgtq.5)
# ---------------------------------------------------------------------------


def _season_client(sport: str):
    """TSDBClient with league lookups and transport stubbed for season tests."""
    from unittest.mock import MagicMock

    from teamarr.providers.tsdb.client import TSDBClient

    client = TSDBClient.__new__(TSDBClient)
    client.get_league_id = MagicMock(return_value="5766")
    client.get_sport = MagicMock(return_value=sport)
    client._cache = MagicMock()
    client._cache.get.return_value = None
    client._request = MagicMock()
    return client


class TestSeasonCandidates:
    def test_soccer_tries_calendar_year_first(self):
        client = _season_client("soccer")
        candidates = client._season_candidates("bra.camp.paranaense")
        assert candidates[0].isdigit()  # "2026"
        assert "-" in candidates[1]  # "2025-2026"

    def test_hockey_tries_fall_spring_first(self):
        client = _season_client("hockey")
        candidates = client._season_candidates("some.league")
        assert "-" in candidates[0]
        assert candidates[1].isdigit()

    def test_get_season_events_retries_alternate_format_on_empty(self):
        # Brazilian league: calendar-year first; simulate TSDB having data
        # only under the second candidate to prove the fall-through fires
        client = _season_client("hockey")  # fall-spring first = wrong guess
        empty = {"events": None}
        good = {"events": [{"idEvent": "1"}]}
        client._request.side_effect = [empty, good]

        result = client.get_season_events("bra.camp.paranaense")

        assert result is good
        assert client._request.call_count == 2
        seasons = [c.args[1]["s"] for c in client._request.call_args_list]
        assert "-" in seasons[0] and seasons[1].isdigit()

    def test_get_season_events_explicit_season_single_request(self):
        client = _season_client("soccer")
        client._request.return_value = {"events": None}

        client.get_season_events("bra.camp.paranaense", season="2024")

        client._request.assert_called_once()
        assert client._request.call_args.args[1]["s"] == "2024"

    def test_get_events_by_season_first_format_hit_stops(self):
        client = _season_client("soccer")
        client._request.return_value = {"events": [{"idEvent": "1"}]}

        result = client.get_events_by_season("bra.camp.paranaense")

        assert result["events"]
        client._request.assert_called_once()
        assert client._request.call_args.args[1]["s"].isdigit()

    def test_get_events_by_season_cached_empty_skips_to_alternate(self):
        # A fresh cached-empty for the first format must not re-request it —
        # only the alternate format goes to the API
        client = _season_client("soccer")
        empty = {"events": None}
        good = {"events": [{"idEvent": "1"}]}
        client._cache.get.side_effect = [empty, None]
        client._request.return_value = good

        result = client.get_events_by_season("bra.camp.paranaense")

        assert result is good
        client._request.assert_called_once()
        assert "-" in client._request.call_args.args[1]["s"]
