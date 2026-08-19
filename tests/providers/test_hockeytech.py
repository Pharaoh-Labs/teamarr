"""HockeyTech league configuration and schema-seed regressions."""

from types import SimpleNamespace

from teamarr.providers.hockeytech.client import HockeyTechClient


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
