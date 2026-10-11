"""ESPN cricket parsing (#944, bead 7cmb.1).

Cricket statuses carry no ``type.name``, only ``state`` and a free-text
description, so every match used to parse as scheduled. Scores are innings
text. The competition description is the match label and the status summary is
the result. Fixture: eight events trimmed from the live score panel on
2026-10-11 — a Test at stumps, two finished limited-overs matches, a live ODI,
a first-class match at stumps, a scheduled T20I, and a women's T20 that ESPN
marks ``in`` while its summary still says "Starts at".
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.matching.team_matcher import _is_placeholder_team
from teamarr.core.types import Team
from teamarr.providers.espn.provider import ESPNProvider

FIXTURE = Path(__file__).parent / "fixtures" / "espn_cricket_scorepanel_2026-10-11.json"
EVENTS = {e["id"]: e for e in json.loads(FIXTURE.read_text())}


def _provider():
    provider = ESPNProvider(client=MagicMock())
    provider._get_sport = lambda league: "cricket"
    return provider


def _parse(event_id):
    data = EVENTS[event_id]
    return _provider()._parse_event(data, data["_league"]["id"])


@pytest.mark.parametrize(
    "event_id, state, detail",
    [
        ("1554416", "final", "Result"),  # ODI, Nepal won by 24 runs
        ("1529232", "final", "Result"),  # 3rd T20I, India won by 14 runs
        ("1554413", "live", "Live"),  # ODI in progress
        ("1525659", "live", "Stumps"),  # 1st Test, day over, match not
        ("1555116", "live", "Stumps"),  # Only Test
        ("1546541", "live", "Stumps"),  # Ranji Trophy first-class
        ("1554579", "scheduled", "Scheduled"),  # T20I tomorrow
        ("1554123", "scheduled", "Live"),  # marked in, summary says Starts at
    ],
)
def test_status_comes_from_state_and_description(event_id, state, detail):
    event = _parse(event_id)
    assert event is not None
    assert (event.status.state, event.status.detail) == (state, detail)


@pytest.mark.parametrize(
    "description, state, expected",
    [
        ("Abandoned", "post", "cancelled"),
        ("Abandoned", "in", "cancelled"),
        ("No result", "post", "final"),
        ("Match postponed", "pre", "postponed"),
        ("Rain delay", "in", "live"),
        ("Final", "post", "final"),
    ],
)
def test_the_words_not_seen_in_the_fixture(description, state, expected):
    type_data = {"state": state, "description": description, "name": None}
    assert ESPNProvider._state_without_type_name(type_data, "") == expected


def test_a_named_status_still_uses_the_map():
    provider = _provider()
    status = provider._parse_status({"type": {"state": "post", "name": "STATUS_FINAL"}})
    assert status.state == "final"


def test_scores_are_text_so_neither_side_parses():
    event = _parse("1554416")  # Canada '211 (48.4/50 ov, target 236)' v Nepal '235'
    assert (event.home_score, event.away_score) == (None, None)


def test_match_label_and_result_text():
    event = _parse("1529232")
    assert event.game_event_note == "3rd T20I"
    assert event.game_recap == "India won by 14 runs"
    assert event.home_team.name == "India" and event.away_team.name == "West Indies"


def test_a_match_in_progress_carries_its_state_text():
    event = _parse("1525659")
    assert event.game_event_note == "1st Test"
    assert event.game_recap == "Australia lead by 139 runs"


def test_a_scheduled_match_has_no_result_text():
    assert _parse("1554579").game_recap == ""
    assert _parse("1554123").game_recap == ""  # "Starts at 10:00 local time" is not a result


@pytest.mark.parametrize("name", ["TBA", "TBC", "To Be Confirmed", "tbd"])
def test_an_undecided_side_with_a_positive_id_is_a_placeholder(name):
    team = Team(
        id="1554600",
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=name[:3].upper(),
        league="24289",
        sport="cricket",
    )
    assert _is_placeholder_team(team)
