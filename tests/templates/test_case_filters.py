"""Case/identifier template filters + chaining + legacy aliases (#484).

The case family (|lower |upper |title |pascal |slug) joins |urlencode. Filters
chain left-to-right. The 10 retired pure-transform variables resolve forever
via resolver legacy aliases, with suffix carry-over and filter stacking.
"""

from teamarr.templates.filters import (
    filter_pascal,
    filter_slug,
    filter_title,
)
from teamarr.templates.resolver import TemplateResolver, rewrite_legacy_tokens

_VARS = {
    "team_name": "Detroit Tigers",
    "team_abbrev": "DET",
    "sport": "Australian Football",
    "result": "W",
    "home_team": "St. Louis Cardinals",
    "opponent_abbrev": "CHI",
    "opponent_abbrev.next": "MIN",
    "session_name": "Qualifying",
}


def _resolve(template: str) -> str:
    return TemplateResolver().resolve_with_map(template, _VARS)


class TestCaseFilters:
    def test_lower(self):
        assert _resolve("{team_abbrev|lower}") == "det"

    def test_upper(self):
        assert _resolve("{team_name|upper}") == "DETROIT TIGERS"

    def test_title(self):
        assert filter_title("ice hockey") == "Ice Hockey"
        assert filter_title("o'neill cup") == "O'Neill Cup"

    def test_pascal(self):
        assert _resolve("{team_name|pascal}") == "DetroitTigers"
        assert filter_pascal("D.C. United") == "DCUnited"
        assert filter_pascal("Atlético Madrid") == "AtleticoMadrid"

    def test_slug(self):
        assert _resolve("{home_team|slug}") == "st-louis-cardinals"
        assert filter_slug("Atlético  Madrid!") == "atletico-madrid"


class TestChaining:
    def test_left_to_right(self):
        assert _resolve("{team_name|pascal|urlencode}") == "DetroitTigers"
        assert _resolve("{home_team|slug|upper}") == "ST-LOUIS-CARDINALS"

    def test_unknown_filter_in_chain_stays_literal(self):
        assert _resolve("{team_name|pascal|nope}") == "{team_name|pascal|nope}"


class TestLegacyAliases:
    """The 10 retired variables render identically forever."""

    def test_simple_aliases(self):
        assert _resolve("{team_name_pascal}") == "DetroitTigers"
        assert _resolve("{team_abbrev_lower}") == "det"
        assert _resolve("{result_lower}") == "w"
        assert _resolve("{home_team_pascal}") == "StLouisCardinals"

    def test_sport_lower_is_slug(self):
        # sport_lower returned the hyphenated sport CODE, not the display name.
        assert _resolve("{sport_lower}") == "australian-football"

    def test_suffix_carries_over(self):
        assert _resolve("{opponent_abbrev_lower.next}") == "min"

    def test_alias_with_extra_filter(self):
        assert _resolve("{team_name_pascal|urlencode}") == "DetroitTigers"

    def test_unknown_lookalike_stays_literal(self):
        assert _resolve("{nope_pascal}") == "{nope_pascal}"


class TestRewriteLegacyTokens:
    """Textual old->new rewrite used by the v84 migration and seed comparison."""

    def test_basic(self):
        assert rewrite_legacy_tokens("{team_name_pascal}") == "{team_name|pascal}"

    def test_suffix_and_chain(self):
        assert (
            rewrite_legacy_tokens("{home_team_pascal.next|urlencode}")
            == "{home_team.next|pascal|urlencode}"
        )

    def test_rendering_identical_after_rewrite(self):
        template = "{team_name_pascal}.{sport_lower}-{opponent_abbrev_lower.next}"
        assert _resolve(template) == _resolve(rewrite_legacy_tokens(template))

    def test_untouched_text_passes_through(self):
        text = "{team_name} vs {opponent} (pascal) {team_name|pascal}"
        assert rewrite_legacy_tokens(text) == text
