"""Regression tests for catchup/timeshift metadata in stream names (#495).

Some providers append catchup window timestamps to stream names:

    "MLB 02 | Dodgers x Yankees start:2026-07-19 17:35:00 stop:2026-07-20 00:48:20"

Generic datetime masking replaces only the FIRST date+time (the start pair),
so the stop timestamp survived into team extraction. The show-name-prefix
cleanup then ate "Yankees start:" and team2 came out as
"stop:2026-07-20 00:48:20" — no_event_found.

The normalizer now recognizes the start/stop labels: the start timestamp
becomes the stream's date/time and the whole metadata tail is stripped before
separator detection.
"""

from datetime import date, time

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.normalizer import (
    extract_and_mask_datetime,
    normalize_stream,
)


class TestCatchupMetadata:
    """start:/stop: catchup tails are stripped and the start timestamp kept."""

    def test_full_start_stop_tail(self):
        masked, d, t, tz = extract_and_mask_datetime(
            "MLB 02 | Dodgers x Yankees start:2026-07-19 17:35:00 stop:2026-07-20 00:48:20"
        )
        assert masked == "MLB 02 | Dodgers x Yankees"
        assert d == date(2026, 7, 19)
        assert t == time(17, 35)
        assert tz is None

    def test_truncated_stop_timestamp(self):
        # Provider name-length limits can cut the stop timestamp short.
        masked, d, t, _ = extract_and_mask_datetime(
            "MLB 02 | Dodgers x Yankees start:2026-07-19 17:35:00 stop:20"
        )
        assert masked == "MLB 02 | Dodgers x Yankees"
        assert d == date(2026, 7, 19)
        assert t == time(17, 35)

    def test_start_without_stop(self):
        masked, d, t, _ = extract_and_mask_datetime(
            "NHL | Bruins vs Rangers start:2026-01-09 19:00:00"
        )
        assert masked == "NHL | Bruins vs Rangers"
        assert d == date(2026, 1, 9)
        assert t == time(19, 0)

    def test_x_separator_stream_classifies(self):
        # The exact stream from #495 end-to-end through the classifier.
        c = classify_stream(
            "MLB 02 | Dodgers x Yankees start:2026-07-19 17:35:00 stop:2026-07-20 00:48:20"
        )
        assert c.category.value == "team_vs_team"
        assert c.team1 == "Dodgers"
        assert c.team2 == "Yankees"
        assert c.league_hint == "mlb"
        assert c.normalized.extracted_date == date(2026, 7, 19)

    def test_invalid_start_timestamp_still_strips(self):
        # Nonsense month: no date extracted, but the tail must not leak into teams.
        masked, d, t, _ = extract_and_mask_datetime(
            "MLB | Dodgers x Yankees start:2026-13-40 17:35:00 stop:2026-07-20 00:48:20"
        )
        assert masked == "MLB | Dodgers x Yankees"
        assert d is None
        assert t is None


class TestNoRegressions:
    """Streams without catchup metadata keep their existing behaviour."""

    def test_plain_time_stream(self):
        norm = normalize_stream("NHL | Bruins vs Rangers 7:00 PM ET")
        assert norm.extracted_time == time(19, 0)
        assert norm.extracted_tz == "America/New_York"

    def test_word_start_in_team_context_untouched(self):
        # "start" without a timestamp is not catchup metadata.
        masked, d, t, _ = extract_and_mask_datetime("NBA | Lakers vs Celtics start of season")
        assert "start of season" in masked
        assert d is None
