"""Extraction refinement against the team-surface index (#799).

Extracted team names carry provider junk — competition labels, channel
numbers, network suffixes, venue tails, pipe metadata — and the matcher used
to score the junk. Each new shape was another anchored regex in
`_clean_team_name` (the show-prefix rule cannot see a digit or a dash, so
"Big 12 Football:" and "B1G Football -" escaped it) or another entry in
ABBREVIATION_STOPWORDS. Instead each side is now refined to the longest run of
tokens that is a known surface in TeamIdentityIndex, guarded so that no team
the run could name has a claim on the stripped tokens, and codes count only
when the stream writes them as codes.

Live evidence (support bundle, v2.17.0, run 3209): all 7 team2_not_found rows
were `<competition> A at B (<network>) @ 12 Sep …`, 45 rows were hand
corrections of the same shape, and the ALL-CAPS feed `CCSU AT TOLEDO | 9.12
3:30 PM | ESPN+` failed on a 4-letter code that never got abbreviation
equality.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.identity import TeamIdentityIndex
from teamarr.consumers.matching.result import FailedReason, ResultCategory
from teamarr.consumers.matching.team_matcher import (
    MatchContext,
    _code_cased_tokens,
    reset_identity_index_cache,
)
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = date(2026, 9, 12)

# (name, short_name, abbreviation, league, sport) — shaped like team_cache.
CACHED_TEAMS = [
    ("Howard Bison", "Howard", "HOW", "college-football", "football"),
    ("Indiana Hoosiers", "Indiana", "IU", "college-football", "football"),
    ("Michigan Wolverines", "Michigan", "MICH", "college-football", "football"),
    ("Oklahoma Sooners", "Oklahoma", "OU", "college-football", "football"),
    ("Washington State Cougars", "Washington State", "WSU", "college-football", "football"),
    ("Kansas State Wildcats", "Kansas State", "KSU", "college-football", "football"),
    ("Michigan State Spartans", "Michigan State", "MSU", "college-football", "football"),
    ("Eastern Michigan Eagles", "Eastern Michigan", "EMU", "college-football", "football"),
    ("Nebraska Cornhuskers", "Nebraska", "NEB", "college-football", "football"),
    ("Bowling Green Falcons", "Bowling Green", "BGSU", "college-football", "football"),
    ("Wisconsin Badgers", "Wisconsin", "WIS", "college-football", "football"),
    ("Western Illinois Leathernecks", "Western Illinois", "WIU", "college-football", "football"),
    ("Texas Tech Red Raiders", "Texas Tech", "TTU", "college-football", "football"),
    ("Oregon State Beavers", "Oregon State", "ORST", "college-football", "football"),
    ("Ohio State Buckeyes", "Ohio State", "OSU", "college-football", "football"),
    ("Ohio Bobcats", "Ohio", "OHIO", "college-football", "football"),
    ("Toledo Rockets", "Toledo", "TOL", "college-football", "football"),
    (
        "Central Connecticut Blue Devils", "Central Connecticut", "CCSU",
        "college-football", "football",
    ),
    ("Alcorn State Braves", "Alcorn State", "ALCN", "college-football", "football"),
    (
        "Arkansas-Pine Bluff Golden Lions", "Arkansas-Pine Bluff", "UAPB",
        "college-football", "football",
    ),
    ("Iowa Hawkeyes", "Iowa", "IOWA", "college-football", "football"),
    ("Albany Great Danes", "Albany", "ALB", "college-football", "football"),
    ("Army Black Knights", "Army", "ARMY", "college-football", "football"),
    ("Navy Midshipmen", "Navy", "NAVY", "college-football", "football"),
    ("Notre Dame Fighting Irish", "Notre Dame", "ND", "college-football", "football"),
    ("Miami (OH) RedHawks", "Miami (OH)", "M-OH", "college-football", "football"),
    ("West Bromwich Albion", "West Brom", "WBA", "eng.2", "soccer"),
    ("Derby County", "Derby", "DER", "eng.2", "soccer"),
    ("FC Dallas", "FC Dallas", "DAL", "usa.1", "soccer"),
    ("St. Louis City SC", "St. Louis City", "STL", "usa.1", "soccer"),
    ("St. Louis Blues", "St. Louis", "STL", "nhl", "hockey"),
    ("Dallas Cowboys", "Dallas", "DAL", "nfl", "football"),
    ("New York Giants", "Giants", "NYG", "nfl", "football"),
    ("San Francisco Giants", "Giants", "SF", "mlb", "baseball"),
    ("Arizona Diamondbacks", "D-backs", "ARI", "mlb", "baseball"),
    ("New York Yankees", "Yankees", "NYY", "mlb", "baseball"),
    ("Tampa Bay Rays", "Rays", "TB", "mlb", "baseball"),
    ("Detroit Tigers", "Tigers", "DET", "mlb", "baseball"),
    ("Tampa Bay Lightning", "Lightning", "TB", "nhl", "hockey"),
    ("Detroit Red Wings", "Red Wings", "DET", "nhl", "hockey"),
    ("South Florida Bulls", "South Florida", "USF", "womens-college-volleyball", "volleyball"),
    ("Dayton Flyers", "Dayton", "DAY", "womens-college-volleyball", "volleyball"),
]
TEAMS = {
    name: Team(
        id=f"t-{abbr.lower()}-{league}",
        provider="espn",
        name=name,
        short_name=short,
        abbreviation=abbr,
        league=league,
        sport=sport,
    )
    for name, short, abbr, league, sport in CACHED_TEAMS
}


# Competition / sport / conference labels, as the leagues, sports and
# provider_group_cache tables supply them on a real install.
LABELS = ["EFL Championship", "NCAA Football", "Soccer", "Football", "Big Ten"]


@pytest.fixture
def index() -> TeamIdentityIndex:
    return TeamIdentityIndex(CACHED_TEAMS, LABELS)


@pytest.fixture
def db_factory():
    """A db_factory over an in-memory team_cache, shaped like the real table."""
    reset_identity_index_cache()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE team_cache (team_name TEXT, team_short_name TEXT, team_abbrev TEXT,"
        " league TEXT, sport TEXT)"
    )
    conn.execute("CREATE TABLE team_aliases (alias TEXT, team_name TEXT, league TEXT)")
    conn.execute("CREATE TABLE leagues (display_name TEXT, league_alias TEXT)")
    conn.execute("CREATE TABLE sports (display_name TEXT)")
    conn.executemany("INSERT INTO team_cache VALUES (?,?,?,?,?)", CACHED_TEAMS)
    conn.executemany(
        "INSERT INTO leagues VALUES (?, NULL)",
        [(x,) for x in ("EFL Championship", "NCAA Football")],
    )
    conn.executemany("INSERT INTO sports VALUES (?)", [(x,) for x in ("Soccer", "Football")])
    conn.commit()

    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return conn

        def __exit__(self, *exc):
            return False

    yield _Factory()
    reset_identity_index_cache()


def _event(home: str, away: str, day: int = 12) -> Event:
    h, a = TEAMS[home], TEAMS[away]
    return Event(
        id=f"e-{h.abbreviation}-{a.abbreviation}",
        provider="espn",
        name=f"{a.name} at {h.name}",
        short_name=f"{a.abbreviation} @ {h.abbreviation}",
        start_time=datetime(2026, 9, day, 16, 0, tzinfo=UTC),
        home_team=h,
        away_team=a,
        status=EventStatus(state="scheduled"),
        league=h.league,
        sport=h.sport,
    )


def _match(stream_name: str, event: Event, db_factory, target: date = TODAY):
    classified = classify_stream(stream_name)
    matcher = make_team_matcher(db_factory=db_factory)
    ctx = MatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=target,
        generation=1,
        user_tz=ZoneInfo("America/New_York"),
        classified=classified,
        team1=classified.team1,
        team2=classified.team2,
    )
    return matcher._match_against_events(ctx, [event], event.league), classified


class TestRefineSide:
    """The index-level primitive: longest known surface, verbatim slice."""

    @pytest.mark.parametrize(
        ("side", "anchor", "expected"),
        [
            # The reporter's shapes: competition label before team 1.
            ("B1G Football - Howard", "end", "Howard"),
            ("Big 12 Football: Washington St.", "end", "Washington St."),
            ("No. 13 Texas Tech", "end", "Texas Tech"),
            # Network suffix and venue tail after team 2.
            ("Indiana (Big Ten Network)", "start", "Indiana"),
            ("Michigan State (Big Ten Network)", "start", "Michigan State"),
            ("West Brom @   London", "start", "West Brom"),
            # Pipe metadata (#652's shape) and a parenthesised venue.
            ("TOLEDO | 9.12  | ESPN+", "start", "TOLEDO"),
            ("ALCORN STATE (IN MEMPHIS, TN)", "start", "ALCORN STATE"),
            # #790's shapes. "EFL Championship" sits flush against "Derby" with
            # no punctuation; it strips because it is a league display name.
            ("+ 01: EFL Championship Derby", "end", "Derby"),
            ("US (Peacock 057): Home Feed: NYY", "end", "NYY"),
            # A sport label touching the name is junk too.
            ("Ohio State Buckeyes Football", "end", "Ohio State Buckeyes"),
            ("Soccer Ohio State", "end", "Ohio State"),
            # Junk on the separator side of team 1 is still found.
            ("Michigan State (Big Ten Network)", "end", "Michigan State"),
        ],
    )
    def test_junk_is_stripped(self, index, side, anchor, expected):
        assert index.refine_side(side, anchor=anchor) == expected

    def test_st_finds_the_state_surface_but_returns_the_original_text(self, index):
        # Lookup canonicalises "st" -> "state"; the slice is verbatim so the
        # scorer keeps its own St/State tolerance and the UI shows the stream.
        assert index.refine_side("Big 12 Football: Kansas St.", anchor="end") == "Kansas St."

    @pytest.mark.parametrize(
        ("side", "anchor"),
        [
            # Already a surface: nothing to do.
            ("Kansas St.", "start"),
            ("Ohio State", "end"),
            ("Tampa Bay Lightning", "end"),
            ("Miami (OH)", "start"),
            ("St. Louis City", "end"),
            # No surface at all: leave it to the fuzzy path.
            ("UAlbany", "start"),
            # A bare word flush against the span may be the rest of the name.
            # Oklahoma State is NOT in this cache; narrowing it to the cached
            # "Oklahoma" would hand a D3-style unknown to the wrong team, which
            # the fuzzy path correctly refuses today ("Ohio Wesleyan" vs the
            # Bobcats). Only a boundary or a known label licenses the strip.
            ("FOX College Football - Big Ten: Oklahoma State", "end"),
            ("Ohio Wesleyan", "end"),
            ("Georgia Tech Yellow", "end"),
            ("Wisconsin Fri", "start"),
            # The remainder is claimable by a team the span names — the
            # #569 discriminators. Refining would erase them.
            ("SF Giants", "end"),
            ("NY Giants", "end"),
            ("Arizona D-backs", "end"),
            # A club suffix in the remainder is a club-name variant, not junk.
            ("Dallas FC", "end"),
            # Prose words that are also codes are not surfaces (#788 by rule).
            ("MLTT - Week 1, Day 1", "end"),
            ("US Open: Day #13 - Court 11", "end"),
        ],
    )
    def test_side_is_left_alone(self, index, side, anchor):
        assert index.refine_side(side, anchor=anchor) is None

    def test_longest_surface_wins_over_a_shorter_one_inside_it(self, index):
        # "ohio" (Bobcats) sits inside "ohio state" (Buckeyes): longest wins,
        # so the Buckeyes side is never narrowed to the Bobcats.
        assert index.refine_side("B1G Football - Ohio State", anchor="end") == "Ohio State"

    def test_labels_come_from_data_not_code(self):
        bare = TeamIdentityIndex(CACHED_TEAMS)
        assert bare.refine_side("+ 01: EFL Championship Derby", anchor="end") is None
        labelled = TeamIdentityIndex(CACHED_TEAMS, ["EFL Championship"])
        assert labelled.refine_side("+ 01: EFL Championship Derby", anchor="end") == "Derby"

    def test_ties_go_to_the_run_nearest_the_anchor(self, index):
        # Two one-token surfaces across a boundary; the one beside the
        # separator is the team.
        assert index.refine_side("Howard | Indiana", anchor="end") == "Indiana"
        assert index.refine_side("Howard | Indiana", anchor="start") == "Howard"


class TestCodeCasedTokens:
    """Codes count only when the stream writes them as codes (#788 by rule)."""

    def test_upper_case_tokens_are_codes(self):
        assert _code_cased_tokens("CCSU AT TOLEDO") >= {"ccsu"}
        assert "tcu" in _code_cased_tokens("GRAMBLING STATE AT TCU")

    def test_prose_is_not_a_code(self):
        assert "day" not in _code_cased_tokens("MLTT - Week 1, Day 1")
        assert "big" not in _code_cased_tokens("Big Ten Network")

    def test_the_whole_side_is_always_a_code(self):
        assert _code_cased_tokens("tb") == {"tb"}
        assert _code_cased_tokens("det") == {"det"}

    def test_alternate_codes_resolve(self):
        assert "ari" in _code_cased_tokens("NYY at AZ")

    def test_long_upper_words_are_names_not_codes(self):
        assert "toledo" not in _code_cased_tokens("CCSU AT TOLEDO")


class TestReporterShapesMatch:
    """The support-bundle rows, end to end through the real matcher."""

    @pytest.mark.parametrize(
        ("stream", "home", "away", "t1", "t2"),
        [
            (
                "NCAAF 02: B1G Football - Howard at Indiana (Big Ten Network) @ 12 Sep 12:00 PM ET",
                "Indiana Hoosiers", "Howard Bison", "Howard", "Indiana",
            ),
            (
                "NCAAF 04: FOX College Football - Big Ten: Oklahoma at Michigan (FOX Sports)"
                " @ 12 Sep 12:00 PM ET",
                "Michigan Wolverines", "Oklahoma Sooners", "Oklahoma", "Michigan",
            ),
            (
                "NCAAF 06: Big 12 Football: Washington St. at Kansas St. @ 12 Sep 12:00 PM ET",
                "Kansas State Wildcats", "Washington State Cougars", "Washington St", "Kansas St",
            ),
            (
                "NCAAF 35: B1G Football - Eastern Michigan at Michigan State (Big Ten Network)"
                " @ 12 Sep 03:30 PM ET",
                "Michigan State Spartans", "Eastern Michigan Eagles",
                "Eastern Michigan", "Michigan State",
            ),
            (
                "NCAAF 86: FOX College Football - Big Ten: Bowling Green at Nebraska (FS1)"
                " @ 12 Sep 07:00 PM ET",
                "Nebraska Cornhuskers", "Bowling Green Falcons", "Bowling Green", "Nebraska",
            ),
            (
                "NCAAF 89: B1G Football - Western Illinois at Wisconsin (Big Ten Network)"
                " @ 12 Sep 07:15 PM ET",
                "Wisconsin Badgers", "Western Illinois Leathernecks",
                "Western Illinois", "Wisconsin",
            ),
            (
                "NCAAF 96: No. 13 Texas Tech at Oregon State @ 12 Sep 07:30 PM ET",
                "Oregon State Beavers", "Texas Tech Red Raiders", "Texas Tech", "Oregon State",
            ),
        ],
    )
    def test_bundle_rows_match_and_store_the_refined_names(
        self, db_factory, stream, home, away, t1, t2
    ):
        result, classified = _match(stream, _event(home, away), db_factory)
        assert result.category is ResultCategory.MATCHED
        # Written back to the classified stream: this is what parsed_team1/2,
        # the token index, the fixture gate and the UI all see.
        assert classified.team1 == t1
        assert classified.team2 == t2

    def test_all_caps_feed_with_pipe_metadata_and_a_four_letter_code(self, db_factory):
        result, classified = _match(
            "NCAAF 041: CCSU AT TOLEDO | 9.12 3:30 PM | ESPN+",
            _event("Toledo Rockets", "Central Connecticut Blue Devils"),
            db_factory,
        )
        assert result.category is ResultCategory.MATCHED
        assert result.confidence == 1.0
        assert (classified.team1, classified.team2) == ("CCSU", "TOLEDO")

    def test_parenthesised_venue_on_the_pipe_feed(self, db_factory):
        result, classified = _match(
            "NCAAF 097: UAPB VS ALCORN STATE (IN MEMPHIS, TN) | 9.12 7:00 PM | HBCU GO",
            _event("Alcorn State Braves", "Arkansas-Pine Bluff Golden Lions"),
            db_factory,
        )
        assert result.category is ResultCategory.MATCHED
        assert (classified.team1, classified.team2) == ("UAPB", "ALCORN STATE")


class TestIssue790Shapes:
    """#790's three regex candidates, none of which needed writing."""

    def test_channel_prefix_and_venue_tail(self, db_factory):
        result, classified = _match(
            "Sky Sports + 01: EFL Championship Derby v West Brom @ 9 Sep 07:30 PM London",
            _event("West Bromwich Albion", "Derby County", day=9),
            db_factory,
            target=date(2026, 9, 9),
        )
        assert result.category is ResultCategory.MATCHED
        assert (classified.team1, classified.team2) == ("Derby", "West Brom")

    def test_feed_label_and_provider_number(self, db_factory):
        result, classified = _match(
            "US (Peacock 057): Home Feed: NYY at AZ (Chase Field)",
            _event("Arizona Diamondbacks", "New York Yankees"),
            db_factory,
        )
        assert result.category is ResultCategory.MATCHED
        assert classified.team1 == "NYY"


class TestNothingNewMatches:
    """Refinement is a strip of junk, never a widening."""

    def test_prose_day_never_reaches_dayton_by_code(self, db_factory):
        result, _ = _match(
            "MLTT - Week 1, Day 1 vs Dayton",
            _event("South Florida Bulls", "Dayton Flyers"),
            db_factory,
        )
        assert result.category is not ResultCategory.MATCHED

    def test_cross_sport_crosstalk_is_still_vetoed(self, db_factory):
        result, _ = _match(
            "ESPN+ 81: Tampa Bay Lightning vs. Detroit Red Wings",
            _event("Detroit Tigers", "Tampa Bay Rays"),
            db_factory,
        )
        assert result.failed_reason is FailedReason.FIXTURE_NOT_IN_LEAGUE

    def test_a_four_letter_code_is_not_another_teams_name(self, db_factory):
        result, _ = _match(
            "NCAAF: Army at Navy",
            _event("Notre Dame Fighting Irish", "Army Black Knights"),
            db_factory,
        )
        assert result.category is not ResultCategory.MATCHED


class TestPassingScoresNeverDrop:
    """A side that matched before refinement matches at least as well after."""

    @pytest.mark.parametrize(
        ("stream", "home", "away"),
        [
            ("NCAAF 34: Albany at Iowa 6pm", "Iowa Hawkeyes", "Albany Great Danes"),
            ("NCAAF: Ohio at Ohio State", "Ohio State Buckeyes", "Ohio Bobcats"),
            ("MLB: SF Giants vs D-backs", "Arizona Diamondbacks", "San Francisco Giants"),
            ("MLB: TB @ DET", "Detroit Tigers", "Tampa Bay Rays"),
            ("MLB: tb vs det", "Detroit Tigers", "Tampa Bay Rays"),
            ("NYY at ARI", "Arizona Diamondbacks", "New York Yankees"),
            ("ESPN+ 12 (D): Tampa Bay Rays vs. Detroit Tigers", "Detroit Tigers", "Tampa Bay Rays"),
        ],
    )
    def test_clean_names_and_codes_still_match_at_full_confidence(
        self, db_factory, stream, home, away
    ):
        result, _ = _match(stream, _event(home, away), db_factory)
        assert result.category is ResultCategory.MATCHED
        assert result.confidence == 1.0

    def test_without_an_index_the_matcher_is_exactly_as_before(self):
        # db_factory=None: no identity index, so refinement is inert and the
        # reporter's shape fails the way it did — the fix needs the cache.
        result, classified = _match(
            "NCAAF 02: B1G Football - Howard at Indiana (Big Ten Network) @ 12 Sep 12:00 PM ET",
            _event("Indiana Hoosiers", "Howard Bison"),
            None,
        )
        assert result.category is not ResultCategory.MATCHED
        assert classified.team1 == "B1G Football - Howard"
