"""Shared-nickname crosstalk across leagues (#569).

ESPN gives both the NFL and MLB Giants short_name "Giants". Because
token_set_ratio returns 100 whenever the short name is a token subset of the
stream, 'US: San Francisco Giants' scored 100 against the New York Giants (57
on the full name) and SF's team-branded stream was attached to NFL channels.

The short_name leg now only stands in when the stream's residual tokens agree
with the team's own discriminator — its words, its initialism, or the
abbreviation — so location survives while #480's 'D-backs' still matches.
"""

from datetime import UTC, datetime

from teamarr.consumers.matching.team_matcher import _best_name_score
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()


def _team(name, abbr, short_name, league, sport):
    return Team(
        id="t-" + abbr.lower(),
        provider="espn",
        name=name,
        short_name=short_name,
        abbreviation=abbr,
        league=league,
        sport=sport,
    )


NYG = _team("New York Giants", "NYG", "Giants", "nfl", "football")
MIN = _team("Minnesota Vikings", "MIN", "Vikings", "nfl", "football")
SFG = _team("San Francisco Giants", "SF", "Giants", "mlb", "baseball")
COL = _team("Colorado Rockies", "COL", "Rockies", "mlb", "baseball")
DBACKS = _team("Arizona Diamondbacks", "ARI", "Diamondbacks", "mlb", "baseball")
ITALY_U17 = _team("Italy U17", "ITA", "Italy", "fifa.world.u17", "soccer")

# Same city, different sports. ESPN's MLS short_name is the bare city
# "Seattle", which is the same subset trap one league over (#580 report).
SOUNDERS = _team("Seattle Sounders FC", "SEA", "Seattle", "usa.1", "soccer")
ATX = _team("Austin FC", "ATX", "Austin", "usa.1", "soccer")
MARINERS = _team("Seattle Mariners", "SEA", "Mariners", "mlb", "baseball")
SEAHAWKS = _team("Seattle Seahawks", "SEA", "Seahawks", "nfl", "football")


def _event(home, away, eid, league, sport):
    start = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(hour=19)
    return Event(
        id=eid,
        provider="espn",
        name=f"{home.name} vs {away.name}",
        short_name=f"{home.short_name} vs {away.short_name}",
        start_time=start,
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league=league,
        sport=sport,
    )


class TestSharedNicknameScoring:
    def test_sf_giants_does_not_match_ny_giants(self):
        # The whole bug in one line: 100 before the gate, 57 after.
        assert _best_name_score("san francisco giants", NYG) < 85

    def test_sf_giants_still_matches_its_own_team(self):
        assert _best_name_score("san francisco giants", SFG) == 100

    def test_city_initialism_pins_the_right_giants(self):
        # 'SF Giants' / 'NY Giants' scored 100 against BOTH teams before #569
        assert _best_name_score("sf giants", SFG) == 100
        assert _best_name_score("sf giants", NYG) < 85
        assert _best_name_score("ny giants", NYG) == 100
        assert _best_name_score("ny giants", SFG) < 85

    def test_bare_nickname_stays_ambiguous(self):
        # No location to contradict — league/sport hints resolve these, not us
        assert _best_name_score("giants", NYG) == 100
        assert _best_name_score("giants", SFG) == 100

    def test_age_group_national_teams_stay_separate(self):
        # short_name 'Italy' made every Italy age group interchangeable
        assert _best_name_score("italy u20", ITALY_U17) < 85
        assert _best_name_score("italy u17", ITALY_U17) == 100

    def test_bare_nickname_still_rides_the_short_name_leg(self):
        # What the short_name leg is FOR (#480): the full name scores only 67
        # against its own nickname, so the leg has to carry it.
        assert _best_name_score("diamondbacks", DBACKS) == 100

    def test_abbreviation_prefixed_nickname_survives(self):
        # 'MLB 13 | ARI Diamondbacks' — the abbreviation is a valid residual
        assert _best_name_score("ari diamondbacks", DBACKS) == 100


class TestTeamOnlyFanOut:
    """End-to-end: the branded stream reaches only the baseball event."""

    def _outcomes(self, team_norm, event):
        matcher = make_team_matcher()
        return matcher._score_single_team_against_event(team_norm, event)

    def test_sf_giants_stream_skips_the_nfl_event(self):
        nfl = _event(NYG, MIN, "nfl-1", "nfl", "football")
        score, side = self._outcomes("san francisco giants", nfl)
        assert score is None
        assert side is None

    def test_sf_giants_stream_hits_the_mlb_event(self):
        mlb = _event(SFG, COL, "mlb-1", "mlb", "baseball")
        score, side = self._outcomes("san francisco giants", mlb)
        assert score is not None
        assert side == "home"


class TestTeamVsTeamScoring:
    """The both-teams path shares _best_name_score, so it is gated too."""

    def test_sf_giants_matchup_does_not_score_an_nfl_event(self):
        matcher = make_team_matcher()
        nfl = _event(NYG, MIN, "nfl-1", "nfl", "football")
        assert matcher._score_teams_against_event(
            "Colorado Rockies", "San Francisco Giants", nfl
        ) is None

    def test_sf_giants_matchup_scores_its_own_event(self):
        matcher = make_team_matcher()
        mlb = _event(SFG, COL, "mlb-1", "mlb", "baseball")
        result = matcher._score_teams_against_event(
            "Colorado Rockies", "San Francisco Giants", mlb
        )
        assert result is not None
        assert result[1] >= 85


class TestSharedCityCrosstalk:
    """Same-city teams in different leagues (#580 report).

    ESPN hands MLS teams a bare-city short_name ("Seattle" for the Sounders),
    so every Seattle-branded stream scored 100 against an MLS Sounders event
    and MLB/NFL streams were attached to the soccer channel. The discriminator
    here is the nickname rather than the location, but the gate is the same.
    """

    def test_mariners_stream_does_not_match_the_sounders(self):
        assert _best_name_score("us seattle mariners a", SOUNDERS) < 85

    def test_seahawks_stream_does_not_match_the_sounders(self):
        assert _best_name_score("nfl seattle seahawks p", SOUNDERS) < 85

    def test_seattle_streams_still_match_their_own_teams(self):
        assert _best_name_score("us seattle mariners a", MARINERS) == 100
        assert _best_name_score("nfl seattle seahawks p", SEAHAWKS) == 100

    def test_sounders_stream_still_matches_its_own_event(self):
        matcher = make_team_matcher()
        mls = _event(SOUNDERS, ATX, "mls-1", "usa.1", "soccer")
        score, side = matcher._score_single_team_against_event(
            "us seattle sounders a", mls
        )
        assert score is not None
        assert side == "home"

    def test_mariners_stream_skips_the_mls_event(self):
        matcher = make_team_matcher()
        mls = _event(SOUNDERS, ATX, "mls-1", "usa.1", "soccer")
        score, side = matcher._score_single_team_against_event(
            "us seattle mariners a", mls
        )
        assert score is None
        assert side is None
