"""Short team-code matching (#472).

Reproduces @FractalBoy's report with real ESPN abbreviations: "SF vs SEA"
must match the Giants/Mariners game (SF's official code is 2 letters) and
must NOT bind to Portland Sea Dogs via literal-token fuzz; "AZ" resolves
to ARI via the alternate-code map.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.result import FailedReason, ResultCategory
from teamarr.consumers.matching.team_matcher import (
    MatchContext,
    _abbrev_equals,
    _is_short_code,
)
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()
# Stream-name spellings of TODAY (#813). Fixtures whose event is built at
# TODAY must annotate their stream with the same day, or the classifier reads
# a date the event cannot satisfy and every such test rots into DATE_MISMATCH
# the moment the wall clock moves past the hardcoded one.
TODAY_MON_DAY = f"{TODAY:%b} {TODAY.day}"  # "Sep 12"
TODAY_DAY_MON = f"{TODAY.day:02d} {TODAY:%b}"  # "12 Sep"


def _team(name: str, abbr: str, league: str = "mlb") -> Team:
    return Team(
        id="t-" + abbr.lower(),
        provider="espn",
        name=name,
        short_name=name.split()[-1],
        abbreviation=abbr,
        league=league,
        sport="baseball",
    )


def _event(home: Team, away: Team, eid: str = "evt-1") -> Event:
    return Event(
        id=eid,
        provider="espn",
        name=f"{home.name} vs {away.name}",
        short_name=f"{home.short_name} vs {away.short_name}",
        start_time=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(
            hour=19
        ),
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league=home.league,
        sport="baseball",
    )


GIANTS = _team("San Francisco Giants", "SF")
MARINERS = _team("Seattle Mariners", "SEA")
ROCKIES = _team("Colorado Rockies", "COL")
DBACKS = _team("Arizona Diamondbacks", "ARI")
SEA_DOGS = _team("Portland Sea Dogs", "POR", "milb-aa")
SOMERSET = _team("Somerset Patriots", "SOM", "milb-aa")

MLB_GAME = _event(GIANTS, MARINERS)
AA_GAME = _event(SOMERSET, SEA_DOGS, "evt-aa")


def _match(stream_name: str, event: Event, league: str = "mlb"):
    classified = classify_stream(stream_name)
    matcher = make_team_matcher()
    ctx = MatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=TODAY,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        classified=classified,
        team1=classified.team1,
        team2=classified.team2,
    )
    return matcher._match_against_events(ctx, [event], league)


class TestShortCodeHelpers:
    def test_is_short_code(self):
        assert _is_short_code("sf")
        assert _is_short_code("sea")
        assert not _is_short_code("giants")
        assert not _is_short_code("sea dogs")

    def test_alt_codes_resolve(self):
        assert _abbrev_equals("az", "ARI")
        assert _abbrev_equals("cws", "CHW")
        assert _abbrev_equals("sf", "SF")
        assert not _abbrev_equals("la", "LAD")  # deliberately not mapped


class TestReportedScenarios:
    def test_sf_vs_sea_matches_mlb_game(self):
        # 2-letter SF was previously unmatchable (>=3 abbrev guard)
        outcome = _match("SF vs SEA", MLB_GAME)
        assert outcome.category == ResultCategory.MATCHED
        assert outcome.confidence == 1.0

    def test_sf_vs_sea_does_not_match_aa_game(self):
        # SEA scored a spurious token_set 100 against "Portland Sea Dogs"
        outcome = _match("SF vs SEA", AA_GAME, "milb-aa")
        assert outcome.category == ResultCategory.FAILED

    def test_col_at_sf_matches(self):
        outcome = _match("COL at SF", _event(GIANTS, ROCKIES, "evt-2"))
        assert outcome.category == ResultCategory.MATCHED

    def test_az_matches_diamondbacks_via_alternate_code(self):
        outcome = _match("AZ vs COL", _event(DBACKS, ROCKIES, "evt-3"))
        assert outcome.category == ResultCategory.MATCHED

    def test_mixed_code_and_full_name_still_matches(self):
        # One side short code, other side full name — per-side scoring
        outcome = _match("SF vs Seattle Mariners", MLB_GAME)
        assert outcome.category == ResultCategory.MATCHED

    def test_full_names_unaffected(self):
        outcome = _match("San Francisco Giants vs Seattle Mariners", MLB_GAME)
        assert outcome.category == ResultCategory.MATCHED


class TestCommonWordAbbreviations:
    """Everyday words that are also team codes never match by code (#705/#788).

    The second pass added day/sun/red/old/may/big/top/pay/run, measured over
    9,608 distinct live stream names: each had prose occurrences and zero
    legitimate standalone code uses. DAY was attaching ~40 confidence-1.0
    streams to a Dayton game via single-team abbreviation hits.
    """

    def test_measured_stopwords_rejected_by_abbrev_equals(self):
        for word in ("day", "sun", "red", "old", "may", "big", "top", "pay", "run"):
            assert not _abbrev_equals(word, word.upper()), word

    def test_active_codes_kept(self):
        # Measured as in active legitimate use — must NOT be stopworded.
        for word in ("can", "van", "sea", "sf", "col"):
            assert _abbrev_equals(word, word.upper()), word

    def test_single_team_junk_side_never_abbrev_matches(self):
        # The live false-match shape: a show title whose "Day 1" token hit
        # Dayton's DAY code at (FUZZY, 100.0).
        dayton = _team("Dayton Flyers", "DAY", "womens-college-volleyball")
        south_florida = _team("South Florida Bulls", "USF", "womens-college-volleyball")
        event = _event(south_florida, dayton, "evt-day")
        matcher = make_team_matcher()
        assert (
            matcher._check_abbreviation_match(
                "TAIF Racing Season 2026 - Week 8, Day 1", None, event
            )
            is None
        )

    def test_junk_day_stream_does_not_match_dayton(self):
        dayton = _team("Dayton Flyers", "DAY", "womens-college-volleyball")
        south_florida = _team("South Florida Bulls", "USF", "womens-college-volleyball")
        event = _event(south_florida, dayton, "evt-day")
        outcome = _match(
            f"DAZN CA 16: MLTT - Week 1, Day 1 @ {TODAY_DAY_MON} 03:00 PM ET", event
        )
        # Dated to the event's own day so the rejection can only come from the
        # DAY stopword — a stale date would pass this test for free, which is
        # exactly how it rotted (#813). Pinning the reason keeps it honest.
        assert outcome.category != ResultCategory.MATCHED
        assert outcome.failed_reason == FailedReason.TEAMS_NOT_PARSED

    def test_full_name_dayton_streams_still_match(self):
        dayton = _team("Dayton Flyers", "DAY", "womens-college-volleyball")
        south_florida = _team("South Florida Bulls", "USF", "womens-college-volleyball")
        event = _event(south_florida, dayton, "evt-day")
        outcome = _match(f"Dayton vs. South Florida @ {TODAY_MON_DAY} 5:00PM ET", event)
        assert outcome.category == ResultCategory.MATCHED
