"""Tests for multi-sport hint support.

Validates that sport hints can map to multiple sports for ambiguous terms
like 'football' (Soccer + American Football) and 'main card' (MMA + Boxing).
"""

from teamarr.consumers.matching.team_matcher import _sport_hint_matches
from teamarr.services.detection_keywords import _parse_sport_target

# ---------------------------------------------------------------------------
# _parse_sport_target
# ---------------------------------------------------------------------------


class TestParseSportTarget:
    """Test parsing target_value from DB storage format."""

    def test_plain_string(self):
        assert _parse_sport_target("Hockey") == "Hockey"

    def test_json_array_multiple(self):
        assert _parse_sport_target('["Soccer", "Football"]') == ["Soccer", "Football"]

    def test_json_array_single_collapses(self):
        """Single-element arrays collapse to plain string."""
        assert _parse_sport_target('["Hockey"]') == "Hockey"

    def test_empty_string(self):
        assert _parse_sport_target("") == ""

    def test_invalid_json_fallback(self):
        """Bad JSON starting with [ falls back to plain string."""
        assert _parse_sport_target("[invalid") == "[invalid"

    def test_json_non_array_fallback(self):
        """JSON object (not array) falls back to plain string."""
        assert _parse_sport_target('{"sport": "Hockey"}') == '{"sport": "Hockey"}'

    def test_json_with_non_strings_rejected(self):
        """Mixed-type arrays fall back to plain string (invalid format)."""
        result = _parse_sport_target('["Hockey", 123, "Soccer"]')
        assert result == '["Hockey", 123, "Soccer"]'


# ---------------------------------------------------------------------------
# _sport_hint_matches
# ---------------------------------------------------------------------------


class TestSportHintMatches:
    """Test sport hint matching in the team matcher."""

    def test_single_hint_exact_match(self):
        assert _sport_hint_matches("Hockey", "Hockey") is True

    def test_single_hint_case_insensitive(self):
        assert _sport_hint_matches("hockey", "Hockey") is True
        assert _sport_hint_matches("HOCKEY", "hockey") is True

    def test_single_hint_no_match(self):
        assert _sport_hint_matches("Hockey", "Soccer") is False

    def test_multi_hint_matches_first(self):
        assert _sport_hint_matches(["Soccer", "Football"], "Soccer") is True

    def test_multi_hint_matches_second(self):
        assert _sport_hint_matches(["Soccer", "Football"], "Football") is True

    def test_multi_hint_case_insensitive(self):
        assert _sport_hint_matches(["Soccer", "Football"], "soccer") is True
        assert _sport_hint_matches(["Soccer", "Football"], "FOOTBALL") is True

    def test_multi_hint_no_match(self):
        assert _sport_hint_matches(["Soccer", "Football"], "Hockey") is False


# ---------------------------------------------------------------------------
# Built-in pattern ordering
# ---------------------------------------------------------------------------


class TestBuiltinPatternOrdering:
    """Test that built-in SPORT_HINT_PATTERNS produce correct results."""

    def test_bare_football_returns_multi(self):
        """Bare 'football' should return both Soccer and Football."""
        from teamarr.services.detection_keywords import DetectionKeywordService

        DetectionKeywordService.invalidate_cache()
        result = DetectionKeywordService.detect_sport("English Football League")
        assert isinstance(result, list)
        assert "Soccer" in result
        assert "Football" in result

    def test_nfl_returns_football_only(self):
        from teamarr.services.detection_keywords import DetectionKeywordService

        DetectionKeywordService.invalidate_cache()
        result = DetectionKeywordService.detect_sport("NFL: Chiefs vs Bills")
        assert result == "Football"

    def test_american_football_returns_football_only(self):
        from teamarr.services.detection_keywords import DetectionKeywordService

        DetectionKeywordService.invalidate_cache()
        result = DetectionKeywordService.detect_sport("American Football: Patriots vs Eagles")
        assert result == "Football"

    def test_college_football_returns_football_only(self):
        from teamarr.services.detection_keywords import DetectionKeywordService

        DetectionKeywordService.invalidate_cache()
        result = DetectionKeywordService.detect_sport("College Football: Ohio State vs Michigan")
        assert result == "Football"

    def test_soccer_returns_soccer_only(self):
        from teamarr.services.detection_keywords import DetectionKeywordService

        DetectionKeywordService.invalidate_cache()
        result = DetectionKeywordService.detect_sport("Soccer: LAFC vs Galaxy")
        assert result == "Soccer"

    def test_ncaaf_returns_football_only(self):
        from teamarr.services.detection_keywords import DetectionKeywordService

        DetectionKeywordService.invalidate_cache()
        result = DetectionKeywordService.detect_sport("NCAAF: Alabama vs Auburn")
        assert result == "Football"

    def test_hockey_unaffected(self):
        from teamarr.services.detection_keywords import DetectionKeywordService

        DetectionKeywordService.invalidate_cache()
        result = DetectionKeywordService.detect_sport("Ice Hockey: Bruins vs Rangers")
        assert result == "Hockey"

    def test_basketball_unaffected(self):
        from teamarr.services.detection_keywords import DetectionKeywordService

        DetectionKeywordService.invalidate_cache()
        result = DetectionKeywordService.detect_sport("Basketball: Lakers vs Celtics")
        assert result == "Basketball"


# ---------------------------------------------------------------------------
# Stream filter integration
# ---------------------------------------------------------------------------


class TestStreamFilterMultiSport:
    """Test that multi-sport hints don't incorrectly filter streams."""

    def test_football_not_filtered_as_unsupported(self):
        """'football' matches Soccer + Football, both supported — not filtered."""
        from teamarr.services.stream_filter import UNSUPPORTED_SPORTS, detect_sport_hint

        sport = detect_sport_hint("English Football League: Arsenal vs Chelsea")
        # Multi-sport hint — should NOT be filtered since Soccer and Football are supported
        sports = sport if isinstance(sport, list) else [sport] if sport else []
        assert not all(s in UNSUPPORTED_SPORTS for s in sports)
