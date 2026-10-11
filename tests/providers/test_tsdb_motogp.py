"""MotoGP via TSDB (#604): TSDB's per-session events become race weekends.

Fixture: rounds 0–2 of TSDB's 2026 MotoGP season as captured on 2026-08-29
(163 events, 23 rounds in full). TSDB names the Sunday race "<X> GP", the
Saturday sprint "<X> Sprint Race", and files every pre-season test under
round 0.
"""

import json
from pathlib import Path

from teamarr.consumers.matching.classifier import has_racing_text_evidence
from teamarr.consumers.racing_segments import _session_duration_hours, _session_in_category
from teamarr.providers.tsdb.racing import parse_racing_events

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tsdb_motogp_2026.json").read_text())


def _weekends():
    return parse_racing_events(FIXTURE, "motogp", "racing", "tsdb")


def test_the_sunday_gp_is_the_race_not_the_saturday_sprint():
    thailand = _weekends()[0]
    assert thailand.name == "Thailand GP"
    race = next(s for s in thailand.sessions if s.code == "race")
    assert race.start_time.isoformat() == "2026-03-01T08:00:00+00:00"
    assert thailand.circuit_name == "Chang International Circuit"


def test_every_motogp_session_gets_a_label():
    codes = [(s.code, s.name) for s in _weekends()[0].sessions]
    assert codes == [
        ("fp1", "Practice 1"),
        ("practice", "Practice"),
        ("fp2", "Practice 2"),
        ("qualifying_1", "Qualifying 1"),
        ("qualifying_2", "Qualifying 2"),
        ("sprint", "Sprint"),
        ("race", "Race"),
    ]


def test_pre_season_tests_filed_under_round_0_are_not_a_weekend():
    weekends = _weekends()
    assert [w.name for w in weekends] == ["Thailand GP", "Brazil GP"]
    assert all(w.start_time.year == 2026 and w.start_time.month >= 2 for w in weekends)


def test_a_stream_saying_qualifying_covers_both_rounds_and_the_sessions_are_short():
    assert _session_in_category("qualifying_1", "qualifying")
    assert _session_in_category("qualifying_2", "qualifying")
    assert _session_duration_hours("qualifying_1", None, "motogp", "Thailand GP") == 0.5


def test_moto2_and_moto3_streams_do_not_land_on_the_motogp_weekend():
    """Same shape as F2/F3 on an F1 weekend: a series with no configured
    league maps to a code no group includes, which blocks the bind."""
    from teamarr.consumers.matching.classifier import detect_racing_series_leagues

    assert detect_racing_series_leagues("MotoGP: Thailand GP") == ("motogp",)
    assert detect_racing_series_leagues("Moto2: Thailand GP") == ("moto-feeder",)
    assert detect_racing_series_leagues("Moto3 Qualifying") == ("moto-feeder",)
    assert "motogp" not in detect_racing_series_leagues("Moto2 Thailand GP")
    assert has_racing_text_evidence("Moto2: Thailand GP")
