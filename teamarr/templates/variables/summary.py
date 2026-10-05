"""Summary variables: provider editorial/context copy for a game.

Near-raw maps of provider fields. The provider boundary picks the EPG-friendly
form (a clean headline over the long wire body) and strips the leftover AP
dateline dash, but does no other rewriting. Each is empty when the provider
didn't supply it (sparse by nature; see
docs/reference/architecture/gracenote-template-design.md). All three free-tier
vars come from the scoreboard payload Teamarr already fetches, so they cost no
extra API calls.
"""

import re

from teamarr.config import get_matchup_order
from teamarr.core import SEASON_POSTSEASON
from teamarr.core.naming import matchup_home_first, team_with_article
from teamarr.core.types import Event, Team
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


@register_variable(
    name="series_game",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    sample="Game 4",
    description="Playoff series game designation (e.g. 'Game 2', 'Game 5'). "
    "Postseason only; empty for regular-season games or when no game number is reported.",
)
def extract_series_game(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.season_type != SEASON_POSTSEASON:
        return ""
    note = event.game_event_note or ""
    if not note:
        return ""
    m = re.search(r"\b(Game\s+\d+)\b", note, re.IGNORECASE)
    if m:
        num = m.group(1).split()[1]
        return f"Game {num}"
    return ""


def _parse_series_state(event: Event) -> tuple[int, int] | None:
    """Parse (away_wins, home_wins) from event.series_summary."""
    summary = (event.series_summary or "").strip().rstrip(".")
    if not summary:
        return None

    # Check for tied series: e.g. "Series tied 1-1" or "Tied 1-1"
    tied_m = re.search(r"(?:series\s+)?tied\s+(\d+)[-–](\d+)", summary, re.IGNORECASE)
    if tied_m:
        w1, w2 = int(tied_m.group(1)), int(tied_m.group(2))
        return (w1, w2)

    # Check for leading/winning team: e.g. "<team> leads [series ]X-Y" or "<team> won [series ]X-Y"
    lead_m = re.match(
        r"(.+?)\s+(?:leads?|wins?|won)\s+(?:(?:the|season)\s+)?(?:series\s+)?(\d+)[-–](\d+)",
        summary,
        re.IGNORECASE,
    )
    if lead_m:
        leader_text, w_high_s, w_low_s = lead_m.groups()
        w_high, w_low = int(w_high_s), int(w_low_s)
        leader_norm = leader_text.strip().casefold()

        home = event.home_team
        away = event.away_team

        def _matches(team: Team | None, text: str) -> bool:
            if not team:
                return False
            for attr in (team.abbreviation, team.name, team.short_name):
                if attr and (
                    attr.casefold() == text or text in attr.casefold() or attr.casefold() in text
                ):
                    return True
            return False

        home_match = _matches(home, leader_norm)
        away_match = _matches(away, leader_norm)

        if home_match and not away_match:
            return (w_low, w_high)
        elif away_match and not home_match:
            return (w_high, w_low)
        else:
            if home and home.abbreviation and home.abbreviation.casefold() == leader_norm:
                return (w_low, w_high)
            if away and away.abbreviation and away.abbreviation.casefold() == leader_norm:
                return (w_high, w_low)
            return (w_low, w_high) if home_match else (w_high, w_low)

    return None


def _ordered_series_wins(event: Event) -> tuple[int, int, Team | None, Team | None] | None:
    """Return (team1_wins, team2_wins, team1, team2) in the localized matchup order."""
    wins = _parse_series_state(event)
    if wins is None:
        return None
    away_wins, home_wins = wins
    home_first = matchup_home_first(event.sport, get_matchup_order(event.league))
    team1, team2 = (
        (event.home_team, event.away_team) if home_first else (event.away_team, event.home_team)
    )
    team1_wins, team2_wins = (home_wins, away_wins) if home_first else (away_wins, home_wins)
    return (team1_wins, team2_wins, team1, team2)


@register_variable(
    name="series_score",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    sample="1-3",
    description=(
        "Playoff series score in localized matchup order (e.g. '1-2' for away-first, "
        "'2-1' for home-first). Postseason only; empty for regular-season games or "
        "when no series data is reported."
    ),
)
def extract_series_score(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.season_type != SEASON_POSTSEASON:
        return ""
    ordered = _ordered_series_wins(event)
    if not ordered:
        return ""
    team1_wins, team2_wins, _, _ = ordered
    return f"{team1_wins}-{team2_wins}"


@register_variable(
    name="series_summary_short",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    sample="GMT 1 - FLI 3",
    description=(
        "Short playoff series standing in localized matchup order "
        "(e.g. 'NYY 1 - BOS 2', 'Tied 1-1'). Postseason only; empty for "
        "regular-season games or when no series data is reported."
    ),
)
def extract_series_summary_short(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.season_type != SEASON_POSTSEASON:
        return ""
    ordered = _ordered_series_wins(event)
    if not ordered:
        return ""
    team1_wins, team2_wins, team1, team2 = ordered
    if team1_wins == team2_wins:
        return f"Tied {team1_wins}-{team2_wins}"
    abbrev1 = (
        (team1.abbreviation if team1 else "") or (team1.short_name if team1 else "") or "Team 1"
    )
    abbrev2 = (
        (team2.abbreviation if team2 else "") or (team2.short_name if team2 else "") or "Team 2"
    )
    return f"{abbrev1} {team1_wins} - {abbrev2} {team2_wins}"


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
    # Home first — matches the seeds' "home host away" sentence lead.
    for team, form in (
        (event.home_team, event.home_last_five),
        (event.away_team, event.away_last_five),
    ):
        if not team or not form or "-" not in form:
            continue
        wins = form.split("-", 1)[0]
        name = team_with_article(team.name, event.league, event.sport)
        parts.append(f"{name} have won {wins} of their last five")
    if not parts:
        return ""
    # A sentence of its own: the article-aware name opens it lowercase.
    text = "; ".join(parts) + "."
    return text[0].upper() + text[1:]
