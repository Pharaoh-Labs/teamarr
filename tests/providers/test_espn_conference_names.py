"""A conference is shown by name, never as "Conference 5" (#996).

ESPN's team payload identifies the conference and division by id only. Those
ids used to be returned dressed as names, and the College Team starter printed
"…host Penn State in Conference 5 play".
"""

from unittest.mock import MagicMock

import pytest

from teamarr.core.types import TeamStats
from teamarr.database.provider_cache import dict_to_stats, stats_to_dict
from teamarr.database.provider_groups import get_group_names, is_placeholder_group_name
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.services.sports_data import SportsDataService
from teamarr.templates.conditions import ConditionEvaluator
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext


def test_college_groups_parse_to_ids():
    provider = ESPNProvider(client=MagicMock())
    groups = {"id": "5", "parent": {"id": "80"}, "isConference": True}
    assert provider._parse_groups(groups) == ("5", "80")  # conference, division


def test_pro_groups_parse_to_ids():
    provider = ESPNProvider(client=MagicMock())
    groups = {"id": "10", "parent": {"id": "7"}, "isConference": False}
    assert provider._parse_groups(groups) == ("7", "10")  # conference, division
    assert provider._parse_groups({}) == (None, None)


@pytest.mark.parametrize(
    "summary, group",
    [
        ("12th in Big Ten", "Big Ten"),
        ("3rd in NFC North", "NFC North"),
        ("1st in Central Division", "Central Division"),
        ("T-2nd in SEC", "SEC"),
        ("Tied for 4th in ACC", "ACC"),
        ("", None),
        (None, None),
        ("Eliminated", None),
    ],
)
def test_standing_line_names_the_teams_own_group(summary, group):
    assert ESPNProvider._standing_group_name(summary) == group


@pytest.mark.parametrize(
    "name, placeholder",
    [("Conference 5", True), ("Division 80", True), ("Big Ten Conference", False),
     ("Conference USA", False), ("", False), (None, False)],
)
def test_placeholder_detection(name, placeholder):
    # A placeholder is always an id behind the label; "Conference USA" is a name.
    assert is_placeholder_group_name(name) is placeholder


@pytest.fixture
def groups_db(db_conn):
    db_conn.executemany(
        "INSERT INTO provider_group_cache (provider, league, group_key, group_name, "
        "group_abbrev, season, parent_key, parent_name) VALUES ('espn', ?, ?, ?, ?, 2026, ?, ?)",
        [
            ("college-football", "5", "Big Ten Conference", "Big Ten", "80", "FBS"),
            ("college-football", "12", "Conference USA", "CUSA", "80", "FBS"),
            ("college-football", "99", "Conference 99", None, "80", "FBS"),
        ],
    )
    db_conn.commit()
    return db_conn


def test_group_names_come_from_the_cached_tree(groups_db):
    assert get_group_names(groups_db, "college-football", "5") == {
        "name": "Big Ten Conference", "abbrev": "Big Ten", "division": "FBS",
    }
    assert get_group_names(groups_db, "college-football", "12")["name"] == "Conference USA"
    # a cached placeholder is no name at all
    assert get_group_names(groups_db, "college-football", "99") is None
    assert get_group_names(groups_db, "college-football", "404") is None
    assert get_group_names(groups_db, "nfl", "5") is None


def test_service_fills_names_from_the_tree(groups_db, db_factory, monkeypatch):
    monkeypatch.setattr("teamarr.services.sports_data.get_db", db_factory)
    stats = TeamStats(record="3-2", conference="Big Ten", conference_abbrev="Big Ten",
                      conference_id="5", division_id="80")
    filled = SportsDataService._with_group_names(stats, "college-football")
    assert (filled.conference, filled.conference_abbrev, filled.division) == (
        "Big Ten Conference", "Big Ten", "FBS",
    )


def test_service_keeps_the_providers_name_when_the_league_has_no_tree(db_factory, monkeypatch):
    monkeypatch.setattr("teamarr.services.sports_data.get_db", db_factory)
    stats = TeamStats(record="3-2", division="NFC North", conference_id="7", division_id="10")
    assert SportsDataService._with_group_names(stats, "nfl") == stats


def test_stats_cache_keeps_ids_and_drops_old_placeholders():
    stats = TeamStats(record="3-2", conference="Big Ten Conference", conference_abbrev="Big Ten",
                      division="FBS", conference_id="5", division_id="80")
    assert dict_to_stats(stats_to_dict(stats)) == stats
    old = stats_to_dict(TeamStats(record="3-2", conference="Conference 5", division="Division 80"))
    del old["conference_id"], old["division_id"]
    restored = dict_to_stats(old)
    assert (restored.conference, restored.division, restored.conference_id) == (None, None, None)


def _same_conference(ours: TeamStats, theirs: TeamStats) -> bool:
    ctx = TemplateContext(
        game_context=None,
        team_config=TeamChannelContext(team_id="130", league="college-football",
                                       sport="football", team_name="Michigan Wolverines"),
        team_stats=ours,
    )
    game = GameContext(event=None, opponent_stats=theirs)
    return ConditionEvaluator()._eval_is_conference_game(None, ctx, game)


def test_conference_game_compares_ids_not_spellings():
    big_ten = TeamStats(record="3-2", conference="Big Ten Conference", conference_id="5")
    also_big_ten = TeamStats(record="3-2", conference="Big Ten", conference_id="5")
    sec = TeamStats(record="4-1", conference="Big Ten", conference_id="8")
    assert _same_conference(big_ten, also_big_ten) is True
    assert _same_conference(big_ten, sec) is False


def test_conference_game_falls_back_to_names_without_ids():
    assert _same_conference(TeamStats(record="1-0", conference="SEC"),
                            TeamStats(record="1-0", conference="sec")) is True
    assert _same_conference(TeamStats(record="1-0"), TeamStats(record="1-0")) is False
