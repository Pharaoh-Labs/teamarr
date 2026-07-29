"""Tests for position-first separator selection (Phase 3a, item 9).

``DetectionKeywordService.find_separator`` currently walks ``GAME_SEPARATORS``
in priority order and returns the first pattern found ANYWHERE in the text —
so a low-priority separator that occurs early can lose to a high-priority one
that occurs much later. New contract: the separator whose match position is
EARLIEST in the string wins; list order (i.e. GAME_SEPARATORS priority) only
breaks ties when two separators start at the exact same index, and among
same-position ties the LONGER match wins (" vs. " beats " vs ").
"""

from teamarr.services.detection_keywords import DetectionKeywordService


def setup_function(_fn):
    # Pattern caches are class-level; clear them so DB-less test runs see the
    # built-in GAME_SEPARATORS list deterministically (matches existing
    # convention in test_multi_sport_hints.py / test_ncaab_gender_classification.py).
    DetectionKeywordService.invalidate_cache()


def test_simple_vs_unchanged():
    # Only one separator present at all -- earliest-position and
    # priority-order agree, so this must keep working exactly as before.
    assert DetectionKeywordService.find_separator("Lakers vs Celtics") == (" vs ", 6)


def test_simple_at_unchanged():
    assert DetectionKeywordService.find_separator("TeamA at TeamB") == (" at ", 5)


def test_earliest_position_wins_over_higher_priority_separator():
    # " vs " (priority index 1) occurs at 15; " at " (priority index 5, i.e.
    # lower priority) occurs earlier, at 7. Old code returns " vs " because it
    # is checked first in GAME_SEPARATORS and matches "anywhere". New contract:
    # the earliest occurring separator must win regardless of list order.
    text = "Norwich at Home vs Ipswich"
    assert text.lower().find(" at ") == 7
    assert text.lower().find(" vs ") == 15
    assert DetectionKeywordService.find_separator(text) == (" at ", 7)


def test_same_position_tie_prefers_longer_match(monkeypatch):
    # Construct a genuine same-start-index tie: " vs" is a literal prefix of
    # " vs ", so both match starting at the same index in "A vs B". List order
    # here deliberately puts the SHORTER pattern first (as if it were the
    # higher "priority" separator) to prove the tie-break -- not list order --
    # decides the winner: the longer match (" vs ") must win even though it is
    # second in priority.
    #
    # (The real GAME_SEPARATORS entries are NOT mutually prefixes of each
    # other -- " vs. " vs " vs " diverge at the character right after "vs",
    # so they can never match at the same start index against real input.
    # A same-position tie can only be demonstrated with a synthetic list, so
    # this test patches get_separators() to construct one directly.)
    monkeypatch.setattr(
        DetectionKeywordService,
        "get_separators",
        classmethod(lambda cls: [" vs", " vs "]),
    )
    text = "A vs B"
    assert text.lower().find(" vs") == 1
    assert text.lower().find(" vs ") == 1
    assert DetectionKeywordService.find_separator(text) == (" vs ", 1)


def test_no_separator_returns_none_and_negative_one():
    assert DetectionKeywordService.find_separator("No separator here") == (None, -1)
