"""Tests for ESPN provider series summary selection (#920).

Ensures that active playoff series are prioritized over completed regular season
series when teams play in the postseason.
"""

from unittest.mock import MagicMock

from teamarr.core.types import Event
from teamarr.providers.espn.preview import apply_generated_preview_fields, select_series
from teamarr.providers.espn.provider import ESPNProvider


def test_select_series_prioritizes_event_id_match():
    series_list = [
        {
            "type": "season",
            "title": "Regular Season Series",
            "summary": "IND wins series 2-1",
            "completed": True,
            "events": [{"id": "1001"}, {"id": "1002"}, {"id": "1003"}],
        },
        {
            "type": "playoff",
            "title": "Playoff Series",
            "summary": "Series tied 1-1",
            "completed": False,
            "events": [{"id": "2001"}, {"id": "2002"}, {"id": "2003"}],
        },
    ]
    # For game 2003 (tonight's playoff game)
    chosen = select_series(series_list, event_id="2003")
    assert chosen is not None
    assert chosen["summary"] == "Series tied 1-1"

    # For game 1002 (regular season game)
    chosen_reg = select_series(series_list, event_id="1002")
    assert chosen_reg is not None
    assert chosen_reg["summary"] == "IND wins series 2-1"


def test_select_series_prioritizes_active_playoff_without_event_id():
    series_list = [
        {
            "type": "season",
            "title": "Regular Season Series",
            "summary": "IND wins series 2-1",
            "completed": True,
        },
        {
            "type": "playoff",
            "title": "Playoff Series",
            "summary": "Series tied 1-1",
            "completed": False,
        },
    ]
    chosen = select_series(series_list, event_id=None)
    assert chosen is not None
    assert chosen["summary"] == "Series tied 1-1"


def test_select_series_accepts_postseason_spelling():
    series_list = [
        {"type": "season", "summary": "IND wins series 2-1", "completed": True},
        {"type": "postseason", "summary": "Series tied 1-1", "completed": False},
    ]
    chosen = select_series(series_list, event_id=None)
    assert chosen is not None
    assert chosen["summary"] == "Series tied 1-1"


def test_select_series_completed_playoff_still_outranks_season():
    # No event_id match and the playoff series is completed, so selection
    # falls to priority 3 (any playoff) — still ahead of the season series.
    series_list = [
        {"type": "season", "summary": "IND wins series 2-1", "completed": True},
        {"type": "playoff", "summary": "LV wins series 3-1", "completed": True},
    ]
    chosen = select_series(series_list, event_id=None)
    assert chosen is not None
    assert chosen["summary"] == "LV wins series 3-1"


def test_select_series_filters_out_preseason():
    series_list = [
        {"type": "preseason", "summary": "Preseason tied 1-1"},
        {"type": "season", "summary": "BOS leads 2-1"},
    ]
    chosen = select_series(series_list)
    assert chosen is not None
    assert chosen["summary"] == "BOS leads 2-1"


def test_select_series_empty_and_invalid():
    assert select_series([]) is None
    assert select_series([{"type": "preseason", "summary": "Tied 1-1"}]) is None
    assert select_series([{"type": "season", "summary": ""}]) is None


def test_select_series_event_match_outranks_stateful_fallback():
    # Live NLCS Game 1 shape (2026-10-11, event 401908030): the playoff entry
    # contains tonight's game but its summary is '' until first pitch, while
    # the completed regular-season head-to-head carries a stateful summary.
    # The containing series must win — callers resolve its empty summary to
    # no series data instead of borrowing "MIL wins series 4-3" (#teamarr-4sfj).
    series_list = [
        {"type": "preseason", "summary": "Series tied 1-1", "completed": True,
         "events": ["401833127", "401833228"]},
        {"type": "season", "summary": "MIL wins series 4-3", "completed": True,
         "events": ["401815450", "401816515"]},
        {"type": "playoff", "summary": "", "completed": False,
         "events": ["401908030", "401908031", "401908032"]},
    ]
    chosen = select_series(series_list, event_id="401908030")
    assert chosen is not None
    assert chosen["type"] == "playoff"
    assert chosen["summary"] == ""


def test_select_series_event_match_with_start_note_does_not_leak():
    # A containing entry whose summary is a schedule note ("Series starts")
    # is the right entry but not a state; callers filter it, so make sure the
    # stateful regular-season entry is not silently substituted here either.
    series_list = [
        {"type": "season", "summary": "MIL wins series 4-3", "completed": True,
         "events": ["401815450"]},
        {"type": "playoff", "summary": "Series starts 10/11", "completed": False,
         "events": ["401908030"]},
    ]
    chosen = select_series(series_list, event_id="401908030")
    assert chosen is not None
    assert chosen["type"] == "playoff"
    assert chosen["summary"] == "Series starts 10/11"


def test_apply_generated_preview_fields_selects_playoff_series():
    event = Event(
        id="401918022",
        provider="espn",
        name="Indiana Fever at Las Vegas Aces",
        short_name="IND @ LV",
        start_time=None,
        home_team=MagicMock(),
        away_team=MagicMock(),
        status=MagicMock(),
        league="wnba",
        sport="basketball",
    )
    payload = {
        "header": {
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "home", "record": [{"type": "total", "summary": "27-13"}]},
                        {"homeAway": "away", "record": [{"type": "total", "summary": "20-20"}]},
                    ]
                }
            ]
        },
        "seasonseries": [
            {
                "type": "season",
                "title": "Regular Season Series",
                "summary": "IND wins series 2-1",
                "completed": True,
                "events": [{"id": "401857042"}, {"id": "401857063"}, {"id": "401857119"}],
            },
            {
                "type": "playoff",
                "title": "Playoff Series",
                "summary": "Series tied 1-1",
                "completed": False,
                "events": [{"id": "401918015"}, {"id": "401918018"}, {"id": "401918022"}],
            },
        ],
    }

    apply_generated_preview_fields(payload, event)
    assert event.series_summary == "Series tied 1-1"


def test_parse_event_extracts_scoreboard_series_summary():
    provider = ESPNProvider(client=MagicMock())
    raw_event = {
        "id": "401918022",
        "name": "Indiana Fever at Las Vegas Aces",
        "shortName": "IND @ LV",
        "date": "2026-10-02T01:00Z",
        "competitions": [
            {
                "id": "401918022",
                "date": "2026-10-02T01:00Z",
                "competitors": [
                    {
                        "id": "17",
                        "homeAway": "home",
                        "team": {
                            "id": "17",
                            "displayName": "Las Vegas Aces",
                            "abbreviation": "LV",
                        },
                    },
                    {
                        "id": "5",
                        "homeAway": "away",
                        "team": {
                            "id": "5",
                            "displayName": "Indiana Fever",
                            "abbreviation": "IND",
                        },
                    },
                ],
                "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED"}},
                "series": {
                    "type": "playoff",
                    "title": "Playoff Series",
                    "summary": "Series tied 1-1",
                    "completed": False,
                },
            }
        ],
    }

    parsed = provider._parse_event(raw_event, "wnba")
    assert parsed is not None
    assert parsed.series_summary == "Series tied 1-1"


def test_parse_event_series_list_uses_containment_match():
    # competition.series arrives as a LIST on the summary endpoint's header
    # competitions. Covers the branch where the event-id containment match
    # runs and the chosen entry's summary must pass is_series_state.
    provider = ESPNProvider(client=MagicMock())
    raw_event = {
        "id": "401908030",
        "name": "Los Angeles Dodgers at Milwaukee Brewers",
        "shortName": "LAD @ MIL",
        "date": "2026-10-12T00:00Z",
        "competitions": [
            {
                "id": "401908030",
                "date": "2026-10-12T00:00Z",
                "competitors": [
                    {
                        "id": "19",
                        "homeAway": "home",
                        "team": {"id": "19", "displayName": "Milwaukee Brewers",
                                 "abbreviation": "MIL"},
                    },
                    {
                        "id": "8",
                        "homeAway": "away",
                        "team": {"id": "8", "displayName": "Los Angeles Dodgers",
                                 "abbreviation": "LAD"},
                    },
                ],
                "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED"}},
                "series": [
                    {"type": "season", "summary": "MIL wins series 4-3",
                     "completed": True, "events": ["401815450"]},
                    {"type": "playoff", "summary": "MIL leads series 2-1",
                     "completed": False,
                     "events": ["401908030", "401908031", "401908032"]},
                ],
            }
        ],
    }
    parsed = provider._parse_event(raw_event, "mlb")
    assert parsed is not None
    assert parsed.series_summary == "MIL leads series 2-1"


def test_parse_event_series_list_game1_renders_empty():
    # Same list shape but the containing playoff entry has no state yet —
    # must render empty, not the season entry's "MIL wins series 4-3".
    provider = ESPNProvider(client=MagicMock())
    raw_event = {
        "id": "401908030",
        "name": "Los Angeles Dodgers at Milwaukee Brewers",
        "shortName": "LAD @ MIL",
        "date": "2026-10-12T00:00Z",
        "competitions": [
            {
                "id": "401908030",
                "date": "2026-10-12T00:00Z",
                "competitors": [
                    {
                        "id": "19",
                        "homeAway": "home",
                        "team": {"id": "19", "displayName": "Milwaukee Brewers",
                                 "abbreviation": "MIL"},
                    },
                    {
                        "id": "8",
                        "homeAway": "away",
                        "team": {"id": "8", "displayName": "Los Angeles Dodgers",
                                 "abbreviation": "LAD"},
                    },
                ],
                "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED"}},
                "series": [
                    {"type": "season", "summary": "MIL wins series 4-3",
                     "completed": True, "events": ["401815450"]},
                    {"type": "playoff", "summary": "", "completed": False,
                     "events": ["401908030"]},
                ],
            }
        ],
    }
    parsed = provider._parse_event(raw_event, "mlb")
    assert parsed is not None
    assert parsed.series_summary == ""


def test_get_event_summary_selects_playoff_series():
    provider = ESPNProvider(client=MagicMock())
    summary_data = {
        "header": {
            "gameNote": "Indiana Fever at Las Vegas Aces",
            "competitions": [
                {
                    "id": "401918022",
                    "date": "2026-10-02T01:00Z",
                    "competitors": [
                        {
                            "id": "17",
                            "homeAway": "home",
                            "team": {
                                "id": "17",
                                "displayName": "Las Vegas Aces",
                                "abbreviation": "LV",
                            },
                        },
                        {
                            "id": "5",
                            "homeAway": "away",
                            "team": {
                                "id": "5",
                                "displayName": "Indiana Fever",
                                "abbreviation": "IND",
                            },
                        },
                    ],
                    "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED"}},
                }
            ],
            "season": {"year": 2026, "type": 3},
        },
        "seasonseries": [
            {
                "type": "season",
                "title": "Regular Season Series",
                "summary": "IND wins series 2-1",
                "completed": True,
                "events": [{"id": "401857042"}, {"id": "401857063"}, {"id": "401857119"}],
            },
            {
                "type": "playoff",
                "title": "Playoff Series",
                "summary": "Series tied 1-1",
                "completed": False,
                "events": [{"id": "401918015"}, {"id": "401918018"}, {"id": "401918022"}],
            },
        ],
    }
    provider._client.get_event = MagicMock(return_value=summary_data)

    event = provider.get_event("401918022", "wnba")
    assert event is not None
    assert event.series_summary == "Series tied 1-1"


def _nlcs_game1_summary_payload(playoff_summary=""):
    """Live ESPN summary shape for NLCS Game 1 (2026-10-11, event 401908030)."""
    return {
        "header": {
            "gameNote": "Los Angeles Dodgers at Milwaukee Brewers",
            "competitions": [
                {
                    "id": "401908030",
                    "date": "2026-10-12T00:00Z",
                    "competitors": [
                        {"id": "19", "homeAway": "home",
                         "team": {"id": "19", "displayName": "Milwaukee Brewers",
                                  "abbreviation": "MIL"}},
                        {"id": "8", "homeAway": "away",
                         "team": {"id": "8", "displayName": "Los Angeles Dodgers",
                                  "abbreviation": "LAD"}},
                    ],
                    "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED"}},
                }
            ],
            "season": {"year": 2026, "type": 3},
        },
        "seasonseries": [
            {"type": "preseason", "summary": "Series tied 1-1", "completed": True,
             "events": ["401833127", "401833228"]},
            {"type": "season", "summary": "MIL wins series 4-3", "completed": True,
             "events": ["401815450", "401816515", "401816530", "401816545", "401816560"]},
            {"type": "playoff", "summary": playoff_summary, "completed": False,
             "events": ["401908030", "401908031", "401908032", "401908033"]},
        ],
    }


def test_get_event_playoff_game1_does_not_borrow_season_series():
    # Regression (#teamarr-4sfj): the playoff entry containing this event has
    # an empty summary (series 0-0), so the old candidate filter skipped it and
    # the completed regular-season "MIL wins series 4-3" leaked into
    # {series_summary}. The containing series now wins and renders empty.
    provider = ESPNProvider(client=MagicMock())
    provider._client.get_event = MagicMock(
        return_value=_nlcs_game1_summary_payload(playoff_summary="")
    )
    event = provider.get_event("401908030", "mlb")
    assert event is not None
    assert event.series_summary == ""


def test_get_event_playoff_start_note_does_not_leak():
    # Same shape, but the containing series carries a "Series starts" note —
    # a schedule note, not state; must not render either.
    provider = ESPNProvider(client=MagicMock())
    provider._client.get_event = MagicMock(
        return_value=_nlcs_game1_summary_payload(playoff_summary="Series starts 10/11")
    )
    event = provider.get_event("401908030", "mlb")
    assert event is not None
    assert event.series_summary == ""


def test_get_event_playoff_series_state_still_renders():
    # After Game 1 the playoff entry carries real state; nothing else changes.
    provider = ESPNProvider(client=MagicMock())
    provider._client.get_event = MagicMock(
        return_value=_nlcs_game1_summary_payload(playoff_summary="MIL leads series 1-0")
    )
    event = provider.get_event("401908030", "mlb")
    assert event is not None
    assert event.series_summary == "MIL leads series 1-0"


def test_apply_generated_preview_fields_playoff_game1_leaves_summary_empty():
    event = Event(
        id="401908030",
        provider="espn",
        name="Los Angeles Dodgers at Milwaukee Brewers",
        short_name="LAD @ MIL",
        start_time=None,
        home_team=MagicMock(),
        away_team=MagicMock(),
        status=MagicMock(),
        league="mlb",
        sport="baseball",
        series_summary="",
    )
    apply_generated_preview_fields(_nlcs_game1_summary_payload(playoff_summary=""), event)
    assert event.series_summary == ""

