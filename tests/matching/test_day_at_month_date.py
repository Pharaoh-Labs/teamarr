"""Regression tests for the "DD @ Mon" datetime tail and month-abbreviation greed.

Some MiLB/provider feeds name streams like:

    "MiLB 08: MiLB A 05: Daytona Tortugas at Bradenton Marauders 30 @ Jun 06:30 PM ET"

i.e. the day comes BEFORE the month and "@" is used as the date/time separator.
Two bugs used to break these streams:

1. The greedy month pattern `(Jan|...|Dec)[a-z]*` let "Mar" swallow "Marauders",
   so "Marauders 30" parsed as March 30 instead of the real June 30 date.
2. The leftover "@" in "30 @ Jun" was picked as the matchup separator (it
   outranks " at " in GAME_SEPARATORS), splitting the teams completely wrong.

Both are fixed in the normalizer by masking "DD @ Mon" as a date (which also
removes the stray "@") and tightening the month names to bounded abbreviations.
"""

from datetime import date

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.normalizer import normalize_stream


class TestDayAtMonthDate:
    """The reversed 'DD @ Mon' datetime tail extracts correctly."""

    def test_month_named_team_not_eaten_by_date(self):
        # "Marauders" must not be read as "Mar" + day 30.
        norm = normalize_stream(
            "Daytona Tortugas at Bradenton Marauders 30 @ Jun 06:30 PM ET"
        )
        assert norm.extracted_date == date(date.today().year, 6, 30)

    def test_full_milb_stream_classifies_correctly(self):
        c = classify_stream(
            "MiLB 08: MiLB A 05: Daytona Tortugas at Bradenton Marauders 30 @ Jun 06:30 PM ET"
        )
        assert c.category.value == "team_vs_team"
        # The real " at " matchup separator wins now that the stray "@" is masked.
        assert c.team1 and c.team1.endswith("Daytona Tortugas")
        assert c.team2 == "Bradenton Marauders"
        assert c.normalized.extracted_date == date(date.today().year, 6, 30)

    def test_non_month_team_unaffected(self):
        c = classify_stream(
            "MiLB 17: MiLB AA 04: Erie SeaWolves at Akron RubberDucks 30 @ Jun 06:35 PM ET"
        )
        assert c.team2 == "Akron RubberDucks"
        assert c.normalized.extracted_date == date(date.today().year, 6, 30)


class TestNoRegressions:
    """Existing date / separator behaviour must be preserved."""

    def test_real_at_matchup_separator_still_works(self):
        # "@" as a genuine matchup separator (no month after it) is untouched.
        c = classify_stream("NBA | Lakers @ Celtics")
        assert c.team1 == "Lakers"
        assert c.team2 == "Celtics"

    def test_day_month_date_still_parses(self):
        # Year is inferred by proximity; assert the month/day were extracted.
        norm = normalize_stream("Arsenal vs Chelsea 14 Jan 3:00 PM ET")
        assert norm.extracted_date is not None
        assert (norm.extracted_date.month, norm.extracted_date.day) == (1, 14)

    def test_month_day_date_still_parses(self):
        norm = normalize_stream("Yankees vs Red Sox Dec 31")
        assert norm.extracted_date is not None
        assert (norm.extracted_date.month, norm.extracted_date.day) == (12, 31)

    def test_full_month_name_still_parses(self):
        norm = normalize_stream("Game on June 30 tonight")
        assert norm.extracted_date is not None
        assert (norm.extracted_date.month, norm.extracted_date.day) == (6, 30)


class TestNumberBeforeAtIsNotADay:
    """#689: 'Court 12 @ Sep 01 11:00AM ET' — the number before '@' is a court
    (or race/game) number; the date is the 'Sep 01' AFTER the month."""

    def test_court_number_not_eaten_as_day(self):
        norm = normalize_stream("ESPN+ 06: Court 12 @ Sep 01 11:00AM ET")
        assert (norm.extracted_date.month, norm.extracted_date.day) == (9, 1)
        assert "Court 12" in norm.normalized

    def test_stadium_and_race_numbers(self):
        for name in (
            "ESPN+ 07: Stadium 17 @ Sep 01 11:00AM ET",
            "NASCAR Cup Series Race 2 @ Sep 01 3:00PM ET",
        ):
            norm = normalize_stream(name)
            assert (norm.extracted_date.month, norm.extracted_date.day) == (9, 1), name

    def test_reversed_tail_with_hour_only_time_still_reads_day_at_month(self):
        # "Jun 7 PM" is a time, not a day number — the reversed form still wins.
        norm = normalize_stream("Tortugas at Marauders 30 @ Jun 7 PM ET")
        assert (norm.extracted_date.month, norm.extracted_date.day) == (6, 30)
