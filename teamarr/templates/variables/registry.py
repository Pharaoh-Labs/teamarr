"""Variable registry and registration decorator.

This module provides the central registry for all template variables.
Variables are registered using the @register_variable decorator, which
captures metadata alongside the extraction function.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teamarr.templates.context import GameContext, TemplateContext

# Type alias for extractor functions
Extractor = Callable[["TemplateContext", "GameContext | None"], str]


class Category(Enum):
    """Variable categories for organization and documentation."""

    IDENTITY = auto()  # team_name, opponent, league, exception_keyword
    DATETIME = auto()  # game_date, game_time
    VENUE = auto()  # venue, venue_city
    HOME_AWAY = auto()  # is_home, vs_at
    RECORDS = auto()  # team_record, opponent_record
    STREAKS = auto()  # streak, streak_raw
    SCORES = auto()  # team_score, final_score
    OUTCOME = auto()  # result, result_text
    STANDINGS = auto()  # playoff_seed, games_back
    STATISTICS = auto()  # team_ppg, opponent_ppg
    PLAYOFFS = auto()  # is_playoff, season_type
    ODDS = auto()  # odds_spread, odds_over_under
    BROADCAST = auto()  # broadcast_simple
    RANKINGS = auto()  # team_rank, is_ranked
    CONFERENCE = auto()  # college_conference, pro_division
    SOCCER = auto()  # soccer_match_league
    COMBAT = auto()  # fighter1, fighter2, card_segment
    MOTORSPORTS = auto()  # race_name, session_name, grid, podium, results
    TENNIS = auto()  # player1/2, tournament_name, tennis_round, tennis_court, tennis_draw
    SUMMARY = auto()  # game_recap, game_event_note (provider editorial/context copy)


class SuffixRules(Enum):
    """Rules for which suffixes a variable supports.

    Variables are generated for base (current game), .next (next game),
    and .last (last game) contexts. Different variables have different
    rules about which suffixes make sense.
    """

    ALL = auto()  # base, .next, .last (most variables)
    BASE_ONLY = auto()  # base only (team_name, league - team-level, not game-specific)
    BASE_NEXT_ONLY = auto()  # base, .next only (odds_* - no odds for past games)
    LAST_ONLY = auto()  # .last only (deprecated - use ALL instead)


class TemplateScope(Enum):
    """Which template types a variable is valid in.

    Team templates render from a specific team's perspective (the subscribed
    team). Event templates are positional — they describe a matchup without an
    "our team" anchor. A variable's scope determines which pickers expose it.

    Mirrors SuffixRules: ALL is the default, TEAM_ONLY / EVENT_ONLY are
    restrictions. Filtering is done at the API boundary by
    VariableRegistry.filter_by_template_type().
    """

    ALL = auto()  # valid in both team and event templates (default)
    TEAM_ONLY = auto()  # only team templates (requires "our team" perspective)
    EVENT_ONLY = auto()  # only event templates (e.g. feed_team family)


@dataclass(frozen=True)
class VariableDefinition:
    """Complete definition of a template variable."""

    name: str
    category: Category
    suffix_rules: SuffixRules
    extractor: Extractor
    description: str = ""
    scope: TemplateScope = TemplateScope.ALL
    sample: str | None = None
    """Optional inline placeholder for the template preview.

    When set, this value is used for the preview when no curated entry exists
    in sample_data.SAMPLE_DATA for the variable. This lets a new variable carry
    its own placeholder at the point of definition, so it is auto-adopted into
    previews without a separate edit to sample_data.py. When omitted, the
    preview falls back to a category-based default (see sample_data.py)."""


class VariableRegistry:
    """Singleton registry for all template variables.

    Variables are registered via the @register_variable decorator.
    The registry provides lookup and introspection capabilities.
    """

    _instance: "VariableRegistry | None" = None
    _variables: dict[str, VariableDefinition]

    def __new__(cls) -> "VariableRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._variables = {}
        return cls._instance

    def register(
        self,
        name: str,
        category: Category,
        suffix_rules: SuffixRules,
        extractor: Extractor,
        description: str = "",
        scope: TemplateScope = TemplateScope.ALL,
        sample: str | None = None,
    ) -> None:
        """Register a variable definition."""
        self._variables[name] = VariableDefinition(
            name=name,
            category=category,
            suffix_rules=suffix_rules,
            extractor=extractor,
            description=description,
            scope=scope,
            sample=sample,
        )

    def get(self, name: str) -> VariableDefinition | None:
        """Get a variable definition by name."""
        return self._variables.get(name)

    def all_variables(self) -> list[VariableDefinition]:
        """Get all registered variables."""
        return list(self._variables.values())

    def by_category(self, category: Category) -> list[VariableDefinition]:
        """Get all variables in a category."""
        return [v for v in self._variables.values() if v.category == category]

    def filter_by_template_type(
        self, template_type: str | None
    ) -> list[VariableDefinition]:
        """Return variables valid for the given template type.

        Args:
            template_type: 'team', 'event', or None. Unknown values and None
                           return all variables (fail-open, matches the
                           conditions endpoint's behavior).

        Returns:
            Variables whose scope is compatible with the requested template
            type. ALL variables are always included. TEAM_ONLY variables are
            included only for 'team'; EVENT_ONLY only for 'event'.
        """
        if template_type == "team":
            return [
                v
                for v in self._variables.values()
                if v.scope in (TemplateScope.ALL, TemplateScope.TEAM_ONLY)
            ]
        if template_type == "event":
            return [
                v
                for v in self._variables.values()
                if v.scope in (TemplateScope.ALL, TemplateScope.EVENT_ONLY)
            ]
        return list(self._variables.values())

    def count(self) -> int:
        """Get total number of registered variables."""
        return len(self._variables)

    def clear(self) -> None:
        """Clear all registered variables (for testing)."""
        self._variables.clear()


def register_variable(
    name: str,
    category: Category,
    suffix_rules: SuffixRules = SuffixRules.ALL,
    description: str = "",
    scope: TemplateScope = TemplateScope.ALL,
    sample: str | None = None,
) -> Callable[[Extractor], Extractor]:
    """Decorator to register a variable extractor.

    Usage:
        @register_variable(
            name="opponent",
            category=Category.IDENTITY,
            suffix_rules=SuffixRules.ALL,
            description="Opponent team name",
            scope=TemplateScope.TEAM_ONLY,
        )
        def extract_opponent(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
            if not game_ctx or not game_ctx.event:
                return ""
            # ... extraction logic
            return opponent.name

    scope defaults to TemplateScope.ALL (valid in both team and event
    templates). Set TEAM_ONLY for "our team" perspective variables
    (team/opponent/is_home/team_record/etc.) or EVENT_ONLY for variables
    that only make sense on event templates (feed_team family).

    sample is an optional inline placeholder for the template preview. Provide
    it so a new variable is auto-adopted into previews with a sensible value
    without editing sample_data.py. When omitted, the preview uses a
    category-based default. Curated per-sport values in sample_data.SAMPLE_DATA
    still take precedence over this inline sample.
    """

    def decorator(func: Extractor) -> Extractor:
        VariableRegistry().register(
            name, category, suffix_rules, func, description, scope, sample
        )
        return func

    return decorator


def get_registry() -> VariableRegistry:
    """Get the singleton variable registry."""
    return VariableRegistry()
