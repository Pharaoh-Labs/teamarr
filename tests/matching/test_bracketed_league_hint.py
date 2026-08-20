"""League hints wrapped in brackets (#580).

The built-in hint patterns end in ``[:\\s-]``, so a bracketed league tag —
the shape most providers ship ("US (MLB) Seattle Mariners (S)") — produced no
hint at all. Without a hint the stream is scored against every league the
group subscribes to, which is how cross-league false positives get their
chance in the first place (the #569 report's streams were all bracketed).

Detection now retries once on a de-bracketed copy. Raw text goes first so
user-defined hint patterns containing literal brackets keep winning.
"""

import pytest

from teamarr.consumers.matching.classifier import classify_stream, detect_league_hint
from teamarr.services.detection_keywords import DetectionKeywordService


def setup_function():
    """Clear compiled pattern cache before each test."""
    DetectionKeywordService.invalidate_cache()


@pytest.mark.parametrize(
    "stream,expected",
    [
        # The reported shapes (#580) — an MLB/NFL stream must never be free to
        # roam an MLS group's events.
        ("US (MLB) Seattle Mariners (S)", "mlb"),
        ("(NFL) Seattle Seahawks (P)", "nfl"),
        ("[NBA] Lakers vs Celtics", "nba"),
        ("(Apple) (MLS) 026 | Seattle vs. Austin", "usa.1"),
        ("{NHL} Bruins vs Rangers", "nhl"),
        # Unbracketed forms are unchanged
        ("NHL: Bruins vs Rangers", "nhl"),
        ("MLB: Brewers vs Dodgers", "mlb"),
    ],
)
def test_bracketed_league_tag_detects(stream, expected):
    assert detect_league_hint(stream) == expected


@pytest.mark.parametrize(
    "stream",
    [
        # Quality/feed markers must not be mistaken for league codes
        "US (HD) Seattle Mariners",
        "US (4K) | Team A vs Team B",
        "(SD) Some Channel",
        "US Seattle Mariners (A)",
    ],
)
def test_non_league_brackets_stay_unhinted(stream):
    assert detect_league_hint(stream) is None


def test_bracketed_umbrella_hint_still_narrows_by_gender():
    # The de-bracketed retry feeds the normal umbrella path, and (W) narrowing
    # reads the original stream name — so the marker survives its own bracket.
    result = classify_stream("(NCAAB) (W): Duke vs UNC")
    assert result.league_hint == "womens-college-basketball"


def test_raw_text_wins_over_the_debracketed_retry():
    # A user pattern written with literal brackets must still take priority.
    DetectionKeywordService.invalidate_cache()
    hints = DetectionKeywordService.get_league_hints()
    import re

    hints.insert(0, (re.compile(r"\(MLB\)", re.IGNORECASE), "llb"))
    try:
        assert detect_league_hint("US (MLB) Little League Classic") == "llb"
    finally:
        DetectionKeywordService.invalidate_cache()
