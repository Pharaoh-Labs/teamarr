"""
Filter Reasons - Single Source of Truth

Centralized definitions for all stream filtering and event matching reasons.
These constants are used throughout the codebase for consistency in:
- Event matcher results
- Preview modal display
- Statistics tracking
- Logging

Usage:
    from utils.filter_reasons import FilterReason, get_display_text

    # In event_matcher.py
    result['reason'] = FilterReason.GAME_FINAL_EXCLUDED

    # In UI/templates
    display_text = get_display_text(reason)
"""


class FilterReason:
    """
    Constants for filter/match reasons.

    Categories:
    1. Stream filtering (pre-matching)
    2. Event matching (post-team-parsing)
    """

    # =========================================================================
    # Stream Filtering Reasons (before team matching)
    # =========================================================================

    # Built-in game indicator filter
    NO_GAME_INDICATOR = 'no_game_indicator'

    # User inclusion regex not matched
    INCLUDE_REGEX_NOT_MATCHED = 'include_regex_not_matched'

    # User exclusion regex matched
    EXCLUDE_REGEX_MATCHED = 'exclude_regex_matched'

    # =========================================================================
    # Event Matching Reasons (after successful team parsing)
    # =========================================================================

    # Game from previous day(s) - always excluded
    GAME_PAST = 'game_past'

    # Today's game is final - excluded by user setting
    GAME_FINAL_EXCLUDED = 'game_final_excluded'

    # No ESPN event found for the team matchup
    NO_GAME_FOUND = 'no_game_found'

    # Teams successfully parsed but outside lookahead window
    OUTSIDE_LOOKAHEAD = 'outside_lookahead'

    # =========================================================================
    # Team Parsing Reasons
    # =========================================================================

    # Could not parse team names from stream
    TEAMS_NOT_PARSED = 'teams_not_parsed'


# Display text for user-facing UI (preview modal, etc.)
DISPLAY_TEXT = {
    FilterReason.NO_GAME_INDICATOR: 'Excluded by filter',
    FilterReason.INCLUDE_REGEX_NOT_MATCHED: 'Did not match inclusion pattern',
    FilterReason.EXCLUDE_REGEX_MATCHED: 'Matched exclusion pattern',
    FilterReason.GAME_PAST: 'Event already passed',
    FilterReason.GAME_FINAL_EXCLUDED: 'Event is final (excluded)',
    FilterReason.NO_GAME_FOUND: 'No event found',
    FilterReason.OUTSIDE_LOOKAHEAD: 'Outside lookahead range',
    FilterReason.TEAMS_NOT_PARSED: 'Teams not parsed',
}

# Internal reasons (used by event_matcher.py for backwards compatibility)
# These map to the FilterReason constants
INTERNAL_REASONS = {
    'Game already completed (past)': FilterReason.GAME_PAST,
    'Game completed (excluded)': FilterReason.GAME_FINAL_EXCLUDED,
    'No game found between teams': FilterReason.NO_GAME_FOUND,
}

# Reverse mapping for converting internal reasons to display text
INTERNAL_TO_DISPLAY = {
    'Game already completed (past)': DISPLAY_TEXT[FilterReason.GAME_PAST],
    'Game completed (excluded)': DISPLAY_TEXT[FilterReason.GAME_FINAL_EXCLUDED],
    'No game found between teams': DISPLAY_TEXT[FilterReason.NO_GAME_FOUND],
}


def get_display_text(reason: str, lookahead_days: int = None) -> str:
    """
    Get user-friendly display text for a filter reason.

    Args:
        reason: The filter reason constant or internal reason string
        lookahead_days: Optional lookahead days for NO_GAME_FOUND reason

    Returns:
        Human-readable display text
    """
    # Check if it's a FilterReason constant
    if reason in DISPLAY_TEXT:
        text = DISPLAY_TEXT[reason]
        if reason == FilterReason.NO_GAME_FOUND and lookahead_days:
            return f'No event in lookahead range ({lookahead_days} days)'
        return text

    # Check if it's an internal reason string (backwards compatibility)
    if reason in INTERNAL_TO_DISPLAY:
        return INTERNAL_TO_DISPLAY[reason]

    # Return as-is if not recognized
    return reason


def normalize_reason(reason: str) -> str:
    """
    Normalize an internal reason string to a FilterReason constant.

    Args:
        reason: Internal reason string from event_matcher

    Returns:
        FilterReason constant, or original string if not recognized
    """
    return INTERNAL_REASONS.get(reason, reason)


def is_excluded_from_count(reason: str) -> bool:
    """
    Check if a reason should exclude the stream from the match rate denominator.

    Streams that match this criteria are not "failures to match" - they're
    streams where matching isn't applicable (past games, finals when excluded,
    or no event found in the lookahead window).

    Args:
        reason: Filter reason constant or internal reason string

    Returns:
        True if stream should be excluded from match rate calculation
    """
    normalized = normalize_reason(reason)
    return normalized in (
        FilterReason.GAME_PAST,
        FilterReason.GAME_FINAL_EXCLUDED,
        FilterReason.NO_GAME_FOUND,  # No event in lookahead range
    )


# Database column mapping for statistics
DB_COLUMN_MAPPING = {
    FilterReason.NO_GAME_INDICATOR: 'filtered_no_indicator',
    FilterReason.INCLUDE_REGEX_NOT_MATCHED: 'filtered_include_regex',
    FilterReason.EXCLUDE_REGEX_MATCHED: 'filtered_exclude_regex',
    FilterReason.GAME_PAST: 'filtered_outside_lookahead',
    FilterReason.GAME_FINAL_EXCLUDED: 'filtered_final',
    FilterReason.NO_GAME_FOUND: 'filtered_outside_lookahead',  # Combined with GAME_PAST
}
