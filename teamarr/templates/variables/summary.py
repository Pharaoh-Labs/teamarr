"""Summary variables: provider editorial/context copy for a game.

Near-raw maps of provider fields. The provider boundary picks the EPG-friendly
form (a clean headline over the long wire body) and strips the leftover AP
dateline dash, but does no other rewriting. Each is empty when the provider
didn't supply it (sparse by nature; see
docs/reference/architecture/gracenote-template-design.md). All three free-tier
vars come from the scoreboard payload Teamarr already fetches, so they cost no
extra API calls.
"""

from teamarr.core.naming import team_with_article
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    register_variable,
)


@register_variable(
    name="game_recap",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    description="Postgame recap headline from the provider — short and self-contained "
    "with the result (e.g. 'Brunson scores 45, and New York tops Spurs for title'). "
    "Empty until a game is final. Free/bulk.",
)
def extract_game_recap(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.game_recap or ""


@register_variable(
    name="game_event_note",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    description="Marquee/playoff designation for the game (e.g. 'NBA Finals - Game 5', "
    "'Stanley Cup Final - Game 6', 'WNBA Commissioner's Cup'). Empty for ordinary "
    "regular-season games. Free/bulk.",
)
def extract_game_event_note(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.game_event_note or ""


@register_variable(
    name="game_preview",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    description="Pregame preview blurb from the provider (e.g. 'Toronto Blue Jays "
    "(35-38) vs. Boston Red Sox…'). Empty once a game is final (use game_recap then). "
    "Comes from the per-event summary fetch refresh already makes — no extra call.",
)
def extract_game_preview(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.game_preview or ""


@register_variable(
    name="series_summary",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    description="Playoff/season-series state for the matchup (e.g. 'Series tied 1-1', "
    "'SF leads series 1-0'). Empty when there's no series context (e.g. group-stage "
    "soccer). From the per-event summary fetch — no extra call.",
)
def extract_series_summary(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.series_summary or ""


# --- Structured preview: recent form (tvnk.15, #329) ---
# From summary lastFiveGames — available days ahead, unlike preview prose.


@register_variable(
    name="home_last_five",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    description="Home team's W-L over its last five games (e.g. '4-1'). "
    "Days-ahead availability; empty when the provider has no recent-form data.",
)
def extract_home_last_five(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.home_last_five or ""


@register_variable(
    name="away_last_five",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    description="Away team's W-L over its last five games (e.g. '2-3').",
)
def extract_away_last_five(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.away_last_five or ""


@register_variable(
    name="last_five_summary",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    description="Recent-form prose for both teams (e.g. 'The Red Sox have won 4 "
    "of their last five; the Rays have won 2 of their last five.'). Empty when "
    "no recent-form data — pair with the has_structured_preview condition.",
)
def extract_last_five_summary(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    parts = []
    # Away first — matches the seeds' "away travel to home" sentence lead.
    for team, form in (
        (event.away_team, event.away_last_five),
        (event.home_team, event.home_last_five),
    ):
        if not team or not form or "-" not in form:
            continue
        wins = form.split("-", 1)[0]
        name = team_with_article(team.name, event.league, event.sport)
        parts.append(f"{name} have won {wins} of their last five")
    if not parts:
        return ""
    return "; ".join(parts) + "."
