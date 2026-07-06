"""Combat sports template variables (UFC, Boxing, MMA).

Variables for UFC card segments, fighter names, matchup formatting, and fight results.

Fighter Identity:
    fighter1, fighter2: Headline bout fighter names
    matchup: "Fighter1 vs Fighter2"
    fighter1_record, fighter2_record: W-L-D records (e.g., "28-4-0")

Event Info:
    event_number: "325" from "UFC 325"
    event_title: Full title "UFC 325: Volkanovski vs Lopes"
    weight_class: "Featherweight", "Lightweight", etc.
    weight_class_short: "FW", "LW", "HW", etc.

Card Segments:
    card_segment: "main_card", "prelims", "early_prelims"
    card_segment_display: "Main Card", "Prelims", "Early Prelims"
    main_card_time, prelims_time, early_prelims_time: Segment start times

Bout Lists:
    bout_count: Total bouts on card
    fight_card: All bouts (newline-separated)
    main_card_bouts, prelims_bouts, early_prelims_bouts: Segment-specific

Fight Results (finished fights only):
    fight_result: "TKO", "Submission", "Decision (Unanimous)"
    fight_result_short: "TKO", "SUB", "UD"
    finish_round: Round fight ended (e.g., "2")
    finish_time: Time in round (e.g., "4:31")
    finish_info: Combined "R2 4:31"
    judge_scores: For decisions, "48-47" or "48-47, 49-46, 48-47"
    fight_summary: Complete summary "TKO R2 4:31" or "UD 48-47"

Conditions (for conditional descriptions):
    is_knockout: KO or TKO finish
    is_submission: Submission finish
    is_decision: Went to judges' scorecards
    is_finish: Any finish (KO/TKO/Submission)
    went_distance: Fight went all scheduled rounds

Usage example:
    "{fighter1} defeats {fighter2} by {fight_result} {finish_info}"
    -> "Volkanovski defeats Lopes by TKO R2 4:31"
"""

from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    register_variable,
)
from teamarr.utilities.tz import format_time


@register_variable(
    name="fighter1",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only, no next/last
    description="First fighter name (headline bout home_team)",
)
def extract_fighter1(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract first fighter name from UFC event.

    For UFC events, home_team and away_team represent fighters in the headline bout.
    """
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    if event.home_team and event.home_team.name:
        return event.home_team.name

    return ""


@register_variable(
    name="fighter2",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Second fighter name (headline bout away_team)",
)
def extract_fighter2(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract second fighter name from UFC event."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    if event.away_team and event.away_team.name:
        return event.away_team.name

    return ""


@register_variable(
    name="matchup",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Full matchup (Fighter1 vs Fighter2)",
)
def extract_matchup(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract full matchup string from UFC event."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    fighter1 = event.home_team.name if event.home_team else ""
    fighter2 = event.away_team.name if event.away_team else ""

    if fighter1 and fighter2:
        return f"{fighter1} vs {fighter2}"
    elif fighter1:
        return fighter1
    elif fighter2:
        return fighter2

    return ""


@register_variable(
    name="event_number",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="UFC event number (e.g., '325' from 'UFC 325')",
)
def extract_event_number(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract event number from UFC event name."""
    import re

    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    # Try to extract number from event name
    # "UFC 325: Volkanovski vs Lopes" -> "325"
    match = re.search(r"UFC\s*(\d+)", event.name, re.IGNORECASE)
    if match:
        return match.group(1)

    # Try short_name
    match = re.search(r"UFC\s*(\d+)", event.short_name, re.IGNORECASE)
    if match:
        return match.group(1)

    return ""


@register_variable(
    name="event_title",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Full event title (e.g., 'UFC 325: Volkanovski vs Lopes')",
)
def extract_event_title(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract full event title from UFC event."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    return event.name


# =============================================================================
# Card Segment Variables
# =============================================================================

# Display names for template output
SEGMENT_DISPLAY_NAMES: dict[str, str] = {
    "early_prelims": "Early Prelims",
    "prelims": "Prelims",
    "main_card": "Main Card",
}


@register_variable(
    name="card_segment",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Segment is specific to current channel
    description="Card segment code (early_prelims, prelims, main_card)",
)
def extract_card_segment(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract card segment for this UFC channel.

    Returns the segment code assigned to this specific stream/channel.
    Used for conditional logic and routing in templates.
    """
    if not game_ctx:
        return ""

    return game_ctx.card_segment or ""


@register_variable(
    name="card_segment_display",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Segment is specific to current channel
    description="Card segment display name (Early Prelims, Prelims, Main Card)",
)
def extract_card_segment_display(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract human-readable card segment name.

    Converts segment code to display format:
    - early_prelims -> "Early Prelims"
    - prelims -> "Prelims"
    - main_card -> "Main Card"
    """
    if not game_ctx or not game_ctx.card_segment:
        return ""

    segment = game_ctx.card_segment
    return SEGMENT_DISPLAY_NAMES.get(segment, segment.replace("_", " ").title())


# =============================================================================
# Segment Time Variables
# =============================================================================


@register_variable(
    name="main_card_time",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Main card start time (e.g., '10:00 PM EST')",
)
def extract_main_card_time(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract main card start time from ESPN segment data."""

    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.segment_times:
        return ""

    main_card_dt = event.segment_times.get("main_card")
    if not main_card_dt:
        return ""

    return format_time(main_card_dt)


@register_variable(
    name="prelims_time",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Prelims start time (e.g., '8:00 PM EST')",
)
def extract_prelims_time(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract prelims start time from ESPN segment data."""

    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.segment_times:
        return ""

    prelims_dt = event.segment_times.get("prelims")
    if not prelims_dt:
        return ""

    return format_time(prelims_dt)


@register_variable(
    name="early_prelims_time",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Early prelims start time (e.g., '6:00 PM EST')",
)
def extract_early_prelims_time(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract early prelims start time from ESPN segment data."""

    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.segment_times:
        return ""

    early_dt = event.segment_times.get("early_prelims")
    if not early_dt:
        return ""

    return format_time(early_dt)


# =============================================================================
# Bout Card Variables - All fighter pairings on the card
# =============================================================================


@register_variable(
    name="bout_count",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Total number of bouts on the card",
)
def extract_bout_count(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return total number of bouts on the UFC card."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    return str(len(event.bouts)) if event.bouts else ""


@register_variable(
    name="fight_card",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="All bouts formatted as 'Fighter1 vs Fighter2' (newline-separated)",
)
def extract_fight_card(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return all bouts on the card, formatted and newline-separated.

    Bouts are ordered from opener to main event.
    """
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.bouts:
        return ""

    return "\n".join(f"{b.fighter1} vs {b.fighter2}" for b in event.bouts)


@register_variable(
    name="main_card_bouts",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Main card bouts only (newline-separated)",
)
def extract_main_card_bouts(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return main card bouts only, formatted and newline-separated."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.bouts:
        return ""

    main_bouts = [b for b in event.bouts if b.segment == "main_card"]
    return "\n".join(f"{b.fighter1} vs {b.fighter2}" for b in main_bouts)


@register_variable(
    name="prelims_bouts",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Prelims bouts only (newline-separated)",
)
def extract_prelims_bouts(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return prelims bouts only, formatted and newline-separated."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.bouts:
        return ""

    prelim_bouts = [b for b in event.bouts if b.segment == "prelims"]
    return "\n".join(f"{b.fighter1} vs {b.fighter2}" for b in prelim_bouts)


@register_variable(
    name="early_prelims_bouts",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,  # Event EPG only
    description="Early prelims bouts only (newline-separated)",
)
def extract_early_prelims_bouts(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Return early prelims bouts only, formatted and newline-separated."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.bouts:
        return ""

    early_bouts = [b for b in event.bouts if b.segment == "early_prelims"]
    return "\n".join(f"{b.fighter1} vs {b.fighter2}" for b in early_bouts)


# =============================================================================
# Fight Result Variables - Outcome data for finished fights
# =============================================================================

# Display names for result methods
RESULT_DISPLAY_NAMES: dict[str, str] = {
    "ko": "KO",
    "tko": "TKO",
    "submission": "Submission",
    "decision_unanimous": "Decision (Unanimous)",
    "decision_split": "Decision (Split)",
    "decision_majority": "Decision (Majority)",
}

RESULT_SHORT_NAMES: dict[str, str] = {
    "ko": "KO",
    "tko": "TKO",
    "submission": "SUB",
    "decision_unanimous": "UD",
    "decision_split": "SD",
    "decision_majority": "MD",
}

# Weight class abbreviations
WEIGHT_CLASS_ABBREV: dict[str, str] = {
    "Strawweight": "SW",
    "Flyweight": "FLW",
    "Bantamweight": "BW",
    "Featherweight": "FW",
    "Lightweight": "LW",
    "Welterweight": "WW",
    "Middleweight": "MW",
    "Light Heavyweight": "LHW",
    "Heavyweight": "HW",
    "Women's Strawweight": "WSW",
    "Women's Flyweight": "WFLW",
    "Women's Bantamweight": "WBW",
    "Women's Featherweight": "WFW",
}


@register_variable(
    name="fight_result",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Fight result method (e.g., 'TKO', 'Decision (Unanimous)')",
)
def extract_fight_result(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract human-readable fight result method."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.fight_result_method:
        return ""

    return RESULT_DISPLAY_NAMES.get(event.fight_result_method, event.fight_result_method)


@register_variable(
    name="fight_result_short",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Fight result abbreviated (e.g., 'TKO', 'UD', 'SUB')",
)
def extract_fight_result_short(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract abbreviated fight result method."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.fight_result_method:
        return ""

    return RESULT_SHORT_NAMES.get(event.fight_result_method, event.fight_result_method.upper())


@register_variable(
    name="finish_round",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Round fight ended (e.g., '3')",
)
def extract_finish_round(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the round number when fight ended."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or event.finish_round is None:
        return ""

    return str(event.finish_round)


@register_variable(
    name="finish_time",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Time in round when fight ended (e.g., '3:48')",
)
def extract_finish_time(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the time in round when fight ended."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.finish_time:
        return ""

    return event.finish_time


@register_variable(
    name="finish_info",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Combined finish info (e.g., 'R3 3:48')",
)
def extract_finish_info(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract combined round and time info."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    parts = []
    if event.finish_round is not None:
        parts.append(f"R{event.finish_round}")
    if event.finish_time:
        parts.append(event.finish_time)

    return " ".join(parts)


@register_variable(
    name="weight_class",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Weight class (e.g., 'Featherweight', 'Lightweight')",
)
def extract_weight_class(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the weight class of the fight."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.weight_class:
        return ""

    return event.weight_class


@register_variable(
    name="weight_class_short",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Weight class abbreviated (e.g., 'FW', 'LW', 'HW')",
)
def extract_weight_class_short(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract abbreviated weight class."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.weight_class:
        return ""

    return WEIGHT_CLASS_ABBREV.get(event.weight_class, event.weight_class[:2].upper())


@register_variable(
    name="fighter1_record",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Fighter 1's record (e.g., '28-4-0')",
)
def extract_fighter1_record(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract first fighter's win-loss-draw record."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    if event.home_team and event.home_team.record_summary:
        return event.home_team.record_summary

    return ""


@register_variable(
    name="fighter2_record",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Fighter 2's record (e.g., '27-8-0')",
)
def extract_fighter2_record(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract second fighter's win-loss-draw record."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    if event.away_team and event.away_team.record_summary:
        return event.away_team.record_summary

    return ""


@register_variable(
    name="judge_scores",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Judge scores for decisions (e.g., '48-47, 49-46, 48-47')",
)
def extract_judge_scores(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract formatted judge scores for decision results.

    Returns scores in format like '48-47, 49-46, 48-47' showing
    fighter1 score - fighter2 score for each judge.
    """
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma":
        return ""

    # Only show scores for decisions
    if not event.fight_result_method or "decision" not in event.fight_result_method:
        return ""

    scores1 = event.fighter1_scores
    scores2 = event.fighter2_scores

    if not scores1 or not scores2:
        return ""

    # Format as "f1-f2, f1-f2, ..." for each judge
    # ESPN typically provides total scores, so we show them
    if len(scores1) == 1 and len(scores2) == 1:
        return f"{scores1[0]}-{scores2[0]}"

    # Multiple judges
    pairs = []
    for s1, s2 in zip(scores1, scores2, strict=False):
        pairs.append(f"{s1}-{s2}")
    return ", ".join(pairs)


@register_variable(
    name="fight_summary",
    category=Category.COMBAT,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Full result summary (e.g., 'TKO R2 4:31' or 'UD 48-47')",
)
def extract_fight_summary(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract complete fight result summary.

    For finishes: 'TKO R2 4:31'
    For decisions: 'UD 48-47'
    """
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "mma" or not event.fight_result_method:
        return ""

    method = RESULT_SHORT_NAMES.get(event.fight_result_method, event.fight_result_method.upper())

    # For decisions, append judge scores if available
    if "decision" in event.fight_result_method:
        scores = extract_judge_scores(ctx, game_ctx)
        if scores:
            return f"{method} {scores}"
        return method

    # For finishes, append round and time
    parts = [method]
    if event.finish_round is not None:
        parts.append(f"R{event.finish_round}")
    if event.finish_time:
        parts.append(event.finish_time)

    return " ".join(parts)
