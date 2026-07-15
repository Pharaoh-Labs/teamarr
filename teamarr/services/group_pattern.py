"""Group-name pattern resolution for rename-resilient source binding (#450).

IPTV providers churn M3U group names ("EPL (MW1)" -> "EPL (MW2)"); Dispatcharr
matches M3U groups by exact name, so a provider rename always spawns a NEW
Dispatcharr group id and a source pinned to the old id goes stale. A source
with pattern binding enabled is instead bound to a regex over live M3U group
NAMES, re-resolved on every stream fetch — renames re-bind automatically.

Scope: M3U-provided groups only (groups carrying at least one M3U-account
relationship). Teamarr-created output/dynamic channel groups and manually
created channel groups are never pattern-resolvable.

Account scoping happens at STREAM fetch, not here: Dispatcharr group names are
global (one ChannelGroup row shared by every account whose playlist has that
group-title), so the resolver returns name matches and the caller passes the
source's m3u_account_id to list_streams. During a provider's transition week
the old (stale) and new groups coexist (~stale_stream_days, default 7); both
resolve, and the existing stale-stream filter drops the old group's streams.
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
