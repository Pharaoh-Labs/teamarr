"""Tests for the duplicate-channel detection safety net (Phase 3b, item 12).

Context: Teamarr dedupes channels only via a DB unique index on
``(event_id, provider, keyword, stream_id)``. When name normalization or
fuzzy matching fails to resolve two differently-formatted streams of the
SAME real game to one ``event_id``, a duplicate channel is created with no
detection anywhere. ``find_suspect_duplicates`` adds DETECTION (for
logging/reporting) -- it does NOT auto-merge anything.

--------------------------------------------------------------------------
CONTRACT (as implemented by ``teamarr.consumers.enforcement.duplicate_detector``)
--------------------------------------------------------------------------

``find_suspect_duplicates(channels, threshold=85.0) -> list[dict]``

Each input channel is a dict::

    {
        "id": int,
        "name": str,
        "sport": str | None,
        "league": str | None,
        "event_start": datetime | None,
        "event_end": datetime | None,
        "event_id": str | None,
    }

``league`` is accepted (part of the channel shape used elsewhere in the
codebase) but is NOT part of the flagging decision -- only ``sport`` is.
Two channels are two-way compared and a pair is flagged iff ALL of:

1. **event_id**: not (both non-None AND equal). i.e. a pair sharing the
   same non-None ``event_id`` is NEVER flagged (legitimate multi-stream
   one-channel handling upstream owns that case). Two channels that are
   BOTH missing an ``event_id`` (``None``) are NOT considered "the same"
   for this check -- ``None`` never counts as equal to anything, including
   another ``None`` -- so that pair remains eligible for the other checks.
2. **sport**: ``channel_a["sport"] == channel_b["sport"]``, AND that value
   is not ``None``. A ``None`` sport matches nothing, not even another
   ``None`` (spec: "None matches nothing") -- so a pair with either side's
   sport missing is never flagged.
3. **window overlap**: a channel's window is "available" only when BOTH
   ``event_start`` and ``event_end`` are non-None. When both channels'
   windows are available, overlap uses half-open interval semantics
   (``[event_start, event_end)``): ``a.start < b.end and b.start < a.end``.
   When EITHER channel's window is unavailable (either timestamp is
   ``None``), the overlap check is BYPASSED (treated as satisfied) --
   there is nothing to disprove overlap with, so the decision falls
   through entirely to the sport/event_id/similarity checks. This means a
   missing window never blocks a flag on its own, but it also never
   rescues a pair whose names don't clear the similarity bar.
4. **name similarity**: ``rapidfuzz.fuzz.token_set_ratio`` over each name
   run through ``teamarr.utilities.fuzzy_match.normalize_text`` (NOT
   ``consumers.matching.normalizer.normalize_for_matching``) is >=
   ``threshold``. ``normalize_text`` is chosen because channel names here
   are event-display-name-shaped ("Lakers vs Celtics"), the same shape
   ``normalize_text``/``match_event_name`` already normalize for
   whole-name comparison in ``fuzzy_match.py``. ``normalize_for_matching``
   additionally strips broadcast-network tokens (ESPN, FOX, ...), which is
   tailored to noisy raw stream text, not already-clean channel names, so
   it is the wrong tool here.

Output shape: a list of dicts, one per flagged unordered pair (never both
orderings of the same pair)::

    {
        "channel_id_a": int,   # smaller id
        "channel_id_b": int,   # larger id
        "channel_a_name": str,
        "channel_b_name": str,
        "similarity": float,
        "sport": str,
    }

Ordering is deterministic: sorted ascending by ``(channel_id_a,
channel_id_b)``, and within each dict ``channel_id_a < channel_id_b``
(canonical pair orientation) regardless of input order.

For a group of 3+ mutually-similar channels ("three-way duplicate"), the
chosen representation is: emit EVERY pairwise flagged combination
independently (not a single grouped record) -- e.g. 3 channels all
pairwise over threshold produce 3 dicts, one per pair. This keeps the
function's contract uniform (always pairs) and lets a caller do its own
grouping/union-find on top if it wants clusters.
"""

from datetime import datetime, timedelta

from teamarr.consumers.enforcement.duplicate_detector import find_suspect_duplicates

# A fixed reference start time so window arithmetic in tests is readable.
_T0 = datetime(2026, 3, 1, 19, 0)


def _channel(
    id: int,
    name: str,
    sport: str | None = "Basketball",
    league: str | None = "NBA",
    event_id: str | None = None,
    start: datetime | None = _T0,
    end: datetime | None = None,
) -> dict:
    """Build a channel dict with sane defaults for a 2.5 hour game window."""
    if end is None and start is not None:
        end = start + timedelta(hours=2, minutes=30)
    return {
        "id": id,
        "name": name,
        "sport": sport,
        "league": league,
        "event_start": start,
        "event_end": end,
        "event_id": event_id,
    }


# ============================================================== basic flagging


def test_similar_names_overlapping_windows_different_event_ids_flagged():
    """Same real game, two differently-formatted stream names, no shared
    event_id -- exactly the case the DB unique index cannot catch."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-abc")
    b = _channel(2, "LA Lakers v Boston Celtics", event_id="evt-xyz")

    result = find_suspect_duplicates([a, b])

    assert len(result) == 1
    pair = result[0]
    assert pair["channel_id_a"] == 1
    assert pair["channel_id_b"] == 2
    assert pair["channel_a_name"] == "Lakers vs Celtics"
    assert pair["channel_b_name"] == "LA Lakers v Boston Celtics"
    assert pair["sport"] == "Basketball"
    assert pair["similarity"] >= 85.0


def test_same_event_id_never_flagged_even_with_identical_names():
    """Legitimate multi-stream-one-channel case: same event_id must never
    be reported, no matter how similar (even identical) the names are."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-shared")
    b = _channel(2, "Lakers vs Celtics", event_id="evt-shared")

    assert find_suspect_duplicates([a, b]) == []


def test_both_event_ids_none_still_eligible():
    """None is not 'equal' to another None for this check -- two channels
    that both simply lack an event_id are NOT treated as 'the same
    event_id' and remain eligible for flagging on the other criteria."""
    a = _channel(1, "Lakers vs Celtics", event_id=None)
    b = _channel(2, "LA Lakers v Boston Celtics", event_id=None)

    result = find_suspect_duplicates([a, b])

    assert len(result) == 1
    assert result[0]["channel_id_a"] == 1
    assert result[0]["channel_id_b"] == 2


def test_one_event_id_none_other_set_still_eligible():
    a = _channel(1, "Lakers vs Celtics", event_id=None)
    b = _channel(2, "LA Lakers v Boston Celtics", event_id="evt-xyz")

    result = find_suspect_duplicates([a, b])

    assert len(result) == 1


# ==================================================================== sport


def test_different_sports_never_flagged_even_at_perfect_similarity():
    """Identical names, identical windows, different event_ids -- but
    different sports means these are NOT the same real-world event."""
    a = _channel(1, "Lakers vs Celtics", sport="Basketball", event_id="evt-1")
    b = _channel(2, "Lakers vs Celtics", sport="Hockey", event_id="evt-2")

    assert find_suspect_duplicates([a, b]) == []


def test_sport_none_on_either_side_never_flagged():
    """'None matches nothing' -- a missing sport can't be assumed to match
    another missing (or present) sport."""
    a = _channel(1, "Lakers vs Celtics", sport=None, event_id="evt-1")
    b = _channel(2, "LA Lakers v Boston Celtics", sport="Basketball", event_id="evt-2")

    assert find_suspect_duplicates([a, b]) == []

    c = _channel(3, "Lakers vs Celtics", sport=None, event_id="evt-3")
    d = _channel(4, "LA Lakers v Boston Celtics", sport=None, event_id="evt-4")

    assert find_suspect_duplicates([c, d]) == []


# =================================================================== windows


def test_non_overlapping_windows_a_week_apart_not_flagged():
    """Same teams, same sport, similar-enough names -- but a week apart is
    two different games, not one mis-split duplicate."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1", start=_T0)
    b = _channel(
        2,
        "LA Lakers v Boston Celtics",
        event_id="evt-2",
        start=_T0 + timedelta(days=7),
    )

    assert find_suspect_duplicates([a, b]) == []


def test_overlapping_windows_flagged():
    """Half-open overlap: game A [19:00, 21:30), game B [19:15, 21:45) --
    B starts before A ends and A starts before B ends, so they overlap."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1", start=_T0)
    b = _channel(
        2,
        "LA Lakers v Boston Celtics",
        event_id="evt-2",
        start=_T0 + timedelta(minutes=15),
        end=_T0 + timedelta(hours=2, minutes=45),
    )

    result = find_suspect_duplicates([a, b])
    assert len(result) == 1


def test_adjacent_non_overlapping_windows_not_flagged():
    """Half-open boundary case: game A ends exactly when game B starts --
    [start_a, end_a) and [end_a, end_b) share only the boundary instant,
    which is NOT an overlap under half-open semantics."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1", start=_T0, end=_T0 + timedelta(hours=2))
    b = _channel(
        2,
        "LA Lakers v Boston Celtics",
        event_id="evt-2",
        start=_T0 + timedelta(hours=2),
        end=_T0 + timedelta(hours=4),
    )

    assert find_suspect_duplicates([a, b]) == []


def test_missing_window_on_both_channels_does_not_block_flag():
    """Neither channel has window data at all -- the overlap check is
    bypassed entirely, so a high-similarity, same-sport, different-event-id
    pair still gets flagged."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1", start=None, end=None)
    b = _channel(2, "LA Lakers v Boston Celtics", event_id="evt-2", start=None, end=None)

    result = find_suspect_duplicates([a, b])
    assert len(result) == 1


def test_missing_window_on_one_channel_does_not_block_flag():
    """Mixed availability: one channel has a full window, the other has
    none -- still bypassed, same outcome as both-missing."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1", start=_T0)
    b = _channel(2, "LA Lakers v Boston Celtics", event_id="evt-2", start=None, end=None)

    result = find_suspect_duplicates([a, b])
    assert len(result) == 1


def test_missing_window_does_not_rescue_low_similarity():
    """A missing window bypasses the OVERLAP check, but similarity is a
    separate, still-mandatory condition -- it isn't rescued by missing
    window data."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1", start=None, end=None)
    b = _channel(2, "Warriors vs Nuggets", event_id="evt-2", start=None, end=None)

    assert find_suspect_duplicates([a, b]) == []


def test_partial_window_missing_end_only_does_not_block_flag():
    """A channel's window counts as 'unavailable' if EITHER timestamp is
    None, not just when both are -- here event_end is missing."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1", start=_T0, end=None)
    a["event_end"] = None  # override the _channel() auto-fill of end
    b = _channel(2, "LA Lakers v Boston Celtics", event_id="evt-2", start=_T0)

    result = find_suspect_duplicates([a, b])
    assert len(result) == 1


# ================================================================ similarity


def test_similarity_below_threshold_not_flagged():
    """Clearly-different team names, same sport, overlapping windows,
    different event_ids -- but the names just don't describe the same
    game, so no flag."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1")
    b = _channel(2, "Warriors vs Nuggets", event_id="evt-2")

    assert find_suspect_duplicates([a, b]) == []


def test_custom_threshold_is_respected():
    """The default threshold (85.0) rejects a mid-similarity pair, but a
    caller-supplied lower threshold accepts it."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1")
    b = _channel(2, "Warriors vs Nuggets", event_id="evt-2")

    assert find_suspect_duplicates([a, b], threshold=85.0) == []
    assert find_suspect_duplicates([a, b], threshold=40.0) != []


# ============================================================ multi-channel


def test_three_way_duplicate_emits_all_three_pairs():
    """Three mutually-similar formattings of the same real game emit one
    dict per pairwise combination (3 channels -> 3 pairs), not a single
    grouped record."""
    a = _channel(10, "Lakers vs Celtics", event_id="evt-a")
    b = _channel(20, "LA Lakers v Boston Celtics", event_id="evt-b")
    c = _channel(30, "Los Angeles Lakers vs Boston Celtics", event_id="evt-c")

    result = find_suspect_duplicates([a, b, c])

    pairs = {(r["channel_id_a"], r["channel_id_b"]) for r in result}
    assert pairs == {(10, 20), (10, 30), (20, 30)}
    assert len(result) == 3


def test_unrelated_channel_in_larger_list_is_not_flagged():
    """A third, unrelated channel in the input must not spuriously pair
    with either of a genuine duplicate pair."""
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1")
    b = _channel(2, "LA Lakers v Boston Celtics", event_id="evt-2")
    unrelated = _channel(3, "Warriors vs Nuggets", event_id="evt-3")

    result = find_suspect_duplicates([a, b, unrelated])

    pairs = {(r["channel_id_a"], r["channel_id_b"]) for r in result}
    assert pairs == {(1, 2)}


# ================================================================= ordering


def test_output_ordered_by_id_pair_ascending_regardless_of_input_order():
    """Feeding channels in descending id order must not change the
    canonical pair orientation or the sort order of the output."""
    a = _channel(5, "Lakers vs Celtics", event_id="evt-a")
    b = _channel(2, "LA Lakers v Boston Celtics", event_id="evt-b")
    c = _channel(9, "Los Angeles Lakers vs Boston Celtics", event_id="evt-c")

    # Deliberately unsorted input order.
    result = find_suspect_duplicates([c, a, b])

    ordered_pairs = [(r["channel_id_a"], r["channel_id_b"]) for r in result]
    assert ordered_pairs == sorted(ordered_pairs)
    for id_a, id_b in ordered_pairs:
        assert id_a < id_b


def test_each_unordered_pair_appears_at_most_once():
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1")
    b = _channel(2, "LA Lakers v Boston Celtics", event_id="evt-2")

    result = find_suspect_duplicates([a, b])
    pairs_seen = [(r["channel_id_a"], r["channel_id_b"]) for r in result]

    assert len(pairs_seen) == len(set(pairs_seen))


# ===================================================================== empty


def test_empty_list_returns_empty_list():
    assert find_suspect_duplicates([]) == []


def test_single_channel_returns_empty_list():
    a = _channel(1, "Lakers vs Celtics", event_id="evt-1")
    assert find_suspect_duplicates([a]) == []
