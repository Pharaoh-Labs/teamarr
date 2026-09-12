"""Exception keywords operations.

Read-only access to consolidation_exception_keywords for lifecycle service.
Full CRUD is in database/exception_keywords.py.
"""

import re
from sqlite3 import Connection

from teamarr.database.exception_keywords import ExceptionKeyword, get_all_keywords


def get_keywords_for_league(
    conn: Connection,
    league: str | None,
    global_keywords: list[ExceptionKeyword] | None = None,
) -> list[ExceptionKeyword]:
    """Race feeds for ``league`` (#245) first, then the global exception keywords.

    Race feeds are league-scoped keywords (driver onboards, pit lane, tracker
    …); a driver's surname is somebody else's team elsewhere, so they only
    ever join the list for streams of their own league. Precedence is the
    more specific list first: a stream that names a driver is that driver's
    feed even if a global keyword would also match it.
    """
    from teamarr.database.race_feeds import race_feed_keywords

    base = global_keywords if global_keywords is not None else get_exception_keywords(conn)
    return race_feed_keywords(conn, league) + base


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


def check_exception_keyword(
    stream_name: str,
    keywords: list[ExceptionKeyword],
) -> tuple[str | None, str | None]:
    """Check if stream name matches any exception keyword.

    Uses smart boundary matching to avoid false positives like "Eli" matching
    "Pelicans", while still supporting terms with special characters like "(ESP)"
    and multi-word phrases like "Peyton and Eli".

    Args:
        stream_name: Stream name to check
        keywords: List of ExceptionKeyword objects

    Returns:
        Tuple of (label, behavior) or (None, None) if no match.
        The label is the configured display name for the keyword, used for
        channel naming and the {exception_keyword} template variable.
    """
    stream_lower = stream_name.lower()

    for kw in keywords:
        for term in kw.match_term_list:
            pattern = _make_keyword_pattern(term)
            if re.search(pattern, stream_lower):
                # Return the label (not the matched term) for channel naming
                return (kw.label, kw.behavior)

    return (None, None)
