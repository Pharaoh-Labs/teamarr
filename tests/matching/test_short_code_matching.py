"""Short team-code matching (#472).

Reproduces @FractalBoy's report with real ESPN abbreviations: "SF vs SEA"
must match the Giants/Mariners game (SF's official code is 2 letters) and
must NOT bind to Portland Sea Dogs via literal-token fuzz; "AZ" resolves
to ARI via the alternate-code map.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.result import ResultCategory
from teamarr.consumers.matching.team_matcher import (
    MatchContext,
    _abbrev_equals,
    _is_short_code,
)
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()


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
