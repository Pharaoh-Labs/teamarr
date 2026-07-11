"""Gracenote category overrides (#371, #355 item 13).

The core promise under test: an override survives the leagues seed's
whole-row INSERT OR REPLACE (the #194 wipe), wins over the curated value at
read time, and clears back to the curated/derived default.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from teamarr.services import league_mappings as lm
from teamarr.services.league_overrides import (
    LeagueNotFoundError,
    get_gracenote_override_state,
    list_gracenote_overrides,
    set_gracenote_override,
)

SCHEMA = Path(__file__).parent.parent / "teamarr" / "database" / "schema.sql"


@pytest.fixture(autouse=True)
def bound_services(db_factory):
    """Real LeagueMappingService + get_db bound to the temp database."""
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    with patch("teamarr.services.league_overrides.get_db", db_factory):
        yield
    lm._league_mapping_service = prior


def test_override_wins_and_clears_to_default():
    service = lm.get_league_mapping_service()
    default = service.get_gracenote_category("nfl")
    assert default == "NFL Football"

    state = set_gracenote_override("nfl", "Pro Football")
    assert state["override"] == "Pro Football"
    assert state["effective"] == "Pro Football"
    assert state["default"] == "NFL Football"
    assert lm.get_league_mapping_service().get_gracenote_category("nfl") == "Pro Football"

    state = set_gracenote_override("nfl", None)
    assert state["override"] is None
    assert state["effective"] == "NFL Football"


def test_override_survives_seed_reapply(db_conn):
    """The startup executescript re-runs the leagues INSERT OR REPLACE —
    the override must survive it (the whole point of the separate table)."""
    set_gracenote_override("nascar-cup", "Stock Car Racing")

    db_conn.executescript(SCHEMA.read_text())
    db_conn.commit()
    lm.get_league_mapping_service().reload()

    assert (
        lm.get_league_mapping_service().get_gracenote_category("nascar-cup")
        == "Stock Car Racing"
    )
    state = get_gracenote_override_state("nascar-cup")
    assert state["override"] == "Stock Car Racing"
    # Derived default (event league → display name), untouched by the override
    assert state["default"] == "NASCAR Cup Series"


def test_empty_string_clears_like_none():
    set_gracenote_override("nba", "Hoops")
    state = set_gracenote_override("nba", "   ")
    assert state["override"] is None
    assert state["effective"] == state["default"]


def test_list_overrides():
    set_gracenote_override("nfl", "Pro Football")
    set_gracenote_override("nba", "Pro Basketball")
    rows = list_gracenote_overrides()
    codes = {r["league_code"]: r for r in rows}
    assert codes["nfl"]["gracenote_category"] == "Pro Football"
    assert codes["nfl"]["default"] == "NFL Football"
    assert "nba" in codes


def test_unknown_league_rejected():
    with pytest.raises(LeagueNotFoundError):
        set_gracenote_override("not-a-league", "X")
