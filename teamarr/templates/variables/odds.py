"""Betting odds template variables.

Variables for game odds (spread, over/under, moneyline).
Only available for same-day games from ESPN scoreboard API.
"""

from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    TemplateScope,
    register_variable,
)


def _has_odds(game_ctx: GameContext | None) -> bool:
    """Check if odds data is available."""
    return game_ctx is not None and game_ctx.odds is not None


@register_variable(
    name="odds_provider",
    category=Category.ODDS,
    suffix_rules=SuffixRules.BASE_NEXT_ONLY,
    description="Odds provider name (e.g., 'ESPN BET')",
)
def extract_odds_provider(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    odds = game_ctx.odds if game_ctx else None
    if odds is None:
        return ""
    return odds.provider


@register_variable(
    name="odds_spread",
    category=Category.ODDS,
    suffix_rules=SuffixRules.BASE_NEXT_ONLY,
    description="Point spread (absolute value, e.g., '7')",
)
def extract_odds_spread(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    odds = game_ctx.odds if game_ctx else None
    if odds is not None and odds.spread:
        spread = odds.spread
        # Format as integer if whole number
        if spread == int(spread):
            return str(int(spread))
        return str(spread)
    return ""


@register_variable(
    name="odds_over_under",
    category=Category.ODDS,
    suffix_rules=SuffixRules.BASE_NEXT_ONLY,
    description="Over/under total (e.g., '47.5')",
)
def extract_odds_over_under(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    odds = game_ctx.odds if game_ctx else None
    if odds is not None and odds.over_under:
        ou = odds.over_under
        if ou == int(ou):
            return str(int(ou))
        return str(ou)
    return ""


@register_variable(
    name="odds_details",
    category=Category.ODDS,
    suffix_rules=SuffixRules.BASE_NEXT_ONLY,
    description="Full odds description string",
)
def extract_odds_details(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    odds = game_ctx.odds if game_ctx else None
    if odds is None:
        return ""
    return odds.details


@register_variable(
    name="odds_moneyline",
    category=Category.ODDS,
    suffix_rules=SuffixRules.BASE_NEXT_ONLY,
    description="Team's moneyline (e.g., '-150' or '+130')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_odds_moneyline(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    odds = game_ctx.odds if game_ctx else None
    if odds is not None and odds.team_moneyline:
        ml = odds.team_moneyline
        if ml > 0:
            return f"+{ml}"
        return str(ml)
    return ""


@register_variable(
    name="odds_opponent_moneyline",
    category=Category.ODDS,
    suffix_rules=SuffixRules.BASE_NEXT_ONLY,
    description="Opponent's moneyline",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_odds_opponent_moneyline(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    odds = game_ctx.odds if game_ctx else None
    if odds is not None and odds.opponent_moneyline:
        ml = odds.opponent_moneyline
        if ml > 0:
            return f"+{ml}"
        return str(ml)
    return ""


@register_variable(
    name="has_odds",
    category=Category.ODDS,
    suffix_rules=SuffixRules.BASE_NEXT_ONLY,
    description="'true' if odds are available for this game",
)
def extract_has_odds(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if _has_odds(game_ctx):
        return "true"
    return ""
