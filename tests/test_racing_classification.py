"""Tests for racing stream classification (follow-up to #242).

Racing leagues are configured with ``event_type='event'`` and have no reliable
text keyword, so a stream is classified ``RACING_EVENT`` purely because the
group is racing-dominant and the stream has no team pattern. This is the
regression-prone path (cf. #157): a team-sport stream that leaks into a
racing-dominant group must NOT be hijacked as a race.
"""

from teamarr.consumers.matching.classifier import StreamCategory, classify_stream
from teamarr.services.detection_keywords import DetectionKeywordService


def setup_function():
    DetectionKeywordService.invalidate_cache()


# ---------------------------------------------------------------------------
# Genuine racing streams classify as RACING_EVENT
# ---------------------------------------------------------------------------


def test_f1_stream_classifies_racing():
    c = classify_stream("F1: Monaco Grand Prix", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT
    assert c.event_hint  # full text carried for fuzzy matching


def test_nascar_stream_classifies_racing():
    c = classify_stream("NASCAR Cup Series - Daytona 500", league_event_type="event")
    assert c.category == StreamCategory.RACING_EVENT


def test_racing_only_applies_for_event_league_type():
    # Same name, but a non-racing (team) group must not route to racing.
    c = classify_stream("F1: Monaco Grand Prix", league_event_type="team")
    assert c.category != StreamCategory.RACING_EVENT


# ---------------------------------------------------------------------------
# Leaked team-sport streams in a racing-dominant group are NOT hijacked
# ---------------------------------------------------------------------------


def test_team_stream_with_separator_falls_through():
    # "SD at BAL" has a game separator → team matching, not racing.
    c = classify_stream("SD at BAL", league_event_type="event")
    assert c.category == StreamCategory.TEAM_VS_TEAM


def test_team_stream_with_nonracing_sport_hint_falls_through():
    # No separator, but a positive non-racing sport hint ("Ice Hockey") vetoes
    # racing classification — the #242 follow-up guard.
    c = classify_stream("NHL | Ice Hockey: Maple Leafs", league_event_type="event")
    assert c.category != StreamCategory.RACING_EVENT


def test_hockey_single_team_in_racing_group_is_not_racing():
    c = classify_stream("US | Ice Hockey: Maple Leafs", league_event_type="event")
    assert c.category != StreamCategory.RACING_EVENT
