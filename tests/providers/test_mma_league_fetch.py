"""ESPN MMA card fetching is keyed on sport, not on the league code (#756).

Adding PFL to the UFC-only card path meant every ``if league == "ufc"`` branch
in the provider had to become "is this league MMA?". These tests pin the two
halves of that: a promotion the leagues table knows about takes the card path
from its SPORT alone (so a new promotion is a schema.sql row, no code), and
the parsed events carry that promotion's own league code rather than "ufc".
"""

from datetime import date

from teamarr.providers.espn.provider import ESPNProvider


def _card(event_id: str, name: str, comp_dates: list[str]) -> dict:
    """Minimal ESPN MMA scoreboard event: one competition per bout time."""
    return {
        "id": event_id,
        "name": name,
        "competitions": [
            {
                "date": d,
                "competitors": [
                    {"athlete": {"displayName": "Fighter A", "shortName": "A"}},
                    {"athlete": {"displayName": "Fighter B", "shortName": "B"}},
                ],
                "status": {"type": {"state": "pre"}},
            }
            for d in comp_dates
        ],
    }


class FakeMapping:
    def __init__(self, sport: str, provider_league_id: str):
        self.sport = sport
        self.provider_league_id = provider_league_id


class FakeMappingSource:
    """Stand-in for LeagueMappingService: league_code -> (sport, provider_league_id)."""

    def __init__(self, rows: dict[str, tuple[str, str]]):
        self._rows = rows

    def get_mapping(self, league_code: str, provider: str):
        row = self._rows.get(league_code.lower())
        return FakeMapping(*row) if row else None

    def get_mapping_by_league(self, league_code: str):
        return self._rows.get(league_code.lower())

    def get_league_sport(self, league_code: str):
        row = self._rows.get(league_code.lower())
        return row[0] if row else None

    def register_discovered_league(self, **kwargs):
        pass


class CapturingClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, str | None]] = []

    def get_mma_scoreboard(self, espn_league="ufc", date_str=None):
        self.calls.append((espn_league, date_str))
        return self.payload

    def get_scoreboard(self, *args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("MMA leagues must not fall through to the team scoreboard")


def _provider(client, rows):
    return ESPNProvider(client=client, league_mapping_source=FakeMappingSource(rows))


LEAGUES = {
    "ufc": ("mma", "mma/ufc"),
    "pfl": ("mma", "mma/pfl"),
    "lfa": ("mma", "mma/lfa"),
}


def test_pfl_fetches_its_own_espn_slug():
    client = CapturingClient({"events": []})
    _provider(client, LEAGUES).get_events("pfl", date(2026, 2, 7))

    assert client.calls == [("pfl", "20260206-20260208")]


def test_lfa_fetches_its_own_espn_slug():
    client = CapturingClient({"events": []})
    _provider(client, LEAGUES).get_events("lfa", date(2026, 3, 13))

    assert client.calls == [("lfa", "20260312-20260314")]


def test_parsed_events_carry_the_requested_league():
    """The card is PFL's, not UFC's — league rides through the parser (#756)."""
    payload = {
        "events": [
            _card("600056964", "PFL Dubai: Nurmagomedov vs. Davis", ["2026-02-07T17:00Z"])
        ]
    }
    events = _provider(CapturingClient(payload), LEAGUES).get_events("pfl", date(2026, 2, 7))

    assert [e.league for e in events] == ["pfl"]
    assert events[0].sport == "mma"
    assert events[0].home_team.league == "pfl"
    assert events[0].away_team.league == "pfl"


def test_new_promotion_needs_only_a_leagues_row():
    """A promotion absent from MMA_LEAGUES still takes the card path via sport.

    This is the whole point of keying on sport: adding the next promotion is
    an INSERT in schema.sql, not an edit to the provider.
    """
    rows = {"oktagon": ("mma", "mma/oktagon")}
    assert "oktagon" not in ESPNProvider.MMA_LEAGUES

    client = CapturingClient({"events": []})
    _provider(client, rows).get_events("oktagon", date(2026, 4, 11))

    assert client.calls == [("oktagon", "20260410-20260412")]


def test_known_promotion_survives_a_missing_mapping():
    """No mapping source (bare provider) must not drop UFC off the card path."""
    client = CapturingClient({"events": []})
    ESPNProvider(client=client).get_events("pfl", date(2026, 2, 7))

    assert client.calls == [("pfl", "20260206-20260208")]


def test_mma_leagues_have_no_teams_or_summary_endpoint():
    for league in ESPNProvider.MMA_LEAGUES:
        assert league in ESPNProvider.LEAGUES_WITHOUT_TEAMS
        assert league in ESPNProvider.LEAGUES_WITHOUT_SUMMARY


class TestMainEventSelection:
    """The card's name picks the headline bout, not the bout order (#756).

    UFC and PFL list the main event last; LFA lists it FIRST, so the old
    ``competitions[-1]`` put an undercard pair into home_team/away_team on 12
    of 36 LFA cards on ESPN's 2025-26 slate (and 7 of 572 in the `other`
    bucket). Measured against those same slates, this pick leaves all 103 UFC
    cards and every PFL card exactly as they were.
    """

    def _comp(self, f1: str, f2: str, when: str = "2026-03-13T04:00Z") -> dict:
        return {
            "date": when,
            "competitors": [
                {"athlete": {"displayName": f1, "shortName": f1}},
                {"athlete": {"displayName": f2, "shortName": f2}},
            ],
            "status": {"type": {"state": "pre"}},
        }

    def _event(self, name: str, comps: list[dict]) -> dict:
        return {"id": "1", "name": name, "competitions": comps}

    def test_main_event_first_is_found(self):
        """LFA 228 opens with its headline bout."""
        payload = {
            "events": [
                self._event(
                    "LFA 228: Natividad vs. Garcia",
                    [
                        self._comp("Adrian Garcia", "Christian Natividad"),
                        self._comp("Gabriel Thimoteo", "Alik Lorenz"),
                        self._comp("Leslie Hernandez", "Aleksandra Savicheva"),
                    ],
                )
            ]
        }
        events = _provider(CapturingClient(payload), LEAGUES).get_events("lfa", date(2026, 3, 13))

        assert {events[0].home_team.name, events[0].away_team.name} == {
            "Adrian Garcia",
            "Christian Natividad",
        }

    def test_main_event_last_is_still_found(self):
        """UFC/PFL ordering is untouched."""
        payload = {
            "events": [
                self._event(
                    "UFC Fight Night: Bautista vs. Oliveira",
                    [
                        self._comp("Leslie Hernandez", "Aleksandra Savicheva"),
                        self._comp("Vinicius Oliveira", "Mario Bautista"),
                    ],
                )
            ]
        }
        events = _provider(CapturingClient(payload), LEAGUES).get_events("ufc", date(2026, 2, 7))

        assert {events[0].home_team.name, events[0].away_team.name} == {
            "Vinicius Oliveira",
            "Mario Bautista",
        }

    def test_accented_names_still_match_the_card_name(self):
        payload = {
            "events": [
                self._event(
                    "FNC 31: Barbir vs. Ilić",
                    [
                        self._comp("Filip Barbir", "Marko Ilic"),
                        self._comp("Someone Else", "Another Person"),
                    ],
                )
            ]
        }
        events = _provider(CapturingClient(payload), LEAGUES).get_events("lfa", date(2026, 5, 30))

        assert {events[0].home_team.name, events[0].away_team.name} == {
            "Filip Barbir",
            "Marko Ilic",
        }

    def test_nameless_card_falls_back_to_the_last_bout(self):
        """"PFL Dubai" / "UFC 335" name no fighters — pre-#756 behavior stands."""
        payload = {
            "events": [
                self._event(
                    "PFL Dubai",
                    [
                        self._comp("Undercard One", "Undercard Two"),
                        self._comp("Usman Nurmagomedov", "Alfie Davis"),
                    ],
                )
            ]
        }
        events = _provider(CapturingClient(payload), LEAGUES).get_events("pfl", date(2026, 11, 14))

        assert {events[0].home_team.name, events[0].away_team.name} == {
            "Usman Nurmagomedov",
            "Alfie Davis",
        }
