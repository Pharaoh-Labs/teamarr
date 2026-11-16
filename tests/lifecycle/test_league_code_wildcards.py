"""The {league_id} and {league_abbrev} wildcards in group and profile patterns (#1207).

``{league}`` resolves the league's alias, which for most NCAA leagues is
already compact ("NCAAF", "NCAAM") but for others is a phrase — college
hockey's alias is "NCAA Hockey", so a profile pattern could never produce the
"NCAAH" a Dispatcharr group might be named.

Both wildcards read the league's stored short code (``leagues.league_id``):
``{league_id}`` as stored, like the template variable of the same name, and
``{league_abbrev}`` uppercased. The first version abbreviated the alias
(capitals plus word initials), which gave Bundesliga, Brasileirao and Boxing
the same value "B" — one Dispatcharr group for three unrelated leagues.
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
        "ger.1": "Bundesliga",
        "boxing": "Boxing",
    }
    r._league_ids = {
        "mens-college-hockey": "ncaah",
        "womens-college-hockey": "ncaawh",
        "nfl": "nfl",
        "eng.1": "epl",
        "ger.1": "bundesliga",
        "boxing": "boxing",
    }
    # Group/profile ids are the created name, so assertions read the resolved text.
    with (
        patch.object(r, "_get_or_create_group", side_effect=lambda n: n),
        patch.object(r, "_get_or_create_profile", side_effect=lambda n: n),
    ):
        yield r


class TestLeagueCodeWildcards:
    def test_ncaa_hockey(self, resolver):
        """The issue's case: NCAAH where {league} spells it out."""
        args = ("hockey", "mens-college-hockey")
        assert resolver.resolve_pattern("{league}", *args) == "NCAA Hockey"
        assert resolver.resolve_pattern("{league_abbrev}", *args) == "NCAAH"
        assert resolver.resolve_pattern("{league_id}", *args) == "ncaah"

    def test_womens_hockey(self, resolver):
        args = ("hockey", "womens-college-hockey")
        assert resolver.resolve_pattern("{league_abbrev}", *args) == "NCAAWH"

    def test_compact_codes(self, resolver):
        assert resolver.resolve_pattern("{league_abbrev}", "football", "nfl") == "NFL"
        assert resolver.resolve_pattern("{league_abbrev}", "soccer", "eng.1") == "EPL"
        assert resolver.resolve_pattern("{league_id}", "soccer", "eng.1") == "epl"

    def test_one_word_leagues_do_not_collapse_to_a_letter(self, resolver):
        """Abbreviating the alias gave both of these "B"."""
        assert resolver.resolve_pattern("{league_abbrev}", "soccer", "ger.1") == "BUNDESLIGA"
        assert resolver.resolve_pattern("{league_abbrev}", "boxing", "boxing") == "BOXING"

    def test_league_without_a_stored_code_uses_its_own_code(self, resolver):
        # A discovered league (league_cache only), like the template variable.
        assert resolver.resolve_pattern("{league_id}", "soccer", "swe.2") == "swe.2"
        assert resolver.resolve_pattern("{league_abbrev}", "soccer", "swe.2") == "SWE.2"

    def test_all_three_side_by_side(self, resolver):
        # The alternation must not stop short at the ``league`` prefix.
        assert (
            resolver.resolve_pattern(
                "{league}|{league_abbrev}|{league_id}", "hockey", "mens-college-hockey"
            )
            == "NCAA Hockey|NCAAH|ncaah"
        )

    def test_filter_chain_applies(self, resolver):
        args = ("hockey", "mens-college-hockey")
        assert resolver.resolve_pattern("{league_abbrev|lower}", *args) == "ncaah"
        assert resolver.resolve_pattern("{league_id|upper}", *args) == "NCAAH"

    def test_pattern_uses_distinguishes_them(self):
        assert pattern_uses("x {league_abbrev} y", "league_abbrev")
        assert not pattern_uses("x {league_abbrev} y", "league")
        assert pattern_uses("x {league_id} y", "league_id")
        assert not pattern_uses("x {league_id} y", "league")
        assert pattern_uses("x {league} y", "league")

    @pytest.mark.parametrize("token", ["{league_abbrev}", "{league_id}"])
    def test_empty_league_leaves_token_unresolved(self, resolver, token):
        out = resolver.resolve_pattern(token, "hockey", None)
        assert out == token
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
            ["{league_abbrev}", "{league_id}"], "hockey", "mens-college-hockey"
        )
        assert resolved == ["NCAAH", "ncaah"]

    def test_unresolved_falls_back_to_static_group(self, resolver):
        group = resolver.resolve_channel_group("{league_abbrev}", "static-1", "hockey", None)
        assert group == "static-1"

    def test_unresolved_skips_profile(self, resolver):
        resolved = resolver.resolve_channel_profiles(["{league_abbrev}"], "hockey", None)
        assert resolved == []


class TestAgainstTheRealLeagueTable:
    """The reason for reading the stored code: it names one league."""

    def test_every_league_has_its_own_code(self, db_factory):
        r = DynamicResolver()
        with db_factory() as conn:
            r._load_names(conn)
            codes = [row["league_code"] for row in conn.execute("SELECT league_code FROM leagues")]
        r._initialized = True
        assert len(codes) > 100
        values = [r.get_league_abbrev(code) for code in codes]
        assert all(values)
        assert len(set(values)) == len(values)

    def test_loaded_from_the_table(self, db_factory):
        r = DynamicResolver()
        with db_factory() as conn:
            r._load_names(conn)
        r._initialized = True
        assert r.get_league_id("mens-college-hockey") == "ncaah"
        assert r.get_league_abbrev("mens-college-hockey") == "NCAAH"
        assert r.get_league_abbrev("ger.1") == "BUNDESLIGA"
