"""Exception keywords operations.

Read-only access to consolidation_exception_keywords for lifecycle service.
Full CRUD is in database/exception_keywords.py.
"""

import re
from sqlite3 import Connection
from typing import Any

from teamarr.database.exception_keywords import ExceptionKeyword, get_all_keywords


def get_exception_keywords(conn: Connection, enabled_only: bool = True) -> list[ExceptionKeyword]:
    """Get all consolidation exception keywords.

    Args:
        conn: Database connection
        enabled_only: Only return enabled keywords

    Returns:
        List of ExceptionKeyword objects
    """
    return get_all_keywords(conn, include_disabled=not enabled_only)


def _make_keyword_pattern(term: str) -> str:
    """Create regex pattern with smart boundaries for term matching.

    Uses \\b for word characters, (?<!\\w)/(?!\\w) for non-word characters.
    This allows terms like "(ESP)" to match correctly while still preventing
    false positives like "Eli" matching "Pelicans".

    Supports phrase matching - multi-word terms like "Peyton and Eli" will
    match as a complete phrase.

    Args:
        term: The term/phrase to create a pattern for

    Returns:
        Regex pattern string
    """
    escaped = re.escape(term.lower())

    # Start boundary: \b if term starts with word char, else (?<!\w)
    if term and re.match(r"\w", term[0]):
        start = r"\b"
    else:
        start = r"(?<!\w)"

    # End boundary: \b if term ends with word char, else (?!\w)
    if term and re.match(r"\w", term[-1]):
        end = r"\b"
    else:
        end = r"(?!\w)"

    return start + escaped + end


def event_identity_text(event: Any) -> str:
    """The words an event is named with, for :func:`check_exception_keyword`.

    Name, short name and venue country — "Tag Heuer Spanish Grand Prix",
    "Spanish GP", "Spain". Accepts an Event, a managed-channel row (which
    only carries ``event_name``) or a plain string.
    """
    if event is None:
        return ""
    if isinstance(event, str):
        return event
    parts = [
        getattr(event, "name", None) or getattr(event, "event_name", None),
        getattr(event, "short_name", None),
        getattr(getattr(event, "venue", None), "country", None),
    ]
    return " | ".join(p for p in parts if p)


def check_exception_keyword(
    stream_name: str,
    keywords: list[ExceptionKeyword],
    event_text: str | None = None,
) -> tuple[str | None, str | None]:
    """Check if stream name matches any exception keyword.

    Uses smart boundary matching to avoid false positives like "Eli" matching
    "Pelicans", while still supporting terms with special characters like "(ESP)"
    and multi-word phrases like "Peyton and Eli".

    A term never fires on a word the matched event is itself named with
    (#803): the seeded "Spanish" keyword, set to Ignore, dropped every
    "Spanish Grand Prix" stream on a live install. Pass the event's identity
    text (:func:`event_identity_text`) and any term found inside it is
    skipped for that stream — "Spanish" for the Spanish GP, "French" for the
    French Open — while "En Español" / "(ESP)" still fire, since the event
    is not named with them.

    Args:
        stream_name: Stream name to check
        keywords: List of ExceptionKeyword objects
        event_text: The matched event's name/short name/venue country, or None

    Returns:
        Tuple of (label, behavior) or (None, None) if no match.
        The label is the configured display name for the keyword, used for
        channel naming and the {exception_keyword} template variable.
    """
    stream_lower = stream_name.lower()
    event_lower = event_text.lower() if event_text else ""
    for kw in keywords:
        for term in kw.match_term_list:
            pattern = _make_keyword_pattern(term)
            if event_lower and re.search(pattern, event_lower):
                continue
            if re.search(pattern, stream_lower):
                return (kw.label, kw.behavior)
    return (None, None)
