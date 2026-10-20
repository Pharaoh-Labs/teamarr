"""Cup knockout rounds, legs and aggregates from ESPN soccer payloads (#916).

Fixture: tests/providers/fixtures/espn_uefa_knockouts_2025-26.json, captured
2026-10-20 from the live scoreboard (2025-26 UCL/UEL) and one summary header.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from teamarr.core.types import Event, EventStatus, Team
from teamarr.database.provider_cache import dict_to_event, event_to_dict
from teamarr.providers.espn.knockout import parse_knockout
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.services.sports_data import SportsDataService

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "espn_uefa_knockouts_2025-26.json").read_text()
)


@pytest.fixture
def provider():
    return ESPNProvider(client=object())  # client unused by _parse_event


def _parsed(provider, key) -> Event:
    case = FIXTURE[key]
    event = provider._parse_event(case["event"], case["league"])
    assert event is not None, key
    return event


def test_first_leg_names_the_round_and_leg_without_an_aggregate(provider):
    ev = _parsed(provider, "r16_leg1")
    assert ev.knockout_round == "Round of 16"
    assert ev.match_leg == 1
    assert ev.match_legs_total == 2
    assert ev.aggregate_home is None and ev.aggregate_away is None
    assert ev.tie_winner == ""
    assert ev.season_type == "postseason"
    assert ev.game_event_note == "1st Leg"  # untouched: the note is not a series note
    assert ev.series_summary == ""  # a UEFA series block has no 'summary'


def test_decided_second_leg_carries_the_aggregate_by_side(provider):
    ev = _parsed(provider, "r16_leg2_aggregate")
    assert ev.match_leg == 2
    assert (ev.home_team.name, ev.away_team.name) == ("Barcelona", "Newcastle United")
    assert (ev.aggregate_home, ev.aggregate_away) == (8, 3)
    assert ev.tie_winner == "home"


def test_one_nil_aggregate_is_not_mistaken_for_missing(provider):
    ev = _parsed(provider, "qf_leg2_aggregate_1_0")
    assert ev.knockout_round == "Quarterfinals"
    assert (ev.aggregate_home, ev.aggregate_away) == (1, 0)
    assert ev.tie_winner == "home"


def test_tied_aggregate_decided_on_penalties_keeps_the_level_score(provider):
    ev = _parsed(provider, "uel_r16_leg2_tied_penalties")
    assert (ev.aggregate_home, ev.aggregate_away) == (2, 2)
    assert ev.tie_winner == "away"  # Nottingham Forest, the shootout winner
    assert ev.status.state == "final"


def test_penalties_statuses_are_final(provider):
    """STATUS_FINAL_PEN was unmapped, so a shootout parsed as 'scheduled' (#916)."""
    assert _parsed(provider, "final_penalties").status.state == "final"
    assert _parsed(provider, "uel_r16_leg2_tied_penalties").status.state == "final"
    # An unknown name still resolves from ESPN's own state, never to 'scheduled'.
    status = provider._parse_status({"type": {"name": "STATUS_SOMETHING_NEW", "state": "post"}})
    assert status.state == "final"
    status = provider._parse_status({"type": {"name": "STATUS_SOMETHING_NEW", "state": "in"}})
    assert status.state == "live"


def test_final_has_a_round_but_no_leg_or_aggregate(provider):
    ev = _parsed(provider, "final_penalties")
    assert ev.knockout_round == "Final"
    assert ev.match_leg is None and ev.match_legs_total is None
    assert ev.aggregate_home is None and ev.tie_winner == ""
    assert ev.season_type == "postseason"


def test_knockout_round_playoffs_is_a_knockout_stage(provider):
    ev = _parsed(provider, "knockout_round_playoffs_leg1")
    assert ev.knockout_round == "Knockout Round Playoffs"
    assert ev.match_leg == 1
    assert ev.season_type == "postseason"


def test_league_phase_is_not_a_knockout(provider):
    ev = _parsed(provider, "league_phase_scheduled")
    assert ev.knockout_round == ""
    assert ev.match_leg is None and ev.match_legs_total is None
    assert ev.aggregate_home is None and ev.tie_winner == ""
    assert ev.season_type == "regular"


def test_summary_header_series_list_parses_the_same_way():
    """The summary endpoint wraps series in a list; seasonseries is never read."""
    case = FIXTURE["summary_header_r16_leg2"]
    comp = case["header"]["competitions"][0]
    home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
    away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
    got = parse_knockout(comp, case["header"]["season"], home["id"], away["id"])
    assert got == {
        "knockout_round": "Round of 16",
        "match_leg": 2,
        "match_legs_total": 2,
        "aggregate_home": 8,
        "aggregate_away": 3,
        "tie_winner": "home",
    }
    assert case["seasonseries"][0]["type"] == "head-to-head"  # the trap, documented


def test_leg_falls_back_to_the_note_when_the_structured_field_is_missing():
    comp = {"notes": [{"headline": "2nd Leg - X advance 2-1 on aggregate"}]}
    assert parse_knockout(comp, {"slug": "round-of-16"}, "1", "2")["match_leg"] == 2
    assert parse_knockout({"notes": [{"headline": "1st Leg"}]}, {}, "1", "2")["match_leg"] == 1


def test_no_aggregate_from_an_unfinished_or_half_known_series():
    series = {"completed": False, "competitors": [{"id": "1", "aggregateScore": 3}]}
    assert parse_knockout({"series": series}, {}, "1", "2")["aggregate_home"] is None
    series = {"completed": True, "competitors": [{"id": "1", "aggregateScore": 3}, {"id": "2"}]}
    got = parse_knockout({"series": series}, {}, "1", "2")
    assert got["aggregate_home"] is None and got["aggregate_away"] is None


def test_hockey_series_never_becomes_a_knockout_round(provider):
    """{knockout_round} is a soccer contract; an NHL series block has a title too."""
    case = FIXTURE["r16_leg1"]
    with patch.object(provider, "_get_sport", return_value="hockey"):
        ev = provider._parse_event(case["event"], "nhl")
    assert ev is not None
    assert ev.knockout_round == "" and ev.match_leg is None


def test_season_slugs_for_the_new_uefa_format(provider):
    assert provider._parse_season_type({"slug": "league-phase"}) == "regular"
    assert provider._parse_season_type({"slug": "knockout-round-playoffs"}) == "postseason"
    assert provider._parse_season_type({"slug": "round-of-32"}) == "postseason"


def test_provider_cache_round_trips_the_fields_and_defaults_old_entries(provider):
    ev = _parsed(provider, "r16_leg2_aggregate")
    back = dict_to_event(event_to_dict(ev))
    assert (back.knockout_round, back.match_leg, back.match_legs_total) == ("Round of 16", 2, 2)
    assert (back.aggregate_home, back.aggregate_away, back.tie_winner) == (8, 3, "home")
    old = event_to_dict(ev)
    for key in ("knockout_round", "match_leg", "match_legs_total", "aggregate_home"):
        old.pop(key)
    pre_upgrade = dict_to_event(old)
    assert pre_upgrade.knockout_round == "" and pre_upgrade.match_leg is None


def _team(i: str, n: str) -> Team:
    return Team(
        id=i,
        provider="espn",
        name=n,
        short_name=n,
        abbreviation=n[:3].upper(),
        league="uefa.champions",
        sport="soccer",
    )


def _event(**overrides) -> Event:
    base = dict(
        id="401862582",
        provider="espn",
        name="Newcastle United at Barcelona",
        short_name="NEW @ BAR",
        league="uefa.champions",
        sport="soccer",
        start_time=datetime(2026, 3, 18, 20, 0),
        home_team=_team("83", "Barcelona"),
        away_team=_team("361", "Newcastle United"),
        status=EventStatus(state="pre"),
        knockout_round="Round of 16",
        match_leg=2,
        match_legs_total=2,
    )
    base.update(overrides)
    return Event(**base)


def test_refresh_overlays_the_aggregate_once_the_tie_is_decided():
    original = _event()
    fresh = _event(
        status=EventStatus(state="final"), aggregate_home=8, aggregate_away=3, tie_winner="home"
    )
    service = SportsDataService(providers=[])
    with (
        patch.object(service, "get_event", return_value=fresh),
        patch.object(service._cache, "delete"),
    ):
        result = service.refresh_event_status(original)
    assert (result.aggregate_home, result.aggregate_away, result.tie_winner) == (8, 3, "home")
    assert result.match_leg == 2 and result.knockout_round == "Round of 16"


def test_refresh_never_blanks_knockout_facts_the_fresh_fetch_lacks():
    original = _event(aggregate_home=8, aggregate_away=3, tie_winner="home")
    fresh = _event(knockout_round="", match_leg=None, match_legs_total=None)
    service = SportsDataService(providers=[])
    with (
        patch.object(service, "get_event", return_value=fresh),
        patch.object(service._cache, "delete"),
    ):
        result = service.refresh_event_status(original)
    assert result.knockout_round == "Round of 16" and result.match_leg == 2
    assert (result.aggregate_home, result.aggregate_away) == (8, 3)
