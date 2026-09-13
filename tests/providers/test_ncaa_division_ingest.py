"""Per-league NCAA division opt-out (#811).

ESPN files a game under a division when EITHER side belongs to it, so a
division a user drops costs only the fixtures played entirely inside it —
measured over four 2026 slates, none of the 345 events unique to college
football's group 35 involved a Division I team. The contract under test:
a dropped division is never REQUESTED, everything else keeps the full slate,
and every way the setting can be absent or wrong lands on the full slate too.
"""

import pytest
from fastapi import HTTPException

import teamarr.api.routes.subscription as sub_route
from teamarr.database.subscription import get_league_config, upsert_league_config
from teamarr.providers.espn.client import (
    COLLEGE_SCOREBOARD_GROUPS,
    ESPNClient,
    scoreboard_groups_for_divisions,
)
from teamarr.providers.espn.provider import ESPNProvider

# =============================================================================
# GROUP SELECTION
# =============================================================================


def test_dropping_a_division_drops_only_its_group():
    assert scoreboard_groups_for_divisions("college-football", ["d1"]) == ("90",)
    assert scoreboard_groups_for_divisions("college-football", ["d2d3"]) == ("35",)
    assert scoreboard_groups_for_divisions("mens-college-basketball", ["d1"]) == ("50",)


@pytest.mark.parametrize("divisions", [None, [], ["nonsense"]])
def test_no_usable_selection_keeps_every_group(divisions):
    """None, empty and unrecognised all mean "the full slate" — never nothing."""
    assert scoreboard_groups_for_divisions("college-football", divisions) == ("90", "35")


def test_conference_supplements_are_not_divisions():
    """Volleyball's 110 and lacrosse's 108 are conferences ESPN omits from the
    division slate (United Athletic, Mid-American). They have no division key,
    so no selection can drop them and lose a whole conference's schedule."""
    for league in ("womens-college-volleyball", "womens-college-lacrosse"):
        assert scoreboard_groups_for_divisions(league, ["d1"]) == COLLEGE_SCOREBOARD_GROUPS[league]


def test_league_with_no_groups_is_unaffected():
    assert scoreboard_groups_for_divisions("nfl", ["d1"]) == ()


# =============================================================================
# CLIENT
# =============================================================================


def _client(monkeypatch, responses):
    client = ESPNClient()
    calls = []

    def request(url, params=None):
        calls.append((params or {}).get("groups"))
        return responses.get((params or {}).get("groups"))

    monkeypatch.setattr(client, "_request", request)
    return client, calls


def test_client_requests_only_the_given_groups(monkeypatch):
    client, calls = _client(monkeypatch, {"90": {"events": [{"id": "d1"}]}})

    result = client.get_scoreboard(
        "college-football", "20260912", ("football", "college-football"), ("90",)
    )

    assert calls == ["90"]
    assert [e["id"] for e in result["events"]] == ["d1"]


def test_client_without_groups_keeps_the_full_set(monkeypatch):
    client, calls = _client(
        monkeypatch, {"90": {"events": [{"id": "d1"}]}, "35": {"events": [{"id": "d3"}]}}
    )

    client.get_scoreboard("college-football", "20260912", ("football", "college-football"))

    assert calls == ["90", "35"]


# =============================================================================
# PROVIDER PLUMBING
# =============================================================================


def _provider(monkeypatch, divisions_fn):
    provider = ESPNProvider()
    provider.set_included_divisions_fn(divisions_fn)
    monkeypatch.setattr(
        provider, "_get_sport_league_from_db", lambda league: ("football", "college-football")
    )
    return provider


def test_provider_narrows_the_fetch_to_the_selected_divisions(monkeypatch):
    provider = _provider(monkeypatch, lambda league: ["d1"])
    seen = {}

    def get_scoreboard(league, date_str=None, sport_league=None, groups=None):
        seen["groups"] = groups
        return {"events": []}

    monkeypatch.setattr(provider._client, "get_scoreboard", get_scoreboard)

    provider._scoreboard_events_for("college-football", "20260912", None)

    assert seen["groups"] == ("90",)


@pytest.mark.parametrize(
    "divisions_fn",
    [
        None,
        lambda league: None,
        lambda league: [],
        pytest.param(
            lambda league: (_ for _ in ()).throw(RuntimeError("db down")), id="lookup-raises"
        ),
    ],
)
def test_provider_falls_back_to_the_full_slate(monkeypatch, divisions_fn):
    """No injection, no selection, and a failed lookup are all pre-setting
    behaviour: a preference must never be able to stop a league being fetched."""
    provider = _provider(monkeypatch, divisions_fn)

    assert provider._scoreboard_groups("college-football") is None


def test_provider_ignores_leagues_without_selectable_divisions(monkeypatch):
    provider = _provider(monkeypatch, lambda league: ["d1"])

    assert provider._scoreboard_groups("nfl") is None
    assert provider._scoreboard_groups("womens-college-volleyball") is None


# =============================================================================
# PERSISTENCE
# =============================================================================


def test_selection_round_trips(db_conn):
    upsert_league_config(db_conn, "college-football", included_divisions=["d1"])

    assert get_league_config(db_conn, "college-football").included_divisions == ["d1"]


def test_default_config_has_no_selection(db_conn):
    upsert_league_config(db_conn, "college-football", channel_group_mode="{league} | {division}")

    assert get_league_config(db_conn, "college-football").included_divisions is None


# =============================================================================
# API VALIDATION
# =============================================================================


def test_full_selection_persists_as_no_override():
    """Spelling "everything" as None is what lets a saved selection survive
    ESPN adding a division later."""
    assert sub_route._validate_included_divisions("college-football", ["d1", "d2d3"]) is None


def test_partial_selection_is_kept_in_catalog_order():
    assert sub_route._validate_included_divisions("college-football", ["d2d3"]) == ["d2d3"]


@pytest.mark.parametrize(
    ("league", "divisions"),
    [
        ("college-football", []),
        ("college-football", ["d1", "d4"]),
        ("nfl", ["d1"]),
    ],
)
def test_invalid_selections_are_refused(league, divisions):
    with pytest.raises(HTTPException) as exc:
        sub_route._validate_included_divisions(league, divisions)
    assert exc.value.status_code == 400


def test_division_catalog_lists_football_and_both_basketballs():
    catalog = sub_route.list_league_divisions().divisions

    assert set(catalog) == {
        "college-football",
        "mens-college-basketball",
        "womens-college-basketball",
    }
    assert [d.key for d in catalog["college-football"]] == ["d1", "d2d3"]
    assert catalog["college-football"][1].label == "Division II & III"
