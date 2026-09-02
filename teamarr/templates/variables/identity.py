"""Identity variables: team names, league, sport.

These variables identify teams and the competition context.
Most are BASE_ONLY since they don't change between games.
"""

from teamarr.core.naming import format_matchup, ranked_with_article, team_with_article
from teamarr.services.league_mappings import get_league_mapping_service
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    TemplateScope,
    register_variable,
)


def _get_opponent(ctx: TemplateContext, game_ctx: GameContext | None):
    """Helper to get opponent team from game context."""
    if not game_ctx or not game_ctx.event:
        return None
    event = game_ctx.event
    is_home = event.home_team.id == ctx.team_config.team_id
    return event.away_team if is_home else event.home_team


@register_variable(
    name="team_name",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team display name (e.g., 'Detroit Lions')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_team_name(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return ctx.team_config.team_name or ""


@register_variable(
    name="team_abbrev",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team abbreviation uppercase (e.g., 'DET')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_team_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    abbrev = ctx.team_config.team_abbrev or ""
    return abbrev.upper()


@register_variable(
    name="team_short",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team short name (e.g., 'Lions', 'Liverpool')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_team_short(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return ctx.team_config.team_short_name or ""


@register_variable(
    name="opponent",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.ALL,
    description="Opponent team name",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    opponent = _get_opponent(ctx, game_ctx)
    return opponent.name if opponent else ""


@register_variable(
    name="opponent_abbrev",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.ALL,
    description="Opponent team abbreviation uppercase",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    opponent = _get_opponent(ctx, game_ctx)
    return opponent.abbreviation.upper() if opponent else ""


@register_variable(
    name="opponent_short",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.ALL,
    description="Opponent short name (e.g., 'Bears', 'Arsenal')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_short(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    opponent = _get_opponent(ctx, game_ctx)
    return opponent.short_name if opponent else ""


def _matchup(game_ctx: GameContext | None, field: str, upper: bool = False) -> str:
    """Sport-conventional matchup from one Team field (#692 phase 1)."""
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    away = getattr(event.away_team, field) or ""
    home = getattr(event.home_team, field) or ""
    if upper:
        away, home = away.upper(), home.upper()
    return format_matchup(away, home, event.sport, event.neutral_site)


@register_variable(
    name="matchup",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.ALL,
    description="Full matchup in the sport's convention: 'Tampa Bay @ Detroit' "
    "for US team sports (visitor first), 'Ipswich Town v Liverpool' for "
    "soccer/rugby/cricket (home first); neutral-site games read 'v'",
)
def extract_matchup(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return _matchup(game_ctx, "name")


@register_variable(
    name="matchup_abbrev",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.ALL,
    description="Abbreviated matchup uppercase in the sport's convention "
    "(e.g., 'TB @ DET', 'IPS v LIV')",
)
def extract_matchup_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return _matchup(game_ctx, "abbreviation", upper=True)


@register_variable(
    name="matchup_short",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.ALL,
    description="Short-name matchup in the sport's convention "
    "(e.g., 'Buccaneers @ Lions', 'Ipswich v Liverpool')",
)
def extract_matchup_short(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return _matchup(game_ctx, "short_name")


@register_variable(
    name="league",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="League short alias (e.g., 'NFL', 'EPL', 'UCL', 'La Liga')",
)
def extract_league(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return league short alias for display.

    Fallback chain:
        1. league_alias from leagues table (e.g., 'EPL', 'UCL')
        2. display_name from leagues table (e.g., 'NFL', 'La Liga')
        3. league_code uppercase

    Examples:
        eng.1 → EPL (has league_alias)
        uefa.champions → UCL (has league_alias)
        nfl → NFL (display_name already short)
        ger.1 → Bundesliga (display_name already short)

    THREAD-SAFE: Uses in-memory cache, no DB access.
    """

    service = get_league_mapping_service()
    return service.get_league_alias(ctx.team_config.league)


def construct_league_abbrev(name: str) -> str:
    """Build an all-caps abbreviation from a league name.

    Keeps any letters that are already uppercase, digits, and the first letter
    of every word (word boundaries are whitespace only, so an apostrophe doesn't
    start a new word). Already-uppercase names pass through unchanged.

    Examples:
        NBA → NBA
        World Cup → WC
        Premier League → PL
        La Liga → LL
        Serie A → SA
        UEFA Champions League → UEFACL
        F1 → F1
    """
    out: list[str] = []
    at_word_start = True
    for ch in name:
        if ch.isalnum():
            if at_word_start or ch.isupper() or ch.isdigit():
                out.append(ch.upper())
            at_word_start = False
        else:
            at_word_start = ch.isspace()
    return "".join(out)


@register_variable(
    name="league_abbrev",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description=(
        "League abbreviation built from the league name — existing capitals "
        "plus the first letter of each word (e.g., 'World Cup' → 'WC', 'NBA' → 'NBA')"
    ),
    sample="NBA",
)
def extract_league_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return an abbreviation constructed from the league display name.

    Unlike {league} (a curated alias), this is derived on the fly so it works
    for any league. Falls back to the raw league code when no display name is
    available.

    THREAD-SAFE: Uses in-memory cache, no DB access.
    """

    service = get_league_mapping_service()
    name = service.get_league_alias(ctx.team_config.league)
    abbrev = construct_league_abbrev(name or "")

    if abbrev:
        return abbrev
    return construct_league_abbrev(ctx.team_config.league or "")


@register_variable(
    name="league_name",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="League full display name (e.g., 'NFL', 'NCAA Men's Basketball')",
)
def extract_league_name(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return league full display name.

    Fallback chain:
        1. Our display_name from leagues table
        2. API's league_name from league_cache table
        3. Raw league code (uppercase)

    Examples:
        nfl → NFL
        mens-college-basketball → NCAA Men's Basketball
        eng.1 → English Premier League

    THREAD-SAFE: Uses in-memory cache, no DB access.
    """

    service = get_league_mapping_service()
    return service.get_league_display_name(ctx.team_config.league)


@register_variable(
    name="sport",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Sport display name (e.g., 'Football', 'MMA')",
)
def extract_sport(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return sport display name with proper casing.

    Uses sports table for display names (handles special cases like 'MMA').
    Falls back to title case if sport not in table.

    THREAD-SAFE: Uses in-memory cache, no DB access.
    """
    sport_code = ctx.team_config.sport
    if not sport_code:
        return ""


    service = get_league_mapping_service()
    return service.get_sport_display_name(sport_code)


@register_variable(
    name="league_id",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="League identifier for URLs (e.g., 'nfl', 'epl', 'ncaabb')",
)
def extract_league_id(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return league_id for URL construction.

    Always lowercase - stored that way in DB.

    Examples:
        nfl → nfl
        college-baseball → ncaabb
        college-softball → ncaasbw
        eng.1 → epl
        ger.1 → bundesliga

    THREAD-SAFE: Uses in-memory cache, no DB access.
    """

    service = get_league_mapping_service()
    return service.get_league_id(ctx.team_config.league)


@register_variable(
    name="league_code",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Raw league code (e.g., 'nfl', 'mens-college-basketball', 'eng.1')",
)
def extract_league_code(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return raw league_code, ignoring any alias."""
    return ctx.team_config.league


@register_variable(
    name="gracenote_category",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Gracenote category for EPG (e.g., 'NFL Football', 'College Basketball')",
)
def extract_gracenote_category(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return Gracenote-compatible category.

    Fallback chain:
        0. User override from league_overrides (Settings → Advanced, #371)
        1. gracenote_category from leagues table (curated value)
        2. Auto-generated by the league's event_type:
           - team_vs_team: "{display_name} {Sport}" (e.g., 'NFL Football')
           - event/event_card: display_name alone (e.g., 'NASCAR Cup Series' —
             Gracenote titles racing/combat by series or promotion name)

    International tournaments are curated WITHOUT a sport suffix (real
    Gracenote is branded + year: 'FIFA World Cup 2026'); compose the year in
    templates via '{gracenote_category} {year}'.

    Examples:
        nfl → NFL Football
        mens-college-basketball → College Basketball (if curated)
        eng.1 → Premier League Soccer (curated; club soccer keeps the suffix)
        fifa.world → FIFA World Cup
        nascar-truck → NASCAR Craftsman Truck Series

    THREAD-SAFE: Uses in-memory cache, no DB access.
    """

    service = get_league_mapping_service()
    return service.get_gracenote_category(ctx.team_config.league)


@register_variable(
    name="exception_keyword",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Exception keyword label (e.g., 'Spanish', '4K', 'Manningcast') - set at channel creation",  # noqa: E501
)
def extract_exception_keyword(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return exception keyword label for channel naming and EPG content.

    This variable is special - it's populated via extra_vars on TemplateContext,
    not extracted from event data. The extractor returns empty string as a
    fallback; actual values are injected by:
    - Lifecycle service (channel creation, via _resolve_template extra_variables)
    - EPG generator (programme generation, via context.extra_vars)

    Works in ALL template fields: channel name, title, subtitle, description, logo URL.

    Used in templates like:
        "{away_team} @ {home_team} ({exception_keyword})"
        "{exception_keyword}: {matchup}"

    Examples:
        Spanish, French, 4K, Manningcast
    """
    # Value is injected via extra_vars on TemplateContext
    # This extractor exists for validation, UI display, and as fallback
    return ""


# --- Article-aware naming (tvnk.7, #329) ---


@register_variable(
    name="team_name_the",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team name with Gracenote-convention article — 'the Detroit "
    "Pistons' for clubs, 'Netherlands' for national teams",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_team_name_the(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    cfg = ctx.team_config
    return team_with_article(cfg.team_name or "", cfg.league, cfg.sport)


@register_variable(
    name="opponent_the",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.ALL,
    description="Opponent name with Gracenote-convention article — 'the Green "
    "Bay Packers' for clubs, 'Japan' for national teams",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_the(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    opponent = _get_opponent(ctx, game_ctx)
    if not opponent:
        return ""
    return team_with_article(opponent.name, opponent.league, opponent.sport)


@register_variable(
    name="team_name_ranked_the",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team name with rank and Gracenote article composed — "
    "'the No. 7 Boston Celtics' ranked, 'the Boston Celtics' unranked",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_team_name_ranked_the(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    cfg = ctx.team_config
    rank = ctx.team_stats.rank if ctx.team_stats else None
    return ranked_with_article(cfg.team_name or "", cfg.league, cfg.sport, rank)


@register_variable(
    name="opponent_ranked_the",
    category=Category.IDENTITY,
    suffix_rules=SuffixRules.ALL,
    description="Opponent with rank and Gracenote article composed — "
    "'the No. 14 Green Bay Packers' ranked, 'the Green Bay Packers' unranked",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_ranked_the(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    opponent = _get_opponent(ctx, game_ctx)
    if not opponent:
        return ""
    rank = game_ctx.opponent_stats.rank if game_ctx and game_ctx.opponent_stats else None
    return ranked_with_article(opponent.name, opponent.league, opponent.sport, rank)
