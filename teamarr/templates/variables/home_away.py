"""Home/Away variables: location context, team positions, feed separation.

These variables provide home/away context, positional team references,
and feed team data for streams broken out into home/away channels.
"""

from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    register_variable,
)


def _to_pascal_case(name: str) -> str:
    """Convert team name to PascalCase.

    Strips non-alphanumeric characters and normalizes accents.
    Examples:
        "Detroit Lions" → "DetroitLions"
        "D.C. United" → "DcUnited"
        "Atlético Madrid" → "AtleticoMadrid"
    """
    import re
    import unicodedata

    # Normalize unicode (é → e)
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    # Keep only alphanumeric, split on non-alpha
    words = re.split(r"[^a-zA-Z0-9]+", ascii_name)
    return "".join(word.capitalize() for word in words if word)


def _is_home(ctx: TemplateContext, game_ctx: GameContext | None) -> bool | None:
    """Determine if configured team is home. Returns None if no game."""
    if not game_ctx or not game_ctx.event:
        return None
    return game_ctx.event.home_team.id == ctx.team_config.team_id


@register_variable(
    name="is_home",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="'true' if team is home, 'false' if away",
)
def extract_is_home(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_home(ctx, game_ctx)
    if is_home is None:
        return ""
    return "true" if is_home else "false"


@register_variable(
    name="is_away",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="'true' if team is away, 'false' if home",
)
def extract_is_away(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_home(ctx, game_ctx)
    if is_home is None:
        return ""
    return "false" if is_home else "true"


@register_variable(
    name="home_away_text",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="'at home' or 'on the road'",
)
def extract_home_away_text(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_home(ctx, game_ctx)
    if is_home is None:
        return ""
    return "at home" if is_home else "on the road"


@register_variable(
    name="vs_at",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="'vs' if home, 'at' if away",
)
def extract_vs_at(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_home(ctx, game_ctx)
    if is_home is None:
        return ""
    return "vs" if is_home else "at"


@register_variable(
    name="vs_@",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="'vs' if home, '@' if away",
)
def extract_vs_symbol(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_home(ctx, game_ctx)
    if is_home is None:
        return ""
    return "vs" if is_home else "@"


@register_variable(
    name="home_team",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Home team name (positional)",
)
def extract_home_team(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.home_team.name


@register_variable(
    name="away_team",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Away team name (positional)",
)
def extract_away_team(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.away_team.name


@register_variable(
    name="home_team_short",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Home team short name (e.g., 'Lions')",
)
def extract_home_team_short(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.home_team.short_name


@register_variable(
    name="away_team_short",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Away team short name (e.g., 'Bears')",
)
def extract_away_team_short(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.away_team.short_name


@register_variable(
    name="home_team_abbrev",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Home team abbreviation uppercase",
)
def extract_home_team_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.home_team.abbreviation.upper()


@register_variable(
    name="away_team_abbrev",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Away team abbreviation uppercase",
)
def extract_away_team_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.away_team.abbreviation.upper()


@register_variable(
    name="home_team_abbrev_lower",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Home team abbreviation lowercase",
)
def extract_home_team_abbrev_lower(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.home_team.abbreviation.lower()


@register_variable(
    name="away_team_abbrev_lower",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Away team abbreviation lowercase",
)
def extract_away_team_abbrev_lower(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.away_team.abbreviation.lower()


@register_variable(
    name="home_team_pascal",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Home team name in PascalCase",
)
def extract_home_team_pascal(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return _to_pascal_case(game_ctx.event.home_team.name)


@register_variable(
    name="away_team_pascal",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Away team name in PascalCase",
)
def extract_away_team_pascal(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return _to_pascal_case(game_ctx.event.away_team.name)


@register_variable(
    name="home_team_logo",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Home team logo URL",
)
def extract_home_team_logo(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.home_team.logo_url or ""


@register_variable(
    name="away_team_logo",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Away team logo URL",
)
def extract_away_team_logo(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.away_team.logo_url or ""


# --- Feed team variables (stream-level home/away feed separation) ---
# These resolve to the team whose broadcast feed this channel carries.
# Empty string when no feed separation is active (graceful disappear).


@register_variable(
    name="feed_team",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Feed team full name (e.g., 'Baltimore Orioles')",
)
def extract_feed_team(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team:
        return ""
    return ctx.feed_team.name


@register_variable(
    name="feed_team_short",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Feed team short name (e.g., 'Orioles')",
)
def extract_feed_team_short(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team:
        return ""
    return ctx.feed_team.short_name or ctx.feed_team.name


@register_variable(
    name="feed_team_abbrev",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Feed team abbreviation uppercase (e.g., 'BAL')",
)
def extract_feed_team_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team:
        return ""
    return ctx.feed_team.abbreviation.upper()


@register_variable(
    name="feed_team_abbrev_lower",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Feed team abbreviation lowercase (e.g., 'bal')",
)
def extract_feed_team_abbrev_lower(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team:
        return ""
    return ctx.feed_team.abbreviation.lower()


@register_variable(
    name="feed_team_logo",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Feed team logo URL",
)
def extract_feed_team_logo(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team:
        return ""
    return ctx.feed_team.logo_url or ""


@register_variable(
    name="is_home_feed",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="'true' if this is the home team's feed, 'false' if away, '' if no feed",
)
def extract_is_home_feed(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team or not game_ctx or not game_ctx.event:
        return ""
    is_home = (
        game_ctx.event.home_team
        and game_ctx.event.home_team.id == ctx.feed_team.id
    )
    return "true" if is_home else "false"


@register_variable(
    name="is_away_feed",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="'true' if this is the away team's feed, 'false' if home, '' if no feed",
)
def extract_is_away_feed(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team or not game_ctx or not game_ctx.event:
        return ""
    is_away = (
        game_ctx.event.away_team
        and game_ctx.event.away_team.id == ctx.feed_team.id
    )
    return "true" if is_away else "false"


@register_variable(
    name="feed_home_away",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="'Home' if home feed, 'Away' if away feed, '' if no feed",
)
def extract_feed_home_away(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team or not game_ctx or not game_ctx.event:
        return ""
    is_home = (
        game_ctx.event.home_team
        and game_ctx.event.home_team.id == ctx.feed_team.id
    )
    return "Home" if is_home else "Away"
