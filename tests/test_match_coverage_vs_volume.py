"""Coverage (distinct streams) vs volume (matched results) accounting.

Regression for the >100% match-rate bug (bead teamarrv2-nnj): EPG/TEAM_ONLY
matching fans one source stream out to many matched results, so a result-count
numerator over a stream-count denominator pushed the per-group rate over 100%.
``matched_stream_count`` must count distinct streams; ``matched_count`` remains
the result/volume count.
"""

from teamarr.consumers.matching.matcher import BatchMatchResult, MatchedStreamResult


def _r(stream_id, matched, is_exception=False):
    # is_exception is derived from exception_keyword being set.
    return MatchedStreamResult(
        stream_name=f"s{stream_id}",
        stream_id=stream_id,
        matched=matched,
        exception_keyword="x" if is_exception else None,
    )


def test_one_stream_many_results_counts_as_one_matched_stream():
    # One linear stream that matched 5 EPG programs => 5 results, 1 stream.
    batch = BatchMatchResult(results=[_r(1, True) for _ in range(5)])
    assert batch.matched_count == 5  # volume
    assert batch.matched_stream_count == 1  # coverage
    assert batch.unmatched_stream_count == 0


def test_coverage_never_exceeds_distinct_streams():
    # 3 streams: stream 1 fans out to 4 matched results, 2 unmatched, 3 matched once.
    results = (
        [_r(1, True) for _ in range(4)]
        + [_r(2, False)]
        + [_r(3, True)]
    )
    batch = BatchMatchResult(results=results)
    assert batch.matched_count == 5  # volume (4 + 1)
    assert batch.matched_stream_count == 2  # distinct matched streams (1, 3)
    assert batch.unmatched_stream_count == 1  # stream 2
    # Coverage rate is a true fraction of distinct streams.
    distinct = batch.matched_stream_count + batch.unmatched_stream_count
    assert batch.matched_stream_count / distinct <= 1.0


def test_stream_with_both_matched_and_unmatched_results_counts_as_matched():
    # Name-match failed but EPG matched for the same stream => matched, not double-counted.
    batch = BatchMatchResult(results=[_r(1, False), _r(1, True)])
    assert batch.matched_stream_count == 1
    assert batch.unmatched_stream_count == 0


def test_exceptions_excluded_from_unmatched_coverage():
    batch = BatchMatchResult(results=[_r(1, False, is_exception=True), _r(2, True)])
    assert batch.matched_stream_count == 1
    assert batch.unmatched_stream_count == 0  # stream 1 is an exception, not a failure
