"""Article-aware naming + Gracenote-fidelity vars (tvnk.7, #329).

Covers the core.naming heuristics (national-team leagues, tournament
articles, surnames, matchup connector), the new template variables, the
resolver's leading-"the" capitalization, and the tennis prose result.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from teamarr.core.naming import (
    is_national_team_league,
    matchup_connector,
    surnames,
    team_with_article,
    tournament_with_article,
)
from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.context import (
    GameContext,
    TeamChannelContext,
    TemplateContext,
)
from teamarr.templates.resolver import TemplateResolver
from teamarr.templates.variables.combat import (
    extract_fighter1_last,
    extract_fighter2_last,
)
from teamarr.templates.variables.home_away import (
    extract_at_vs,
    extract_away_team_the,
    extract_home_away_verb,
    extract_home_team_the,
)
from teamarr.templates.variables.identity import (
    extract_opponent_the,
    extract_team_name_the,
)
from teamarr.templates.variables.tennis import (
    extract_tennis_result,
    extract_tournament_name_the,
)

# --- heuristics ---


def test_national_team_league_detection():
    assert is_national_team_league("fifa.world")
    assert is_national_team_league("fifa.worldq.uefa")
    assert is_national_team_league("uefa.euro")
    assert is_national_team_league("uefa.nations")
    assert is_national_team_league("conmebol.america")
    assert is_national_team_league("concacaf.gold")
    assert is_national_team_league("caf.nations")
    assert is_national_team_league("fifa.friendly")
    assert is_national_team_league("itm")  # rugby test matches

    assert not is_national_team_league("fifa.cwc")  # Club World Cup
    assert not is_national_team_league("uefa.champions")
    assert not is_national_team_league("conmebol.libertadores")
    assert not is_national_team_league("eng.1")
    assert not is_national_team_league("nba")
    assert not is_national_team_league(None)


def test_team_with_article():
    assert team_with_article("Detroit Pistons", "nba", "basketball") == "the Detroit Pistons"
    # Soccer club names are proper nouns in the match register (tvnk.9):
    # "Arsenal face Chelsea", never "the Arsenal"/"the Manchester United"
    assert team_with_article("Arsenal", "eng.1", "soccer") == "Arsenal"
    assert team_with_article("Manchester United", "eng.1", "soccer") == "Manchester United"
    assert team_with_article("LA Galaxy", "usa.1", "soccer") == "LA Galaxy"
    assert team_with_article("Netherlands", "fifa.world", "soccer") == "Netherlands"
    assert team_with_article("Carlos Alcaraz", "atp", "tennis") == "Carlos Alcaraz"
    assert team_with_article("Jon Jones", "ufc", "mma") == "Jon Jones"
    # Name already carrying an article isn't doubled
    assert team_with_article("The Citadel Bulldogs", "ncaaf", "football") == (
        "The Citadel Bulldogs"
    )
    assert team_with_article("", "nba", "basketball") == ""


def test_tournament_with_article():
    assert tournament_with_article("Wimbledon") == "Wimbledon"
    assert tournament_with_article("Roland Garros") == "Roland Garros"
    assert tournament_with_article("US Open") == "the US Open"
    assert tournament_with_article("Australian Open") == "the Australian Open"
    assert tournament_with_article("Miami Masters") == "the Miami Masters"
    assert tournament_with_article("Davis Cup") == "the Davis Cup"
    assert tournament_with_article("") == ""


def test_matchup_connector():
    assert matchup_connector("basketball") == "at"
    assert matchup_connector("football") == "at"
    assert matchup_connector("soccer") == "vs."
    assert matchup_connector("tennis") == "vs."
    assert matchup_connector("mma") == "vs."


def test_surnames():
    assert surnames("Alex de Minaur") == "de Minaur"
    assert surnames("Camilo Ugo Carabelli") == "Ugo Carabelli"
    assert surnames("Hugo Nys / Edouard Roger-Vasselin") == "Nys/Roger-Vasselin"
    assert surnames("Alcaraz") == "Alcaraz"


# --- variables ---


def _team(name, league="nba", sport="basketball", id_="1"):
    return Team(
        id=id_, provider="espn", name=name, short_name=name,
        abbreviation=name[:3].upper(), league=league, sport=sport,
    )


def _ctx(home, away, league="nba", sport="basketball", team_is_home=True, **event_kw):
    event = Event(
        id="1", provider="espn", name=f"{away.name} at {home.name}",
        short_name="x", start_time=datetime(2026, 7, 10, 19, 0, tzinfo=UTC),
        home_team=home, away_team=away, status=EventStatus(state="pre"),
        league=league, sport=sport, **event_kw,
    )
    us = home if team_is_home else away
    them = away if team_is_home else home
    gc = GameContext(event=event, is_home=team_is_home, team=us, opponent=them)
    tc = TeamChannelContext(
        team_id=us.id, league=league, sport=sport, team_name=us.name
    )
    return TemplateContext(game_context=gc, team_config=tc, team_stats=None), gc


def test_article_vars_club_vs_national():
    ctx, gc = _ctx(_team("Los Angeles Lakers"), _team("Detroit Pistons", id_="2"))
    assert extract_home_team_the(ctx, gc) == "the Los Angeles Lakers"
    assert extract_away_team_the(ctx, gc) == "the Detroit Pistons"
    assert extract_team_name_the(ctx, gc) == "the Los Angeles Lakers"
    assert extract_opponent_the(ctx, gc) == "the Detroit Pistons"

    ctx, gc = _ctx(
        _team("France", "fifa.world", "soccer"),
        _team("Netherlands", "fifa.world", "soccer", id_="2"),
        league="fifa.world",
        sport="soccer",
    )
    assert extract_home_team_the(ctx, gc) == "France"
    assert extract_away_team_the(ctx, gc) == "Netherlands"
    assert extract_opponent_the(ctx, gc) == "Netherlands"


def test_at_vs_and_verb():
    ctx, gc = _ctx(_team("Los Angeles Lakers"), _team("Detroit Pistons", id_="2"))
    assert extract_at_vs(ctx, gc) == "at"
    assert extract_home_away_verb(ctx, gc) == "host"

    ctx, gc = _ctx(
        _team("Los Angeles Lakers"),
        _team("Detroit Pistons", id_="2"),
        team_is_home=False,
    )
    assert extract_home_away_verb(ctx, gc) == "visit"

    ctx, gc = _ctx(
        _team("France", "fifa.world", "soccer"),
        _team("Netherlands", "fifa.world", "soccer", id_="2"),
        league="fifa.world",
        sport="soccer",
    )
    assert extract_at_vs(ctx, gc) == "vs."


def test_fighter_last_names():
    ctx, gc = _ctx(
        _team("Alexander Volkanovski", "ufc", "mma"),
        _team("Diego Lopes", "ufc", "mma", id_="2"),
        league="ufc",
        sport="mma",
    )
    assert extract_fighter1_last(ctx, gc) == "Volkanovski"
    assert extract_fighter2_last(ctx, gc) == "Lopes"


def test_tournament_name_the_var():
    ctx, gc = _ctx(
        _team("Carlos Alcaraz", "atp", "tennis"),
        _team("Jannik Sinner", "atp", "tennis", id_="2"),
        league="atp",
        sport="tennis",
        tournament_name="US Open",
    )
    assert extract_tournament_name_the(ctx, gc) == "the US Open"

    ctx, gc = _ctx(
        _team("Carlos Alcaraz", "atp", "tennis"),
        _team("Jannik Sinner", "atp", "tennis", id_="2"),
        league="atp",
        sport="tennis",
        tournament_name="Wimbledon",
    )
    assert extract_tournament_name_the(ctx, gc) == "Wimbledon"


def test_tennis_result_prose():
    ctx, gc = _ctx(
        _team("Marton Piros", "atp", "tennis"),
        _team("Ivan Ivanov", "atp", "tennis", id_="2"),
        league="atp",
        sport="tennis",
        game_recap="Piros (HUN) bt Ivanov (BUL) 6-2 6-2",
    )
    assert extract_tennis_result(ctx, gc) == "Piros defeats Ivanov 6-2, 6-2"

    # Tiebreak set scores keep their parenthetical
    ctx, gc = _ctx(
        _team("A Zverev", "atp", "tennis"),
        _team("A Fery", "atp", "tennis", id_="2"),
        league="atp",
        sport="tennis",
        game_recap="Zverev (GER) bt Fery (GBR) 6-3 6-4 7-6(5)",
    )
    assert extract_tennis_result(ctx, gc) == "Zverev defeats Fery 6-3, 6-4, 7-6(5)"

    # No recap yet → empty (postgame falls through to constructed text)
    ctx, gc = _ctx(
        _team("A", "atp", "tennis"),
        _team("B", "atp", "tennis", id_="2"),
        league="atp",
        sport="tennis",
    )
    assert extract_tennis_result(ctx, gc) == ""


# --- resolver capitalization ---


@pytest.fixture
def mock_league_mapping_service():
    """Mock the league mapping service singleton (full resolution needs it)."""
    svc = MagicMock()
    svc.get_league_alias.side_effect = lambda code: code.upper()
    svc.get_league_display_name.side_effect = lambda code: code.upper()
    svc.get_league_id.side_effect = lambda code: code
    svc.get_league_logo.return_value = ""
    svc.get_gracenote_category.side_effect = lambda code: code.upper()
    svc.get_sport_display_name.side_effect = lambda code: code.title()
    with patch("teamarr.services.league_mappings._league_mapping_service", svc):
        yield svc


def test_resolver_capitalizes_leading_the(mock_league_mapping_service):
    ctx, _ = _ctx(_team("Los Angeles Lakers"), _team("Detroit Pistons", id_="2"))
    resolver = TemplateResolver()
    out = resolver.resolve("{team_name_the} host {opponent_the} tonight.", ctx)
    assert out == "The Los Angeles Lakers host the Detroit Pistons tonight."
