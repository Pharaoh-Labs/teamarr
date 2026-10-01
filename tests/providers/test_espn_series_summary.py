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
