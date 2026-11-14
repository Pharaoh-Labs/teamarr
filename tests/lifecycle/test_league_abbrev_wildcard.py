"""The {league_abbrev} wildcard in dynamic group and profile patterns (#1207).

``{league}`` resolves the league's alias, which for most NCAA leagues is
already compact ("NCAAF", "NCAAM") but for others is a phrase — college
hockey's alias is "NCAA Hockey", so a profile pattern could never produce the
"NCAAH" a Dispatcharr group might be named. ``{league_abbrev}`` abbreviates
that same alias the way the ``{league_abbrev}`` template variable does
(existing capitals plus the first letter of every word), so the wildcard and
the template variable can never disagree.
"""

from unittest.mock import patch

import pytest

from teamarr.consumers.lifecycle.dynamic_resolver import (
    DynamicResolver,
    has_unresolved_wildcard,
    pattern_uses,
)


@pytest.fixture
def resolver():
    r = DynamicResolver()
    r._initialized = True
    r._sport_display_names = {"hockey": "Hockey"}
    r._league_aliases = {
        "mens-college-hockey": "NCAA Hockey",
        "womens-college-hockey": "NCAA W Hockey",
        "nfl": "NFL",
        "eng.1": "EPL",
        "college-baseball": "NCAA Baseball",  # alias NULL → display_name fallback
    }
    # Group/profile ids are the created name, so assertions read the resolved text.
    with (
        patch.object(r, "_get_or_create_group", side_effect=lambda n: n),
        patch.object(r, "_get_or_create_profile", side_effect=lambda n: n),
    ):
        yield r


class TestLeagueAbbrevWildcard:
    def test_ncaa_hockey_abbreviates(self, resolver):
        """The issue's case: 'NCAA Hockey' → NCAAH where {league} spells it out."""
        assert resolver.resolve_pattern("{league}", "hockey", "mens-college-hockey") == (
            "NCAA Hockey"
        )
        assert resolver.resolve_pattern("{league_abbrev}", "hockey", "mens-college-hockey") == (
            "NCAAH"
        )

    def test_womens_hockey_abbreviates(self, resolver):
        assert resolver.resolve_pattern("{league_abbrev}", "hockey", "womens-college-hockey") == (
            "NCAAWH"
        )

    def test_compact_alias_passes_through(self, resolver):
        assert resolver.resolve_pattern("{league_abbrev}", "football", "nfl") == "NFL"
        assert resolver.resolve_pattern("{league_abbrev}", "soccer", "eng.1") == "EPL"

    def test_display_name_fallback_abbreviates(self, resolver):
        # college-baseball's alias is its display name; same chain the template
        # variable walks (alias → display_name).
        assert resolver.resolve_pattern("{league_abbrev}", "baseball", "college-baseball") == (
            "NCAAB"
        )

    def test_unknown_league_abbreviates_the_code(self, resolver):
        assert resolver.resolve_pattern("{league_abbrev}", "soccer", "swe.2") == "SWE2"

    def test_league_and_abbrev_side_by_side(self, resolver):
        # The alternation must not stop short at the ``league`` prefix.
        assert (
            resolver.resolve_pattern("{league}|{league_abbrev}", "hockey", "mens-college-hockey")
            == "NCAA Hockey|NCAAH"
        )

    def test_filter_chain_applies(self, resolver):
        assert resolver.resolve_pattern(
            "{league_abbrev|lower}", "hockey", "mens-college-hockey"
        ) == ("ncaah")

    def test_pattern_uses_distinguishes_the_two(self):
        assert pattern_uses("x {league_abbrev} y", "league_abbrev")
        assert not pattern_uses("x {league_abbrev} y", "league")
        assert pattern_uses("x {league} y", "league")

    def test_empty_league_leaves_token_unresolved(self, resolver):
        out = resolver.resolve_pattern("{league_abbrev}", "hockey", None)
        assert out == "{league_abbrev}"
        assert has_unresolved_wildcard(out)


class TestResolutionPaths:
    def test_group_pattern_resolves(self, resolver):
        group = resolver.resolve_channel_group(
            "{league_abbrev}", "static-1", "hockey", "mens-college-hockey"
        )
        assert group == "NCAAH"

    def test_group_pattern_mixed_with_sport(self, resolver):
        group = resolver.resolve_channel_group(
            "{sport} | {league_abbrev}", "static-1", "hockey", "mens-college-hockey"
        )
        assert group == "Hockey | NCAAH"

    def test_profile_pattern_resolves(self, resolver):
        resolved = resolver.resolve_channel_profiles(
            ["{league_abbrev}"], "hockey", "mens-college-hockey"
        )
        assert resolved == ["NCAAH"]

    def test_unresolved_abbrev_falls_back_to_static_group(self, resolver):
        group = resolver.resolve_channel_group("{league_abbrev}", "static-1", "hockey", None)
        assert group == "static-1"

    def test_unresolved_abbrev_skips_profile(self, resolver):
        resolved = resolver.resolve_channel_profiles(["{league_abbrev}"], "hockey", None)
        assert resolved == []
