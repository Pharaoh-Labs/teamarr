"""Home/Away variables: location context, team positions, feed separation.

These variables provide home/away context, positional team references,
and feed team data for streams broken out into home/away channels.
"""

from teamarr.core.naming import matchup_connector, team_with_article
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    TemplateScope,
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
    scope=TemplateScope.TEAM_ONLY,
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
    scope=TemplateScope.TEAM_ONLY,
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
    scope=TemplateScope.TEAM_ONLY,
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
    scope=TemplateScope.TEAM_ONLY,
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
    scope=TemplateScope.TEAM_ONLY,
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


def _abbrev_or_name(team) -> str:
    """Abbreviation (uppercased) with a graceful fallback for leagues whose
    teams have none: short_name, then full name — kept as-is (uppercasing a
    full club name would shout). Retires the need for a separate "No-Abbrev"
    template variant (#329)."""
    if team.abbreviation:
        return team.abbreviation.upper()
    return team.short_name or team.name


@register_variable(
    name="home_team_abbrev",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description=(
        "Home team abbreviation uppercase (falls back to short/full name "
        "when the league has none)"
    ),
)
def extract_home_team_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return _abbrev_or_name(game_ctx.event.home_team)


@register_variable(
    name="away_team_abbrev",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description=(
        "Away team abbreviation uppercase (falls back to short/full name "
        "when the league has none)"
    ),
)
def extract_away_team_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return _abbrev_or_name(game_ctx.event.away_team)


@register_variable(
    name="home_team_abbrev_lower",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Home team abbreviation lowercase",
)
def extract_home_team_abbrev_lower(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return _abbrev_or_name(game_ctx.event.home_team).lower()


@register_variable(
    name="away_team_abbrev_lower",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Away team abbreviation lowercase",
)
def extract_away_team_abbrev_lower(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return _abbrev_or_name(game_ctx.event.away_team).lower()


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
    scope=TemplateScope.EVENT_ONLY,
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
    scope=TemplateScope.EVENT_ONLY,
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
    scope=TemplateScope.EVENT_ONLY,
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
    scope=TemplateScope.EVENT_ONLY,
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
    scope=TemplateScope.EVENT_ONLY,
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
    scope=TemplateScope.EVENT_ONLY,
)
def extract_is_home_feed(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team or not game_ctx or not game_ctx.event:
        return ""
    is_home = game_ctx.event.home_team and game_ctx.event.home_team.id == ctx.feed_team.id
    return "true" if is_home else "false"


@register_variable(
    name="is_away_feed",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="'true' if this is the away team's feed, 'false' if home, '' if no feed",
    scope=TemplateScope.EVENT_ONLY,
)
def extract_is_away_feed(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team or not game_ctx or not game_ctx.event:
        return ""
    is_away = game_ctx.event.away_team and game_ctx.event.away_team.id == ctx.feed_team.id
    return "true" if is_away else "false"


@register_variable(
    name="feed_home_away",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="'Home' if home feed, 'Away' if away feed, '' if no feed",
    scope=TemplateScope.EVENT_ONLY,
)
def extract_feed_home_away(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team or not game_ctx or not game_ctx.event:
        return ""
    is_home = game_ctx.event.home_team and game_ctx.event.home_team.id == ctx.feed_team.id
    return "Home" if is_home else "Away"


# --- Broadcast feed labels (#195) ---
# Pre-formatted strings that include the literal " Feed" suffix so users can
# drop them into EPG titles without orphan-text issues. When feed separation
# is inactive, both return "" — the resolver's whitespace cleanup then drops
# the whole phrase, unlike "{feed_home_away} Team Feed" which would leave
# "Team Feed" behind.


@register_variable(
    name="broadcast_feed",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="'Home Team Feed' / 'Away Team Feed' / '' (empty when no feed separation)",
    scope=TemplateScope.EVENT_ONLY,
)
def extract_broadcast_feed(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team or not game_ctx or not game_ctx.event:
        return ""
    is_home = game_ctx.event.home_team and game_ctx.event.home_team.id == ctx.feed_team.id
    return "Home Team Feed" if is_home else "Away Team Feed"


@register_variable(
    name="broadcast_feed_team",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="'{Team Name} Feed' (e.g., 'Seattle Mariners Feed') or '' if no feed",
    scope=TemplateScope.EVENT_ONLY,
)
def extract_broadcast_feed_team(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not ctx.feed_team:
        return ""
    return f"{ctx.feed_team.name} Feed"


# --- Article-aware naming + matchup connector (tvnk.7, #329) ---
# Gracenote convention: clubs/franchises take "the", national teams and
# individual-sport competitors don't. Lowercase "the" — the resolver
# capitalizes a leading "the " when it opens the rendered text.


@register_variable(
    name="home_team_the",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Home team name with Gracenote-convention article — "
    "'the Detroit Pistons' for clubs, 'Netherlands' for national teams",
)
def extract_home_team_the(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    return team_with_article(event.home_team.name, event.league, event.sport)


@register_variable(
    name="away_team_the",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Away team name with Gracenote-convention article — "
    "'the Green Bay Packers' for clubs, 'Japan' for national teams",
)
def extract_away_team_the(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    return team_with_article(event.away_team.name, event.league, event.sport)


@register_variable(
    name="at_vs",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Perspective-free matchup connector between away and home — "
    "'at' for US team sports ('Mystics at Liberty'), 'vs.' otherwise "
    "('Scotland vs. Morocco')",
)
def extract_at_vs(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return matchup_connector(game_ctx.event.sport)


@register_variable(
    name="home_away_verb",
    category=Category.HOME_AWAY,
    suffix_rules=SuffixRules.ALL,
    description="Prose verb from the team's perspective: 'host' at home, 'visit' away",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_home_away_verb(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_home(ctx, game_ctx)
    if is_home is None:
        return ""
    return "host" if is_home else "visit"
