"""Template filters in dynamic group and profile patterns (#1050).

``{sport}`` resolves to a Title Case display name ("Hockey") while ``{league}``
is usually an upper-case alias ("NHL"), so a pattern mixing them produced
"Baseball" beside "MLB". The same ``|filter`` chain templates take now works
on every wildcard: ``{sport|upper}`` → HOCKEY.
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
    r._sport_display_names = {"hockey": "Hockey", "soccer": "Soccer"}
    r._league_aliases = {"nhl": "NHL", "eng.1": "Premier League"}
    # Group/profile ids are the created name, so assertions read the resolved text.
    with (
        patch.object(r, "_get_or_create_group", side_effect=lambda n: n),
        patch.object(r, "_get_or_create_profile", side_effect=lambda n: n),
    ):
        yield r


class TestResolvePattern:
    def test_upper_filter_on_sport(self, resolver):
        out = resolver.resolve_pattern("{sport|upper} | {league}", "hockey", "nhl")
        assert out == "HOCKEY | NHL"

    def test_lower_and_title_filters(self, resolver):
        assert resolver.resolve_pattern("{league|lower}", "hockey", "nhl") == "nhl"
        assert resolver.resolve_pattern("{league|title}", "soccer", "eng.1") == "Premier League"

    def test_filters_chain_left_to_right(self, resolver):
        out = resolver.resolve_pattern("{league|lower|pascal}", "soccer", "eng.1")
        assert out == "PremierLeague"

    def test_filter_name_is_case_insensitive(self, resolver):
        assert resolver.resolve_pattern("{sport|UPPER}", "hockey", "nhl") == "HOCKEY"

    def test_unfiltered_patterns_are_unchanged(self, resolver):
        assert resolver.resolve_pattern("Sports | {sport} | {league}", "hockey", "nhl") == (
            "Sports | Hockey | NHL"
        )

    def test_every_wildcard_takes_a_filter(self, resolver):
        out = resolver.resolve_pattern(
            "{conference|upper}/{conference_abbrev|lower}/{division|slug}/{exception_keyword|upper}",
            "football",
            "college-football",
            conference="Big Ten Conference",
            division="FBS",
            conference_abbrev="Big Ten",
            exception_keyword="Spanish",
        )
        assert out == "BIG TEN CONFERENCE/big ten/fbs/SPANISH"

    def test_unknown_filter_keeps_the_token_literal(self, resolver):
        # Like templates: a typo stays visible instead of naming a group after it.
        out = resolver.resolve_pattern("{sport|uppper} | {league}", "hockey", "nhl")
        assert out == "{sport|uppper} | NHL"
        assert has_unresolved_wildcard(out)

    def test_empty_value_leaves_the_filtered_token_unresolved(self, resolver):
        out = resolver.resolve_pattern("{league} | {conference|upper}", "hockey", "nhl")
        assert out == "NHL | {conference|upper}"
        assert has_unresolved_wildcard(out)


class TestHelpers:
    def test_pattern_uses_sees_through_filters(self):
        assert pattern_uses("{league} | {conference_abbrev|upper}", "conference_abbrev")
        assert not pattern_uses("{league} | {conference_abbrev|upper}", "conference")
        assert pattern_uses("{conference}", "conference")

    def test_unresolved_only_for_known_wildcards(self):
        assert not has_unresolved_wildcard("Hockey | {something_else}")
        assert has_unresolved_wildcard("Hockey | {league|upper}")


class TestGroupAndProfileResolution:
    def test_group_pattern_with_filter_creates_the_upper_case_group(self, resolver):
        assert resolver.resolve_channel_group("{sport|upper}", 7, "hockey", "nhl") == "HOCKEY"

    def test_group_pattern_with_unknown_filter_falls_back_to_static(self, resolver):
        assert resolver.resolve_channel_group("{sport|nope}", 7, "hockey", "nhl") == 7

    def test_profile_pattern_with_filter(self, resolver):
        assert resolver.resolve_channel_profiles(["{league|lower}"], "hockey", "nhl") == ["nhl"]

    def test_profile_pattern_with_unresolvable_wildcard_is_skipped(self, resolver):
        # Profiles never get conference data; a filtered token must not
        # create a profile literally named "{conference|upper}".
        assert resolver.resolve_channel_profiles(["{conference|upper}"], "hockey", "nhl") == []
