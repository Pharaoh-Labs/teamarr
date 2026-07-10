"""Tennis template variables (ATP, WTA).

One Teamarr Event = one tennis match; players ride the standard home/away
team variables ({home_team}, {away_team}, {home_team_abbrev}=surname, ...).
This module adds the tournament context around a match. All extractors are
gated on `event.sport == "tennis"`.

Variables:
    tournament_name: Tournament name (e.g., "Wimbledon")
    tennis_round: Round within the draw (e.g., "Round 4", "Quarterfinals")
    tennis_court: Assigned court (e.g., "Centre Court", "No. 1 Court")
    tennis_draw: Draw type (e.g., "Men's Singles", "Mixed Doubles")
    player1, player2: Player names in event-title order (mirrors combat's
        fighter1/fighter2 — no "home" player in tennis; player1 is the first
        name in "X vs Y")
    player1_last, player2_last: Surnames only (e.g., "de Minaur")

Usage example:
    "{tournament_name} {tennis_draw}: {player1_last} vs {player2_last}"
        -> "Wimbledon Men's Singles: Cobolli vs de Minaur"
    "{tennis_round} - {tennis_court}" -> "Round 4 - No. 1 Court"
"""

import re

from teamarr.core.naming import tournament_with_article
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    TemplateScope,
    register_variable,
)


def _tennis_event(game_ctx: GameContext | None):
    """Return the event when it is a tennis event, else None."""
    if not game_ctx or not game_ctx.event:
        return None
    event = game_ctx.event
    if event.sport != "tennis":
        return None
    return event


@register_variable(
    name="tournament_name",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Tennis tournament name (e.g., 'Wimbledon')",
    sample="Wimbledon",
)
def extract_tournament_name(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the tournament name."""
    event = _tennis_event(game_ctx)
    if not event:
        return ""
    return event.tournament_name or ""


@register_variable(
    name="tennis_round",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Round within the draw (e.g., 'Round 4', 'Quarterfinals')",
    sample="Round 4",
)
def extract_tennis_round(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the round name."""
    event = _tennis_event(game_ctx)
    if not event:
        return ""
    return event.round_name or ""


@register_variable(
    name="tennis_court",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Assigned court (e.g., 'Centre Court', 'No. 1 Court')",
    sample="Centre Court",
)
def extract_tennis_court(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the court assignment."""
    event = _tennis_event(game_ctx)
    if not event:
        return ""
    return event.court or ""


@register_variable(
    name="player1",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="First player/pair in the matchup (mirrors combat's fighter1; "
    "tennis has no home player)",
    sample="Flavio Cobolli",
)
def extract_player1(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """First player — the away slot, which is always first in the event title."""
    event = _tennis_event(game_ctx)
    if not event or not event.away_team:
        return ""
    return event.away_team.name or ""


@register_variable(
    name="player2",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Second player/pair in the matchup (mirrors combat's fighter2)",
    sample="Alex de Minaur",
)
def extract_player2(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Second player — the home slot, second in the event title."""
    event = _tennis_event(game_ctx)
    if not event or not event.home_team:
        return ""
    return event.home_team.name or ""


@register_variable(
    name="player1_last",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="First player's surname (multi-word surnames preserved: 'de Minaur')",
    sample="Cobolli",
)
def extract_player1_last(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """First player's surname (the Team abbreviation carries it)."""
    event = _tennis_event(game_ctx)
    if not event or not event.away_team:
        return ""
    return event.away_team.abbreviation or ""


@register_variable(
    name="player2_last",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Second player's surname (multi-word surnames preserved: 'de Minaur')",
    sample="de Minaur",
)
def extract_player2_last(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Second player's surname (the Team abbreviation carries it)."""
    event = _tennis_event(game_ctx)
    if not event or not event.home_team:
        return ""
    return event.home_team.abbreviation or ""


@register_variable(
    name="tennis_draw",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Draw type (e.g., \"Men's Singles\", 'Mixed Doubles')",
    sample="Men's Singles",
)
def extract_tennis_draw(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the draw type."""
    event = _tennis_event(game_ctx)
    if not event:
        return ""
    return event.draw_type or ""


# --- Article-aware tournament + prose result (tvnk.7, #329) ---


@register_variable(
    name="tournament_name_the",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Tournament name with its natural article — 'the US Open', "
    "but 'Wimbledon' (no article for bare proper names)",
    sample="Wimbledon",
)
def extract_tournament_name_the(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Tournament name with the article English usage expects."""
    event = _tennis_event(game_ctx)
    if not event:
        return ""
    return tournament_with_article(event.tournament_name or "")


_RESULT_COUNTRY = re.compile(r"\s*\([A-Z]{2,3}\)")
_RESULT_SET_GAP = re.compile(r"(\d\)?)\s+(?=\d+-\d)")


@register_variable(
    name="tennis_result",
    category=Category.TENNIS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Prose match result once final (e.g., 'Zverev defeats Fery "
    "6-3, 6-4, 7-6') — reshaped from ESPN's result note; empty until the "
    "match is final",
    sample="Alcaraz defeats Sinner 6-4, 3-6, 6-3",
)
def extract_tennis_result(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """ESPN's result note ('Piros (HUN) bt Ivanov (BUL) 6-2 6-2') as prose."""
    event = _tennis_event(game_ctx)
    if not event or not event.game_recap:
        return ""
    text = _RESULT_COUNTRY.sub("", event.game_recap)
    text = text.replace(" bt ", " defeats ")
    text = _RESULT_SET_GAP.sub(r"\1, ", text)
    return text.strip()
