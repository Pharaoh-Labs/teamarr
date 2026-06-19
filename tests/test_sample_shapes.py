"""Tests for the 3-shape sample-data system (epic gruy .1/.2).

Every league previews against one of three generic, FICTITIOUS shapes
("team" / "combat" / "racing") so a sample never looks like a real (and likely
wrong-league) game. These tests pin the sport->shape mapping and assert the
funny placeholder identities surface for representative leagues of each shape.
"""

import pytest

from teamarr.templates.sample_data import (
    get_all_sample_data_for_league,
    resolve_shape,
)


@pytest.mark.parametrize(
    "sport,expected",
    [
        ("basketball", "team"),
        ("hockey", "team"),
        ("football", "team"),
        ("soccer", "team"),
        ("baseball", "team"),
        ("mma", "combat"),
        ("boxing", "combat"),
        ("racing", "racing"),
        ("", "team"),
        (None, "team"),
        ("UNKNOWN", "team"),
    ],
)
def test_resolve_shape(sport, expected):
    assert resolve_shape(sport) == expected


def test_team_shape_uses_funny_identities():
    """Team-sport leagues (incl. soccer) preview the fictitious team identity."""
    for code, sport in [
        ("nba", "basketball"),
        ("nhl", "hockey"),
        ("usa.nwsl", "soccer"),
    ]:
        data = get_all_sample_data_for_league(code, sport)
        assert data["home_team"] == "Flint Tropics"
        assert data["team_name"] == "Flint Tropics"
        assert data["opponent"] == "Greenwich Mean Time"
        assert data["league"] == "Placeholder Premier League"
        assert data["league_abbrev"] == "PPL"
        assert data["venue"] == "The Coconut Coliseum"


def test_team_shape_carries_both_pro_and_college_fields():
    """One shape must fill BOTH pro (conference) AND college (rank) identity so
    pro and college templates both render — no real league has both."""
    data = get_all_sample_data_for_league("nba", "basketball")
    assert data["pro_conference"]  # non-empty pro-style field
    assert data["pro_division"]
    assert data["team_rank"]  # non-empty college/AP-style field
    assert data["college_conference"]


def test_combat_shape_uses_funny_fighters():
    data = get_all_sample_data_for_league("ufc", "mma")
    assert data["fighter1"] == "Little Mac"
    assert data["fighter2"] == "Super Macho Man"
    assert data["league"] == "World Video Boxing Association"
    assert data["venue"] == "Madison Square Pixels"


def test_racing_shape_uses_funny_drivers():
    data = get_all_sample_data_for_league("f1", "racing")
    assert data["race_winner"] == "Ricky Bobby"
    assert data["pole_position"] == "Lightning McQueen"
    assert data["circuit_name"] == "Radiator Springs Speedway"
    assert data["league"] == "Piston Cup Series"
    assert data["league_abbrev"] == "PCS"


def test_team_shape_has_no_real_team_leak():
    """Regression guard: no real franchise/RSN may bleed into the fictitious
    team shape. A substring-replace bug once leaked 'Detroit Pistons' into the
    .next/.last matchups when the override keys got corrupted."""
    blob = " ".join(str(v) for v in get_all_sample_data_for_league("nba", "basketball").values())
    for token in ("Pistons", "Bucks", "Cavaliers", "Lakers", "Bulls",
                  "Detroit", "Milwaukee", "Cleveland", "Bally Sports"):
        assert token not in blob, f"real-team leak in team sample: {token!r}"


def test_live_preview_surfaces_gaps(monkeypatch):
    """In live mode a variable the real event can't fill is surfaced as a gap
    (empty + listed in `gaps`), NOT masked with the fictitious sample, so the
    preview doesn't imply a variable populates when it won't."""
    from teamarr.api.routes import variables as v

    monkeypatch.setattr(v, "_lookup_league_fields", lambda league: ("basketball", "espn"))
    monkeypatch.setattr(
        v, "_fetch_live_samples",
        lambda league: {"home_team": "Real Live Team", "score": "10-7"},
    )
    resp = v.get_sample_data(league="nba", live=True)

    assert resp["live"] is True
    s = resp["samples"]
    assert s["home_team"] == "Real Live Team"  # live value wins
    assert s["score"] == "10-7"
    # A RELEVANT team var the live event didn't provide → surfaced gap (not sample)
    assert s["venue"] == ""
    assert "venue" in resp["gaps"]
    assert "home_team" not in resp["gaps"]
    # A cross-sport var (combat) is N/A for basketball — empty, but NOT a gap and
    # NOT counted toward coverage (option B: only relevant gaps surface).
    assert s["fighter1"] == ""
    assert "fighter1" not in resp["gaps"]
    assert resp["live_populated"] == 2
    assert resp["live_total"] < len(s)  # only relevant vars counted, not all 470


def test_static_preview_has_no_gaps():
    """Without live, every variable is filled by the shape sample (no gaps)."""
    from teamarr.api.routes import variables as v

    resp = v.get_sample_data(sport="NBA", live=False)
    assert resp["live"] is False
    assert resp["gaps"] == []
    assert resp["live_populated"] is None


@pytest.mark.parametrize(
    "code,sport,must_fill",
    [
        ("nba", "basketball", ["home_team", "away_team", "score", "team_record",
                               "team_rank", "pro_conference", "college_conference",
                               "venue", "streak"]),
        ("ufc", "mma", ["fighter1", "fighter2", "weight_class", "fight_card",
                        "event_title", "venue"]),
        ("f1", "racing", ["race_winner", "pole_position", "circuit_name",
                          "podium", "grid", "venue"]),
    ],
)
def test_each_shape_fills_its_native_variables(code, sport, must_fill):
    """Kitchen-sink coverage: each shape fills its native variables, so a
    template of that kind previews with no blanks where data should exist."""
    data = get_all_sample_data_for_league(code, sport)
    for var in must_fill:
        assert data.get(var), f"{code}/{sport} shape left {var!r} empty"
