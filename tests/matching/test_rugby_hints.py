"""Rugby sport hint and URC league hint (#1141).

``URC Rugby - Sharks @ Cardiff Blues`` was matched to the San Jose Sharks on an
install that never cached the rugby Sharks: the fixture gate could not veto the
NHL, and the name's own sport and league words were not hints. Bare ``rugby``
now hints Rugby (union and league share the sport) and ``URC`` hints ``urc``.
"""

import pytest

from teamarr.consumers.matching.classifier import classify_stream, detect_league_hint
from teamarr.services.detection_keywords import DetectionKeywordService

DISCORD_STREAM = "URC Rugby - Sharks @ Cardiff Blues"


def setup_function():
    DetectionKeywordService.invalidate_cache()


@pytest.mark.parametrize(
    "stream,expected",
    [
        (DISCORD_STREAM, "Rugby"),
        ("Rugby: Leinster vs Munster", "Rugby"),
        ("NRL Rugby League: Sharks vs Storm", "Rugby"),
        ("Gallagher Premiership Rugby | Sale Sharks v Bath", "Rugby"),
        # Flo's vertical keeps working and still names the sport.
        ("florugby: 2026 Toulon vs RC Vannes", "Rugby"),
        # A hockey stream is untouched.
        ("NHL: San Jose Sharks @ Vegas Golden Knights", "Hockey"),
    ],
)
def test_rugby_sport_hint(stream, expected):
    assert DetectionKeywordService.detect_sport(stream) == expected


@pytest.mark.parametrize(
    "stream,expected",
    [
        (DISCORD_STREAM, "urc"),
        ("URC: Glasgow Warriors v Edinburgh", "urc"),
        ("NRL: Cronulla Sharks vs Melbourne Storm", "nrl"),
        ("Super Rugby: Crusaders vs Blues", "super-rugby"),
    ],
)
def test_rugby_league_hints(stream, expected):
    assert detect_league_hint(stream) == expected


def test_the_discord_stream_classifies_with_both_hints():
    """Both hints reach the classified stream, where the matcher gates on them."""
    classified = classify_stream(DISCORD_STREAM)
    assert classified.sport_hint == "Rugby"
    assert classified.league_hint == "urc"
    # The label prefix is stripped later, against the team-surface index
    # (#799); here the sides are the raw halves of the matchup.
    assert classified.team1.endswith("Sharks")
    assert classified.team2 == "Cardiff Blues"
