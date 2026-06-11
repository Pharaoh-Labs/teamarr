"""Racing session segment handling.

Expands racing events (F1, NASCAR, IndyCar, MotoGP, ...) into session-based
channels (Practice 1, Practice 2, Qualifying, Race, ...). Each matched racing
stream is expanded into one channel entry per session in `event.sessions`,
using ESPN-provided session start times for exact EPG timing.

NASCAR-style single-session events (a single "race" session) degenerate to
one segment via the same code path - no special-casing required.
"""

import logging
from datetime import datetime, timedelta

from teamarr.core.types import Event

logger = logging.getLogger(__name__)

# Canonical session order, earliest to latest within a race weekend.
SESSION_ORDER = [
    "fp1",
    "fp2",
    "fp3",
    "sprint_qualifying",
    "sprint",
    "qualifying",
    "race",
]


def is_racing_event(event: Event | None) -> bool:
    """Check if event is a racing event with session data to expand."""
    if not event:
        return False
    return event.sport == "racing" and bool(event.sessions)


def get_session_times(
    event: Event,
    session_code: str,
    sport_durations: dict[str, float] | None = None,
) -> tuple[datetime, datetime]:
    """Get start/end times for a session from ESPN session data.

    End time is the next session's start time, or an estimated duration
    (sport_durations["racing"], default 3 hours) for the last session.

    Args:
        event: Racing Event with sessions from ESPN
        session_code: Session code (e.g., "fp1", "qualifying", "race")
        sport_durations: Optional duration settings (for last-session fallback)

    Returns:
        Tuple of (start_time, end_time)
    """
    racing_duration = (sport_durations or {}).get("racing", 3.0)
    sessions = sorted(event.sessions, key=lambda s: s.start_time)

    for idx, session in enumerate(sessions):
        if session.code != session_code:
            continue
        start_time = session.start_time
        if idx + 1 < len(sessions):
            end_time = sessions[idx + 1].start_time
        else:
            end_time = start_time + timedelta(hours=racing_duration)
        return start_time, end_time

    # Session not found - fall back to event start/duration
    return event.start_time, event.start_time + timedelta(hours=racing_duration)


def expand_racing_segments(
    matched_streams: list[dict],
    sport_durations: dict[str, float] | None = None,
) -> list[dict]:
    """Expand racing matched streams into session-based channels.

    For each matched racing stream, creates one entry per session in
    `event.sessions`, with `segment`, `segment_display`, `segment_start`,
    and `segment_end` fields populated from ESPN session data. Non-racing
    streams pass through unchanged.

    Args:
        matched_streams: List of {'stream': ..., 'event': ...} dicts
        sport_durations: Optional sport duration settings

    Returns:
        Expanded list with racing streams split by session
    """
    result = []
    racing_duration = (sport_durations or {}).get("racing", 3.0)
    expanded_streams = 0
    session_entries = 0

    for match in matched_streams:
        event = match.get("event")

        if not is_racing_event(event):
            result.append(match)
            continue

        expanded_streams += 1
        sessions = sorted(event.sessions, key=lambda s: s.start_time)

        for idx, session in enumerate(sessions):
            start_time = session.start_time
            if idx + 1 < len(sessions):
                end_time = sessions[idx + 1].start_time
            else:
                end_time = start_time + timedelta(hours=racing_duration)

            result.append(
                {
                    **match,
                    "segment": session.code,
                    "segment_display": session.name,
                    "segment_start": start_time,
                    "segment_end": end_time,
                }
            )
            session_entries += 1

    if expanded_streams:
        logger.info(
            "[RACING_SEGMENTS] Expanded %d racing stream(s) into %d session channels",
            expanded_streams,
            session_entries,
        )

    return result
