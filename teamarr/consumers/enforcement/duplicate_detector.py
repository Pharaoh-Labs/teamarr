"""Duplicate-channel detection safety net (Phase 3b, item 12).

Teamarr dedupes channels only via a DB unique index on ``(event_id,
provider, keyword, stream_id)``. When name normalization or fuzzy matching
fails to resolve two differently-formatted streams of the SAME real game to
one ``event_id``, a duplicate channel is created with no detection anywhere.
``find_suspect_duplicates`` adds DETECTION (for logging/reporting) -- it does
NOT auto-merge anything.

See ``tests/test_duplicate_detector.py`` for the full behavioral contract
this module implements.
"""

from itertools import combinations

from rapidfuzz import fuzz

from teamarr.utilities.fuzzy_match import normalize_text


def _windows_overlap_or_unavailable(channel_a: dict, channel_b: dict) -> bool:
    """Half-open overlap check, bypassed when either window is unavailable.

    A channel's window is "available" only when BOTH event_start and
    event_end are non-None. When either channel's window is unavailable, the
    overlap requirement is treated as satisfied (there's nothing to disprove
    overlap with) -- the decision falls through to the other checks.
    """
    a_start = channel_a.get("event_start")
    a_end = channel_a.get("event_end")
    b_start = channel_b.get("event_start")
    b_end = channel_b.get("event_end")

    if a_start is None or a_end is None or b_start is None or b_end is None:
        return True

    return a_start < b_end and b_start < a_end


def find_suspect_duplicates(
    channels: list[dict],
    threshold: float = 85.0,
) -> list[dict]:
    """Find pairs of channels that are probably duplicates of the same event.

    Each input channel is a dict with keys ``id``, ``name``, ``sport``,
    ``league`` (accepted but not used in the decision), ``event_start``,
    ``event_end``, ``event_id``. Two channels are two-way compared and a pair
    is flagged iff ALL of:

    1. event_id: not (both non-None AND equal). None never counts as equal
       to anything, including another None.
    2. sport: equal and non-None. A None sport matches nothing.
    3. window overlap: half-open ``[event_start, event_end)`` overlap, or
       bypassed entirely if either channel's window is unavailable (either
       timestamp missing).
    4. name similarity: ``rapidfuzz.fuzz.token_set_ratio`` over each name run
       through ``normalize_text`` is >= ``threshold``.

    Args:
        channels: Channel dicts to pairwise-compare.
        threshold: Minimum token_set_ratio similarity score (0-100) to flag
            a pair.

    Returns:
        A list of dicts (one per flagged unordered pair), each with keys
        ``channel_id_a`` (smaller id), ``channel_id_b`` (larger id),
        ``channel_a_name``, ``channel_b_name``, ``similarity``, ``sport``.
        Sorted ascending by ``(channel_id_a, channel_id_b)``. For a group of
        3+ mutually-similar channels, every pairwise combination is emitted
        independently.
    """
    results: list[dict] = []

    for channel_a, channel_b in combinations(channels, 2):
        event_id_a = channel_a.get("event_id")
        event_id_b = channel_b.get("event_id")
        if event_id_a is not None and event_id_a == event_id_b:
            continue

        sport_a = channel_a.get("sport")
        sport_b = channel_b.get("sport")
        if sport_a is None or sport_a != sport_b:
            continue

        if not _windows_overlap_or_unavailable(channel_a, channel_b):
            continue

        name_a = channel_a["name"]
        name_b = channel_b["name"]
        similarity = fuzz.token_set_ratio(normalize_text(name_a), normalize_text(name_b))
        if similarity < threshold:
            continue

        id_a, id_b = channel_a["id"], channel_b["id"]
        if id_a < id_b:
            ordered_name_a, ordered_name_b = name_a, name_b
        else:
            id_a, id_b = id_b, id_a
            ordered_name_a, ordered_name_b = name_b, name_a

        results.append(
            {
                "channel_id_a": id_a,
                "channel_id_b": id_b,
                "channel_a_name": ordered_name_a,
                "channel_b_name": ordered_name_b,
                "similarity": similarity,
                "sport": sport_a,
            }
        )

    results.sort(key=lambda pair: (pair["channel_id_a"], pair["channel_id_b"]))
    return results
