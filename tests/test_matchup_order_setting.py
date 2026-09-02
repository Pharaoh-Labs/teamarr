"""Matchup order setting (#692 phase 2): global mode + per-league override,
read at render time by {matchup*} and {team1}/{team2}."""

import sqlite3
from datetime import UTC, datetime

import pytest

from teamarr.config import (
    Config,
    get_matchup_order,
    set_global_matchup_order,
    set_league_matchup_order,
    set_matchup_orders,
)
from teamarr.core.naming import MATCHUP_ORDER_MODES, format_matchup, matchup_home_first
from teamarr.core.types import Event, EventStatus, Team
from teamarr.database.connection import get_connection
from teamarr.database.settings import get_all_settings, update_display_settings
from teamarr.database.subscription import (
    delete_league_config,
    get_league_config,
    upsert_league_config,
)
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.variables.identity import (
    extract_matchup,
    extract_matchup_abbrev,
    extract_team1,
    extract_team1_abbrev,
    extract_team1_short,
    extract_team2,
    extract_team2_abbrev,
    extract_team2_short,
)


@pytest.fixture(autouse=True)
def _reset_matchup_cache():
    set_matchup_orders("auto", {})
    yield
    set_matchup_orders("auto", {})


def _team(name, short, abbrev, sport, league):
    return Team(
        id=name, provider="espn", name=name, short_name=short,
        abbreviation=abbrev, league=league, sport=sport,
    )


def _ctx(home, away, sport, league):
    event = Event(
        id="1", provider="espn", name=f"{away.name} at {home.name}", short_name="x",
        start_time=datetime(2026, 9, 2, 19, 0, tzinfo=UTC),
        home_team=home, away_team=away, status=EventStatus(state="pre"),
        league=league, sport=sport,
    )
    gc = GameContext(event=event, is_home=True, team=home, opponent=away)
    tc = TeamChannelContext(team_id=home.id, league=league, sport=sport, team_name=home.name)
    return TemplateContext(game_context=gc, team_config=tc, team_stats=None), gc


def _nfl():
    return _ctx(
        _team("Detroit Lions", "Lions", "det", "football", "nfl"),
        _team("Chicago Bears", "Bears", "chi", "football", "nfl"),
        "football", "nfl",
    )


def _epl():
    return _ctx(
        _team("Ipswich Town", "Ipswich", "ips", "soccer", "eng.1"),
        _team("Liverpool", "Liverpool", "liv", "soccer", "eng.1"),
        "soccer", "eng.1",
    )


def test_order_modes_resolve_home_first():
    assert matchup_home_first("football", "auto") is False
    assert matchup_home_first("soccer", "auto") is True
    assert matchup_home_first("football", "home_first") is True
    assert matchup_home_first("soccer", "away_first") is False
    assert format_matchup("Bears", "Lions", "football", order="home_first") == "Lions @ Bears"
    flipped = format_matchup("Liverpool", "Ipswich", "soccer", order="away_first")
    assert flipped == "Liverpool v Ipswich"
    assert MATCHUP_ORDER_MODES == {"auto", "away_first", "home_first"}


def test_config_cache_precedence_and_case():
    assert get_matchup_order("nfl") == "auto"
    set_global_matchup_order("home_first")
    assert get_matchup_order("nfl") == "home_first"
    set_league_matchup_order("ENG.1", "away_first")
    assert get_matchup_order("eng.1") == "away_first"  # override wins, case-insensitive
    assert get_matchup_order("nfl") == "home_first"
    set_league_matchup_order("eng.1", None)
    assert get_matchup_order("eng.1") == "home_first"  # cleared → global
    set_matchup_orders("auto", {"mlb": "home_first", "nba": None})
    assert get_matchup_order("mlb") == "home_first" and get_matchup_order("nba") == "auto"
    assert Config.get_matchup_order() == "auto"


def test_team1_team2_follow_auto_convention():
    ctx, gc = _nfl()
    assert (extract_team1(ctx, gc), extract_team2(ctx, gc)) == ("Chicago Bears", "Detroit Lions")
    assert (extract_team1_short(ctx, gc), extract_team2_short(ctx, gc)) == ("Bears", "Lions")
    assert (extract_team1_abbrev(ctx, gc), extract_team2_abbrev(ctx, gc)) == ("CHI", "DET")
    ctx, gc = _epl()
    assert (extract_team1(ctx, gc), extract_team2(ctx, gc)) == ("Ipswich Town", "Liverpool")
    assert extract_matchup(ctx, gc) == "Ipswich Town v Liverpool"


def test_global_setting_flips_variables():
    set_global_matchup_order("home_first")
    ctx, gc = _nfl()
    assert extract_team1(ctx, gc) == "Detroit Lions"
    assert extract_matchup(ctx, gc) == "Detroit Lions @ Chicago Bears"
    assert extract_matchup_abbrev(ctx, gc) == "DET @ CHI"
    set_global_matchup_order("away_first")
    ctx, gc = _epl()
    assert extract_team1(ctx, gc) == "Liverpool"
    assert extract_matchup(ctx, gc) == "Liverpool v Ipswich Town"


def test_per_league_override_beats_global():
    set_global_matchup_order("home_first")
    set_league_matchup_order("nfl", "away_first")
    ctx, gc = _nfl()
    assert extract_team1(ctx, gc) == "Chicago Bears"
    ctx, gc = _epl()  # no override → global home_first (same as auto here)
    assert extract_team1(ctx, gc) == "Ipswich Town"


def test_no_event_renders_empty():
    assert extract_team1(None, None) == "" and extract_team2_abbrev(None, None) == ""


def test_display_setting_and_league_override_persist(db_path):
    with get_connection(db_path) as conn:
        assert get_all_settings(conn).display.matchup_order == "auto"
        update_display_settings(conn, matchup_order="home_first")
        conn.commit()
        assert get_all_settings(conn).display.matchup_order == "home_first"
        cfg = upsert_league_config(conn, "eng.1", matchup_order="away_first")
        assert cfg.matchup_order == "away_first"
        assert get_league_config(conn, "eng.1").matchup_order == "away_first"
        # other override fields untouched by a matchup-only save
        assert cfg.channel_group_mode is None
        delete_league_config(conn, "eng.1")
        assert get_league_config(conn, "eng.1") is None


def test_schema_rejects_unknown_modes(db_path):
    with get_connection(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE settings SET matchup_order = 'sideways'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO subscription_league_config (league_code, matchup_order)"
                " VALUES ('x', 'sideways')"
            )
