"""Team channel name and logo templates go through the template engine (#983).

The name and logo fields of a team template were rendered from a four-entry
variable map copied into five call sites, so ``{league_abbrev} | {team_short}``
reached the guide and Dispatcharr with its braces intact. They now share
``services/team_channel_templates.py``.
"""

from types import SimpleNamespace

import pytest

import teamarr.services.league_mappings as lm
from teamarr.consumers.team_processor import TeamConfig, TeamProcessor
from teamarr.database.leagues import get_league_display
from teamarr.services.team_channel_manager import TeamChannelManager
from teamarr.services.team_channel_templates import (
    resolve_team_channel_logo,
    resolve_team_channel_name,
    team_channel_context,
)
from teamarr.templates.resolver import TemplateResolver

TEAM = {
    "id": 1,
    "provider": "espn",
    "provider_team_id": "8",
    "primary_league": "nfl",
    "sport": "football",
    "team_name": "Detroit Lions",
    "team_abbrev": "DET",
    "team_logo_url": "https://a.espncdn.com/i/teamlogos/nfl/500/det.png",
    "channel_id": "DetroitLions.nfl",
    "template_id": 5,
}


@pytest.fixture(autouse=True)
def real_league_service(db_factory):
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


@pytest.fixture
def conn(db_conn):
    db_conn.execute(
        "INSERT INTO team_cache (team_name, team_abbrev, team_short_name, provider, "
        "provider_team_id, league, sport) VALUES "
        "('Detroit Lions', 'DET', 'Lions', 'espn', '8', 'nfl', 'football')"
    )
    db_conn.commit()
    return db_conn


def test_the_reported_template_resolves(conn):
    assert resolve_team_channel_name(conn, TEAM, "{league_abbrev} | {team_short}") == "NFL | Lions"


def test_other_team_identity_variables_resolve(conn):
    assert resolve_team_channel_name(conn, TEAM, "{team_abbrev} {sport}") == "DET Football"


def test_the_four_original_variables_keep_their_values(conn):
    """No existing channel is renamed: these resolve exactly as before."""
    team = dict(TEAM, primary_league="college-football")
    name = resolve_team_channel_name(
        conn, team, "{league} | {team_name} | {league_id} | {league_code}"
    )
    display = get_league_display(conn, "college-football")
    assert name == f"{display} | Detroit Lions | college-football | college-football"


def test_a_game_variable_resolves_empty_rather_than_literal(conn):
    """There is no game behind a channel name, and it must not vary per run."""
    assert resolve_team_channel_name(conn, TEAM, "{team_name} {opponent}") == "Detroit Lions"


def test_an_unknown_variable_stays_literal(conn):
    assert resolve_team_channel_name(conn, TEAM, "{team_name} {no_such_var}") == (
        "Detroit Lions {no_such_var}"
    )


def test_no_template_means_the_team_name(conn):
    assert resolve_team_channel_name(conn, TEAM, None) == "Detroit Lions"
    assert resolve_team_channel_name(conn, TEAM, "") == "Detroit Lions"


def test_a_team_missing_from_the_cache_still_resolves(db_conn):
    assert resolve_team_channel_name(db_conn, TEAM, "{league_abbrev} | {team_short}") == "NFL |"
    assert resolve_team_channel_name(db_conn, TEAM, "{league_abbrev} | {team_name}") == (
        "NFL | Detroit Lions"
    )


def test_guide_and_dispatcharr_resolve_the_same_name(conn, monkeypatch):
    """The two used to hold separate copies of the variable map. A name that
    differs between them renames the channel on every run."""
    text = "{league_abbrev} | {team_short} ({team_abbrev})"
    template = SimpleNamespace(team_channel_name=text, team_channel_logo_url=None)

    import teamarr.database.templates as templates

    monkeypatch.setattr(templates, "get_template", lambda *_: template)

    team_config = TeamConfig(
        id=1, provider="espn", provider_team_id="8", primary_league="nfl", leagues=["nfl"],
        sport="football", team_name="Detroit Lions", team_abbrev="DET",
        team_logo_url=TEAM["team_logo_url"], channel_id="DetroitLions.nfl",
        channel_logo_url=None, template_id=5, active=True,
    )
    options = SimpleNamespace(template=template, art_base_url="")

    guide = TeamProcessor._resolve_channel_name(conn, options, team_config)
    dispatcharr = TeamChannelManager._channel_name(conn, TEAM)

    assert guide == dispatcharr == "NFL | Lions (DET)"


def test_logo_template_resolves_through_the_engine(conn):
    url = resolve_team_channel_logo(
        conn, TEAM, "https://logos.example/{league_code}/{team_abbrev|lower}.png", ""
    )
    assert url == "https://logos.example/nfl/det.png"


def test_relative_logo_needs_an_art_base_url(conn):
    """A game-thumbs path with no base URL is not a fetchable logo (#826)."""
    text = "{league_id}/{team_name|pascal}/logo.png?style=1"
    assert resolve_team_channel_logo(conn, TEAM, text, "") is None
    assert resolve_team_channel_logo(conn, TEAM, text, "https://thumbs.example") == (
        "https://thumbs.example/nfl/DetroitLions/logo.png?style=1"
    )
    assert resolve_team_channel_logo(conn, TEAM, None, "https://thumbs.example") is None


def test_every_registered_variable_survives_a_gameless_team_context(conn):
    """The engine runs every extractor to build its map; one that assumes a
    game would take the channel sync down with it."""
    resolver = TemplateResolver()
    variables = resolver.build_variables(team_channel_context(conn, TEAM))
    assert variables["team_short"] == "Lions"
    assert len(variables) >= resolver.get_variable_count() // 2
