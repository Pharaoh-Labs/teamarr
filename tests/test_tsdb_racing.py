"""Tests for TSDB racing event grouping (WEC, IMSA).

TheSportsDB models a race weekend as several flat per-session events sharing
a (strSeason, intRound). `parse_racing_events` groups these into a single
multi-session `Event`, mirroring the ESPN racing pipeline's shape.
"""

from datetime import date
from unittest.mock import MagicMock

from teamarr.providers.tsdb.provider import TSDBProvider
from teamarr.providers.tsdb.racing import parse_racing_events


def _event(event_id, name, date_str, time_str, round_, season="2026", venue="Circuit de la Sarthe", country="France"):
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
    _event("4", "24 Hours of Le Mans Hyperpole Qualifying – LMP2 & LMGT3", "2026-06-10", "16:45:00", "3"),
    _event("5", "24 Hours of Le Mans Hyperpole Qualifying – Hypercar", "2026-06-10", "17:30:00", "3"),
    _event("6", "24 Hours of Le Mans Hyperpole 1 - LMP2 & LMGT3", "2026-06-11", "18:00:00", "3"),
    _event("7", "24 Hours of Le Mans Hyperpole 1 - Hypercar", "2026-06-11", "19:05:00", "3"),
    _event("8", "24 Hours of Le Mans", "2026-06-13", "10:00:00", "3"),
]

# A round-500 "Prologue" weekend with only Morning/Afternoon sessions - no
# event in the group qualifies as "the race".
WEC_PROLOGUE = [
    _event("10", "Imola Prologue Morning Session", "2026-04-14", "07:00:00", "500", venue="Imola Circuit", country="Italy"),
    _event("11", "Imola Prologue Afternoon Session", "2026-04-14", "12:00:00", "500", venue="Imola Circuit", country="Italy"),
]

# IMSA: one event per round, no session suffix.
IMSA_ROUND = [
    _event("20", "Rolex 24 At DAYTONA", "2026-01-25", "00:00:00", "1", venue="Daytona International Speedway", country="USA"),
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
