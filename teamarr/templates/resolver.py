"""Template variable resolver.

Resolves {variable} placeholders in template strings using registered extractors.
Supports three suffix types: base, .next, .last

Also supports conditional descriptions - selecting the best template based on
game conditions (is_home, win_streak, etc.) and priority.
"""

import logging
import re
from typing import Any

from teamarr.templates.conditions import get_condition_selector
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.filters import FILTERS
from teamarr.templates.variables import SuffixRules, get_registry
from teamarr.utilities.art_url import apply_art_base_url

logger = logging.getLogger(__name__)

# Pattern matches: {variable}, {variable.next}, {variable.last}, and an optional
# chain of trailing `|filter` modifiers (e.g. {race_name|urlencode},
# {team_name|pascal|url} — applied left-to-right, #484). Group 1 is the
# variable token (name + optional suffix); group 2 is the filter chain, if any.
# Note: @ is allowed to support {vs_@} variable.
VARIABLE_PATTERN = re.compile(
    r"\{([a-z_][a-z0-9_@]*(?:\.[a-z]+)?)((?:\|[a-z_]+)*)\}", re.IGNORECASE
)

# Retired pure-transform variables (#484) resolve FOREVER as base|filter so
# pre-migration backups, Discord-shared templates, and community guides keep
# working. They are gone from the picker, docs, and the variable count — but
# never from here. sport_lower maps to |slug (not |lower) because it returned
# the hyphenated sport CODE ('australian-football'), not the display name.
_LEGACY_ALIASES: dict[str, tuple[str, str]] = {
    "team_name_pascal": ("team_name", "pascal"),
    "home_team_pascal": ("home_team", "pascal"),
    "away_team_pascal": ("away_team", "pascal"),
    "team_abbrev_lower": ("team_abbrev", "lower"),
    "home_team_abbrev_lower": ("home_team_abbrev", "lower"),
    "away_team_abbrev_lower": ("away_team_abbrev", "lower"),
    "opponent_abbrev_lower": ("opponent_abbrev", "lower"),
    "feed_team_abbrev_lower": ("feed_team_abbrev", "lower"),
    "result_lower": ("result", "lower"),
    "sport_lower": ("sport", "slug"),
}


def rewrite_legacy_tokens(text: str) -> str:
    """Rewrite retired transform tokens to their base|filter form (#484).

    ``{team_name_pascal}`` -> ``{team_name|pascal}``; suffixes carry over and
    an existing filter chain stays appended. Rendering is identical either way
    (the resolver aliases the old names forever) — this exists for comparison
    and migration paths that need old- and new-form text to look the same.
    """
    for old, (new, filt) in _LEGACY_ALIASES.items():
        text = re.sub(
            r"\{" + old + r"(\.[a-z]+)?((?:\|[a-z_]+)*)\}",
            r"{" + new + r"\g<1>|" + filt + r"\g<2>}",
            text,
            flags=re.IGNORECASE,
        )
    return text


class TemplateResolver:
    """Resolves template variables in strings.

    Usage:
        resolver = TemplateResolver()
        result = resolver.resolve("{team_name} vs {opponent}", context)
        # -> "Detroit Lions vs Chicago Bears"

        # Conditional descriptions
        options = '[{"condition": "is_home", "priority": 50, "template": "Home: {team_name}"}]'
        result = resolver.resolve_conditional(options, context)
    """

    def __init__(self, art_base_url: str = "") -> None:
        self._registry = get_registry()
        self._condition_selector = get_condition_selector()
        # Game-thumbs base URL (epic z02s), applied by resolve_art() so every art
        # sink (EPG icon, Dispatcharr channel logo, fillers) reconstructs URLs the
        # same way. Empty = no prefixing.
        self.art_base_url = art_base_url or ""

    def build_variables(self, context: TemplateContext) -> dict[str, str]:
        """Materialize the full variable map for a context.

        Every ``resolve()`` runs all 252 registered extractors (plus their
        ``.next``/``.last`` suffixes) from scratch, but one programme resolves
        five to eight fields — title, subtitle, description, art, each
        category — against a context that does not change between them. Callers
        rendering a whole programme can build the map once here and pass it to
        each ``resolve``/``resolve_art`` call as ``variables=``.

        Deliberately a returned value rather than a cache on the resolver: a
        single ``TemplateResolver`` is shared across the team scan's worker
        threads, so resolver-held state would be a data race.
        """
        return self._build_all_variables(context)

    def resolve_art(
        self,
        template: str,
        context: TemplateContext,
        variables: dict[str, str] | None = None,
    ) -> str:
        """Resolve an art/icon field, then apply the game-thumbs base URL.

        The single entry point for ALL art/logo URLs so the base-URL reconstruction
        happens in one place and propagates to every consumer. Relative paths get
        the base prefixed; absolute URLs pass through unchanged (idempotent).
        """

        return (
            apply_art_base_url(
                self.resolve(template, context, variables=variables), self.art_base_url
            )
            or ""
        )

    def resolve(
        self,
        template: str,
        context: TemplateContext,
        variables: dict[str, str] | None = None,
    ) -> str:
        """Replace all {variable} placeholders with values.

        Args:
            template: String with {variable} placeholders
            context: Complete template context
            variables: Optional pre-built map from :meth:`build_variables` for
                this same context, so a run of resolves over one programme
                does not rebuild it per field.

        Returns:
            String with all variables resolved
        """
        if not template:
            return ""

        # Build all variables (base + suffixed)
        if variables is None:
            variables = self._build_all_variables(context)
        return self.resolve_with_map(template, variables)

    def resolve_with_map(self, template: str, variables: dict[str, str]) -> str:
        """Replace {variable} placeholders from a pre-built name -> value map.

        The substitution/cleanup core of resolve(), exposed for callers that
        have a variable map but no TemplateContext — e.g. the preview endpoint
        rendering against static sample data (#357). Unknown variables stay
        literal; known-but-empty values are replaced then cleaned up, exactly
        as in context-based resolution.
        """
        if not template:
            return ""

        unreplaced = []

        def replace(match: re.Match) -> str:
            var_name = match.group(1).lower()
            # Filter chain: "|pascal|url" -> ["pascal", "url"], applied
            # left-to-right (#484).
            filter_names = [f for f in (match.group(2) or "").lower().split("|") if f]

            # Keep unknown variables literal (helps users identify typos)
            # Known variables with empty values still get replaced with ""
            legacy = None
            if var_name not in variables:
                legacy = self._resolve_legacy_alias(var_name, variables)
            if var_name in variables:
                value = variables[var_name]
            elif legacy is not None:
                # Retired transform variable (#484): resolve the base and
                # prepend its implied filter to the chain.
                value, alias_filter = legacy
                filter_names.insert(0, alias_filter)
            elif self._is_contextless_suffix(var_name):
                # A VALID registry variable with a LEGAL suffix that's simply
                # missing its game context (no next/last game — offseason,
                # season end) resolves to empty like any known-but-empty value
                # (#418) — raw {game_time.next} braces must never reach a real
                # guide. Typos and illegal suffix usage (e.g. .next on a
                # BASE_ONLY variable) still stay literal.
                value = ""
            else:
                unreplaced.append(var_name)
                return match.group(0)  # Return original {variable} unchanged

            # Apply the `|filter` chain (e.g. |urlencode #478, |pascal #484).
            # An unknown filter anywhere in the chain is treated like a typo:
            # keep the whole token literal so the author can see and fix it,
            # rather than silently dropping it.
            for filter_name in filter_names:
                filter_fn = FILTERS.get(filter_name)
                if filter_fn is None:
                    unreplaced.append(match.group(0))
                    return match.group(0)
                value = filter_fn(value)
            return value

        result = VARIABLE_PATTERN.sub(replace, template)

        if unreplaced:
            logger.debug("[UNREPLACED] Template variables: %s", unreplaced)

        # Clean up artifacts from empty variables (e.g., double spaces, empty wrappers)
        result = self._cleanup_result(result)

        return result

    def _resolve_legacy_alias(
        self, var_name: str, variables: dict[str, str]
    ) -> tuple[str, str] | None:
        """Resolve a retired transform variable (#484) to (base value, filter).

        ``team_name_pascal`` -> value of ``team_name`` + implied ``pascal``;
        suffixes carry over (``home_team_pascal.next`` -> ``home_team.next``).
        Returns None when var_name isn't a legacy alias or its base can't
        resolve — the caller then falls through to the normal literal path.
        """
        base, sep, suffix = var_name.partition(".")
        alias = _LEGACY_ALIASES.get(base)
        if alias is None:
            return None
        real_name = alias[0] + (sep + suffix if sep else "")
        if real_name in variables:
            return variables[real_name], alias[1]
        if self._is_contextless_suffix(real_name):
            return "", alias[1]
        return None

    def _is_contextless_suffix(self, var_name: str) -> bool:
        """True for a valid variable + legal suffix that lacks game context.

        ``{game_time.next}`` when there is no next game is valid authoring —
        the context is missing, not the variable. Anything else absent from
        the map (unknown base name, illegal suffix for the variable's rules)
        is a template error and must stay literal so the author can see it.
        """
        base, sep, suffix = var_name.partition(".")
        if not sep or suffix not in ("next", "last"):
            return False
        var_def = self._registry.get(base)
        if var_def is None:
            return False
        if suffix == "next":
            return var_def.suffix_rules in (SuffixRules.ALL, SuffixRules.BASE_NEXT_ONLY)
        return var_def.suffix_rules in (SuffixRules.ALL, SuffixRules.LAST_ONLY)

    def _cleanup_result(self, text: str) -> str:
        """Clean up artifacts left when variables resolve to empty strings.

        Removes:
        - Empty parentheses/brackets: () []
        - Multiple consecutive spaces
        - Leading/trailing whitespace
        """
        # Collapse runs of spaces first so wrapper removal sees at most one
        # space in any position — keeps the patterns below bounded (no adjacent
        # unbounded quantifiers; CodeQL py/polynomial-redos).
        text = re.sub(r" {2,}", " ", text)

        # Remove empty parentheses and brackets
        text = re.sub(r" ?\( ?\)", "", text)
        text = re.sub(r" ?\[ ?\]", "", text)

        # Wrapper removal can leave one double space behind ("a () b" -> "a  b")
        text = re.sub(r" {2,}", " ", text)

        text = text.strip()

        # Article-aware vars ({team_name_the}, {tournament_name_the}) emit a
        # lowercase "the " for mid-sentence use; capitalize it when it opens
        # the rendered text (Gracenote: "The Washington Mystics play…").
        if text.startswith("the "):
            text = f"T{text[1:]}"

        return text

    def build_variable_map(self, ctx: TemplateContext) -> dict[str, str]:
        """Public: resolve every registered variable for a context.

        Returns the full name -> value map (including .next/.last suffixes),
        the same map used internally during resolution. Useful for previewing
        a real event against every variable (live sample data).
        """
        return self._build_all_variables(ctx)

    def _build_all_variables(self, ctx: TemplateContext) -> dict[str, str]:
        """Build complete variable dict with all suffixes.

        Generates up to 3 values per variable:
        - base (no suffix): from ctx.game_context
        - .next suffix: from ctx.next_game
        - .last suffix: from ctx.last_game

        Suffix generation follows each variable's SuffixRules.
        """
        variables: dict[str, str] = {}

        for var_def in self._registry.all_variables():
            rules = var_def.suffix_rules

            # Base variable (current game)
            if rules != SuffixRules.LAST_ONLY:
                value = var_def.extractor(ctx, ctx.game_context)
                variables[var_def.name] = value

            # .next suffix
            if rules in (SuffixRules.ALL, SuffixRules.BASE_NEXT_ONLY):
                if ctx.next_game:
                    value = var_def.extractor(ctx, ctx.next_game)
                    variables[f"{var_def.name}.next"] = value

            # .last suffix
            if rules in (SuffixRules.ALL, SuffixRules.LAST_ONLY):
                if ctx.last_game:
                    value = var_def.extractor(ctx, ctx.last_game)
                    variables[f"{var_def.name}.last"] = value

        # Merge extra_vars (override extractor values for injected variables)
        if ctx.extra_vars:
            for key, val in ctx.extra_vars.items():
                variables[key.lower()] = val

        return variables

    def resolve_conditional(
        self,
        description_options: str | list[dict[str, Any]] | None,
        context: TemplateContext,
        game_ctx: GameContext | None = None,
        variables: dict[str, str] | None = None,
    ) -> str:
        """Select and resolve a conditional description.

        Evaluates conditions against the game context to select the best
        template, then resolves variables in that template.

        Args:
            description_options: JSON string or list of description options.
                Each option has: condition, condition_value, priority, template
            context: Template context
            game_ctx: Game context for condition evaluation.
                If None, uses context.game_context.
            variables: Optional pre-built map from :meth:`build_variables`.

        Returns:
            Resolved description string, or empty string if no match.

        Example:
            options = [
                {"condition": "win_streak", "condition_value": "5", "priority": 10,
                 "template": "{team_name} on a {win_streak}-game win streak!"},
                {"condition": "is_home", "priority": 50,
                 "template": "{team_name} hosts {opponent}"},
                {"priority": 100, "template": "{team_name} vs {opponent}"}  # Fallback
            ]
            result = resolver.resolve_conditional(options, ctx)
        """
        if game_ctx is None:
            game_ctx = context.game_context

        # Select the best template based on conditions
        template = self._condition_selector.select(description_options, context, game_ctx)

        if not template:
            logger.debug("[CONDITION] No matching template found")
            return ""

        # Resolve variables in the selected template
        return self.resolve(template, context, variables=variables)

    def get_available_variables(self) -> list[str]:
        """Get list of all registered variable names."""
        return [v.name for v in self._registry.all_variables()]

    def get_variable_count(self) -> int:
        """Get count of registered variables."""
        return self._registry.count()

    def get_available_conditions(self) -> list[str]:
        """Get list of all available condition types.

        TODO: PRUNE? — no callers; stale vs conditions.py (missing combat/
        racing/summary conditions). The API's /variables/conditions endpoint
        is the served list; verify with user before removing.
        """
        return [
            "is_home",
            "is_away",
            "win_streak",
            "loss_streak",
            "is_ranked",
            "is_ranked_opponent",
            "is_ranked_matchup",
            "is_top_ten_matchup",
            "is_conference_game",
            "is_playoff",
            "is_preseason",
            "is_national_broadcast",
            "has_odds",
            "opponent_name_contains",
            "always",
        ]


def resolve(template: str, context: TemplateContext) -> str:
    """Convenience function for one-off resolution.

    For repeated resolution, create a TemplateResolver instance instead.
    """
    return TemplateResolver().resolve(template, context)
