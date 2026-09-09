"""HockeyTech league configuration and schema-seed regressions."""

from types import SimpleNamespace

import pytest

from teamarr.providers.hockeytech.client import HockeyTechClient
from teamarr.providers.hockeytech.provider import HockeyTechProvider


class _MappingSource:
    def __init__(self, mappings: dict[str, tuple[str, str]]):
        self._mappings = mappings

    def supports_league(self, league: str, provider: str) -> bool:
        return league.lower() in self._mappings and provider == "hockeytech"

    def get_mapping(self, league: str, provider: str):
        if provider != "hockeytech":
            return None
        config = self._mappings.get(league.lower())
        if not config:
            return None
        client_code, sport = config
        return SimpleNamespace(provider_league_id=client_code, sport=sport)

    def get_league_sport(self, league: str) -> str | None:
        config = self._mappings.get(league.lower())
        return config[1] if config else None


def test_gohl_mapping_resolves_hockeytech_client_configuration():
    client = HockeyTechClient(_MappingSource({"gohl": ("gojhl", "hockey")}))

    assert client.supports_league("gohl") is True
    assert client.get_league_config("gohl") == ("gojhl", "34b10d4d34d7b59a")
    assert client.get_sport("gohl") == "hockey"


def test_unconfigured_hockeytech_client_code_is_rejected():
    client = HockeyTechClient(_MappingSource({"unknown": ("not-configured", "hockey")}))

    assert client.supports_league("unmapped") is False
    assert client.get_league_config("unmapped") is None
    assert client.get_league_config("unknown") is None


def test_schema_seeds_gohl_hockeytech_mapping(db_conn):
    row = db_conn.execute(
        """
        SELECT provider, provider_league_id, display_name, sport, import_enabled,
               league_alias, league_id, event_type, enabled
        FROM leagues
        WHERE league_code = 'gohl'
        """
    ).fetchone()

    assert tuple(row) == (
        "hockeytech",
        "gojhl",
        "Greater Ontario Hockey League",
        "hockey",
        1,
        "GOHL",
        "gohl",
        "team_vs_team",
        1,
    )


# ---------------------------------------------------------------------------
# Broadcaster parsing (#752)
#
# HockeyTech sends `broadcasters` as a home/away/national mapping when a game
# has any, and as an empty LIST when it has none. `_parse_broadcasts` defaulted
# it to {} and called .get() on it, so the list shape raised AttributeError —
# which reached `_parse_event`'s handler and dropped the ENTIRE GAME. A fixture
# with no listed broadcaster never became an Event, so no stream could match it:
# 17 distinct games a day on one production install, re-dropped every run.
#
# The load-bearing assertion is not that broadcasts parse — it is that the
# EVENT survives a broadcaster field of any shape.
# ---------------------------------------------------------------------------

def _provider() -> HockeyTechProvider:
    """Provider instance without touching __init__'s client wiring."""
    return HockeyTechProvider.__new__(HockeyTechProvider)


@pytest.mark.parametrize(
    "shape,expected",
    [
        ({}, []),                                              # no broadcasters, dict form
        ([], []),                                              # no broadcasters, LIST form (#752)
        (None, []),                                            # key present but null
        ("Sportsnet", []),                                     # scalar — not a mapping
        ({"home": []}, []),                                    # mapping, empty side
        ({"home": "CBC"}, []),                                 # side is a scalar, not a list
        ({"home": [{"name": "TSN"}]}, ["TSN"]),
        ({"national": ["Sportsnet"]}, ["Sportsnet"]),
        ({"home": [{"short_name": "TSN2"}]}, ["TSN2"]),
    ],
)
def test_broadcaster_shapes_never_raise(shape, expected):
    assert _provider()._parse_broadcasts({"broadcasters": shape}) == expected


def test_missing_broadcasters_key_is_empty():
    assert _provider()._parse_broadcasts({}) == []


def test_broadcast_names_are_deduplicated_across_sides():
    got = _provider()._parse_broadcasts(
        {"broadcasters": {"home": [{"name": "TSN"}], "away": [{"name": "TSN"}]}}
    )
    assert got == ["TSN"]


class _StubClient:
    def get_sport(self, league):
        return "hockey"

    def get_league_config(self, league):
        return ("ahl", "key")

    def get_teams(self, *a, **kw):
        return []


def _game(broadcasters):
    return {
        "game_id": "32635",
        "GameDateISO8601": "2026-09-08T19:00:00-04:00",
        "home_team": "1",
        "home_team_city": "Hershey",
        "home_team_nickname": "Bears",
        "home_team_code": "HER",
        "visiting_team": "2",
        "visiting_team_city": "Wilkes-Barre",
        "visiting_team_nickname": "Penguins",
        "visiting_team_code": "WBS",
        "game_status": "1",
        "broadcasters": broadcasters,
    }


@pytest.mark.parametrize("broadcasters", [[], {}, None, "Sportsnet"])
def test_a_game_survives_any_broadcaster_shape(broadcasters):
    """The regression that mattered: the FIXTURE must not be dropped (#752)."""
    provider = _provider()
    provider._client = _StubClient()

    event = provider._parse_event(_game(broadcasters), "ahl")

    assert event is not None, "game was dropped over a cosmetic broadcaster field"
    assert event.id == "32635"
    assert event.home_team.name == "Hershey Bears"
    assert event.away_team.name == "Wilkes-Barre Penguins"


def test_a_game_with_real_broadcasters_still_carries_them():
    provider = _provider()
    provider._client = _StubClient()

    event = provider._parse_event(_game({"national": [{"name": "TSN"}]}), "ahl")

    assert event is not None
    assert event.broadcasts == ["TSN"]
