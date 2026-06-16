"""Tests for NCAAB gender-aware stream classification (#150).

NCAAB streams should match both men's and women's college basketball.
Gender markers (W)/(M) in stream names should narrow the hint to the
correct league. The (W)/(M) markers should also be stripped from team names.
"""

from teamarr.consumers.matching.classifier import (
    _clean_team_name,
    _narrow_by_gender,
    detect_league_hint,
)
from teamarr.services.detection_keywords import DetectionKeywordService


class TestNcaabUmbrellaHint:
    """NCAAB hint should map to both men's and women's leagues."""

    def setup_method(self):
        """Clear compiled pattern cache before each test."""
        DetectionKeywordService.invalidate_cache()

    def test_ncaab_returns_list(self):
        result = detect_league_hint("NCAAB: Duke vs UNC")
        assert isinstance(result, list)
        assert "mens-college-basketball" in result
        assert "womens-college-basketball" in result

    def test_ncaam_returns_mens_only(self):
        result = detect_league_hint("NCAAM: Duke vs UNC")
        assert result == "mens-college-basketball"

    def test_ncaaw_returns_womens_only(self):
        result = detect_league_hint("NCAAW: South Carolina vs LSU")
        assert result == "womens-college-basketball"


class TestGenderNarrowing:
    """_narrow_by_gender should narrow umbrella hints using (W)/(M) markers."""

    def test_w_marker_narrows_to_womens(self):
        leagues = ["mens-college-basketball", "womens-college-basketball"]
        result = _narrow_by_gender(leagues, "NCAAB 216: SOUTH CAROLINA @ LSU (W)")
        assert result == "womens-college-basketball"

    def test_m_marker_narrows_to_mens(self):
        leagues = ["mens-college-basketball", "womens-college-basketball"]
        result = _narrow_by_gender(leagues, "NCAAB 100: Duke @ UNC (M)")
        assert result == "mens-college-basketball"

    def test_no_marker_keeps_full_list(self):
        leagues = ["mens-college-basketball", "womens-college-basketball"]
        result = _narrow_by_gender(leagues, "NCAAB 100: Duke @ UNC")
        assert result == leagues

    def test_non_gendered_leagues_unaffected(self):
        leagues = ["eng.2", "eng.3", "eng.4", "eng.fa"]
        result = _narrow_by_gender(leagues, "EFL: Portsmouth vs Southampton (W)")
        assert result == leagues

    def test_women_keyword(self):
        leagues = ["mens-college-basketball", "womens-college-basketball"]
        result = _narrow_by_gender(leagues, "NCAAB: Women: South Carolina @ LSU")
        assert result == "womens-college-basketball"

    def test_case_insensitive(self):
        leagues = ["mens-college-basketball", "womens-college-basketball"]
        result = _narrow_by_gender(leagues, "NCAAB 216: LSU (w)")
        assert result == "womens-college-basketball"


class TestGenderMarkerStripping:
    """(W) and (M) should be stripped from team names."""

    def test_strips_w_from_team_name(self):
        assert _clean_team_name("LSU (W)") == "LSU"

    def test_strips_m_from_team_name(self):
        assert _clean_team_name("Duke (M)") == "Duke"

    def test_strips_women_from_team_name(self):
        assert _clean_team_name("LSU (Women)") == "LSU"

    def test_strips_men_from_team_name(self):
        assert _clean_team_name("Duke (Men)") == "Duke"

    def test_preserves_other_parenthetical(self):
        # Round indicators are handled by a different pattern
        name = _clean_team_name("Team (CBS)")
        # CBS is a broadcast indicator, should also be stripped
        assert "CBS" not in name

    def test_case_insensitive(self):
        assert _clean_team_name("LSU (w)") == "LSU"


class TestEndToEndClassification:
    """Integration test for the full classification pipeline."""

    def setup_method(self):
        DetectionKeywordService.invalidate_cache()

    def test_ncaab_womens_stream_classified(self):
        """The exact stream from issue #150 should classify correctly."""
        from teamarr.consumers.matching.classifier import classify_stream

        result = classify_stream("NCAAB 216: 3 SOUTH CAROLINA @ 6 LSU (W) | 2.14 8:30 PM | ABC")

        # League hint should be narrowed to women's
        assert result.league_hint == "womens-college-basketball"
        # Team names should not contain (W)
        if result.team1:
            assert "(W)" not in result.team1
        if result.team2:
            assert "(W)" not in result.team2

    def test_ncaab_mens_stream_classified(self):
        from teamarr.consumers.matching.classifier import classify_stream

        result = classify_stream("NCAAB 100: Duke @ UNC (M) | 2.15 7:00 PM")

        assert result.league_hint == "mens-college-basketball"
        if result.team2:
            assert "(M)" not in result.team2

    def test_ncaab_no_gender_marker_keeps_umbrella(self):
        from teamarr.consumers.matching.classifier import classify_stream

        result = classify_stream("NCAAB: Duke @ UNC")

        # Should keep the umbrella hint (both leagues)
        assert isinstance(result.league_hint, list)
        assert "mens-college-basketball" in result.league_hint
        assert "womens-college-basketball" in result.league_hint


class TestSpanishGenderMarkers:
    """Spanish/Portuguese gender markers narrow umbrella hints like English ones.

    Non-English EPGs label gender as femenino/femenina/feminino (women) and
    masculino/masculina (men), or the (F) marker — not Women/Men/(W).
    """

    PAIR = ["mens-college-basketball", "womens-college-basketball"]

    def test_femenino_narrows_to_womens(self):
        assert _narrow_by_gender(self.PAIR, "Fútbol Femenino: España vs Italia") == (
            "womens-college-basketball"
        )

    def test_femenina_narrows_to_womens(self):
        assert _narrow_by_gender(self.PAIR, "Liga Femenina") == "womens-college-basketball"

    def test_portuguese_feminino_narrows_to_womens(self):
        assert _narrow_by_gender(self.PAIR, "Brasil Feminino") == "womens-college-basketball"

    def test_f_marker_narrows_to_womens(self):
        assert _narrow_by_gender(self.PAIR, "España (F)") == "womens-college-basketball"

    def test_masculino_narrows_to_mens(self):
        assert _narrow_by_gender(self.PAIR, "Liga Masculina") == "mens-college-basketball"

    def test_english_feminine_does_not_match(self):
        # "feminine" lacks the trailing o/a, so it must not trigger women's.
        assert _narrow_by_gender(self.PAIR, "Feminine Hygiene Show") == self.PAIR

    def test_menorca_does_not_match_mens(self):
        # "Men" inside "Menorca" must not trigger men's narrowing.
        assert _narrow_by_gender(self.PAIR, "Menorca CF vs Ibiza") == self.PAIR

    def test_strips_f_marker_from_team_name(self):
        assert _clean_team_name("España (F)") == "España"

    def test_strips_femenino_marker_from_team_name(self):
        assert _clean_team_name("Boca (Femenino)") == "Boca"

    def test_strips_masculino_marker_from_team_name(self):
        assert _clean_team_name("Madrid (Masculino)") == "Madrid"
