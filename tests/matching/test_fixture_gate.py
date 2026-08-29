"""Cross-sport false positives: the fixture gate end to end (epic goax).

Reproduces the Discord report of 2026-08-24. An "ESPN + 2" source scoped to MLB
created channel "MLB | TB/DET" for event 401816657 and then attached
`ESPN+ 81 (D): Tampa Bay Lightning vs. Detroit Red Wings` to it, because the
shared cities alone score above the accept floor:

    Tampa Bay Lightning / Tampa Bay Rays = 78.3
    Detroit Red Wings   / Detroit Tigers = 71.0   -> min() = 71.0 >= 60

Nothing downstream could catch it: `classify_stream` returns no sport hint and no
league hint for these names, and they carry no date, so neither the sport gate
nor the trusted-date gate fires.

These tests drive the real `TeamMatcher` against a real `team_cache`, because
the gate is inert without one — a matcher built with `db_factory=None` has no
identity index and behaves exactly as it did before.
"""

import sqlite3
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.identity import TeamIdentityIndex
from teamarr.consumers.matching.result import FailedReason, ResultCategory
from teamarr.consumers.matching.team_matcher import MatchContext
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()

# (name, short_name, abbrev, league, sport)
CACHED_TEAMS = [
    ("Tampa Bay Rays", "Rays", "TB", "mlb", "baseball"),
    ("Detroit Tigers", "Tigers", "DET", "mlb", "baseball"),
    ("Colorado Rockies", "Rockies", "COL", "mlb", "baseball"),
    ("Washington Nationals", "Nationals", "WSH", "mlb", "baseball"),
    ("New York Mets", "Mets", "NYM", "mlb", "baseball"),
    ("Tampa Bay Lightning", "Lightning", "TB", "nhl", "hockey"),
    ("Detroit Red Wings", "Red Wings", "DET", "nhl", "hockey"),
    ("New York Jets", "Jets", "NYJ", "nfl", "football"),
    ("Northern Colorado Bears", "Bears", "UNC", "college-baseball", "baseball"),
    ("Eastern Washington Eagles", "Eagles", "EWU", "college-baseball", "baseball"),
    # Partial broadcast labels below exactly identify unrelated short names.
    ("Milwaukee Brewers", "Brewers", "MIL", "mlb", "baseball"),
    ("Milwaukee Bucks", "Milwaukee", "MIL", "nba", "basketball"),
    ("Los Angeles Dodgers", "Dodgers", "LAD", "mlb", "baseball"),
    ("Atlanta Braves", "Braves", "ATL", "mlb", "baseball"),
    ("Atlanta United", "Atlanta", "ATL", "usa.1", "soccer"),
    ("Kansas City Royals", "Royals", "KC", "mlb", "baseball"),
    ("Toronto Blue Jays", "Blue Jays", "TOR", "mlb", "baseball"),
    ("Kansas City Chiefs", "Kansas City", "KC", "nfl", "football"),
    ("Toronto FC", "Toronto", "TOR", "can.1", "soccer"),
    # A code stored AS a short name (TSDB does this) must not pre-empt the
    # abbreviation table: "SEA" is the Orcas' short name AND the Mariners' code.
    ("Seattle Mariners", "Mariners", "SEA", "mlb", "baseball"),
    ("St. Louis Cardinals", "Cardinals", "STL", "mlb", "baseball"),
    ("Seattle Orcas", "SEA", "SEA", "mlc", "cricket"),
    ("Houston Astros", "Astros", "HOU", "mlb", "baseball"),
    ("Houston Texans", "Texans", "HOU", "nfl", "football"),
    # A full name that IS another team's city ("Utah", the usa.ncaa row) must
    # not hide the Jazz behind it. UTAH is four letters, so it is not a code.
    ("Utah Jazz", "Jazz", "UTAH", "nba", "basketball"),
    ("Utah", "Utah", "UTAH", "usa.ncaa.w.1", "soccer"),
    ("Washington Wizards", "Wizards", "WSH", "nba", "basketball"),
]


@pytest.fixture
def db_factory():
    """A db_factory over an in-memory team_cache, shaped like the real table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE team_cache (
            team_name TEXT, team_short_name TEXT, team_abbrev TEXT,
            league TEXT, sport TEXT
        )
        """
    )
    # The matcher also loads user aliases at construction; an empty table keeps
    # the test log free of a misleading "no such table" warning.
    conn.execute("CREATE TABLE team_aliases (alias TEXT, team_name TEXT, league TEXT)")
    conn.executemany("INSERT INTO team_cache VALUES (?,?,?,?,?)", CACHED_TEAMS)
    conn.commit()

    class _Factory:
        def __call__(self):
            return self

        def __enter__(self):
            return conn

        def __exit__(self, *exc):
            return False

    return _Factory()


def _team(name, short, abbr, league, sport) -> Team:
    return Team(
        id=f"t-{abbr.lower()}-{league}",
        provider="espn",
        name=name,
        short_name=short,
        abbreviation=abbr,
        league=league,
        sport=sport,
    )


def _event(home: Team, away: Team, eid: str) -> Event:
    return Event(
        id=eid,
        provider="espn",
        name=f"{away.name} at {home.name}",
        short_name=f"{away.short_name} at {home.short_name}",
        start_time=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(hour=23),
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league=home.league,
        sport=home.sport,
    )


RAYS = _team("Tampa Bay Rays", "Rays", "TB", "mlb", "baseball")
TIGERS = _team("Detroit Tigers", "Tigers", "DET", "mlb", "baseball")
ROCKIES = _team("Colorado Rockies", "Rockies", "COL", "mlb", "baseball")
NATIONALS = _team("Washington Nationals", "Nationals", "WSH", "mlb", "baseball")
LIGHTNING = _team("Tampa Bay Lightning", "Lightning", "TB", "nhl", "hockey")
RED_WINGS = _team("Detroit Red Wings", "Red Wings", "DET", "nhl", "hockey")
BREWERS = _team("Milwaukee Brewers", "Brewers", "MIL", "mlb", "baseball")
METS = _team("New York Mets", "Mets", "NYM", "mlb", "baseball")
DODGERS = _team("Los Angeles Dodgers", "Dodgers", "LAD", "mlb", "baseball")
BRAVES = _team("Atlanta Braves", "Braves", "ATL", "mlb", "baseball")
ROYALS = _team("Kansas City Royals", "Royals", "KC", "mlb", "baseball")
BLUE_JAYS = _team("Toronto Blue Jays", "Blue Jays", "TOR", "mlb", "baseball")

# The two channels from the report.
TB_DET = _event(TIGERS, RAYS, "401816657")
COL_WSH = _event(NATIONALS, ROCKIES, "401816656")
NHL_GAME = _event(RED_WINGS, LIGHTNING, "nhl-1")
BREWERS_METS = _event(METS, BREWERS, "mlb-mil-nym")
DODGERS_BRAVES = _event(BRAVES, DODGERS, "mlb-lad-atl")
ROYALS_BLUE_JAYS = _event(BLUE_JAYS, ROYALS, "mlb-kc-tor")
MARINERS = _team("Seattle Mariners", "Mariners", "SEA", "mlb", "baseball")
CARDINALS = _team("St. Louis Cardinals", "Cardinals", "STL", "mlb", "baseball")
ASTROS = _team("Houston Astros", "Astros", "HOU", "mlb", "baseball")
JAZZ = _team("Utah Jazz", "Jazz", "UTAH", "nba", "basketball")
WIZARDS = _team("Washington Wizards", "Wizards", "WSH", "nba", "basketball")
MARINERS_CARDINALS = _event(CARDINALS, MARINERS, "mlb-sea-stl")
ASTROS_METS = _event(METS, ASTROS, "mlb-hou-nym")
JAZZ_WIZARDS = _event(WIZARDS, JAZZ, "nba-utah-wsh")


def _match(stream_name: str, event: Event, league: str, db_factory=None):
    classified = classify_stream(stream_name)
    matcher = make_team_matcher(db_factory=db_factory)
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


def _match_multi(stream_name: str, event: Event, db_factory):
    classified = classify_stream(stream_name)
    matcher = make_team_matcher(db_factory=db_factory)
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
    return matcher._match_against_multi_league_events(ctx, [(event.league, event)])


class TestReportedFalsePositives:
    """The exact streams and events from the 2026-08-24 report."""

    def test_nhl_stream_does_not_match_the_mlb_channel(self, db_factory):
        result = _match(
            "ESPN+ 81 (D): Tampa Bay Lightning vs. Detroit Red Wings",
            TB_DET,
            "mlb",
            db_factory,
        )
        assert result.category is not ResultCategory.MATCHED
        assert result.failed_reason is FailedReason.FIXTURE_NOT_IN_LEAGUE

    def test_ncaa_stream_does_not_match_the_mlb_channel(self, db_factory):
        result = _match(
            "ESPN+ 146 (D): Northern Colorado vs. Eastern Washington",
            COL_WSH,
            "mlb",
            db_factory,
        )
        assert result.category is not ResultCategory.MATCHED

    def test_the_real_mlb_stream_still_matches(self, db_factory):
        result = _match(
            "ESPN+ 12 (D): Tampa Bay Rays vs. Detroit Tigers", TB_DET, "mlb", db_factory
        )
        assert result.category is ResultCategory.MATCHED
        assert result.event.id == "401816657"

    def test_the_nhl_stream_matches_an_nhl_source(self, db_factory):
        """The gate rejects a league, never a stream — the same feed is fine here."""
        result = _match(
            "ESPN+ 81 (D): Tampa Bay Lightning vs. Detroit Red Wings",
            NHL_GAME,
            "nhl",
            db_factory,
        )
        assert result.category is ResultCategory.MATCHED


class TestPartialTeamNames:
    """Partial broadcast labels must not be vetoed by short-name identities."""

    @pytest.mark.parametrize(
        ("stream_name", "event"),
        [
            ("Milwaukee @ New York Mets", BREWERS_METS),
            ("Los Angeles Dodgers @ Atlanta", DODGERS_BRAVES),
            ("Kansas City @ Toronto", ROYALS_BLUE_JAYS),
        ],
    )
    def test_partial_names_match_their_mlb_fixture(self, db_factory, stream_name, event):
        result = _match(stream_name, event, "mlb", db_factory)
        assert result.category is ResultCategory.MATCHED
        assert result.event.id == event.id

    def test_partial_names_match_in_the_multi_league_path(self, db_factory):
        result = _match_multi("Milwaukee @ New York Mets", BREWERS_METS, db_factory)
        assert result.category is ResultCategory.MATCHED
        assert result.event.id == BREWERS_METS.id

    def test_city_only_pair_resolves_to_every_league_those_cities_share(self, db_factory):
        """"Kansas City @ Toronto" is an MLB game AND an MLS game. The index must
        say so, not pick one: the schedule (which events exist) decides."""
        index = TeamIdentityIndex(CACHED_TEAMS)
        assert index.fixture_leagues("Kansas City", "Toronto") == {"mlb"}
        assert index.fixture_leagues("Milwaukee", "New York Mets") == {"mlb"}

    def test_bare_city_alias_does_not_swear_off_the_other_teams(self, db_factory):
        """TEAM_ALIASES maps "atlanta" -> "atlanta united" for the scoring
        ladder. As an identity that would veto the Braves (#619)."""
        index = TeamIdentityIndex(CACHED_TEAMS)
        resolution = index.resolve("Atlanta")
        assert not resolution.exact
        assert {i.league for i in resolution.identities} >= {"usa.1", "mlb"}


class TestExplicitLeagueHints:
    def test_ncaaf_hint_overrides_incomplete_cross_league_identity(self, db_factory):
        with db_factory() as conn:
            # Simulate an incomplete football directory where these schools are
            # known only through basketball, while the league itself is seeded.
            conn.executemany(
                "INSERT INTO team_cache VALUES (?,?,?,?,?)",
                [
                    ("Mercyhurst", "Mercyhurst", "MER", "mens-college-basketball", "basketball"),
                    (
                        "Youngstown State",
                        "Youngstown State",
                        "YSU",
                        "mens-college-basketball",
                        "basketball",
                    ),
                    ("Ohio State Buckeyes", "Ohio State", "OSU", "college-football", "football"),
                ],
            )
            conn.commit()

        event = _event(
            _team(
                "Youngstown State Penguins",
                "Youngstown State",
                "YSU",
                "college-football",
                "football",
            ),
            _team("Mercyhurst Lakers", "Mercyhurst", "MER", "college-football", "football"),
            "fcs-mer-ysu",
        )

        # Date must track TODAY (the event's date) or this becomes DATE_MISMATCH
        # the day after it is written.
        result = _match_multi(
            f"NCAAF: Mercyhurst vs. Youngstown State @ {TODAY:%b %-d} 6:00PM ET",
            event,
            db_factory,
        )

        assert result.category is ResultCategory.MATCHED


class TestShortCodesAreNeverHijacked:
    """A code is read by the abbreviation table, unioned with any team whose
    name or short name IS that code — never pre-empted by one such row (#619).

    Before: "SEA" resolved to the Seattle Orcas alone (their short_name is the
    code) and "SEA @ STL" was FIXTURE_NOT_IN_LEAGUE on an MLB source."""

    @pytest.mark.parametrize(
        ("stream_name", "event", "league"),
        [
            ("SEA @ STL", MARINERS_CARDINALS, "mlb"),
            ("US (Peacock 005) | Away Feed: HOU at NYM", ASTROS_METS, "mlb"),
            ("UTAH @ WSH", JAZZ_WIZARDS, "nba"),
        ],
    )
    def test_code_streams_reach_their_event(self, db_factory, stream_name, event, league):
        result = _match(stream_name, event, league, db_factory)
        assert result.category is ResultCategory.MATCHED, result.failed_reason
        assert result.event.id == event.id

    def test_a_code_resolves_to_every_team_bearing_it(self):
        index = TeamIdentityIndex(CACHED_TEAMS)
        sea = index.resolve("SEA")
        assert not sea.exact
        assert {i.league for i in sea.identities} == {"mlb", "mlc"}
        hou = index.resolve("HOU")
        assert {i.league for i in hou.identities} == {"mlb", "nfl"}

    def test_full_name_that_is_another_teams_city_keeps_both_readings(self):
        utah = TeamIdentityIndex(CACHED_TEAMS).resolve("UTAH")
        assert utah.exact  # the usa.ncaa row really is named "Utah"
        assert {i.league for i in utah.identities} == {"usa.ncaa.w.1", "nba"}


class TestUnknownLeagueIsNeverVetoed:
    """The gate is a statement about who plays in a league. For a league the
    cache has never seen — custom, unseeded, added since the last refresh — it
    has no standing to refuse anything (#619)."""

    def test_event_in_uncached_league_is_not_fixture_rejected(self, db_factory):
        custom = Event(
            **{**NHL_GAME.__dict__, "id": "custom-1", "league": "my-custom-hockey"}
        )
        result = _match(
            "ESPN+ 81 (D): Tampa Bay Lightning vs. Detroit Red Wings",
            custom,
            "my-custom-hockey",
            db_factory,
        )
        assert result.failed_reason is not FailedReason.FIXTURE_NOT_IN_LEAGUE
        assert result.category is ResultCategory.MATCHED


class TestGateIsInertWithoutData:
    """Absent a seeded team_cache the matcher must behave exactly as before."""

    def test_no_db_factory_leaves_matching_untouched(self):
        result = _match("ESPN+ 12 (D): Tampa Bay Rays vs. Detroit Tigers", TB_DET, "mlb")
        assert result.category is ResultCategory.MATCHED

    def test_empty_team_cache_does_not_veto(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE team_cache (team_name TEXT, team_short_name TEXT,"
            " team_abbrev TEXT, league TEXT, sport TEXT)"
        )

        class _Factory:
            def __call__(self):
                return self

            def __enter__(self):
                return conn

            def __exit__(self, *exc):
                return False

        result = _match(
            "ESPN+ 12 (D): Tampa Bay Rays vs. Detroit Tigers", TB_DET, "mlb", _Factory()
        )
        assert result.category is ResultCategory.MATCHED


class TestOneSidedStreamsAreNotVetoed:
    """A fixture needs two teams. When only one side resolves, the gate has no
    opinion and matching proceeds on the old rules."""

    def test_single_team_stream_still_reaches_its_event(self, db_factory):
        result = _match("Tampa Bay Rays", TB_DET, "mlb", db_factory)
        assert result.failed_reason is not FailedReason.FIXTURE_NOT_IN_LEAGUE

    def test_unknown_team_names_do_not_veto(self, db_factory):
        """Neither side is in team_cache — resolution is empty, so no veto."""
        result = _match(
            "Some Unlisted FC vs Another Unlisted FC", TB_DET, "mlb", db_factory
        )
        assert result.failed_reason is not FailedReason.FIXTURE_NOT_IN_LEAGUE


# NOTE: the "TB/DET is a valid fixture in BOTH mlb and nhl" property is asserted
# in tests/matching/test_fixture_corpus.py against the identity index directly.
# It cannot be driven end-to-end here because `classify_stream` does not parse a
# bare two/three-letter "TB vs DET" into two sides — it returns TEAM_ONLY with
# team1="TB vs D". That is pre-existing classifier behaviour, unrelated to this
# gate, and is tracked separately (bead goax.5).


class TestMascotlessLeaguesDoNotShadowMascotedOnes:
    """NCAA soccer publishes no mascots, so its full name IS the bare school —
    and that made it an *exact* identity that vetoed every other college sport
    (#650).

    ESPN abbreviates the SCHOOL for college ("Fairmont State Falcons" ->
    "Fairmont St"), never the mascot, so the short_name prefix rule could not
    supply "fairmont state" as a reading of the football team. The school-only
    form therefore reached the soccer row and nothing else, narrowing the
    fixture to usa.ncaa.w.1 and rejecting college-football for 20 of the 73
    games on the 2026-08-29 slate.
    """

    # Exactly the shape that broke: mascoted football row whose short_name is an
    # abbreviated school, alongside a mascotless soccer row for the same school.
    COLLEGE = [
        ("Fairmont State Falcons", "Fairmont St", "FMSU", "college-football", "football"),
        ("Fairmont State", "Fairmont St", "FAI", "usa.ncaa.w.1", "soccer"),
        ("Dayton Flyers", "Dayton", "DAY", "college-football", "football"),
        ("Dayton", "Dayton", "DAY", "usa.ncaa.w.1", "soccer"),
        # Two-word mascot: dropping a single token is not enough.
        (
            "Central Connecticut Blue Devils",
            "Central Conn",
            "CCSU",
            "college-football",
            "football",
        ),
        ("Central Connecticut", "Central Conn", "CCSU", "usa.ncaa.w.1", "soccer"),
        ("South Dakota Coyotes", "South Dakota", "SDAK", "college-football", "football"),
        ("South Dakota", "South Dakota", "SD", "usa.ncaa.w.1", "soccer"),
    ]

    def test_school_only_name_reaches_the_football_team(self):
        index = TeamIdentityIndex(self.COLLEGE)
        assert "college-football" in index.resolve("Fairmont State").leagues

    def test_two_word_mascot_is_also_dropped(self):
        index = TeamIdentityIndex(self.COLLEGE)
        assert "college-football" in index.resolve("Central Connecticut").leagues

    def test_football_fixture_is_not_vetoed_by_the_soccer_row(self):
        index = TeamIdentityIndex(self.COLLEGE)
        leagues = index.fixture_leagues("Fairmont State", "Dayton")
        assert leagues is not None
        assert "college-football" in leagues

    def test_two_word_mascot_fixture_is_not_vetoed(self):
        index = TeamIdentityIndex(self.COLLEGE)
        leagues = index.fixture_leagues("Central Connecticut", "South Dakota")
        assert leagues is not None
        assert "college-football" in leagues

    def test_soccer_remains_a_candidate_for_the_same_names(self):
        """Widening must not trade one league's false veto for another's."""
        index = TeamIdentityIndex(self.COLLEGE)
        assert "usa.ncaa.w.1" in index.fixture_leagues("Fairmont State", "Dayton")

    def test_bare_first_word_is_not_registered_as_a_prefix(self):
        """Prefixes stop at two tokens, so a lone "central" is never *entered*
        as a partial reading of every school beginning with it.

        Asserted against the partial table rather than resolve(), because a
        one-word query still reaches teams through the fuzzy fallback — that
        path predates this rule and is deliberately left alone.
        """
        index = TeamIdentityIndex(self.COLLEGE)
        assert "central" not in index._partial
        assert "central connecticut" in index._partial

    def test_cross_sport_veto_still_fires(self):
        """The widening is scoped to prefixes of a team's own name, so the
        original crosstalk case is untouched."""
        index = TeamIdentityIndex(CACHED_TEAMS)
        assert index.fixture_leagues("Tampa Bay Lightning", "Tampa Bay Rays") == set()
