"""Tests for NCAAB gender-aware stream classification (#150).

NCAAB streams should match both men's and women's college basketball.
Gender markers (W)/(M) in stream names should narrow the hint to the
correct league, and the markers are stripped from team names. Spanish/
Portuguese markers (femenino/feminino/masculino, "(F)") work like the
English ones — non-English EPGs label gender that way, not Women/(W).
"""

import pytest

from teamarr.consumers.matching.classifier import (
    _clean_team_name,
    _narrow_by_gender,
    classify_stream,
    detect_league_hint,
)
from teamarr.services.detection_keywords import DetectionKeywordService

PAIR = ["mens-college-basketball", "womens-college-basketball"]


def setup_function():
    """Clear compiled pattern cache before each test."""
    DetectionKeywordService.invalidate_cache()


@pytest.mark.parametrize(
    "stream,expected",
    [
        # NCAAB is an umbrella hint mapping to BOTH leagues (returned as a list).
        ("NCAAB: Duke vs UNC", set(PAIR)),
        ("NCAAM: Duke vs UNC", {"mens-college-basketball"}),
        ("NCAAW: South Carolina vs LSU", {"womens-college-basketball"}),
    ],
)
def test_detect_league_hint_gender(stream, expected):
    result = detect_league_hint(stream)
    if len(expected) > 1:
        assert isinstance(result, list)
    got = set(result) if isinstance(result, list) else {result}
    assert got == expected


@pytest.mark.parametrize(
    "leagues,text,expected",
    [
        # English (W)/(M) markers and the Women keyword narrow the umbrella pair.
        (PAIR, "NCAAB 216: SOUTH CAROLINA @ LSU (W)", "womens-college-basketball"),
        (PAIR, "NCAAB 100: Duke @ UNC (M)", "mens-college-basketball"),
        (PAIR, "NCAAB 100: Duke @ UNC", PAIR),  # no marker keeps full list
        (PAIR, "NCAAB: Women: South Carolina @ LSU", "womens-college-basketball"),
        (PAIR, "NCAAB 216: LSU (w)", "womens-college-basketball"),  # case-insensitive
        # Non-gendered league lists pass through untouched.
        (["eng.2", "eng.3", "eng.4", "eng.fa"],
         "EFL: Portsmouth vs Southampton (W)",
         ["eng.2", "eng.3", "eng.4", "eng.fa"]),
        # Spanish/Portuguese markers.
        (PAIR, "Fútbol Femenino: España vs Italia", "womens-college-basketball"),
        (PAIR, "Liga Femenina", "womens-college-basketball"),
        (PAIR, "Brasil Feminino", "womens-college-basketball"),
        (PAIR, "España (F)", "womens-college-basketball"),
        (PAIR, "Liga Masculina", "mens-college-basketball"),
        # "feminine" lacks the trailing o/a, so it must not trigger women's.
        (PAIR, "Feminine Hygiene Show", PAIR),
        # "Men" inside "Menorca" must not trigger men's narrowing.
        (PAIR, "Menorca CF vs Ibiza", PAIR),
    ],
)
def test_narrow_by_gender(leagues, text, expected):
    assert _narrow_by_gender(leagues, text) == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("LSU (W)", "LSU"),
        ("Duke (M)", "Duke"),
        ("LSU (Women)", "LSU"),
        ("Duke (Men)", "Duke"),
        ("LSU (w)", "LSU"),  # case-insensitive
        ("España (F)", "España"),
        ("Boca (Femenino)", "Boca"),
        ("Madrid (Masculino)", "Madrid"),
    ],
)
def test_gender_marker_stripped_from_team_name(name, expected):
    assert _clean_team_name(name) == expected


def test_broadcast_parenthetical_also_stripped():
    # CBS is a broadcast indicator, should also be stripped (round indicators
    # are handled by a different pattern).
    assert "CBS" not in _clean_team_name("Team (CBS)")


# ---------------------------------------------------------------------------
# End-to-end classification through classify_stream
# ---------------------------------------------------------------------------


def test_ncaab_womens_stream_classified():
    """The exact stream from issue #150 should classify correctly."""
    result = classify_stream("NCAAB 216: 3 SOUTH CAROLINA @ 6 LSU (W) | 2.14 8:30 PM | ABC")

    # League hint should be narrowed to women's
    assert result.league_hint == "womens-college-basketball"
    # Team names should not contain (W)
    if result.team1:
        assert "(W)" not in result.team1
    if result.team2:
        assert "(W)" not in result.team2


def test_ncaab_mens_stream_classified():
    result = classify_stream("NCAAB 100: Duke @ UNC (M) | 2.15 7:00 PM")

    assert result.league_hint == "mens-college-basketball"
    if result.team2:
        assert "(M)" not in result.team2


def test_ncaab_no_gender_marker_keeps_umbrella():
    result = classify_stream("NCAAB: Duke @ UNC")

    # Should keep the umbrella hint (both leagues)
    assert isinstance(result.league_hint, list)
    assert "mens-college-basketball" in result.league_hint
    assert "womens-college-basketball" in result.league_hint
