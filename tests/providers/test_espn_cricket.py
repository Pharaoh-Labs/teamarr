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


# ============================== series discovery: format leagues over the day's panel


class _PanelClient:
    """A client whose cricket panel is the fixture, grouped back into series."""

    def __init__(self, panel=None):
        self.calls = []
        if panel is None:
            blocks = {}
            for e in EVENTS.values():
                lg = e["_league"]
                blocks.setdefault(lg["id"], {"leagues": [lg], "events": []})["events"].append(e)
            panel = {"scores": list(blocks.values())}
        self.panel = panel

    def get_cricket_panel(self, date_str):
        self.calls.append(date_str)
        return self.panel


class _Mapping:
    def __init__(self, provider_league_id):
        self.provider_league_id = provider_league_id
        self.sport = "Cricket"


class _Mappings:
    ROWS = {"cricket-odi": "cricket/panel:odi", "cricket-t20i": "cricket/panel:t20i"}

    def get_mapping(self, league, provider):
        pid = self.ROWS.get(league)
        return _Mapping(pid) if pid else None

    def get_league_sport(self, league):
        return "cricket" if league in self.ROWS else None

    def supports_league(self, league, provider):
        return league in self.ROWS

    def get_mapping_by_league(self, league):
        return self.get_mapping(league, "espn")


def _panel_provider(client=None):
    return ESPNProvider(client=client or _PanelClient(), league_mapping_source=_Mappings())


def test_a_format_league_is_a_filter_over_the_days_panel():
    from datetime import date

    provider = _panel_provider()
    t20 = provider.get_events("cricket-t20i", date(2026, 10, 11))
    odi = provider.get_events("cricket-odi", date(2026, 10, 11))
    assert sorted(e.id for e in t20) == ["1529232", "1554579"]
    assert sorted(e.id for e in odi) == ["1554413", "1554416"]
    # Tests, first-class and women's T20 are on the panel and in neither league.
    assert all(e.league == "cricket-t20i" and e.sport == "cricket" for e in t20)
    assert t20[0].game_event_note in ("3rd T20I", "12th Match")


def test_panel_events_carry_their_series_slug():
    from datetime import date

    events = _panel_provider().get_events("cricket-t20i", date(2026, 10, 11))
    by_id = {e.id: e for e in events}
    # The fixture's series blocks have no slug, so the league id is the
    # fallback — numeric either way (bead s7ny). 1554555 is the T20 World
    # Cup qualifier, a pure series id with no name-shaped slug at all.
    assert by_id["1529232"].series_slug == "24289"
    assert by_id["1554579"].series_slug == "1554555"


def test_a_present_series_slug_wins_over_the_league_id():
    from datetime import date

    panel = {
        "scores": [
            {
                "leagues": [
                    {"id": "24289", "slug": "8050", "name": "West Indies tour of India 2026/27"}
                ],
                "events": [EVENTS["1529232"]],
            }
        ]
    }
    events = _panel_provider(_PanelClient(panel)).get_events("cricket-t20i", date(2026, 10, 11))
    assert [e.series_slug for e in events] == ["8050"]


def test_a_blank_slug_falls_back_to_the_events_league_id():
    from datetime import date

    event = dict(EVENTS["1529232"], leagueId="4242")
    panel = {"scores": [{"leagues": [{"slug": "", "name": "Tour"}], "events": [event]}]}
    events = _panel_provider(_PanelClient(panel)).get_events("cricket-t20i", date(2026, 10, 11))
    assert [e.series_slug for e in events] == ["4242"]


def test_no_series_information_anywhere_leaves_the_slug_empty():
    from datetime import date

    panel = {"scores": [{"events": [EVENTS["1529232"]]}]}
    events = _panel_provider(_PanelClient(panel)).get_events("cricket-t20i", date(2026, 10, 11))
    assert [e.series_slug for e in events] == [""]


def test_the_two_leagues_share_one_panel_request_per_day():
    from datetime import date

    client = _PanelClient()
    provider = _panel_provider(client)
    provider.get_events("cricket-t20i", date(2026, 10, 11))
    provider.get_events("cricket-odi", date(2026, 10, 11))
    # The fake has no memo; the real client memoises per day. Here we only
    # pin that both leagues ask for the same day string.
    assert client.calls == ["20261011", "20261011"]


def test_a_multi_day_match_listed_twice_is_one_event():
    from datetime import date

    panel = _PanelClient().panel
    dup = {"leagues": [{"id": "x", "name": "dup"}], "events": [EVENTS["1529232"]]}
    panel["scores"].append(dup)
    assert [
        e.id
        for e in _panel_provider(_PanelClient(panel)).get_events("cricket-t20i", date(2026, 10, 11))
    ].count("1529232") == 1


def test_an_empty_day_is_no_events_not_an_error():
    from datetime import date

    provider = _panel_provider(_PanelClient({"scores": []}))
    assert provider.get_events("cricket-odi", date(2026, 10, 11)) == []


def test_a_format_league_has_no_teams_endpoint_and_no_team_schedule():
    client = _PanelClient()
    client.get_teams = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called"))
    provider = _panel_provider(client)
    assert provider.get_league_teams("cricket-odi") == []
    assert provider.get_team_schedule("2", "cricket-odi") == []


def test_the_real_client_memoises_a_days_panel_but_never_a_failure(monkeypatch):
    from teamarr.providers.espn.client import ESPNClient

    client = ESPNClient()
    try:
        answers = iter([None, {"scores": []}, {"scores": [{"x": 1}]}])
        calls = []
        monkeypatch.setattr(
            client, "_request", lambda url, params=None: (calls.append(params), next(answers))[1]
        )
        assert client.get_cricket_panel("20261011") is None  # failure: not memoised
        assert client.get_cricket_panel("20261011") == {"scores": []}  # fetched again, memoised
        assert client.get_cricket_panel("20261011") == {"scores": []}  # served from the memo
        assert len(calls) == 2 and calls[0] == {"dates": "20261011"}
    finally:
        client.close()


# ============================== Tests: one channel per day, as sessions (bead 7cmb.8)


class _TestMappings(_Mappings):
    ROWS = {**_Mappings.ROWS, "cricket-test": "cricket/panel:test"}


def _test_provider(client=None):
    return ESPNProvider(client=client or _PanelClient(), league_mapping_source=_TestMappings())


def test_a_test_carries_one_session_per_day_capped_at_five():
    from datetime import UTC, date, datetime, timedelta

    events = {e.id: e for e in _test_provider().get_events("cricket-test", date(2026, 10, 11))}
    assert sorted(events) == ["1525659", "1555116"]
    aus = events["1525659"]  # date 2026-10-09T07:30Z, endDate 2026-10-14T23:59Z (reserve day)
    assert [s.code for s in aus.sessions] == ["day1", "day2", "day3", "day4", "day5"]
    assert [s.name for s in aus.sessions][:2] == ["Day 1", "Day 2"]
    d1 = datetime(2026, 10, 9, 7, 30, tzinfo=UTC)
    assert [s.start_time for s in aus.sessions] == [d1 + timedelta(days=i) for i in range(5)]
    assert aus.status.state == "live" and aus.status.detail == "Stumps"


def test_a_test_already_decided_keeps_no_future_days(monkeypatch):
    from datetime import date

    import teamarr.providers.espn.provider as prov

    data = EVENTS["1525659"]
    data = {
        **data,
        "status": {
            **data["status"],
            "type": {**data["status"]["type"], "state": "post", "description": "Result"},
        },
    }
    data["competitions"] = [{**data["competitions"][0], "status": data["status"]}]
    panel = {"scores": [{"leagues": [data["_league"]], "events": [data]}]}

    class _Now(prov.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 12, 15, 0, tzinfo=tz)  # won inside day 4

    monkeypatch.setattr(prov, "datetime", _Now)
    (event,) = _test_provider(_PanelClient(panel)).get_events("cricket-test", date(2026, 10, 12))
    assert event.status.state == "final"
    assert [s.code for s in event.sessions] == ["day1", "day2", "day3", "day4"]


def test_a_test_day_is_seven_hours_and_a_stream_naming_its_day_scopes_to_it():
    from datetime import date

    from teamarr.consumers.racing_segments import (
        _session_duration_hours,
        expand_racing_segments,
        has_session_channels,
    )

    (test_event,) = [
        e
        for e in _test_provider().get_events("cricket-test", date(2026, 10, 11))
        if e.id == "1525659"
    ]
    assert has_session_channels(test_event)
    assert _session_duration_hours("day3", {"cricket": 4.0}) == 7.0

    whole = {"stream": {"name": "South Africa v Australia - 1st Test"}, "event": test_event}
    day3 = {"stream": {"name": "SA vs AUS 1st Test Day 3 [1080p]"}, "event": test_event}
    day9 = {"stream": {"name": "SA vs AUS 1st Test Day 9"}, "event": test_event}
    out = expand_racing_segments([whole, day3, day9], {"cricket": 4.0})
    by_name = {}
    for m in out:
        by_name.setdefault(m["stream"]["name"], []).append(m["segment"])
    # A feed with no day word covers the whole match: one channel per day.
    assert by_name["South Africa v Australia - 1st Test"] == [
        "day1",
        "day2",
        "day3",
        "day4",
        "day5",
    ]
    assert by_name["SA vs AUS 1st Test Day 3 [1080p]"] == ["day3"]
    assert "SA vs AUS 1st Test Day 9" not in by_name  # names a day the Test has not got
    d3 = next(m for m in out if m["segment"] == "day3" and "Day 3" in m["stream"]["name"])
    assert (d3["segment_end"] - d3["segment_start"]).total_seconds() == 7 * 3600


def test_racing_words_on_a_cricket_stream_do_not_scope():
    from datetime import date

    from teamarr.consumers.racing_segments import expand_racing_segments

    (test_event,) = [
        e
        for e in _test_provider().get_events("cricket-test", date(2026, 10, 11))
        if e.id == "1525659"
    ]
    out = expand_racing_segments(
        [
            {
                "stream": {"name": "Australia v South Africa Test - Race for the Ashes"},
                "event": test_event,
            }
        ],
        {},
    )
    assert len(out) == 5


def test_session_name_variable_reads_a_tests_day():
    from datetime import date
    from types import SimpleNamespace

    from teamarr.templates.variables.motorsports import extract_session_name, extract_session_type

    (test_event,) = [
        e
        for e in _test_provider().get_events("cricket-test", date(2026, 10, 11))
        if e.id == "1525659"
    ]
    game_ctx = SimpleNamespace(event=test_event, card_segment="day3")
    assert extract_session_name(None, game_ctx) == "Day 3"
    assert extract_session_type(None, game_ctx) == "day3"
    # No session on the channel: nothing, as for a race weekend's main row.
    assert extract_session_name(None, SimpleNamespace(event=test_event, card_segment=None)) == ""


# ============================== no team, schedule or summary endpoint (bead 7cmb.2)


def test_a_panel_league_never_asks_for_a_summary_or_a_scoreboard(monkeypatch):

    client = _PanelClient()
    for name in ("get_event", "get_scoreboard", "get_teams", "get_team_schedule", "get_team"):
        setattr(client, name, lambda *a, _n=name, **k: (_ for _ in ()).throw(AssertionError(_n)))
    provider = _panel_provider(client)
    assert provider.get_event("1529232", "cricket-t20i") is None
    assert provider.get_league_teams("cricket-t20i") == []
    assert provider.get_team_schedule("6", "cricket-t20i") == []

    import teamarr.providers.espn.provider as prov

    class _Today(prov.date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 11)

    monkeypatch.setattr(prov, "date", _Today)
    recent = provider.get_recent_final("cricket-t20i")
    assert recent is not None and recent.id == "1529232" and recent.status.state == "final"
    assert client.calls and set(client.calls) <= {"20261011", "20261010", "20261009", "20261008"}
    assert len(provider.get_sample_candidates("cricket-odi")) == 2
