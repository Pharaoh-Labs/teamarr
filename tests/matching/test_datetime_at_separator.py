"""Regression tests for rejecting "@ <datetime>" as a matchup separator (#787).

GAME_SEPARATORS ranks " @ " above " at ", and separator selection was
priority-ordered with no position awareness. In streams shaped
"<title> @ Sep 11 12:00 PM ET" the date "@"" therefore won the scan: the
right side masked to nothing, team1 became the whole show title, and the
lone junk side flowed into single-team matching — where any code token
equal to an event team's abbreviation returns (FUZZY, 100.0). On a live
install that attached ~40 streams ("US Open: Day #13 ...", "MLTT - Week 1,
Day 1", "America's Day at the Races") to a Dayton volleyball game (abbrev
DAY) and 4 F1 "Pit Lane" feeds to the Pirates (PIT).

The fix: a separator occurrence whose right side is entirely date/time
material is skipped and the scan continues. The #689 normalizer fix did
this for the "DD @ Mon" shape only; this generalizes it to any datetime
tail, at the separator-selection layer.
"""

from teamarr.consumers.matching.classifier import classify_stream, find_game_separator
from teamarr.consumers.matching.normalizer import is_datetime_tail, normalize_stream


class TestIsDatetimeTail:
    """The tail predicate itself."""

    def test_masked_date_time_tail(self):
        assert is_datetime_tail("DATE_MASK TIME_MASK")

    def test_raw_date_time_tails(self):
        assert is_datetime_tail("Sep 10 10:00AM ET")
        assert is_datetime_tail("11 Sep 12:00 PM")
        assert is_datetime_tail("6 Sep 01:00 PM")
        assert is_datetime_tail("(2026-09-12 19:00:00)")

    def test_empty_tail(self):
        # Dangling separator: no second team either way.
        assert is_datetime_tail("")
        assert is_datetime_tail("   ")

    def test_venue_and_team_material_is_not_a_tail(self):
        assert not is_datetime_tail("9 Sep 07:30 PM London")
        assert not is_datetime_tail("Celtics")
        assert not is_datetime_tail("Wisconsin Fri DATE_MASK TIME_MASK")


class TestSeparatorRejection:
    """A datetime-only right side never wins the separator scan."""

    def test_date_at_yields_no_separator(self):
        norm = normalize_stream("US Open 11: Court 8 @ Sep 10 10:00AM ET")
        assert find_game_separator(norm.normalized) == (None, -1)

    def test_second_datetime_still_raw_is_rejected(self):
        # extract_and_mask_datetime masks only the first date+time — here the
        # Sep 9 prefix — so the date after "@" reaches the separator scan raw
        # and must still be recognized as a datetime tail.
        norm = normalize_stream("Sep 9 Final: Court 8 @ Sep 11 10:00AM ET")
        assert find_game_separator(norm.normalized) == (None, -1)

    def test_earlier_team_separator_wins_over_date_at(self):
        # "@" outranks "at" in GAME_SEPARATORS; the datetime tail must not
        # let it steal the split.
        norm = normalize_stream(
            "BIG10+ 21: Soccer (M) Ohio State at Wisconsin Fri @ Sep 11 08:00PM ET"
        )
        sep, _ = find_game_separator(norm.normalized)
        assert sep == " at "

    def test_all_at_separator_before_date_still_works(self):
        norm = normalize_stream("DAZN CA 16: MLTT - Week 1, Day 1 @ 11 Sep 03:00 PM ET")
        assert find_game_separator(norm.normalized) == (None, -1)


class TestClassificationNoLongerJunk:
    """The junk single-team shape is gone end to end."""

    def test_court_feed_not_team_vs_team(self):
        c = classify_stream("US Open 11: Court 8 @ Sep 10 10:00AM ET")
        assert c.category.value != "team_vs_team"
        assert c.team1 is None and c.team2 is None

    def test_us_open_day_feed_not_team_vs_team(self):
        c = classify_stream(
            "TSN+ 19: US Open: Day #13 - Court 11 (ft. Wheelchair Doubles Finals)"
            " @ 11 Sep 12:00 PM ET"
        )
        assert c.category.value != "team_vs_team"
        assert c.team1 is None

    def test_f1_pit_lane_not_team_vs_team(self):
        c = classify_stream(
            "TSN+ 03: Formula 1 Pit Lane - Spanish Grand Prix Practice #1 @ 11 Sep 07:20 AM ET"
        )
        assert c.category.value != "team_vs_team"
        assert c.team1 is None

    def test_big10_splits_at_team_separator(self):
        c = classify_stream("BIG10+ 21: Soccer (M) Ohio State at Wisconsin Fri @ Sep 11 08:00PM ET")
        assert c.category.value == "team_vs_team"
        assert c.team1 and c.team1.endswith("Ohio State")
        assert c.team2 and c.team2.startswith("Wisconsin")


class TestRealSeparatorsPreserved:
    """Genuine matchup separators are untouched."""

    def test_team_at_team(self):
        c = classify_stream("NBA | Lakers @ Celtics")
        assert c.team1 == "Lakers"
        assert c.team2 == "Celtics"

    def test_at_wins_when_date_at_has_venue_tail(self):
        # "London" after the time is venue material: the "@ " occurrence
        # stays valid in principle, and the " v " matchup still splits it.
        c = classify_stream(
            "Sky Sports + 01: EFL Championship Derby v West Brom @ 9 Sep 07:30 PM London"
        )
        assert c.separator_found == " v "
        assert c.team2 and c.team2.startswith("West Brom")

    def test_vs_with_later_date_at(self):
        c = classify_stream("ESPN+ 95: Utah Valley vs. #20 Marshall @ Sep 11 7:10PM ET")
        assert c.separator_found == " vs. "
        assert c.team1 == "Utah Valley"
        assert c.team2 == "#20 Marshall"

    def test_milb_day_at_month_shape_still_classifies(self):
        # #689's regression: the reversed "DD @ Mon" tail with a real " at ".
        c = classify_stream(
            "MiLB 08: MiLB A 05: Daytona Tortugas at Bradenton Marauders 30 @ Jun 06:30 PM ET"
        )
        assert c.category.value == "team_vs_team"
        assert c.team1 and c.team1.endswith("Daytona Tortugas")
        assert c.team2 == "Bradenton Marauders"
