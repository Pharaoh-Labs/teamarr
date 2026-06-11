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

# Fixed session durations (hours), independent of when the next session
# starts. Practice/qualifying/sprint sessions run ~1 hour; the race itself
# uses the configurable "racing" sport duration (default 3 hours).
SESSION_DURATION_HOURS = {
    "fp1": 1.0,
    "fp2": 1.0,
    "fp3": 1.0,
    "sprint_qualifying": 1.0,
    "sprint": 1.0,
    "qualifying": 1.0,
}


def _session_duration_hours(
    session_code: str, sport_durations: dict[str, float] | None
) -> float:
    """Get the fixed duration (hours) for a session code."""
    if session_code == "race":
        return (sport_durations or {}).get("racing", 3.0)
    return SESSION_DURATION_HOURS.get(session_code, 1.0)


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

    Each session runs for a fixed duration based on its type (practice/
    qualifying/sprint sessions: 1 hour; race: sport_durations["racing"],
    default 3 hours), regardless of when the next session starts.

    Args:
        event: Racing Event with sessions from ESPN
        session_code: Session code (e.g., "fp1", "qualifying", "race")
        sport_durations: Optional duration settings (for race duration)

    Returns:
        Tuple of (start_time, end_time)
    """
    for session in event.sessions:
        if session.code != session_code:
            continue
        start_time = session.start_time
        duration = _session_duration_hours(session.code, sport_durations)
        return start_time, start_time + timedelta(hours=duration)

    # Session not found - fall back to event start/duration
    duration = _session_duration_hours(session_code, sport_durations)
    return event.start_time, event.start_time + timedelta(hours=duration)


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
    expanded_streams = 0
    session_entries = 0

    for match in matched_streams:
        event = match.get("event")

        if not is_racing_event(event):
            result.append(match)
            continue

        expanded_streams += 1
        sessions = sorted(event.sessions, key=lambda s: s.start_time)

        for session in sessions:
            start_time = session.start_time
            duration = _session_duration_hours(session.code, sport_durations)
            end_time = start_time + timedelta(hours=duration)

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
