"""Regex over live M3U group names.

Resolves a case-insensitive pattern against the Dispatcharr channel groups
that at least one M3U account provides. It backs the live "matches N
groups" preview in the exception-keyword source editor (a keyword matched
by M3U group, #931). Pattern-bound sources and re-bind suggestions, the
original users of this module (#450), were retired in #1056: source
discovery covers a renamed group on its own.

Scope: M3U-provided groups only (groups carrying at least one M3U-account
relationship). Teamarr-created output/dynamic channel groups and manually
created channel groups are never pattern-resolvable.
"""

import logging
import re

from teamarr.dispatcharr.types import DispatcharrChannelGroup

logger = logging.getLogger(__name__)


def compile_group_pattern(pattern: str | None) -> re.Pattern | None:
    """Compile a group-name pattern, or None if empty/invalid.

    Case-insensitive substring semantics (``re.search``), matching the
    behavior of the other user-facing regex fields (stream include/exclude).
    """
    if not pattern or not pattern.strip():
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        logger.warning("[GROUP_PATTERN] Invalid pattern %r: %s", pattern, e)
        return None


def resolve_group_name_pattern(
    live_groups: list[DispatcharrChannelGroup],
    pattern: str | None,
) -> list[DispatcharrChannelGroup]:
    """Resolve a group-name pattern against live Dispatcharr groups.

    Args:
        live_groups: Current groups from ``m3u.list_groups()``
        pattern: Regex to match against group names (case-insensitive search)

    Returns:
        Matching M3U-provided groups (empty on empty/invalid pattern).
    """
    rx = compile_group_pattern(pattern)
    if rx is None:
        return []
    # getattr with an EMPTY default fails closed: a group object without
    # account relations (or without the field at all) is never pattern-bound.
    return [g for g in live_groups if getattr(g, "m3u_accounts", ()) and rx.search(g.name)]
