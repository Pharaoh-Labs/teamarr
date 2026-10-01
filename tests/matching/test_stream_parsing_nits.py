"""Three small parsing defects from prod's failure data (#925).

1. "Field Hockey" was hinted as (ice) Hockey: the hockey pattern's optional
   "ice" lets it match the bare word.
2. A weekday written beside the date stuck to the team: "UCLA at Maryland Sun
   @ Sep 27" parsed the home side as "Maryland Sun".
3. ESPN+'s "En Español-" language marker stuck to the first team.
"""

from datetime import date

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.identity import TeamIdentityIndex
from teamarr.consumers.matching.team_matcher import _weekday_words
from teamarr.services.detection_keywords import DetectionKeywordService
from teamarr.services.stream_filter import UNSUPPORTED_SPORTS

SUNDAY = date(2026, 9, 27)
TUESDAY = date(2026, 9, 29)

# (name, short_name, abbrev, league, sport)
TEAMS = [
    ("Maryland Terrapins", "Maryland", "MD", "usa.ncaa.w.1", "soccer"),
    ("UCLA Bruins", "UCLA", "UCLA", "usa.ncaa.w.1", "soccer"),
    ("Michigan Wolverines", "Michigan", "MICH", "usa.ncaa.m.1", "soccer"),
    ("Connecticut Sun", "Sun", "CONN", "wnba", "basketball"),
    ("UConn Huskies", "UConn", "CONN", "womens-college-basketball", "basketball"),
    ("Las Vegas Aces", "Aces", "LV", "wnba", "basketball"),
]


@pytest.fixture(autouse=True)
def _fresh_keywords():
    DetectionKeywordService.invalidate_cache()
    yield
    DetectionKeywordService.invalidate_cache()


class TestFieldHockeyIsNotIceHockey:
    @pytest.mark.parametrize(
        "name",
        [
            "(US) (BTN+ 010) | Field Hockey: Iowa at Michigan (2026-10-02 16:50:00)",
            "BIG10+ 02: Field Hockey La Salle at Rutgers Sun @ Sep 27 12:00PM ET",
            "Flo Sports 16: flolive: 2026 Dickinson vs Juniata - Field Hockey (Dickinson v Juniata)",
        ],
    )
    def test_field_hockey_is_its_own_sport(self, name):
        assert DetectionKeywordService.detect_sport(name) == "Field Hockey"

    def test_it_is_unsupported_so_the_filter_drops_it(self):
        """No provider carries field hockey; hinting it Hockey kept ice-hockey
        games in play for schools that play both."""
        assert "Field Hockey" in UNSUPPORTED_SPORTS

    @pytest.mark.parametrize(
        "name",
        [
            "(US) (BTN+ 006) | Ice Hockey (W): Boston U at #1 Wisconsin (2026-10-01 19:50:00)",
            "Hockey: Bruins vs Rangers",
            "flohockey: 2026 Shawinigan Cataractes vs Rimouski Oceanic",
        ],
    )
    def test_ice_hockey_is_unchanged(self, name):
        assert DetectionKeywordService.detect_sport(name) == "Hockey"


class TestWeekdayBesideTheDate:
    """Stripped during side refinement, where the team index can tell a
    weekday from a team: only the stream's own weekday, only around a known
    team, and never when a team could own the word."""

    def test_weekday_words_follow_the_streams_date(self):
        assert _weekday_words(SUNDAY) == {"sun", "sunday"}
        assert "tue" in _weekday_words(TUESDAY) and "sun" not in _weekday_words(TUESDAY)
        assert _weekday_words(None) == frozenset()

    def test_the_streams_own_weekday_is_stripped(self):
        index = TeamIdentityIndex(TEAMS)
        assert index.refine_side("Maryland Sun", anchor="start", junk=_weekday_words(SUNDAY)) == (
            "Maryland"
        )
        assert index.refine_side("Michigan Tue", anchor="start", junk=_weekday_words(TUESDAY)) == (
            "Michigan"
        )

    def test_without_the_date_the_side_is_left_alone(self):
        """This is how every stream behaved before, and still does when the
        stream carries no date to vouch for the word."""
        index = TeamIdentityIndex(TEAMS)
        assert index.refine_side("Maryland Sun", anchor="start") is None

    def test_another_days_weekday_is_not_junk(self):
        index = TeamIdentityIndex(TEAMS)
        assert (
            index.refine_side("Maryland Sun", anchor="start", junk=_weekday_words(TUESDAY)) is None
        )

    def test_connecticut_sun_keeps_its_name_on_a_sunday(self):
        """The whole side is a surface in its own right, so nothing is stripped —
        the case a regex in the normalizer got wrong."""
        index = TeamIdentityIndex(TEAMS)
        assert (
            index.refine_side("Connecticut Sun", anchor="start", junk=_weekday_words(SUNDAY))
            is None
        )

    def test_a_team_that_owns_the_word_keeps_it(self):
        """ "Sun" alone is the Connecticut Sun's short name: a word that IS the
        span is never the remainder."""
        index = TeamIdentityIndex(TEAMS)
        assert index.refine_side("WNBA: Sun", anchor="start", junk=_weekday_words(SUNDAY)) == "Sun"

    def test_classifier_output_feeds_refinement(self):
        classified = classify_stream(
            "BIG10+ 01: Soccer (W) UCLA at Maryland Sun @ Sep 27 12:00PM ET"
        )
        index = TeamIdentityIndex(TEAMS, labels=["Soccer"])
        junk = _weekday_words(classified.normalized.extracted_date)
        assert index.refine_side(classified.team2, anchor="start", junk=junk) == "Maryland"


class TestLanguagePrefix:
    def test_en_espanol_prefix_is_not_part_of_the_team(self):
        classified = classify_stream("ESPN+ 20: En Español-Burgos vs. Eldense @ Sep 27 12:20PM ET")
        assert (classified.team1, classified.team2) == ("Burgos", "Eldense")

    def test_colon_and_spaced_forms(self):
        assert classify_stream("En Español: Navy vs. UAB").team1 == "Navy"
        assert (
            classify_stream("ESPN+ 02: En Espanol - Valladolid vs. Cordoba").team1 == "Valladolid"
        )

    def test_trailing_parenthetical_is_untouched(self):
        """Only the glued prefix; "(Español)" after the matchup is a different
        shape handled elsewhere."""
        before = classify_stream("Peacock 04: USA vs. Chile (Español) @ 29 Sep 07:30 PM ET")
        assert before.team1 == "USA"
