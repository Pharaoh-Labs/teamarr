"""Provider group (conference) cache — #91, epic y5l8.

Covers the DB round-trip, the core-tree walk with $ref parsing, the
conferences API endpoint, and the dynamic-resolver {conference} and
{division} (#717) wildcards.
"""

from unittest.mock import MagicMock

from teamarr.consumers.cache.refresh import CacheRefresher
from teamarr.consumers.lifecycle.dynamic_resolver import DynamicResolver
from teamarr.database.provider_groups import (
    get_league_groups,
    get_team_group,
    save_provider_groups,
)

CFB = "college-football"

SEC = {
    "key": "8",
    "name": "Southeastern Conference",
    "abbrev": "SEC",
    "parent_key": "80",
    "parent_name": "FBS",
    "team_ids": ["2", "57"],
}
B1G = {
    "key": "5",
    "name": "Big Ten Conference",
    "abbrev": "Big Ten",
    "parent_key": "80",
    "parent_name": "FBS",
    "team_ids": ["130"],
}
# A tree cached before #717 carries no parent — {division} must stay silent
MVFC = {"key": "21", "name": "Missouri Valley Football Conference", "team_ids": ["2"]}


# ---------------------------------------------------------------------------
# DB round-trip
# ---------------------------------------------------------------------------


def test_save_and_read_league_groups(db_conn):
    saved = save_provider_groups(db_conn, "espn", CFB, 2026, [SEC, B1G])
    assert saved == 2

    groups = get_league_groups(db_conn, CFB)
    assert [g["name"] for g in groups] == ["Big Ten Conference", "Southeastern Conference"]
    sec = next(g for g in groups if g["key"] == "8")
    assert sec["abbrev"] == "SEC"
    assert sec["team_count"] == 2
    assert set(sec["team_ids"]) == {"2", "57"}


def test_resave_replaces_snapshot(db_conn):
    save_provider_groups(db_conn, "espn", CFB, 2026, [SEC, B1G])
    # Realignment: team 130 moves to the SEC, Big Ten drops out of the tree
    moved = {**SEC, "team_ids": ["2", "57", "130"]}
    save_provider_groups(db_conn, "espn", CFB, 2027, [moved])

    groups = get_league_groups(db_conn, CFB)
    assert len(groups) == 1
    assert groups[0]["team_count"] == 3
    assert get_team_group(db_conn, "espn", CFB, "130")["name"] == "Southeastern Conference"


def test_team_group_lookup(db_conn):
    save_provider_groups(db_conn, "espn", CFB, 2026, [SEC])
    assert get_team_group(db_conn, "espn", CFB, "2") == {
        "name": "Southeastern Conference",
        "abbrev": "SEC",
        "division": "FBS",
    }
    assert get_team_group(db_conn, "espn", CFB, "9999") is None
    assert get_team_group(db_conn, "espn", "mens-college-basketball", "2") is None


def test_unknown_league_returns_empty(db_conn):
    assert get_league_groups(db_conn, "nfl") == []


# ---------------------------------------------------------------------------
# Core-tree walk ($ref parsing)
# ---------------------------------------------------------------------------

BASE = "http://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/2026"


def _fake_client():
    client = MagicMock()
    client.get_season_group_children.return_value = {
        "items": [
            {"$ref": f"{BASE}/types/2/groups/8?lang=en"},
            {"$ref": f"{BASE}/types/2/groups/99?lang=en"},  # non-conference bucket
        ]
    }

    def group_meta(sport, league, season, group_id):
        if group_id == "80":
            return {"id": "80", "name": "FBS", "shortName": "FBS", "isConference": False}
        if group_id == "8":
            return {
                "id": "8",
                "name": "Southeastern Conference",
                "shortName": "SEC",
                "abbreviation": "sec",
                "isConference": True,
            }
        return {"id": "99", "name": "Independents Bucket", "isConference": False}

    client.get_season_group.side_effect = group_meta
    client.get_season_group_teams.return_value = {
        "items": [
            {"$ref": f"{BASE}/teams/2?lang=en&region=us"},
            {"$ref": f"{BASE}/teams/57?lang=en&region=us"},
        ]
    }
    return client


def test_fetch_tree_parses_refs_and_skips_non_conferences():
    groups = CacheRefresher._fetch_conference_tree(
        _fake_client(), "football", "college-football", 2026, ("80",)
    )
    assert len(groups) == 1
    assert groups[0]["key"] == "8"
    assert groups[0]["abbrev"] == "SEC"  # shortName preferred over lowercase abbreviation
    assert groups[0]["team_ids"] == ["2", "57"]
    # Root group tagged onto every child — the {division} source (#717)
    assert groups[0]["parent_key"] == "80"
    assert groups[0]["parent_name"] == "FBS"


def test_fetch_tree_empty_children_yields_no_groups():
    client = MagicMock()
    client.get_season_group_children.return_value = {"items": []}
    groups = CacheRefresher._fetch_conference_tree(
        client, "football", "college-football", 2026, ("80", "81")
    )
    assert groups == []


# ---------------------------------------------------------------------------
# Conferences API endpoint
# ---------------------------------------------------------------------------


def test_conferences_endpoint_shape(db_path, monkeypatch):
    import teamarr.api.routes.cache as cache_routes
    from teamarr.database.connection import get_db

    with get_db(db_path) as conn:
        save_provider_groups(conn, "espn", CFB, 2026, [SEC])
    monkeypatch.setattr(cache_routes, "get_db", lambda: get_db(db_path))

    result = cache_routes.get_league_conferences(CFB)
    assert result[0]["name"] == "Southeastern Conference"
    assert result[0]["team_ids"] == ["2", "57"]
    assert cache_routes.get_league_conferences("nfl") == []


# ---------------------------------------------------------------------------
# {conference} wildcard
# ---------------------------------------------------------------------------


def _resolver_with_cache(db_conn) -> DynamicResolver:
    save_provider_groups(db_conn, "espn", CFB, 2026, [SEC])
    resolver = DynamicResolver()
    resolver._db_conn = db_conn
    return resolver


def _cfb_event(team_id: str):
    home = MagicMock()
    home.id = team_id
    event = MagicMock()
    event.provider = "espn"
    event.league = CFB
    event.home_team = home
    return event


def test_resolve_pattern_replaces_conference():
    resolver = DynamicResolver()
    assert (
        resolver.resolve_pattern(
            "NCAA | {conference}", "football", CFB, "Southeastern Conference"
        )
        == "NCAA | Southeastern Conference"
    )


def test_event_conference_from_home_team(db_conn):
    resolver = _resolver_with_cache(db_conn)
    assert resolver.get_event_conference(_cfb_event("2")) == "Southeastern Conference"
    # Unknown team / non-NCAA league resolves to None (pattern falls back)
    assert resolver.get_event_conference(_cfb_event("9999")) is None
    assert resolver.get_event_conference(None) is None


def test_save_and_read_division(db_conn):
    save_provider_groups(db_conn, "espn", CFB, 2026, [SEC])
    assert get_league_groups(db_conn, CFB)[0]["division"] == "FBS"


def test_division_absent_for_pre_717_rows(db_conn):
    save_provider_groups(db_conn, "espn", CFB, 2026, [MVFC])
    assert get_team_group(db_conn, "espn", CFB, "2")["division"] is None


def test_fetch_tree_survives_missing_root_meta():
    """A root fetch that fails leaves parent_name unset, not the walk broken."""
    client = _fake_client()

    def group_meta(sport, league, season, group_id):
        if group_id == "80":
            return None
        if group_id == "8":
            return {
                "id": "8",
                "name": "Southeastern Conference",
                "shortName": "SEC",
                "isConference": True,
            }
        return {"id": "99", "isConference": False}

    client.get_season_group.side_effect = group_meta
    groups = CacheRefresher._fetch_conference_tree(
        client, "football", "college-football", 2026, ("80",)
    )
    assert len(groups) == 1
    assert groups[0]["parent_name"] is None


# ---------------------------------------------------------------------------
# {division} wildcard (#717)
# ---------------------------------------------------------------------------


def test_resolve_pattern_replaces_division():
    resolver = DynamicResolver()
    resolver._initialized = True
    resolver._league_aliases = {CFB: "NCAAF"}
    assert (
        resolver.resolve_pattern("{league} | {division}", "football", CFB, None, "FBS")
        == "NCAAF | FBS"
    )


def test_event_division_from_home_team(db_conn):
    resolver = _resolver_with_cache(db_conn)
    assert resolver.get_event_division(_cfb_event("2")) == "FBS"
    assert resolver.get_event_division(_cfb_event("9999")) is None
    assert resolver.get_event_division(None) is None


def test_event_division_none_without_parent_data(db_conn):
    """Pre-#717 cache rows defer to the static group rather than invent one."""
    save_provider_groups(db_conn, "espn", CFB, 2026, [MVFC])
    resolver = DynamicResolver()
    resolver._db_conn = db_conn
    event = _cfb_event("2")
    assert resolver.get_event_conference(event) == "Missouri Valley Football Conference"
    assert resolver.get_event_division(event) is None


def test_home_team_group_cached_once(db_conn):
    """Conference and division share one lookup per team."""
    resolver = _resolver_with_cache(db_conn)
    event = _cfb_event("2")
    resolver.get_event_conference(event)
    resolver.get_event_division(event)
    assert len(resolver._group_by_team) == 1


def test_resolve_channel_group_falls_back_when_division_unknown(db_conn):
    """An NFL event under a {division} pattern lands in the static group."""
    resolver = _resolver_with_cache(db_conn)
    resolver._initialized = True
    resolver._groups_loaded = True
    resolver._known_group_ids = {7}
    resolver._league_aliases = {CFB: "NCAAF", "nfl": "NFL"}
    resolver._get_or_create_group = MagicMock(return_value=42)

    nfl_event = _cfb_event("2")
    nfl_event.league = "nfl"
    assert (
        resolver.resolve_channel_group(
            mode="{league} | {division}",
            static_group_id=7,
            event_sport="football",
            event_league="nfl",
            event=nfl_event,
        )
        == 7
    )

    cfb_event = _cfb_event("2")
    assert (
        resolver.resolve_channel_group(
            mode="{league} | {division}",
            static_group_id=7,
            event_sport="football",
            event_league=CFB,
            event=cfb_event,
        )
        == 42
    )
    resolver._get_or_create_group.assert_called_once_with("NCAAF | FBS")
