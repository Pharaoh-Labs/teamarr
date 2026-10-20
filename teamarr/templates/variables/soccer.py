"""Soccer-specific template variables.

Variables for handling multi-league soccer (team plays in multiple competitions).
"""

from teamarr.config import get_matchup_order
from teamarr.core.naming import matchup_home_first
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
def extract_soccer_match_league_name(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
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


# --- Cup knockout ties (#916) -------------------------------------------------
# Structured round/leg/aggregate from ESPN (providers/espn/knockout.py).
# Soccer-only like soccer_match_note; empty on league-phase and group games,
# so an artwork row keyed on these never fires outside a knockout stage. The
# North American series variables keep their own rule: {series_game} reads a
# 'Game N' note, which a soccer leg never carries.


@register_variable(
    name="knockout_round",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.ALL,
    sample="Round of 16",
    description="Cup knockout stage for THIS match ('Knockout Round Playoffs', 'Round of 16', "
    "'Quarterfinals', 'Semifinals', 'Final'). Soccer-only; empty for league-phase, "
    "group and domestic-league games.",
)
def extract_knockout_round(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.knockout_round or ""


@register_variable(
    name="match_leg",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.ALL,
    sample="2nd Leg",
    description="Which leg of a two-legged tie THIS match is ('1st Leg', '2nd Leg'). "
    "Empty for one-off finals, league-phase and group games — a leg badge never "
    "lands on a match that is not a leg.",
)
def extract_match_leg(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    leg = game_ctx.event.match_leg
    if leg == 1:
        return "1st Leg"
    if leg == 2:
        return "2nd Leg"
    return ""


@register_variable(
    name="aggregate_score",
    category=Category.SOCCER,
    suffix_rules=SuffixRules.ALL,
    sample="3-1",
    description="Aggregate score of a two-legged tie once it is decided, in matchup order "
    "(home first for soccer unless overridden). Empty before the second leg is final "
    "and on one-off matches; a tie level on aggregate shows the level score "
    "(the penalty shootout is not an aggregate).",
)
def extract_aggregate_score(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.aggregate_home is None or event.aggregate_away is None:
        return ""
    home_first = matchup_home_first(event.sport, get_matchup_order(event.league))
    first, second = (
        (event.aggregate_home, event.aggregate_away)
        if home_first
        else (event.aggregate_away, event.aggregate_home)
    )
    return f"{first}-{second}"
