"""A game with no announced start time is not a midnight game (#995).

ESPN lists such a game at midnight Eastern with ``timeValid: false`` and a
"TBD" status. The timestamp is a placeholder; the guide used to print it as
"12:00 AM EDT".
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from teamarr.core.types import Event, EventStatus, Team
from teamarr.database.provider_cache import dict_to_event, event_to_dict
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.variables.datetime import extract_game_time


def _competition(time_valid):
    comp = {
        "id": "401858490",
        "date": "2026-10-17T04:00Z",
        "competitors": [
            {"id": "130", "homeAway": "home",
             "team": {"id": "130", "displayName": "Michigan Wolverines", "abbreviation": "MICH"}},
            {"id": "213", "homeAway": "away",
             "team": {"id": "213", "displayName": "Penn State Nittany Lions",
                      "abbreviation": "PSU"}},
        ],
        "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED", "shortDetail": "TBD"}},
    }
    if time_valid is not None:
        comp["timeValid"] = time_valid
    return comp


def _scoreboard_event(time_valid):
    return {
        "id": "401858490",
        "name": "Penn State Nittany Lions at Michigan Wolverines",
        "shortName": "PSU @ MICH",
        "date": "2026-10-17T04:00Z",
        "competitions": [_competition(time_valid)],
    }


@pytest.mark.parametrize("time_valid, tbd", [(False, True), (True, False), (None, False)])
def test_scoreboard_time_valid_sets_time_tbd(time_valid, tbd):
    """Only an explicit ``false`` means unannounced; a missing flag is a
    provider or payload that does not say, and the time stands."""
    provider = ESPNProvider(client=MagicMock())
    event = provider._parse_event(_scoreboard_event(time_valid), "college-football")
    assert event is not None
    assert event.time_tbd is tbd


def test_summary_reads_the_header_level_flag():
    """The summary endpoint carries the flag on the header, not the competition."""
    provider = ESPNProvider(client=MagicMock())
    provider._client.get_event = MagicMock(return_value={
        "header": {
            "gameNote": "",
            "timeValid": False,
            "competitions": [_competition(None)],
            "season": {"year": 2026, "type": 2},
        },
    })
    event = provider.get_event("401858490", "college-football")
    assert event is not None
    assert event.time_tbd is True


def _event(time_tbd):
    def team(id_, name):
        return Team(id=id_, provider="espn", name=name, short_name=name, abbreviation=name[:3],
                    league="college-football", sport="football")

    return Event(
        id="401858490", provider="espn", name="x", short_name="x",
        start_time=datetime(2026, 10, 17, 4, 0, tzinfo=UTC), league="college-football",
        sport="football", status=EventStatus(state="pre"),
        home_team=team("130", "Michigan Wolverines"),
        away_team=team("213", "Penn State Nittany Lions"), time_tbd=time_tbd,
    )


def test_time_tbd_survives_the_event_cache():
    assert dict_to_event(event_to_dict(_event(True))).time_tbd is True
    assert dict_to_event(event_to_dict(_event(False))).time_tbd is False
    # a row cached before the field existed
    legacy = event_to_dict(_event(True))
    del legacy["time_tbd"]
    assert dict_to_event(legacy).time_tbd is False


def test_game_time_says_tbd_instead_of_the_placeholder():
    def game_time(event):
        ctx = TemplateContext(
            game_context=GameContext(event=event),
            team_config=TeamChannelContext(team_id="130", league="college-football",
                                           sport="football", team_name="Michigan Wolverines"),
            team_stats=None,
        )
        return extract_game_time(ctx, ctx.game_context)

    with patch("teamarr.templates.variables.datetime.format_time", return_value="12:00 AM EDT"):
        assert game_time(_event(True)) == "TBD"
        assert game_time(_event(False)) == "12:00 AM EDT"
