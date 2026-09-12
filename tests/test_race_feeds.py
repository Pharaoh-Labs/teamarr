"""Race feeds (#245): league-scoped driver/variant rows on the exception-keyword engine."""

from __future__ import annotations

import re
import sqlite3

import pytest

from teamarr.database.channels.keywords import check_exception_keyword, get_keywords_for_league
from teamarr.database.exception_keywords import ExceptionKeyword
from teamarr.database.race_feeds import (
    VARIANT_FEEDS,
    RosterEntry,
    driver_feed_key,
    driver_match_terms,
    list_race_feeds,
    race_feed_keywords,
    race_feed_leagues,
    set_behavior_for_kind,
    update_race_feed,
    upsert_roster,
)
from teamarr.providers.espn.tournament import TournamentParserMixin, _driver_code

ROSTER = [
    RosterEntry("Charles Leclerc", "C. Leclerc", "LEC"),
    RosterEntry("Sergio Pérez", "S. Pérez", "PER"),
    RosterEntry("Carlos Sainz Jr.", "C. Sainz Jr.", "SAI"),
    RosterEntry("Lewis Hamilton", "L. Hamilton", "HAM"),
]


@pytest.fixture
def conn():
    schema = open("teamarr/database/schema.sql").read()
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS race_feeds \(.*?\n\);", schema, re.S).group(0)
    kw = re.search(
        r"CREATE TABLE IF NOT EXISTS consolidation_exception_keywords \(.*?\n\);", schema, re.S
    ).group(0)
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(ddl + "\n" + kw)
    return c


class TestDriverTerms:
    def test_every_provider_shape_is_covered(self):
        terms = driver_match_terms(RosterEntry("Sergio Pérez", "S. Pérez", "PER")).split(", ")
        assert "Sergio Pérez" in terms and "Sergio Perez" in terms  # accented + plain
        assert "Pérez" in terms and "Perez" in terms  # surname
        assert "S. Perez" in terms  # ESPN shortName
        assert "PER" in terms  # FIA code

    def test_suffixes_stay_with_the_surname(self):
        assert "Sainz Jr." in driver_match_terms(RosterEntry("Carlos Sainz Jr.")).split(", ")

    @pytest.mark.parametrize(
        ("name", "code"),
        [
            ("Charles Leclerc", "LEC"),
            ("Carlos Sainz Jr.", "SAI"),
            ("Nico Hülkenberg", "HUL"),
            ("Andrea Kimi Antonelli", "ANT"),
            ("Mick Schumacher", "MSC"),  # FIA override
            ("Kimi", None),
        ],
    )
    def test_driver_codes(self, name, code):
        assert _driver_code(name) == code

    def test_feed_key_is_stable_and_plain(self):
        assert driver_feed_key("Sergio Pérez") == "driver:sergio-perez"


class TestRosterHarvest:
    def test_roster_from_a_completed_competition(self):
        competition = {
            "competitors": [
                {
                    "athlete": {
                        "fullName": "Kimi Antonelli",
                        "shortName": "K. Antonelli",
                        "flag": {"href": "https://a.espncdn.com/ita.png"},
                    },
                    "order": 1,
                },
                {
                    "athlete": {"displayName": "George Russell", "shortName": "G. Russell"},
                    "order": 2,
                },
                {"athlete": {"fullName": "Kimi Antonelli"}},  # duplicate collapses
                {"athlete": {}},  # no name, skipped
            ]
        }
        roster = TournamentParserMixin._roster_from_competition(competition)
        assert [r.name for r in roster] == ["Kimi Antonelli", "George Russell"]
        assert roster[0].code == "ANT" and roster[0].logo_url.endswith("ita.png")
        assert roster[1].short_name == "G. Russell"

    def test_last_session_state_reads_the_race_not_friday(self):
        event = {
            "competitions": [
                {"date": "2026-09-04T10:30Z", "status": {"type": {"state": "post"}}},
                {"date": "2026-09-06T13:00Z", "status": {"type": {"state": "pre"}}},
            ]
        }
        assert TournamentParserMixin._last_session_state(event) == "pre"


class TestUpsert:
    def test_first_refresh_inserts_drivers_and_variants_default_ignore(self, conn):
        result = upsert_roster(conn, "f1", ROSTER)
        feeds = list_race_feeds(conn, "f1")
        assert result["inserted"] == len(ROSTER) + len(VARIANT_FEEDS)
        assert {f.behavior for f in feeds} == {"ignore"}
        assert all(f.enabled and f.managed for f in feeds)
        # Drivers first, variants after, generic Onboard last.
        assert [f.kind for f in feeds][: len(ROSTER)] == ["driver"] * len(ROSTER)
        assert feeds[-1].feed_key == "variant:onboard"

    def test_refresh_keeps_the_users_choices(self, conn):
        upsert_roster(conn, "f1", ROSTER)
        leclerc = next(f for f in list_race_feeds(conn, "f1") if f.label == "Charles Leclerc")
        update_race_feed(conn, leclerc.id, behavior="consolidate", enabled=False)
        # A later refresh renames the row and updates terms; behavior/enabled survive.
        upsert_roster(
            conn, "f1", [RosterEntry("Charles Leclerc", "C. Leclerc", "LEC"), *ROSTER[1:]]
        )
        again = next(f for f in list_race_feeds(conn, "f1") if f.feed_key == leclerc.feed_key)
        assert again.behavior == "consolidate" and again.enabled is False

    def test_departed_driver_row_is_kept_not_deleted(self, conn):
        upsert_roster(conn, "f1", ROSTER)
        upsert_roster(conn, "f1", ROSTER[:2])
        keys = {f.feed_key for f in list_race_feeds(conn, "f1")}
        assert driver_feed_key("Lewis Hamilton") in keys

    def test_bulk_behavior_touches_one_kind_only(self, conn):
        upsert_roster(conn, "f1", ROSTER)
        assert set_behavior_for_kind(conn, "f1", "driver", "consolidate") == len(ROSTER)
        feeds = list_race_feeds(conn, "f1")
        assert all(f.behavior == "consolidate" for f in feeds if f.kind == "driver")
        assert all(f.behavior == "ignore" for f in feeds if f.kind == "variant")

    def test_leagues_listing(self, conn):
        upsert_roster(conn, "f1", ROSTER)
        assert race_feed_leagues(conn) == ["f1"]


class TestScopedKeywords:
    def test_only_the_leagues_feeds_join_the_list(self, conn):
        upsert_roster(conn, "f1", ROSTER)
        assert race_feed_keywords(conn, "nfl") == []
        assert race_feed_keywords(conn, None) == []
        assert [k.label for k in race_feed_keywords(conn, "f1")][:1] == ["Charles Leclerc"]

    def test_race_feeds_precede_global_keywords(self, conn):
        upsert_roster(conn, "f1", ROSTER)
        spanish = ExceptionKeyword(
            id=99, label="Spanish", match_terms="Spanish, Español", behavior="consolidate"
        )
        merged = get_keywords_for_league(conn, "f1", [spanish])
        assert merged[0].label == "Charles Leclerc" and merged[-1].label == "Spanish"
        # A stream naming a driver AND a language is the driver's feed.
        label, _ = check_exception_keyword("F1 TV 41: Ferrari: Charles Leclerc (Español)", merged)
        assert label == "Charles Leclerc"

    def test_disabled_feed_drops_out(self, conn):
        upsert_roster(conn, "f1", ROSTER)
        row = next(f for f in list_race_feeds(conn, "f1") if f.label == "Lewis Hamilton")
        update_race_feed(conn, row.id, enabled=False)
        assert "Lewis Hamilton" not in {k.label for k in race_feed_keywords(conn, "f1")}

    @pytest.mark.parametrize(
        ("stream", "label", "behavior"),
        [
            (
                "TSN+ 04: Formula 1 On-Board Camera: Charles Leclerc - Spanish GP Practice #3",
                "Charles Leclerc",
                "ignore",
            ),
            (
                "Apple TV F1 3: AppleTV 3 | Formula 1: Spain: Qualifying - Sergio Pérez (English)",
                "Sergio Pérez",
                "ignore",
            ),
            (
                "F1 TV 26: [4K] Ferrari: Charles Leclerc @ 6 Sep 01:00 PM",
                "Charles Leclerc",
                "ignore",
            ),
            ("UK: [F1]: LEC - LECLERC FERRARI [1080p]", "Charles Leclerc", "ignore"),
            (
                "TSN+ 02: Formula 1 Bonus Pit Lane - Spanish Grand Prix Practice #3",
                "Pit Lane",
                "ignore",
            ),
            ("F1 TV 07: [4K] TRACKER @ 6 Sep 01:00 PM", "Driver Tracker", "ignore"),
            ("F1 TV 09: DATA @ 6 Sep 01:00 PM", None, None),  # bare DATA is not a term (too common)
            ("DK|ViaPlay 4 - Onboard | Motorsport", "Onboard", "ignore"),
            ("F1 TV 05: F1 LIVE @ 6 Sep 01:00 PM", None, None),  # main feed: no keyword
            ("F1: SKY SPORTS F1 [1080p]", None, None),
        ],
    )
    def test_captured_provider_shapes(self, conn, stream, label, behavior):
        upsert_roster(conn, "f1", ROSTER)
        got = check_exception_keyword(stream, race_feed_keywords(conn, "f1"))
        assert got == (label, behavior)

    def test_a_driver_surname_never_fires_outside_its_league(self, conn):
        upsert_roster(conn, "f1", ROSTER)
        cfl = get_keywords_for_league(conn, "cfl", [])
        assert check_exception_keyword("CFL: Hamilton Tiger-Cats at Toronto Argonauts", cfl) == (
            None,
            None,
        )


class TestRefreshHook:
    def test_refresh_race_feeds_writes_through_the_refreshers_db(self, conn, monkeypatch):
        """The hook must use the refresher's own db handle — a regression that
        the API-level refresh hit on first run (AttributeError on _db_factory)."""
        from teamarr.consumers.cache import refresh as refresh_mod

        class Provider:
            name = "espn"
            ROSTER_LEAGUES = frozenset({"f1"})

            def get_race_roster(self, league):
                return ROSTER if league == "f1" else []

        class Service:
            _providers = [Provider()]

        monkeypatch.setattr(
            "teamarr.services.sports_data.create_default_service", lambda: Service()
        )

        class Factory:
            def __call__(self):
                return self

            def __enter__(self):
                return conn

            def __exit__(self, *exc):
                return False

        refresher = refresh_mod.CacheRefresher(db_factory=Factory())
        results = refresher.refresh_race_feeds(only_league="f1")
        assert results["f1"]["drivers"] == len(ROSTER)
        assert len(list_race_feeds(conn, "f1")) == len(ROSTER) + len(VARIANT_FEEDS)
        assert refresher.refresh_race_feeds(only_league="nfl") == {}
