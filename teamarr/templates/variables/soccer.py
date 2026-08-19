"""Soccer-specific template variables.

Variables for handling multi-league soccer (team plays in multiple competitions).
"""

from teamarr.services.league_mappings import get_league_mapping_service
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    register_variable,
)


@register_variable(
    name="soccer_primary_league",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team's home league name (e.g., 'Premier League')",
)
def extract_soccer_primary_league(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    # First check team config (set at channel creation)
    if ctx.team_config.soccer_primary_league:
        return ctx.team_config.soccer_primary_league
    # Fall back to league_name
    if ctx.team_config.league_name:
        return ctx.team_config.league_name
    return ""


@register_variable(
    name="soccer_primary_league_id",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team's home league ID (e.g., 'eng.1')",
)
def extract_soccer_primary_league_id(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if ctx.team_config.soccer_primary_league_id:
        return ctx.team_config.soccer_primary_league_id
    return ctx.team_config.league


@register_variable(
    name="soccer_match_league",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.ALL,
    description="League for THIS game (may differ from primary)",
)
def extract_soccer_match_league(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    if not game_ctx.event.league:
        return ""

    service = get_league_mapping_service()
    return service.get_league_alias(game_ctx.event.league)


@register_variable(
    name="soccer_match_league_name",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.ALL,
    description="Full league display name for THIS game (e.g., 'English Premier League')",
)
def extract_soccer_match_league_name(
    ctx: TemplateContext, game_ctx: GameContext | None
) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    if not game_ctx.event.league:
        return ""

    service = get_league_mapping_service()
    return service.get_league_display_name(game_ctx.event.league)


@register_variable(
    name="soccer_match_league_id",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.ALL,
    description="League ID for THIS game (e.g., 'uefa.champions')",
)
def extract_soccer_match_league_id(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.league


@register_variable(
    name="soccer_match_league_logo",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.ALL,
    description="Logo URL for THIS game's league",
)
def extract_soccer_match_league_logo(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    if not game_ctx.event.league:
        return ""

    service = get_league_mapping_service()
    return service.get_league_logo(game_ctx.event.league)


@register_variable(
    name="soccer_match_note",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.ALL,
    description="Provider's competition note for THIS match, untouched — competition "
    "name plus group/stage where present (e.g. 'FIFA World Cup, Group J'). Unlike "
    "soccer_match_league_name (which Teamarr builds), this is the raw provider value "
    "and carries group-level detail. Soccer-only; empty otherwise.",
)
def extract_soccer_match_note(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.soccer_match_note or ""
