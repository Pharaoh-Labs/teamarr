"""Tests for live-broadcast status prefix stripping (i18n EPG matching).

Non-English EPG feeds prepend live-status words to the matchup
("DIRECTO España - Inglaterra"). Left in place they leak into the first team
("DIRECTO España"). These tokens must be stripped during normalization, while
real team names that merely start with the same letters stay intact.

English "live" is intentionally NOT stripped — it collides with team names like
"Live Oak FC". See LIVE_STATUS_PREFIXES in teamarr/utilities/constants.py.
"""

from teamarr.consumers.matching.normalizer import (
    normalize_stream,
    strip_live_status_prefix,
)


class TestStripLiveStatusPrefix:
    """Unit coverage for the strip function itself."""

    def test_spanish_directo(self):
        out, removed = strip_live_status_prefix("DIRECTO España - Inglaterra")
        assert out == "España - Inglaterra"
        assert removed == "DIRECTO"

    def test_spanish_en_directo_multiword(self):
        # Multi-word form wins over a bare "directo".
        out, removed = strip_live_status_prefix("EN DIRECTO España vs Inglaterra")
        assert out == "España vs Inglaterra"
        assert removed == "EN DIRECTO"

    def test_spanish_en_vivo(self):
        out, removed = strip_live_status_prefix("EN VIVO Boca vs River")
        assert out == "Boca vs River"
        assert removed == "EN VIVO"

    def test_portuguese_ao_vivo(self):
        out, removed = strip_live_status_prefix("AO VIVO Flamengo x Palmeiras")
        assert out == "Flamengo x Palmeiras"
        assert removed == "AO VIVO"

    def test_italian_diretta(self):
        out, removed = strip_live_status_prefix("DIRETTA Juventus - Milan")
        assert out == "Juventus - Milan"
        assert removed == "DIRETTA"

    def test_german_direkt(self):
        out, removed = strip_live_status_prefix("Direkt Malmö - AIK")
        assert out == "Malmö - AIK"
        assert removed == "Direkt"

    def test_strips_trailing_separator_punctuation(self):
        out, removed = strip_live_status_prefix("DIRECTO: España vs Inglaterra")
        assert out == "España vs Inglaterra"
        assert removed == "DIRECTO:"

    def test_matchup_separator_left_untouched(self):
        # Only the leading whitespace after the token is consumed; the " - "
        # matchup separator further along must survive for the classifier.
        out, _ = strip_live_status_prefix("DIRECTO España - Inglaterra")
        assert " - " in out

    def test_no_prefix_passthrough(self):
        out, removed = strip_live_status_prefix("Real Madrid - Barcelona")
        assert out == "Real Madrid - Barcelona"
        assert removed is None

    def test_word_boundary_protects_embedded_letters(self):
        # "directo..." with no boundary must not strip (defensive).
        out, removed = strip_live_status_prefix("Directos United vs City")
        assert removed is None
        assert out == "Directos United vs City"

    def test_english_live_not_stripped(self):
        # English "live" is excluded to avoid "Live Oak FC" collisions.
        out, removed = strip_live_status_prefix("Live Oak FC vs Austin")
        assert removed is None
        assert out == "Live Oak FC vs Austin"

    def test_empty_string(self):
        assert strip_live_status_prefix("") == ("", None)


class TestNormalizePipelineIntegration:
    """The full normalize_stream pipeline applies the strip at step 2."""

    def test_directo_removed_in_pipeline(self):
        result = normalize_stream("DIRECTO España - Inglaterra")
        assert not result.normalized.lower().startswith("directo")
        assert "España" in result.normalized or "Espana" in result.normalized

    def test_stacked_provider_and_live_either_order(self):
        # "DAZN DIRECTO ..." and "DIRECTO DAZN ..." both fully strip.
        a = normalize_stream("DAZN DIRECTO Real Madrid - Barcelona").normalized
        b = normalize_stream("DIRECTO DAZN Real Madrid - Barcelona").normalized
        assert "directo" not in a.lower() and "dazn" not in a.lower()
        assert "directo" not in b.lower() and "dazn" not in b.lower()

    def test_no_prefix_unchanged(self):
        result = normalize_stream("Real Madrid - Barcelona")
        assert "Real Madrid" in result.normalized
