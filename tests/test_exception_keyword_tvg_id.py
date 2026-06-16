"""Tests for exception keyword EPG uniqueness (teamarrv2-a6b).

Verifies that:
1. generate_event_tvg_id produces unique IDs per exception keyword
2. slugify_keyword sanitizes labels correctly
3. TemplateContext extra_vars override registered extractors
4. Backward compatibility: no keyword = unchanged tvg-id
"""

from unittest.mock import patch

import pytest

from teamarr.consumers.lifecycle.types import generate_event_tvg_id, slugify_keyword
from teamarr.templates.context import TeamChannelContext, TemplateContext
from teamarr.templates.resolver import TemplateResolver

# =============================================================================
# SLUGIFY KEYWORD
# =============================================================================


class TestSlugifyKeyword:
    """Test keyword → slug conversion for tvg-id safety."""

    def test_simple_word(self):
        assert slugify_keyword("Spanish") == "spanish"

    def test_multi_word(self):
        assert slugify_keyword("Peyton and Eli") == "peyton-and-eli"

    def test_alphanumeric(self):
        assert slugify_keyword("4K HDR") == "4k-hdr"

    def test_parenthesized(self):
        assert slugify_keyword("(ESP)") == "esp"

    def test_leading_trailing_whitespace(self):
        assert slugify_keyword("  French  ") == "french"

    def test_special_chars(self):
        assert slugify_keyword("En Español") == "en-espa-ol"

    def test_unicode_cjk(self):
        # CJK characters are non-alphanumeric and get replaced with hyphens
        result = slugify_keyword("中文")
        assert result == ""  # All non-ascii-alnum chars stripped

    def test_empty_string(self):
        assert slugify_keyword("") == ""


# =============================================================================
# GENERATE EVENT TVG ID
# =============================================================================


class TestGenerateEventTvgId:
    """Test tvg-id generation with exception keyword support.

    All five parameters are required (no defaults on discriminators). This is
    intentional — tests pass explicit None to document which discriminators
    each scenario exercises and which it intentionally omits, mirroring the
    discipline production callers must follow.
    """

    def test_basic_no_keyword(self):
        assert (
            generate_event_tvg_id("401547679", "espn", None, None, None)
            == "teamarr-event-401547679"
        )

    def test_with_segment(self):
        result = generate_event_tvg_id("401547679", "espn", "prelims", None, None)
        assert result == "teamarr-event-401547679-prelims"

    def test_with_keyword(self):
        result = generate_event_tvg_id("401547679", "espn", None, "Spanish", None)
        assert result == "teamarr-event-401547679-spanish"

    def test_with_segment_and_keyword(self):
        result = generate_event_tvg_id("401547679", "espn", "main_card", "French", None)
        assert result == "teamarr-event-401547679-main_card-french"

    def test_none_keyword_same_as_no_keyword(self):
        assert generate_event_tvg_id("123", "espn", None, None, None) == "teamarr-event-123"

    def test_empty_keyword_same_as_no_keyword(self):
        assert generate_event_tvg_id("123", "espn", None, "", None) == "teamarr-event-123"

    def test_different_keywords_produce_different_ids(self):
        id_spanish = generate_event_tvg_id("123", "espn", None, "Spanish", None)
        id_french = generate_event_tvg_id("123", "espn", None, "French", None)
        id_none = generate_event_tvg_id("123", "espn", None, None, None)
        assert id_spanish != id_french
        assert id_spanish != id_none
        assert id_french != id_none

    def test_multi_word_keyword(self):
        result = generate_event_tvg_id("123", "espn", None, "4K HDR", None)
        assert result == "teamarr-event-123-4k-hdr"

    def test_with_feed_team_id(self):
        result = generate_event_tvg_id("401547679", "espn", None, None, "23")
        assert result == "teamarr-event-401547679-feed-23"

    def test_feed_team_id_distinct_from_no_feed(self):
        # Same event, three feed scenarios — must produce three distinct tvg_ids
        # so XMLTV channel/programme entries don't collide and Dispatcharr can
        # show the correct EPG for each feed-separated channel.
        no_feed = generate_event_tvg_id("401", "espn", None, None, None)
        home_feed = generate_event_tvg_id("401", "espn", None, None, "10")
        away_feed = generate_event_tvg_id("401", "espn", None, None, "20")
        assert no_feed != home_feed != away_feed != no_feed
        assert no_feed == "teamarr-event-401"
        assert home_feed == "teamarr-event-401-feed-10"
        assert away_feed == "teamarr-event-401-feed-20"

    def test_feed_team_id_combines_with_segment_and_keyword(self):
        result = generate_event_tvg_id("401", "espn", "prelims", "Spanish", "23")
        assert result == "teamarr-event-401-prelims-spanish-feed-23"

    def test_none_feed_team_id_unchanged(self):
        # Backwards compat: no feed_team_id matches the pre-fix tvg_id format
        assert generate_event_tvg_id("123", "espn", None, None, None) == "teamarr-event-123"

    def test_feed_team_id_slugified(self):
        # Provider IDs are usually numeric but the function accepts strings —
        # if a provider ever uses a non-slug-safe ID, slugify guards it.
        result = generate_event_tvg_id("123", "espn", None, None, "ABC.42")
        assert result == "teamarr-event-123-feed-abc-42"

    def test_missing_args_is_typeerror(self):
        # Required-args discipline: catching the v2.4.4-style miss at write time.
        import pytest

        with pytest.raises(TypeError):
            generate_event_tvg_id("123")  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            generate_event_tvg_id("123", "espn", None, None)  # type: ignore[call-arg]


# =============================================================================
# TEMPLATE CONTEXT EXTRA_VARS
# =============================================================================


class TestTemplateContextExtraVars:
    """Test that extra_vars on TemplateContext override registered extractors.

    Uses mock on _build_all_variables to avoid needing full service initialization
    (LeagueMappingService, etc.). We only test the extra_vars merge behavior.
    """

    @pytest.fixture
    def minimal_context(self):
        """Create a minimal TemplateContext for testing."""
        return TemplateContext(
            game_context=None,
            team_config=TeamChannelContext(
                team_name="Test",
                team_abbrev="TST",
                team_id="1",
                league="nba",
                sport="basketball",
            ),
            team_stats=None,
        )

    def _make_build_vars(self, base_vars: dict):
        """Create a mock _build_all_variables that returns base_vars + extra_vars."""

        def build(ctx):
            variables = dict(base_vars)
            if ctx.extra_vars:
                for key, val in ctx.extra_vars.items():
                    variables[key.lower()] = val
            return variables

        return build

    def test_extra_vars_default_empty(self, minimal_context):
        assert minimal_context.extra_vars == {}

    def test_extra_vars_override_registered_variable(self, minimal_context):
        """exception_keyword extractor returns '' but extra_vars should override."""
        resolver = TemplateResolver()
        mock_build = self._make_build_vars({"exception_keyword": ""})

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            # Without extra_vars: exception_keyword resolves to ""
            result_without = resolver.resolve("{exception_keyword}", minimal_context)
            assert result_without == ""

            # With extra_vars: exception_keyword resolves to "Spanish"
            minimal_context.extra_vars = {"exception_keyword": "Spanish"}
            result_with = resolver.resolve("{exception_keyword}", minimal_context)
            assert result_with == "Spanish"

    def test_extra_vars_in_title_template(self, minimal_context):
        """Verify exception_keyword works in title-style templates."""
        resolver = TemplateResolver()
        minimal_context.extra_vars = {"exception_keyword": "French"}
        mock_build = self._make_build_vars({"exception_keyword": ""})

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            result = resolver.resolve("Game ({exception_keyword})", minimal_context)
        assert result == "Game (French)"

    def test_extra_vars_empty_keyword_cleaned_up(self, minimal_context):
        """Empty exception_keyword should produce clean output (no empty parens)."""
        resolver = TemplateResolver()
        minimal_context.extra_vars = {"exception_keyword": ""}
        mock_build = self._make_build_vars({"exception_keyword": ""})

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            result = resolver.resolve("Game ({exception_keyword})", minimal_context)
        # Resolver cleans up empty wrappers
        assert result == "Game"

    def test_extra_vars_case_insensitive(self, minimal_context):
        """Variable lookup is case-insensitive."""
        resolver = TemplateResolver()
        minimal_context.extra_vars = {"Exception_Keyword": "Spanish"}
        mock_build = self._make_build_vars({"exception_keyword": ""})

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            result = resolver.resolve("{exception_keyword}", minimal_context)
        assert result == "Spanish"

    def test_extra_vars_mixed_with_regular_variables(self, minimal_context):
        """Extra vars work alongside normal template variables."""
        resolver = TemplateResolver()
        minimal_context.extra_vars = {"exception_keyword": "Spanish"}
        mock_build = self._make_build_vars(
            {
                "exception_keyword": "",
                "home_team": "Lakers",
                "away_team": "Celtics",
            }
        )

        with patch.object(resolver, "_build_all_variables", side_effect=mock_build):
            result = resolver.resolve(
                "{away_team} @ {home_team} ({exception_keyword})", minimal_context
            )
        assert result == "Celtics @ Lakers (Spanish)"
