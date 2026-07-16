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
from difflib import SequenceMatcher

from teamarr.dispatcharr.types import DispatcharrChannelGroup

logger = logging.getLogger(__name__)

# A rename candidate must be at least this similar to the stale source's old
# group name to be suggested. Below this the "match" is coincidence, and a
# wrong re-bind suggestion is worse than none.
SIMILARITY_THRESHOLD = 0.6

# A suggested pattern needs at least this many literal (non-wildcard)
# characters — "^.+$" style patterns match everything and must never be
# offered.
_MIN_LITERAL_CHARS = 4


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


def suggest_pattern(old_name: str, new_name: str) -> str | None:
    """Synthesize a name pattern from a rename pair (bpqb.5, the flywheel).

    Diffs the old and new group names into common prefix + varying token +
    common suffix, and builds an anchored regex that literal-matches the
    stable parts: ``EPL (MW1)`` vs ``EPL (MW2)`` -> ``^EPL\\ \\(MW\\d+\\)$``.
    The varying token becomes ``\\d+`` when it is numeric on both sides,
    otherwise ``.+`` (``.*`` when one side's token is empty).

    Returns None when no safe pattern exists: identical names, too little
    stable text (the pattern would match everything), or the synthesized
    regex failing to match either name under resolver semantics.
    """
    if not old_name or not new_name or old_name == new_name:
        return None

    # Common prefix, then common suffix of the remainders (never overlapping).
    max_common = min(len(old_name), len(new_name))
    prefix = 0
    while prefix < max_common and old_name[prefix] == new_name[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < max_common - prefix
        and old_name[len(old_name) - 1 - suffix] == new_name[len(new_name) - 1 - suffix]
    ):
        suffix += 1

    if prefix + suffix < _MIN_LITERAL_CHARS:
        return None

    old_mid = old_name[prefix : len(old_name) - suffix]
    new_mid = new_name[prefix : len(new_name) - suffix]

    if old_mid.isdigit() and new_mid.isdigit():
        token = r"\d+"
    elif not old_mid or not new_mid:
        token = r".*"
    else:
        token = r".+"

    pattern = (
        "^"
        + re.escape(old_name[:prefix])
        + token
        + re.escape(old_name[len(old_name) - suffix :] if suffix else "")
        + "$"
    )

    # Must round-trip under the exact semantics the resolver uses.
    rx = compile_group_pattern(pattern)
    if rx is None or not rx.search(old_name) or not rx.search(new_name):
        return None
    return pattern


def find_rebind_suggestions(
    stale_sources: list[dict],
    live_groups: list[DispatcharrChannelGroup],
    bound_group_ids: set[int],
    account_group_ids: dict[int, set[int]] | None = None,
) -> list[dict]:
    """Match stale sources to likely-renamed live groups (bpqb.4).

    For each stale source (its pinned group vanished), scan live M3U-provided
    groups that no source is bound to and pick the closest name match. A hit
    above SIMILARITY_THRESHOLD yields a re-bind suggestion, enriched with a
    synthesized pattern (see suggest_pattern) when one can be built safely.

    A rename happens WITHIN one provider playlist, so candidates are scoped
    to the stale source's own M3U account: Dispatcharr group names are
    global, and ``list_groups``'s nested account payload is version-dependent
    (absent on 0.27.2), so attribution comes from the account detail endpoint
    (``account_group_ids``). An account-bound source whose account has no
    entry in that map (detail fetch failed) gets NO suggestion — a
    cross-account false positive is worse than none. Sources without an
    account binding scan all M3U-provided groups, mirroring fetch semantics.

    Args:
        stale_sources: Rows from ``get_stale_groups`` (need ``id``, ``name``,
            ``display_name``, ``m3u_group_name``, ``m3u_account_id``)
        live_groups: Current groups from ``m3u.list_groups()``
        bound_group_ids: m3u_group_ids already pinned by ANY source —
            a group someone is already using is not a rename candidate
        account_group_ids: m3u_account_id -> ids of the groups that account
            provides (from ``get_account_group_counts``); entries present
            only for successfully fetched accounts

    Returns:
        One suggestion dict per stale source with a viable candidate.
    """
    all_candidates = [
        g
        for g in live_groups
        if getattr(g, "m3u_accounts", ()) and g.id not in bound_group_ids
    ]
    suggestions: list[dict] = []
    for row in stale_sources:
        old_name = row.get("m3u_group_name")
        if not old_name:
            continue
        account_id = row.get("m3u_account_id")
        if account_id is not None:
            account_groups = (account_group_ids or {}).get(account_id)
            if account_groups is None:
                continue  # attribution unavailable — never suggest cross-account
            candidates = [g for g in all_candidates if g.id in account_groups]
        else:
            candidates = all_candidates
        if not candidates:
            continue
        scored = max(
            (
                (SequenceMatcher(None, old_name.lower(), g.name.lower()).ratio(), g)
                for g in candidates
            ),
            key=lambda pair: pair[0],
        )
        ratio, best = scored
        if ratio < SIMILARITY_THRESHOLD:
            continue
        suggestions.append(
            {
                "group_id": row["id"],
                "group_name": row.get("display_name") or row.get("name"),
                "old_group_name": old_name,
                "candidate_group_id": best.id,
                "candidate_group_name": best.name,
                "similarity": round(ratio, 3),
                "suggested_pattern": suggest_pattern(old_name, best.name),
            }
        )
    return suggestions
