"""Motorsports template variables (F1, NASCAR, IndyCar, MotoGP, ...).

Variables for race weekend sessions, grid/qualifying order, and race results.
All extractors are gated on `event.sport == "racing"`.

Event Info:
    race_name: Grand Prix / race name (e.g., "Monaco Grand Prix")
    circuit_name: Circuit name (e.g., "Circuit de Monaco")

Sessions:
    session_name: Display name of this channel's session ("Practice 1", "Race")
    session_type: Raw session code for this channel ("fp1", "qualifying", "race")
    next_session_name, next_session_time: Next session after this one

Race Format (NASCAR, oval tracks):
    race_laps: Scheduled lap count (e.g., "267")
    race_distance: Scheduled distance in miles (e.g., "400")
    stage_1_laps: Cumulative lap where stage 1 ends (e.g., "90")
    stage_2_laps: Cumulative lap where stage 2 ends (e.g., "185")
    stage_3_laps: Cumulative lap where stage 3 ends (e.g., "267")
    stage_summary: All stage endpoints joined (e.g., "90/185/267")

Grid/Qualifying:
    pole_position, pole_team: Driver/team that took pole position
    grid: Full starting order (newline-separated "N. Driver (Team)")

Results (race session, once finished):
    race_winner: Race winner driver name
    podium_2, podium_3: 2nd/3rd place drivers
    podium: Combined "1. X, 2. Y, 3. Z"
    results: Full finishing order (newline-separated "N. Driver (Team)")
    fastest_lap_driver: Driver awarded fastest lap

Usage example:
    "{race_name} - {session_name}" -> "Monaco Grand Prix - Qualifying"
    "Pole: {pole_position} ({pole_team})"
"""

from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    TemplateScope,
    register_variable,
)

# Mirrors teamarr.providers.espn.tournament._RACING_SESSION_NAMES
SESSION_DISPLAY_NAMES: dict[str, str] = {
    "fp1": "Practice 1",
    "fp2": "Practice 2",
    "fp3": "Practice 3",
    "fp4": "Practice 4",
    "sprint_qualifying": "Sprint Qualifying",
    "sprint": "Sprint",
    "qualifying": "Qualifying",
    "race": "Race",
}


def _session_display_name(code: str) -> str:
    return SESSION_DISPLAY_NAMES.get(code, code.replace("_", " ").title())


def _find_session(event, code: str):
    """Find a session by code, if present."""
    for session in event.sessions:
        if session.code == code:
            return session
    return None


def _qualifying_session(event):
    """Find the most relevant qualifying session for grid/pole info."""
    return _find_session(event, "qualifying") or _find_session(event, "sprint_qualifying")


def _format_result_line(result) -> str:
    pos = result.grid_position if result.position is None else result.position
    prefix = f"{pos}. " if pos is not None else ""
    if result.team_name:
        return f"{prefix}{result.driver_name} ({result.team_name})"
    return f"{prefix}{result.driver_name}"


@register_variable(
    name="race_name",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Race weekend / Grand Prix name (e.g., 'Monaco Grand Prix')",
)
def extract_race_name(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the race weekend name."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    return event.name or ""


@register_variable(
    name="circuit_name",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Circuit/track name (e.g., 'Circuit de Monaco')",
)
def extract_circuit_name(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the circuit name."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    return event.circuit_name or ""


@register_variable(
    name="session_name",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,  # Session is specific to current channel
    description="This channel's session display name (e.g., 'Practice 1', 'Race')",
)
def extract_session_name(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the display name of this channel's racing session."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing" or not game_ctx.card_segment:
        return ""

    return _session_display_name(game_ctx.card_segment)


@register_variable(
    name="session_type",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,  # Session is specific to current channel
    description="This channel's session code (e.g., 'fp1', 'qualifying', 'race')",
)
def extract_session_type(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the raw session code for this channel."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    return game_ctx.card_segment or ""


@register_variable(
    name="next_session_name",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,  # Session is specific to current channel
    description="Display name of the next session after this one",
)
def extract_next_session_name(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the display name of the session following this channel's session."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing" or not game_ctx.card_segment:
        return ""

    sessions = sorted(event.sessions, key=lambda s: s.start_time)
    for idx, session in enumerate(sessions):
        if session.code == game_ctx.card_segment and idx + 1 < len(sessions):
            return _session_display_name(sessions[idx + 1].code)

    return ""


@register_variable(
    name="next_session_time",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,  # Session is specific to current channel
    description="Start time of the next session after this one",
)
def extract_next_session_time(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the start time of the session following this channel's session."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing" or not game_ctx.card_segment:
        return ""

    sessions = sorted(event.sessions, key=lambda s: s.start_time)
    for idx, session in enumerate(sessions):
        if session.code == game_ctx.card_segment and idx + 1 < len(sessions):
            return sessions[idx + 1].start_time.strftime("%-I:%M %p")

    return ""


@register_variable(
    name="race_laps",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Scheduled lap count (e.g., '267')",
)
def extract_race_laps(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the scheduled number of laps."""
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.sport != "racing" or event.race_laps is None:
        return ""
    return str(event.race_laps)


@register_variable(
    name="race_distance",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Scheduled race distance in miles (e.g., '400')",
)
def extract_race_distance(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the scheduled race distance."""
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.sport != "racing" or event.race_distance_miles is None:
        return ""
    miles = event.race_distance_miles
    return str(int(miles)) if miles == int(miles) else str(miles)


def _cumulative_stage_laps(event) -> list[int]:
    """Convert per-stage counts to cumulative lap endpoints."""
    cumulative = []
    total = 0
    for laps in event.stage_laps:
        total += laps
        cumulative.append(total)
    return cumulative


@register_variable(
    name="stage_1_laps",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Cumulative lap where stage 1 ends (e.g., '90')",
)
def extract_stage_1_laps(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the lap number at which stage 1 ends."""
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.sport != "racing":
        return ""
    ends = _cumulative_stage_laps(event)
    return str(ends[0]) if len(ends) >= 1 else ""


@register_variable(
    name="stage_2_laps",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Cumulative lap where stage 2 ends (e.g., '185')",
)
def extract_stage_2_laps(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the lap number at which stage 2 ends."""
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.sport != "racing":
        return ""
    ends = _cumulative_stage_laps(event)
    return str(ends[1]) if len(ends) >= 2 else ""


@register_variable(
    name="stage_3_laps",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Cumulative lap where stage 3 ends (e.g., '267')",
)
def extract_stage_3_laps(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the lap number at which stage 3 ends."""
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.sport != "racing":
        return ""
    ends = _cumulative_stage_laps(event)
    return str(ends[2]) if len(ends) >= 3 else ""


@register_variable(
    name="stage_summary",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Stage endpoints joined by slash (e.g., '90/185/267')",
)
def extract_stage_summary(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract a slash-joined summary of cumulative stage lap endpoints."""
    if not game_ctx or not game_ctx.event:
        return ""
    event = game_ctx.event
    if event.sport != "racing":
        return ""
    ends = _cumulative_stage_laps(event)
    return "/".join(str(n) for n in ends) if ends else ""


@register_variable(
    name="pole_position",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Driver who took pole position (P1 in qualifying)",
)
def extract_pole_position(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the pole position driver's name."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    session = _qualifying_session(event)
    if not session:
        return ""

    for result in session.results:
        if result.grid_position == 1 or result.position == 1:
            return result.driver_name

    return ""


@register_variable(
    name="pole_team",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team/constructor of the pole position driver",
)
def extract_pole_team(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the pole position driver's team name."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    session = _qualifying_session(event)
    if not session:
        return ""

    for result in session.results:
        if result.grid_position == 1 or result.position == 1:
            return result.team_name or ""

    return ""


@register_variable(
    name="grid",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Full starting grid order (newline-separated 'N. Driver (Team)')",
)
def extract_grid(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the full starting grid order from qualifying."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    session = _qualifying_session(event)
    if not session or not session.results:
        return ""

    ordered = sorted(
        session.results,
        key=lambda r: (r.grid_position is None, r.grid_position, r.position is None, r.position),
    )
    return "\n".join(_format_result_line(r) for r in ordered)


@register_variable(
    name="race_winner",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Race winner's name (once the race has finished)",
)
def extract_race_winner(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the race winner's name."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    session = _find_session(event, "race")
    if not session:
        return ""

    for result in session.results:
        if result.position == 1:
            return result.driver_name

    return ""


@register_variable(
    name="podium_2",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="2nd place finisher's name (once the race has finished)",
)
def extract_podium_2(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the 2nd place finisher's name."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    session = _find_session(event, "race")
    if not session:
        return ""

    for result in session.results:
        if result.position == 2:
            return result.driver_name

    return ""


@register_variable(
    name="podium_3",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="3rd place finisher's name (once the race has finished)",
)
def extract_podium_3(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the 3rd place finisher's name."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    session = _find_session(event, "race")
    if not session:
        return ""

    for result in session.results:
        if result.position == 3:
            return result.driver_name

    return ""


@register_variable(
    name="podium",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Top 3 finishers, combined (e.g., '1. X, 2. Y, 3. Z')",
)
def extract_podium(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the combined podium summary."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    session = _find_session(event, "race")
    if not session:
        return ""

    podium = {r.position: r.driver_name for r in session.results if r.position in (1, 2, 3)}
    if not podium:
        return ""

    return ", ".join(f"{pos}. {podium[pos]}" for pos in sorted(podium))


@register_variable(
    name="results",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Full race finishing order (newline-separated 'N. Driver (Team)')",
)
def extract_results(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the full race finishing order."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    session = _find_session(event, "race")
    if not session or not any(r.position is not None for r in session.results):
        return ""

    ordered = sorted(
        session.results,
        key=lambda r: (r.position is None, r.position, r.grid_position is None, r.grid_position),
    )
    return "\n".join(_format_result_line(r) for r in ordered)


@register_variable(
    name="fastest_lap_driver",
    category=Category.MOTORSPORTS,
    scope=TemplateScope.EVENT_ONLY,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Driver awarded fastest lap (once the race has finished)",
)
def extract_fastest_lap_driver(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    """Extract the fastest lap driver's name."""
    if not game_ctx or not game_ctx.event:
        return ""

    event = game_ctx.event
    if event.sport != "racing":
        return ""

    session = _find_session(event, "race")
    if not session:
        return ""

    for result in session.results:
        if result.fastest_lap:
            return result.driver_name

    return ""
