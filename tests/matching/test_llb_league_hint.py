"""Tests for the Little League Baseball league hint (#560).

Without an LLB hint, streams like "Little League Baseball: ... MIL vs. LAD"
carried no league constraint, so the team abbreviations matched the MLB
Brewers/Dodgers matchup and LLB games landed in MLB channels. The hint
hard-scopes such streams to llb — matched there when subscribed, filtered
(never crosstalk) when not.

Ordering matters the other way too: the MLB Little League Classic is an
MLB game ("MLB: Little League Classic ..."), and the earlier MLB pattern
must keep winning for it.
"""

import pytest

from teamarr.consumers.matching.classifier import detect_league_hint
from teamarr.services.detection_keywords import DetectionKeywordService


def setup_function():
    """Clear compiled pattern cache before each test."""
    DetectionKeywordService.invalidate_cache()


@pytest.mark.parametrize(
    "stream,expected",
    [
        # The reporter's exact stream shape (#560)
        (
            "US (ESPN+ 141) | Little League Baseball: "
            "Little League Baseball Regionals • MIL vs. LAD (2026-08-14 21:00:15)",
            "llb",
        ),
        ("Little League World Series: Japan vs Mexico", "llb"),
        ("LLWS Semifinal: Texas vs Florida", "llb"),
        ("LLB: Great Lakes vs Mountain", "llb"),
        # MLB Little League Classic is an MLB game — MLB pattern wins by order
        ("MLB: Little League Classic • NYM vs SEA", "mlb"),
        # Plain MLB streams keep their hint
        ("MLB: Brewers vs Dodgers", "mlb"),
    ],
)
def test_llb_league_hint(stream, expected):
    assert detect_league_hint(stream) == expected
