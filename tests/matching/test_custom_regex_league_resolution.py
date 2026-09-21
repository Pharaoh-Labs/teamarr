"""Custom league regex captures resolve to canonical league codes (#820).

A custom league regex captures whatever the provider writes — in the
reporting support bundle, display names like 'Premier League', 'Bundesliga'
and 'Serie A'. The matcher compares the hint against subscribed codes
('eng.1', 'ger.1', 'ita.1'), so the raw capture filtered every one of those
otherwise valid streams as league_not_included. The capture now goes through
the same league mapping built-in hint detection uses; text naming no known
league is kept as-is so the filter detail still shows what was captured.
"""

import pytest

from teamarr.consumers.matching.classifier import CustomRegexConfig, classify_stream
from teamarr.services import detection_keywords
from teamarr.services.detection_keywords import DetectionKeywordService


@pytest.fixture(autouse=True)
def seeded_leagues(db_factory, monkeypatch):
    """Point the detection service at a fully seeded temp database."""
    monkeypatch.setattr(detection_keywords, "get_db", db_factory)
    DetectionKeywordService.invalidate_cache()
    yield
    DetectionKeywordService.invalidate_cache()


@pytest.mark.parametrize(
    "captured,expected",
    [
        # The reporter's captures
        ("Premier League", "eng.1"),
        ("Bundesliga", "ger.1"),
        ("Serie A", "ita.1"),
        # Display names, case and whitespace insensitive
        ("English Premier League", "eng.1"),
        ("serie   a", "ita.1"),
        ("La Liga", "esp.1"),
        ("2. Bundesliga", "ger.2"),
        # A display name outranks the hint patterns: the `serie a` hint
        # must not claim the Brazilian league
        ("Brazilian Serie A", "bra.1"),
        # league_alias and league_id
        ("EPL", "eng.1"),
        ("laliga", "esp.1"),
        # Already canonical
        ("eng.1", "eng.1"),
        ("ITA.1", "ita.1"),
        # Hint patterns reached without a trailing delimiter
        ("Champions League", "uefa.champions"),
    ],
)
def test_resolves_capture_to_league_code(captured, expected):
    assert DetectionKeywordService.resolve_league_name(captured) == expected


@pytest.mark.parametrize("captured", ["Totally Made Up League", "", "   "])
def test_unknown_capture_resolves_to_none(captured):
    assert DetectionKeywordService.resolve_league_name(captured) is None


def _league_cfg(pattern: str) -> CustomRegexConfig:
    return CustomRegexConfig(league_pattern=pattern, league_enabled=True)


@pytest.mark.parametrize(
    "stream,expected",
    [
        ("Premier League | Arsenal vs Chelsea", "eng.1"),
        ("Bundesliga | Bayern Munich vs Dortmund", "ger.1"),
        ("Serie A | Inter vs Milan", "ita.1"),
    ],
)
def test_classifier_hint_is_canonical(stream, expected):
    classified = classify_stream(stream, custom_regex=_league_cfg(r"^(?P<league>[^|]+?)\s*\|"))
    assert classified.league_hint == expected


def test_classifier_keeps_unresolvable_capture():
    classified = classify_stream(
        "Obscure Cup | Alpha vs Beta",
        custom_regex=_league_cfg(r"^(?P<league>[^|]+?)\s*\|"),
    )
    assert classified.league_hint == "obscure cup"
