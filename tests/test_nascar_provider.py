"""Tests for the NASCAR public API provider.

Exercises NASCARProvider with mocked HTTP responses to verify:
- Session parsing (practice/qualifying/race from run_type and event_name)
- Admin entries (run_type 0) are excluded
- Cup response (plain list) and ORAP/Trucks response (series_N dict) both parse correctly
- get_events filters by session date correctly
- get_event lookup by ID works
- HTTP failures and malformed data are handled gracefully
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from teamarr.providers.nascar.provider import NASCARProvider, _session_code_and_name

# ---------------------------------------------------------------------------
# Unit tests: session code mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_name,run_type,expected_code,expected_name", [
    ("Race", 3, "race", "Race"),
    ("", 3, "race", "Race"),
    ("Qualifying (Impound)", 2, "qualifying", "Qualifying (Impound)"),
    ("Practice 1", 1, "fp1", "Practice 1"),
    ("Practice 2", 1, "fp2", "Practice 2"),
    ("Practice 3", 1, "fp3", "Practice 3"),
    ("Practice 4", 1, "fp4", "Practice 4"),
    ("Practice / Qualifying", 1, "practice", "Practice / Qualifying"),
    ("Final Practice", 1, "practice", "Final Practice"),
    ("", 1, "practice", "Practice"),
])
def test_session_code_and_name(event_name, run_type, expected_code, expected_name):
    code, name = _session_code_and_name(event_name, run_type)
    assert code == expected_code
    assert name == expected_name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _s(name, run_type, utc):
    return {"event_name": name, "run_type": run_type, "start_time_utc": utc}


_DAYTONA_500 = {
    "race_id": 5600,
    "race_name": "DAYTONA 500",
    "track_name": "Daytona International Speedway",
    "television_broadcaster": "FOX",
    "scheduled_laps": 200,
    "scheduled_distance": 500,
    "stage_1_laps": 60,
    "stage_2_laps": 65,
    "stage_3_laps": 75,
    "schedule": [
        # run_type 0 = admin noise, must be skipped
        _s("Haulers Enter",        0, "2026-02-11T11:00:00"),
        _s("Practice 1",           1, "2026-02-11T15:00:00"),
        _s("Qualifying (Impound)", 2, "2026-02-12T01:15:00"),
        _s("Practice 2",           1, "2026-02-13T22:35:00"),
        _s("Practice 3",           1, "2026-02-14T20:00:00"),
        _s("Race",                 3, "2026-02-15T18:30:00"),
    ],
}

_CLASH = {
    "race_id": 5593,
    "race_name": "Cook Out Clash at Bowman Gray",
    "track_name": "Bowman Gray Stadium",
    "schedule": [
        _s("Practice / Qualifying", 1, "2026-02-04T18:30:00"),
        _s("Race",                  3, "2026-02-04T23:00:00"),
    ],
}

_XFINITY_RACE = {
    "race_id": 5634,
    "race_name": "United Rentals 300",
    "track_name": "Daytona International Speedway",
    "schedule": [
        _s("Practice 1", 1, "2026-02-13T20:00:00"),
        _s("Race",       3, "2026-02-14T17:00:00"),
    ],
}

_TRUCK_RACE = {
    "race_id": 5700,
    "race_name": "NextEra Energy 250",
    "track_name": "Daytona International Speedway",
    "schedule": [
        _s("Practice 1", 1, "2026-02-13T22:30:00"),
        _s("Race",       3, "2026-02-14T19:30:00"),
    ],
}

# Cup API returns a plain list; ORAP+Trucks return {series_2: [...], series_3: [...]}
_CUP_RESPONSE = [_DAYTONA_500, _CLASH]
_SHARED_RESPONSE = {"series_2": [_XFINITY_RACE], "series_3": [_TRUCK_RACE]}


def _provider_with_data(cup=None, shared=None, year=2026):
    """Build a NASCARProvider whose _fetch is stubbed and cache pre-loaded."""
    p = NASCARProvider(league_mapping_source=None)

    cup_url = f"https://cf.nascar.com/cacher/{year}/1/race_list_basic.json"
    shared_url = f"https://cf.nascar.com/cacher/{year}/race_list_basic.json"
    responses = {cup_url: cup, shared_url: shared}
    p._fetch = lambda url: responses.get(url)
    p._events_by_league = p._load(year)
    # Pin the lazy-load cache so get_events()/get_event() don't refetch live.
    p._loaded_at = datetime.now(UTC)
    return p


# ---------------------------------------------------------------------------
# Session parsing
# ---------------------------------------------------------------------------


def test_daytona_500_sessions():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    events = p._events_by_league.get("nascar-cup", [])
    daytona = next(e for e in events if e.id == "5600")

    # run_type 0 (Haulers Enter) must be excluded → 5 on-track sessions
    assert len(daytona.sessions) == 5

    codes = [s.code for s in daytona.sessions]
    assert codes == ["fp1", "qualifying", "fp2", "fp3", "race"]

    # start_time anchors to first session (Practice 1)
    assert daytona.start_time == datetime(2026, 2, 11, 15, 0, tzinfo=UTC)


def test_clash_combined_practice_qualifying():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    events = p._events_by_league.get("nascar-cup", [])
    clash = next(e for e in events if e.id == "5593")

    assert len(clash.sessions) == 2
    assert clash.sessions[0].code == "practice"
    assert clash.sessions[0].name == "Practice / Qualifying"
    assert clash.sessions[1].code == "race"


def test_television_broadcaster_in_broadcasts():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    events = p._events_by_league.get("nascar-cup", [])
    daytona = next(e for e in events if e.id == "5600")
    assert daytona.broadcasts == ["FOX"]


def test_race_laps_and_distance():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    events = p._events_by_league.get("nascar-cup", [])
    daytona = next(e for e in events if e.id == "5600")
    assert daytona.race_laps == 200
    assert daytona.race_distance_miles == 500.0


def test_stage_laps():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    events = p._events_by_league.get("nascar-cup", [])
    daytona = next(e for e in events if e.id == "5600")
    assert daytona.stage_laps == [60, 65, 75]


def test_missing_laps_and_distance_gives_none():
    bare = {**_DAYTONA_500}
    del bare["scheduled_laps"]
    del bare["scheduled_distance"]
    del bare["stage_1_laps"]
    del bare["stage_2_laps"]
    del bare["stage_3_laps"]
    p = _provider_with_data(cup=[bare])
    events = p._events_by_league.get("nascar-cup", [])
    daytona = next(e for e in events if e.id == "5600")
    assert daytona.race_laps is None
    assert daytona.race_distance_miles is None
    assert daytona.stage_laps == []


def test_no_broadcaster_gives_empty_broadcasts():
    no_tv = {**_DAYTONA_500}
    del no_tv["television_broadcaster"]
    p = _provider_with_data(cup=[no_tv, _CLASH])
    events = p._events_by_league.get("nascar-cup", [])
    daytona = next(e for e in events if e.id == "5600")
    assert daytona.broadcasts == []


def test_circuit_name_propagated():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    events = p._events_by_league.get("nascar-cup", [])
    daytona = next(e for e in events if e.id == "5600")
    assert daytona.circuit_name == "Daytona International Speedway"
    assert daytona.venue is not None
    assert daytona.venue.name == "Daytona International Speedway"


# ---------------------------------------------------------------------------
# Multi-series response parsing
# ---------------------------------------------------------------------------


def test_xfinity_and_trucks_parsed_from_shared_response():
    p = _provider_with_data(shared=_SHARED_RESPONSE)
    xfinity = p._events_by_league.get("nascar-xfinity", [])
    trucks = p._events_by_league.get("nascar-truck", [])
    assert len(xfinity) == 1
    assert xfinity[0].name == "United Rentals 300"
    assert len(trucks) == 1
    assert trucks[0].name == "NextEra Energy 250"


def test_cup_missing_from_shared_response_gives_empty():
    # Cup league with a shared-style response (wrong format for Cup)
    p = _provider_with_data(cup=_SHARED_RESPONSE)
    # Cup expects a list; passing a dict → no races parsed
    assert p._events_by_league.get("nascar-cup") == []


# ---------------------------------------------------------------------------
# get_events date filtering
# ---------------------------------------------------------------------------


def test_get_events_practice_day():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    # Practice 1 for Daytona 500 is 2026-02-11
    events = p.get_events("nascar-cup", date(2026, 2, 11))
    assert len(events) == 1
    assert events[0].name == "DAYTONA 500"


def test_get_events_qualifying_day():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    events = p.get_events("nascar-cup", date(2026, 2, 12))
    assert len(events) == 1
    assert events[0].name == "DAYTONA 500"


def test_get_events_race_day():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    events = p.get_events("nascar-cup", date(2026, 2, 15))
    assert len(events) == 1
    assert events[0].name == "DAYTONA 500"


def test_get_events_off_day_returns_empty():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    events = p.get_events("nascar-cup", date(2026, 2, 10))  # day before any session
    assert events == []


def test_get_events_unsupported_league_returns_empty():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    assert p.get_events("f1", date(2026, 2, 11)) == []


# ---------------------------------------------------------------------------
# get_event by ID
# ---------------------------------------------------------------------------


def test_get_event_by_id():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    event = p.get_event("5600", "nascar-cup")
    assert event is not None
    assert event.name == "DAYTONA 500"


def test_get_event_unknown_id_returns_none():
    p = _provider_with_data(cup=_CUP_RESPONSE)
    assert p.get_event("9999", "nascar-cup") is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_fetch_failure_gives_empty_league():
    p = _provider_with_data(cup=None, shared=None)
    assert p._events_by_league.get("nascar-cup") == []
    assert p._events_by_league.get("nascar-xfinity") == []
    assert p._events_by_league.get("nascar-truck") == []


def test_race_without_sessions_is_skipped():
    no_sessions = {**_DAYTONA_500, "schedule": [
        _s("Haulers Enter", 0, "2026-02-11T11:00:00"),
    ]}
    p = _provider_with_data(cup=[no_sessions])
    assert p._events_by_league.get("nascar-cup") == []


def test_race_missing_name_is_skipped():
    bad = {**_DAYTONA_500, "race_name": ""}
    p = _provider_with_data(cup=[bad])
    assert p._events_by_league.get("nascar-cup") == []


def test_malformed_start_time_skips_session():
    bad_schedule = {**_DAYTONA_500, "schedule": [
        _s("Practice 1", 1, "not-a-date"),
        _s("Race",       3, "2026-02-15T18:30:00"),
    ]}
    p = _provider_with_data(cup=[bad_schedule])
    events = p._events_by_league.get("nascar-cup", [])
    assert len(events) == 1
    # Only the Race session survives; the malformed Practice is silently skipped
    assert len(events[0].sessions) == 1
    assert events[0].sessions[0].code == "race"


# ---------------------------------------------------------------------------
# Lazy loading & cache lifetime (take-and-fix: no constructor fetch)
# ---------------------------------------------------------------------------


def test_constructor_does_not_fetch():
    calls = []
    p = NASCARProvider(league_mapping_source=None)
    p._fetch = lambda url: calls.append(url)
    assert calls == []
    assert p._loaded_at is None


def test_first_get_events_triggers_load():
    p = NASCARProvider(league_mapping_source=None)
    year = datetime.now(UTC).year
    responses = {
        f"https://cf.nascar.com/cacher/{year}/1/race_list_basic.json": [_DAYTONA_500],
    }
    p._fetch = lambda url: responses.get(url)
    events = p.get_events("nascar-cup", date(2026, 2, 15))
    assert p._loaded_at is not None
    assert [e.name for e in events] == ["DAYTONA 500"]


def test_failed_refresh_keeps_previous_schedule():
    p = _provider_with_data(cup=[_DAYTONA_500])
    # Expire the cache, then make every fetch fail.
    p._loaded_at = datetime.now(UTC) - timedelta(seconds=p._CACHE_TTL_SECONDS + 1)
    p._fetch = lambda url: None
    events = p.get_events("nascar-cup", date(2026, 2, 15))
    assert [e.name for e in events] == ["DAYTONA 500"]  # old data survives


def test_empty_cache_retries_sooner_than_ttl():
    p = NASCARProvider(league_mapping_source=None)
    p._fetch = lambda url: None
    p.get_events("nascar-cup", date(2026, 2, 15))  # first load fails → empty

    # Within the empty-retry window: no refetch.
    calls = []
    p._fetch = lambda url: calls.append(url)
    p.get_events("nascar-cup", date(2026, 2, 15))
    assert calls == []

    # Past the empty-retry window (but well under the full TTL): refetches.
    p._loaded_at = datetime.now(UTC) - timedelta(seconds=p._EMPTY_RETRY_SECONDS + 1)
    p.get_events("nascar-cup", date(2026, 2, 15))
    assert calls  # refetch attempted


def test_fresh_cache_not_refetched():
    p = _provider_with_data(cup=[_DAYTONA_500])
    calls = []
    p._fetch = lambda url: calls.append(url)
    p.get_events("nascar-cup", date(2026, 2, 15))
    assert calls == []


# ---------------------------------------------------------------------------
# Cache round-trip: race-format fields must survive provider_cache serialization
# (the normal generation path serves events from the prefetch cache — #242 hit
# this same gap with sessions/circuit_name)
# ---------------------------------------------------------------------------


def test_race_format_fields_survive_cache_roundtrip():
    from teamarr.database.provider_cache import dict_to_event, event_to_dict

    p = _provider_with_data(cup=_CUP_RESPONSE)
    daytona = next(e for e in p._events_by_league["nascar-cup"] if e.id == "5600")

    restored = dict_to_event(event_to_dict(daytona))

    assert restored.race_laps == 200
    assert restored.race_distance_miles == 500.0
    assert restored.stage_laps == [60, 65, 75]
    assert [s.code for s in restored.sessions] == [s.code for s in daytona.sessions]
