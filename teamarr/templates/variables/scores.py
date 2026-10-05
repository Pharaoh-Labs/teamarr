"""Score-related template variables.

Variables for game scores. These only apply to completed games (LAST_ONLY).
"""

from teamarr.core.naming import team_with_article
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    TemplateScope,
    register_variable,
)


def _is_team_home(ctx: TemplateContext, game_ctx: GameContext | None) -> bool | None:
    """Check if team is home. Returns None if context unavailable."""
    if not game_ctx or not game_ctx.event:
        return None
    return game_ctx.event.home_team.id == ctx.team_config.team_id


@register_variable(
    name="team_score",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Team's score (empty if game not started)",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_team_score(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_team_home(ctx, game_ctx)
    if is_home is None or not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    score = event.home_score if is_home else event.away_score
    return str(score) if score is not None else ""


@register_variable(
    name="opponent_score",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Opponent's score (empty if game not started)",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_score(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_team_home(ctx, game_ctx)
    if is_home is None or not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    score = event.away_score if is_home else event.home_score
    return str(score) if score is not None else ""


@register_variable(
    name="score",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Score (e.g., '24-17'). Empty if game not started.",
)
def extract_score(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""
    return f"{event.home_score}-{event.away_score}"


@register_variable(
    name="final_score",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Score with team perspective (e.g., '24-17' with team score first)",
)
def extract_final_score(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_team_home(ctx, game_ctx)
    if is_home is None or not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""

    team_score = event.home_score if is_home else event.away_score
    opp_score = event.away_score if is_home else event.home_score

    # Team score always first (winner's perspective for wins, team's perspective for losses)
    return f"{team_score}-{opp_score}"


@register_variable(
    name="score_diff",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Score differential (positive=won by, negative=lost by)",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_score_diff(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_team_home(ctx, game_ctx)
    if is_home is None or not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""

    team_score = event.home_score if is_home else event.away_score
    opp_score = event.away_score if is_home else event.home_score
    diff = team_score - opp_score
    if diff > 0:
        return f"+{diff}"
    return str(diff)


@register_variable(
    name="score_differential",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Score differential as absolute value (e.g., '7')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_score_differential(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_team_home(ctx, game_ctx)
    if is_home is None or not game_ctx or not game_ctx.event:
        return "0"
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return "0"

    team_score = event.home_score if is_home else event.away_score
    opp_score = event.away_score if is_home else event.home_score
    return str(abs(team_score - opp_score))


@register_variable(
    name="score_differential_text",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Score differential as text (e.g., 'by 7' or 'by 3')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_score_diff_text(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    is_home = _is_team_home(ctx, game_ctx)
    if is_home is None or not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""

    team_score = event.home_score if is_home else event.away_score
    opp_score = event.away_score if is_home else event.home_score
    diff = abs(team_score - opp_score)
    return f"by {diff}" if diff > 0 else "tie"


@register_variable(
    name="home_team_score",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,  # Positional - works for event channels without suffix
    description="Home team's score (empty if game not started/finished)",
)
def extract_home_team_score(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    score = game_ctx.event.home_score
    return str(score) if score is not None else ""


@register_variable(
    name="away_team_score",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,  # Positional - works for event channels without suffix
    description="Away team's score (empty if game not started/finished)",
)
def extract_away_team_score(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    score = game_ctx.event.away_score
    return str(score) if score is not None else ""


# =============================================================================
# EVENT-SPECIFIC VARIABLES (positional, for event channels)
# These work without suffixes for single-event context
# =============================================================================


@register_variable(
    name="event_result",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Full event result (e.g., 'Giants 24 - Patriots 17'). Empty if not final.",
)
def extract_event_result(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""
    # Check if game is final
    if event.status.state not in ("final", "post"):
        return ""
    home_name = event.home_team.name if event.home_team else ""
    away_name = event.away_team.name if event.away_team else ""
    return f"{home_name} {event.home_score} - {away_name} {event.away_score}"


@register_variable(
    name="event_result_abbrev",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Abbreviated event result (e.g., 'NYG 24 - NE 17'). Empty if not final.",
)
def extract_event_result_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""
    # Check if game is final
    if event.status.state not in ("final", "post"):
        return ""
    home_abbrev = event.home_team.abbreviation.upper() if event.home_team else ""
    away_abbrev = event.away_team.abbreviation.upper() if event.away_team else ""
    return f"{home_abbrev} {event.home_score} - {away_abbrev} {event.away_score}"


@register_variable(
    name="winner",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Winning team name. Empty if not final or tie.",
)
def extract_winner(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""
    if event.status.state not in ("final", "post"):
        return ""
    if event.home_score > event.away_score:
        return event.home_team.name if event.home_team else ""
    elif event.away_score > event.home_score:
        return event.away_team.name if event.away_team else ""
    return ""  # Tie


@register_variable(
    name="winner_abbrev",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Winning team abbreviation uppercase. Empty if not final or tie.",
)
def extract_winner_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""
    if event.status.state not in ("final", "post"):
        return ""
    if event.home_score > event.away_score:
        return event.home_team.abbreviation.upper() if event.home_team else ""
    elif event.away_score > event.home_score:
        return event.away_team.abbreviation.upper() if event.away_team else ""
    return ""


@register_variable(
    name="loser",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Losing team name. Empty if not final or tie.",
)
def extract_loser(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""
    if event.status.state not in ("final", "post"):
        return ""
    if event.home_score < event.away_score:
        return event.home_team.name if event.home_team else ""
    elif event.away_score < event.home_score:
        return event.away_team.name if event.away_team else ""
    return ""


@register_variable(
    name="loser_abbrev",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Losing team abbreviation uppercase. Empty if not final or tie.",
)
def extract_loser_abbrev(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return ""
    if event.status.state not in ("final", "post"):
        return ""
    if event.home_score < event.away_score:
        return event.home_team.abbreviation.upper() if event.home_team else ""
    elif event.away_score < event.home_score:
        return event.away_team.abbreviation.upper() if event.away_team else ""
    return ""


def _final_scores(game_ctx: GameContext | None) -> tuple[int, int] | None:
    """(home, away) scores of a finished game, else None."""
    if not game_ctx or not game_ctx.event:
        return None
    event = game_ctx.event
    if event.home_score is None or event.away_score is None:
        return None
    if event.status.state not in ("final", "post"):
        return None
    return event.home_score, event.away_score


@register_variable(
    name="result_score",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Final score with the winner's score first, whichever side won "
    "(e.g., '32-26'). Empty if not final.",
)
def extract_result_score(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """The score the way a guide writes it: "a 21-18 loss", "lost, 31-24"."""
    scores = _final_scores(game_ctx)
    if scores is None:
        return ""
    return f"{max(scores)}-{min(scores)}"


@register_variable(
    name="event_result_text",
    category=Category.SCORES,
    suffix_rules=SuffixRules.ALL,
    description="Result as a sentence, winner first (e.g., 'The Carolina Panthers beat "
    "the Detroit Lions, 32-26.'; a draw reads 'Arsenal and Chelsea drew, 1-1.'). "
    "Empty if not final.",
)
def extract_event_result_text(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Perspective-free result prose for event channels, article-aware."""
    scores = _final_scores(game_ctx)
    event = game_ctx.event if game_ctx else None
    if scores is None or event is None or not event.home_team or not event.away_team:
        return ""
    home = team_with_article(event.home_team.name, event.league, event.sport)
    away = team_with_article(event.away_team.name, event.league, event.sport)
    home_score, away_score = scores
    if home_score == away_score:
        text = f"{away} and {home} drew, {home_score}-{away_score}."
    else:
        winner, loser = (home, away) if home_score > away_score else (away, home)
        text = f"{winner} beat {loser}, {max(scores)}-{min(scores)}."
    return text[0].upper() + text[1:]
