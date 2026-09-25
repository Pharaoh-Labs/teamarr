"""UK EPG kick-off subtitles must not become a team or a fixture separator (#876)."""

import pytest

from teamarr.consumers.matching.classifier import StreamCategory, classify_stream
from teamarr.consumers.matching.epg_matcher import build_match_input
from teamarr.consumers.matching.normalizer import normalize_stream, strip_kickoff_suffix
from teamarr.dispatcharr.types import DispatcharrProgram


@pytest.mark.parametrize(
    "title",
    [
        "Live UEFA Nations League|England v Spain: Kick-off 7.45pm",
        "England v Spain: Kick-off 7.45pm",
        "England v Spain (Kick-off 7.45pm)",
        "Live International Football|England v Spain. Kick-off 7.45pm",
        "England v Spain - Kickoff 19:45 BST",
    ],
)
def test_trailing_kickoff_clock_is_not_a_team(title):
    result = classify_stream(title)
    assert result.category == StreamCategory.TEAM_VS_TEAM
    assert (result.team1, result.team2) == ("England", "Spain")
    assert "Kick-off" not in result.normalized.normalized
    assert result.normalized.extracted_date is None  # 7.45 is not a date


def test_non_clock_kickoff_text_is_preserved():
    title = "Kick-Off FC v Spain: Kick-off coverage begins soon"
    assert strip_kickoff_suffix(title) == title
    assert classify_stream(title).team1 == "Kick-Off FC"


def test_only_trailing_clock_is_removed():
    title = "Kick-off 7.45pm special | England v Spain"
    assert strip_kickoff_suffix(title) == title


def test_existing_time_hint_outside_subtitle_survives():
    result = normalize_stream("England v Spain @ 19:00 GMT: Kick-off 7.45pm")
    assert result.extracted_time is not None
    assert result.extracted_time.hour == 19
    assert "Kick-off" not in result.normalized


def test_epg_title_and_subtitle_reach_clean_fixture():
    program = DispatcharrProgram.from_api(
        {
            "id": 876,
            "tvg_id": "sports",
            "title": "Live UEFA Nations League",
            "sub_title": "England v Spain: Kick-off 7.45pm",
            "start_time": "2026-09-25T18:45:00Z",
            "end_time": "2026-09-25T21:00:00Z",
            "epg_source": "ext",
        }
    )
    result = classify_stream(build_match_input(program))
    assert (result.team1, result.team2) == ("England", "Spain")
