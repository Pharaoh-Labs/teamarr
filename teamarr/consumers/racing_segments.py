"""Racing session segment handling.

Expands racing events (F1, NASCAR, IndyCar, MotoGP, ...) into session-based
channels (Practice 1, Practice 2, Qualifying, Race, ...). Each matched racing
stream is expanded into one channel entry per session in `event.sessions`,
using ESPN-provided session start times for exact EPG timing — UNLESS the
stream's own name clearly names one specific session (e.g. "Free Practice
3"), in which case it's scoped to just that session instead of fanning out
across the whole weekend (see _session_category_from_stream_name).

Practice sessions are excluded from that whole-weekend fan-out (they're only
included when a stream's name specifically names one): providers frequently
don't carry a dedicated practice feed at all, and a generic linear stream
landing on a Practice channel is more likely to produce a channel with
nothing actually airing yet than a legitimate live source.

NASCAR-style single-session events (a single "race" session) degenerate to
one segment via the same code path - no special-casing required.
"""

import logging
import re
from datetime import datetime, timedelta

from teamarr.core.types import Event

logger = logging.getLogger(__name__)

# Session-label regexes (looser than the providers.tsdb.racing parser's:
# its _FREE_PRACTICE_RE requires a digit and literal "free practice"/"fp",
# and would miss stream labels like "Practice 2").
_FREE_PRACTICE_RE = re.compile(r"^(?:free\s*practice|practice|fp)\s*(\d*)$", re.IGNORECASE)
_QUALIFYING_RE = re.compile(
    r"^(?:hyperpole\s+)?qualifying(?:\s*[-–]\s*(.+))?$", re.IGNORECASE
)
_HYPERPOLE_RE = re.compile(
    r"^hyperpole\s*(\d*)\s*(?:[-–]\s*(.+))?$", re.IGNORECASE
)
_PROLOGUE_RE = re.compile(r"prologue", re.IGNORECASE)

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


# Session labels that don't need a regex (either fully generic words that
# would be too risky to substring-match anywhere in a stream name, or short
# fixed phrases the tsdb parser's regexes don't cover on their own).
_EXACT_SESSION_LABELS = {
    "race": "race",
    "feature race": "race",
    "sprint": "sprint",
    "sprint race": "sprint",
    "sprint qualifying": "sprint_qualifying",
    "warm up": "warmup",
    "warmup": "warmup",
}

# Fallback for labels shaped "<Series/event description> <SessionType>"
# (session type as a TRAILING word, not the whole label) — e.g. NASCAR/TSN+
# streams named "NASCAR Cup Series Qualifying" or "2026 NASCAR ORAP Series
# Qualifying", where the tsdb-style anchored regexes above (which require
# the label to BE the session type) don't match. Anchored at the end of the
# label (not a bare substring search), so "Pre-Race" still counts as naming
# the race, while "Pre-Race Show" (doesn't end in the keyword) and
# "Racecourse Network" (keyword mid-word, not at the end) do not.
_TRAILING_FP_RE = re.compile(r"\b(?:free\s*practice|practice|fp)\s*(\d?)\s*$", re.IGNORECASE)
_TRAILING_SPRINT_QUALIFYING_RE = re.compile(r"\bsprint\s*qualifying\s*$", re.IGNORECASE)
_TRAILING_HYPERPOLE_RE = re.compile(r"\bhyperpole\s*$", re.IGNORECASE)
_TRAILING_WARMUP_RE = re.compile(r"\bwarm[\s-]?up\s*$", re.IGNORECASE)
_TRAILING_QUALIFYING_RE = re.compile(r"\bqualifying\s*$", re.IGNORECASE)
_TRAILING_SPRINT_RACE_RE = re.compile(r"\bsprint\s*race\s*$", re.IGNORECASE)
_TRAILING_RACE_RE = re.compile(r"\brace\s*$", re.IGNORECASE)
_TRAILING_SPRINT_RE = re.compile(r"\bsprint\s*$", re.IGNORECASE)


def _session_category_from_trailing_keyword(label: str) -> str | None:
    """Session category for a label ending in a session-type WORD.

    Checked in specificity order so e.g. "Sprint Qualifying" resolves to
    sprint_qualifying rather than the bare "qualifying" suffix match.
    """
    if m := _TRAILING_FP_RE.search(label):
        # NASCAR emits an unnumbered "practice" session code, and TSN+ labels
        # the feed "<Series> Practice" with no digit — same mapping as
        # _FREE_PRACTICE_RE's bare-"Practice" case.
        return f"fp{m.group(1)}" if m.group(1) else "practice"
    if _TRAILING_SPRINT_QUALIFYING_RE.search(label):
        return "sprint_qualifying"
    if _TRAILING_HYPERPOLE_RE.search(label):
        return "hyperpole"
    if _TRAILING_WARMUP_RE.search(label):
        return "warmup"
    if _TRAILING_QUALIFYING_RE.search(label):
        return "qualifying"
    if _TRAILING_SPRINT_RACE_RE.search(label):
        return "sprint"
    if _TRAILING_RACE_RE.search(label):
        return "race"
    if _TRAILING_SPRINT_RE.search(label):
        return "sprint"
    return None


def _isolate_stream_session_label(stream_name: str) -> str:
    """Best-effort isolation of a session-label field from a stream name.

    Provider-tagged racing streams are commonly shaped like
    "<provider tag> | <Session Label>: <description> (<timestamp>)" (e.g.
    "AU (STAN 36) | Free Practice 3: 6 Hours of Sao Paulo WEC 2026 (...)").
    Taking the segment after the last "|" and before the first ":" isolates
    just the label field, so keyword detection runs against a narrow,
    structured slice instead of the whole noisy name — "Race" only counts as
    a session label when it more or less stands alone, not when it's merely
    a substring of some unrelated branding text.
    """
    segment = stream_name.rsplit("|", 1)[-1] if "|" in stream_name else stream_name
    return segment.split(":", 1)[0].strip()


def _session_category_from_stream_name(stream_name: str) -> str | None:
    """Best-effort session-type CATEGORY from a stream's own name.

    Reuses the same anchored regexes the TSDB parser uses to classify
    session labels (inlined above), applied to the
    isolated label field instead of a full TSDB event name. Returns a
    CATEGORY, not necessarily an exact `RacingSession.code` — a bare
    "Qualifying" can't disambiguate "qualifying_hypercar" from
    "qualifying_lmgt3", so it maps to a category that covers every session
    of that type via `_session_in_category` below, rather than guessing
    wrong and excluding one.

    Returns None when the label doesn't clearly encode a session type
    (the common case for a linear/whole-weekend channel's own name, e.g.
    "HBO UK 065"), so callers can fall back to their existing full
    session fan-out — this function is deliberately conservative to avoid
    false negatives (a real session-specific stream getting excluded from
    the one session channel it actually belongs on).
    """
    label = _isolate_stream_session_label(stream_name)
    if not label:
        return None
    if category := _EXACT_SESSION_LABELS.get(label.lower()):
        return category
    if m := _FREE_PRACTICE_RE.match(label):
        return f"fp{m.group(1)}" if m.group(1) else "practice"
    if _QUALIFYING_RE.match(label):
        return "qualifying"
    if _HYPERPOLE_RE.match(label):
        return "hyperpole"
    if _PROLOGUE_RE.search(label):
        return "prologue"
    # Fallback: the label isn't ENTIRELY a session type, but ENDS in one —
    # e.g. NASCAR/TSN+'s "NASCAR Cup Series Qualifying" or "2026 NASCAR ORAP
    # Series Qualifying", vs. tsdb/STAN's convention of the label being just
    # "Qualifying" on its own (handled above).
    return _session_category_from_trailing_keyword(label)


def _session_in_category(session_code: str, category: str) -> bool:
    """True if `session_code` belongs to the coarse `category`.

    Numbered practice sessions (fp1/fp2/fp3) must match exactly — a stream
    labeled "Free Practice 3" names ONE specific session, not every
    practice session. Everything else matches the category itself or any
    class-suffixed variant (category="qualifying" covers both
    "qualifying_hypercar" and "qualifying_lmgt3").

    A bare "qualifying" category also covers hyperpole sessions: WEC's
    Hyperpole is itself a qualifying-shootout round, and providers rarely
    label it distinctly from regular qualifying — a stream generically
    labeled "Qualifying" is a real candidate for a Hyperpole session too,
    not just an exact-name "qualifying_*" one.
    """
    if category.startswith("fp"):
        return session_code == category
    if category == "qualifying" and (
        session_code == "hyperpole" or session_code.startswith("hyperpole_")
    ):
        return True
    return session_code == category or session_code.startswith(f"{category}_")


def _is_practice_session(session_code: str) -> bool:
    """True for practice-type sessions (fp1/fp2/fp3, or an unnumbered "practice")."""
    return session_code.startswith("fp") or session_code == "practice"


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

        # is_racing_event returned True, so event is a non-None racing Event.
        assert event is not None

        expanded_streams += 1
        sessions = sorted(event.sessions, key=lambda s: s.start_time)

        # Scope to a single session (or session category) when the stream's
        # own name clearly names one — e.g. a dedicated "Free Practice 3"
        # feed must not also show up as the Qualifying/Race channel's
        # source. A stream whose name carries no such hint (a linear
        # channel's own branding, e.g. "HBO UK 065") keeps the full
        # fan-out, unchanged from before — EXCEPT practice sessions, which
        # are dropped from that fan-out rather than kept (see below).
        stream_name = match.get("stream", {}).get("name") or ""
        if category := _session_category_from_stream_name(stream_name):
            scoped = [s for s in sessions if _session_in_category(s.code, category)]
            if scoped:
                sessions = scoped
        else:
            # Providers frequently don't carry a dedicated practice feed at
            # all (coverage often starts at qualifying), so a generic
            # whole-weekend stream landing on a Practice channel is more
            # likely to produce a channel with nothing actually airing yet
            # than a legitimate live source. Only include a practice
            # session when the stream's own name specifically named it
            # (handled by the scoping above); otherwise skip practice
            # sessions in the full fan-out — better no channel than one
            # that's dead air until qualifying starts.
            sessions = [s for s in sessions if not _is_practice_session(s.code)]

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
