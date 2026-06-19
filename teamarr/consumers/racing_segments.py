"""Racing session segment handling.

Expands racing events (F1, NASCAR, IndyCar, MotoGP, ...) into session-based
channels (Practice 1, Practice 2, Qualifying, Race, ...). Each matched racing
stream is expanded into one channel entry per session in `event.sessions`,
using ESPN-provided session start times for exact EPG timing.

NASCAR-style single-session events (a single "race" session) degenerate to
one segment via the same code path - no special-casing required.
"""

import logging
import re
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
# is resolved via _session_duration_hours (name parsing, then per-league
# fallback, then the configurable "racing" sport duration).
SESSION_DURATION_HOURS = {
    "fp1": 1.0,
    "fp2": 1.0,
    "fp3": 1.0,
    "sprint_qualifying": 1.0,
    "sprint": 1.0,
    "qualifying": 1.0,
}

# Per-league fallback race durations (hours), for endurance series whose
# typical race length differs significantly from the global "racing" sport
# default. Used when the race name doesn't encode an explicit duration (see
# _parse_duration_from_name) - e.g. IMSA sprint races and WEC's "Petit
# Le Mans" / "Prologue" rounds.
LEAGUE_RACE_DURATION_HOURS = {
    "wec": 6.0,
    "imsa": 2.75,
}

# Word-number forms used in classic endurance race names (e.g. "Mobil 1
# Twelve Hours of Sebring").
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "twenty-four": 24,
    "twenty four": 24,
}

_DURATION_NAME_RE = re.compile(
    r"\b(\d{1,2}|" + "|".join(_WORD_NUMBERS) + r")\s+hours?\b",
    re.IGNORECASE,
)


def _parse_duration_from_name(name: str | None) -> float | None:
    """Extract an explicit race duration (hours) from an event name.

    Handles classics like "24 Hours of Le Mans", "6 Hours of Spa", and
    "Mobil 1 Twelve Hours of Sebring". Returns None if no duration is found.
    """
    if not name:
        return None
    match = _DURATION_NAME_RE.search(name)
    if not match:
        return None
    token = match.group(1).lower()
    if token in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[token])
    return float(token)


def _session_duration_hours(
    session_code: str,
    sport_durations: dict[str, float] | None,
    league: str | None = None,
    event_name: str | None = None,
) -> float:
    """Get the duration (hours) for a session code.

    For the "race" session, resolves in order: an explicit duration parsed
    from the event name (e.g. "24 Hours of Le Mans"), a per-league fallback
    (LEAGUE_RACE_DURATION_HOURS, for endurance series like WEC/IMSA), then
    the configurable "racing" sport duration.
    """
    if session_code == "race":
        if (duration := _parse_duration_from_name(event_name)) is not None:
            return duration
        if league and league in LEAGUE_RACE_DURATION_HOURS:
            return LEAGUE_RACE_DURATION_HOURS[league]
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
        duration = _session_duration_hours(session.code, sport_durations, event.league, event.name)
        return start_time, start_time + timedelta(hours=duration)

    # Session not found - fall back to event start/duration
    duration = _session_duration_hours(session_code, sport_durations, event.league, event.name)
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
            duration = _session_duration_hours(
                session.code, sport_durations, event.league, event.name
            )
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
