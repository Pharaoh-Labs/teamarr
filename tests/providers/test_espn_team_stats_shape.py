"""ESPN team-stats payload shapes (#1047).

A record stat can arrive as a bare name with no value. On 2026-10-13 every
Conference USA football team started carrying ``{"name": "divisionRecord"}``
in its overall record, and the stat map's ``s["value"]`` raised KeyError,
which dropped the whole team's stats. The fixture is the live payload for
Jacksonville State (team 55), trimmed to the fields the parser reads.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from teamarr.providers.espn.provider import ESPNProvider

FIXTURE = Path(__file__).parent / "fixtures" / "espn_team_cusa_2026-10-14.json"


def _provider(payload):
    client = MagicMock()
    client.get_team.return_value = payload
    provider = ESPNProvider(client=client)
    provider._get_sport_league_from_db = lambda league: ("football", "college-football")
    return provider


def _payload():
    return json.loads(FIXTURE.read_text())


def test_fixture_carries_a_stat_without_a_value():
    stats = _payload()["team"]["record"]["items"][0]["stats"]
    assert {"name": "divisionRecord"} in stats


def test_valueless_stat_is_skipped_and_the_rest_parse():
    stats = _provider(_payload()).get_team_stats("55", "ncaaf")

    assert stats is not None
    assert stats.record == "5-2"
    assert stats.wins == 5 and stats.losses == 2
    assert stats.streak == "W4"
    assert stats.ppg == pytest.approx(27.29, abs=0.01)
    assert stats.papg == pytest.approx(22.71, abs=0.01)
    assert stats.conference == "CUSA"
    assert stats.conference_id == "12"


def test_stat_with_null_value_is_skipped_too():
    payload = _payload()
    payload["team"]["record"]["items"][0]["stats"].append({"name": "wins", "value": None})

    stats = _provider(payload).get_team_stats("55", "ncaaf")

    assert stats is not None
    assert stats.record == "5-2"
