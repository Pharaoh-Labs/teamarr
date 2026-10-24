"""A newly taught team clears only the cached failures that could name it (#1153).

The schedule-taught lesson (#912) used to call ``clear_failed`` — the whole
negative cache — whenever any competitor was new to the process. The taught
set is process memory, so every restart re-taught the schedule as news, and a
tournament's daily draw brought new names every day: on a real install the
~2,000 cached failures were wiped every two or three runs and re-scored from
scratch each time. These tests pin the scoped clear and what it must leave.
"""

import pytest

from teamarr.consumers.matching.result import FailedReason
from teamarr.consumers.stream_match_cache import (
    FAILED_MATCH_EVENT_ID,
    NullStreamMatchCache,
    StreamMatchCache,
)

EVENT = {"id": "e1", "name": "Rays at Tigers"}


@pytest.fixture
def cache(db_factory):
    return StreamMatchCache(db_factory)


def _fail(cache, stream_id, name, group_id=1):
    cache.set_failed(
        group_id=group_id,
        stream_id=stream_id,
        stream_name=name,
        generation=5,
        reason=FailedReason.NO_EVENT_FOUND.value,
    )


def _failed_names(cache):
    with cache._conn() as conn:
        rows = conn.execute(
            "SELECT stream_name FROM stream_match_cache WHERE event_id = ? ORDER BY stream_id",
            (FAILED_MATCH_EVENT_ID,),
        ).fetchall()
    return [r["stream_name"] for r in rows]


class TestOnlyTheRowsNamingTheTeamGo:
    def test_whole_word_phrases(self, cache):
        _fail(cache, 1, "Fairmont State vs Howard")
        _fail(cache, 2, "West Virginia State at Glenville")
        _fail(cache, 3, "FLO: Fairmont St. Falcons - Charleston")
        _fail(cache, 4, "Rays at Tigers")

        cleared = cache.clear_failed_naming(
            {"fairmont state falcons", "fairmont st", "fairmont state"}
        )

        assert cleared == 2
        assert _failed_names(cache) == ["West Virginia State at Glenville", "Rays at Tigers"]

    def test_a_phrase_matches_whole_words_only(self, cache):
        _fail(cache, 1, "Indiana State vs Ball State")
        _fail(cache, 2, "Indianapolis Colts at Houston")

        assert cache.clear_failed_naming({"indiana"}) == 1
        assert _failed_names(cache) == ["Indianapolis Colts at Houston"]

    def test_a_code_counts_only_where_the_stream_writes_a_code(self, cache):
        _fail(cache, 1, "TCU vs Baylor")
        _fail(cache, 2, "Day 1 highlights")  # DAY the code never matches "Day"
        _fail(cache, 3, "tcu at smu")  # lower-case: not written as a code

        assert cache.clear_failed_naming(set(), {"tcu", "day"}) == 1
        assert _failed_names(cache) == ["Day 1 highlights", "tcu at smu"]

    def test_nothing_asked_clears_nothing(self, cache):
        _fail(cache, 1, "Rays at Tigers")
        assert cache.clear_failed_naming(set(), set()) == 0
        assert cache.clear_failed_naming({"", "  "}) == 0
        assert _failed_names(cache) == ["Rays at Tigers"]


class TestWhatMustSurvive:
    def test_successes_and_pins_are_left_alone(self, cache):
        cache.set(
            group_id=1,
            stream_id=10,
            stream_name="Rays at Tigers",
            event_id="e1",
            league="mlb",
            generation=5,
            match_method="fuzzy",
            cached_data=EVENT,
        )
        cache.set_user_correction(
            group_id=1,
            stream_id=11,
            stream_name="Rays at Tigers (alt)",
            event_id="e1",
            league="mlb",
            cached_data=EVENT,
        )
        _fail(cache, 12, "Rays at Tigers (rerun)")

        assert cache.clear_failed_naming({"rays"}) == 1
        assert cache.get(1, 10, "Rays at Tigers") is not None
        assert cache.get(1, 11, "Rays at Tigers (alt)").user_corrected
        assert cache.get(1, 12, "Rays at Tigers (rerun)", include_failed=True) is None

    def test_a_pinned_failure_is_not_cleared(self, cache):
        _fail(cache, 1, "Rays at Tigers")
        with cache._conn() as conn:
            conn.execute("UPDATE stream_match_cache SET user_corrected = 1")
            conn.commit()

        assert cache.clear_failed_naming({"rays"}) == 0
        assert _failed_names(cache) == ["Rays at Tigers"]


class TestDiscoveryStillOwesTheInvalidation:
    def test_the_null_cache_reaches_the_real_table(self, cache):
        """Source discovery matches with a NullStreamMatchCache (#997); the
        lesson it learns still invalidates the real cache's failures (#912)."""
        _fail(cache, 1, "Vanderbilt vs LSU")
        _fail(cache, 2, "Rays at Tigers")

        null = NullStreamMatchCache(cache._get_connection)
        assert null.clear_failed_naming({"vanderbilt"}) == 1
        assert _failed_names(cache) == ["Rays at Tigers"]
