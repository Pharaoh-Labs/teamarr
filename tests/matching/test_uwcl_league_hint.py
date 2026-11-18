"""Tests for UEFA Women's Champions League (uefa.wchampions) league hint (#1236).

The unanchored "champions league" pattern for men's uefa.champions previously
matched inside "Women's Champions League" / "UEFA Women's Champions League
Soccer", pinning UWCL EPG programs and streams to uefa.champions instead of
uefa.wchampions.
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
        # Live CBS Sports Network EPG shape (#1236)
        ("UEFA Women's Champions League Soccer | Real Madrid vs. Inter", "uefa.wchampions"),
        ("UEFA Women's Champions League Soccer | Juventus vs. OH Leuven", "uefa.wchampions"),
        ("Women's Champions League | Arsenal vs. Lyon", "uefa.wchampions"),
        ("Womens Champions League: Barcelona vs. Chelsea", "uefa.wchampions"),
        ("UWCL: Bayern Munich vs. PSG", "uefa.wchampions"),
        # Men's UCL patterns must continue to resolve to uefa.champions
        ("UEFA Champions League | Real Madrid vs. Inter", "uefa.champions"),
        ("Champions League: Arsenal vs. Bayern Munich", "uefa.champions"),
        ("UCL: Barcelona vs. PSG", "uefa.champions"),
    ],
)
def test_uwcl_league_hint(stream, expected):
    assert detect_league_hint(stream) == expected


def test_uwcl_classify_stream_extracts_teams_and_hint():
    result = classify_stream("UEFA Women's Champions League Soccer | Real Madrid vs. Inter")
    assert result.league_hint == "uefa.wchampions"
    assert result.team1 == "Real Madrid"
    assert result.team2 == "Inter"
