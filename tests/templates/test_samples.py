"""Template live-preview sample system: shapes, coverage guard, event selection.

Every league previews against one of three generic, FICTITIOUS shapes
("team" / "combat" / "racing") so a sample never looks like a real (and likely
wrong-league) game — epic gruy .1/.2. The template builder's live preview
resolves every variable through a precedence chain (curated SAMPLE_DATA ->
inline registry sample -> category auto-default, see
teamarr/templates/sample_data.py); because the chain always yields a value, a
newly-registered variable is auto-adopted into previews without a separate edit
here.

League -> shape resolution is data-driven: it reads each league's real
sport/provider from a freshly initialized database rather than any hardcoded
list, so the coverage tests also exercise resolve_profile_for_league() against
the live schema.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from teamarr.core import Event, EventStatus, Team
from teamarr.database.connection import init_db
from teamarr.services.sports_data import SportsDataService
from teamarr.templates.sample_data import (
    AVAILABLE_SPORTS,
    get_all_sample_data,
    get_all_sample_data_for_league,
    resolve_profile_for_league,
    resolve_shape,
)
from teamarr.templates.variables import SuffixRules, get_registry

# The three generic sample shapes every league resolves to.
SHAPES = ("team", "combat", "racing")


# ---------------------------------------------------------------------------
# Sport -> shape mapping and fictitious identities
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Coverage guard: every registered variable resolves for every shape/league.
# Guards two regressions: an unresolved variable, and a niche shape/league
# leaking another sport's identity (the old "fall back to the first sport"
# behavior).
# ---------------------------------------------------------------------------


def _registered_variable_names() -> list[str]:
    """All registered variable names, expanded with their supported suffixes."""
    names: list[str] = []
    for var in get_registry().all_variables():
        names.append(var.name)
        if var.suffix_rules in (SuffixRules.ALL, SuffixRules.BASE_NEXT_ONLY):
            names.append(f"{var.name}.next")
        if var.suffix_rules == SuffixRules.ALL:
            names.append(f"{var.name}.last")
    return names


@pytest.fixture(scope="module")
def league_records(tmp_path_factory) -> list[tuple[str, str, str]]:
    """(code, provider, sport) for every league in a freshly seeded database."""
    db_path = tmp_path_factory.mktemp("samples") / "fresh.db"
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT league_code, provider, sport FROM leagues"
        ).fetchall()
    finally:
        conn.close()
    return [(r["league_code"], r["provider"], r["sport"]) for r in rows]


def test_every_variable_resolves_for_every_shape():
    """Every registered variable (and suffix) resolves for each shape.

    Some variables legitimately resolve to an empty string (e.g. no national
    broadcast, pre-game scores); the guarantee is that the name is present and
    never renders as its raw ``{name}`` literal in the preview.
    """
    names = _registered_variable_names()
    for shape in SHAPES:
        samples = get_all_sample_data(shape)
        for name in names:
            assert name in samples, f"{name!r} unresolved for shape {shape!r}"


def test_every_variable_resolves_for_every_base_profile():
    """Every registered variable resolves for each shape-base profile.

    The ``sport=`` query param selects a base profile (NBA/UFC/F1) directly;
    guard that path stays fully covered too.
    """
    names = _registered_variable_names()
    for profile in AVAILABLE_SPORTS:
        samples = get_all_sample_data(profile)
        for name in names:
            assert name in samples, f"{name!r} unresolved for profile {profile!r}"


def test_no_identity_leak_across_shapes():
    """Combat/racing shapes must not show the team shape's identity."""
    team = get_all_sample_data("team")
    for shape in ("combat", "racing"):
        samples = get_all_sample_data(shape)
        for var in ("team_name", "opponent", "team_short"):
            assert samples.get(var) != team.get(var), (
                f"shape {shape!r} leaks team {var!r}={team.get(var)!r}"
            )


def test_team_shape_uses_fictitious_identity():
    """The team shape previews against a fictitious team, never a real one."""
    blob = " ".join(str(v) for v in get_all_sample_data("team").values())
    for real in ("Pistons", "Detroit", "Lakers"):
        assert real not in blob, f"team shape leaks real-team token {real!r}"


def test_every_league_resolves_to_a_known_shape(league_records):
    """Every league resolves (from its sport/provider) to a known shape.

    Driven by the live DB, so a newly-added league can't slip through without a
    sport mapping, and every variable still resolves for it.
    """
    names = _registered_variable_names()
    for code, provider, sport in league_records:
        shape = resolve_profile_for_league(code, sport, provider)
        assert shape in SHAPES, (
            f"league {code!r} (sport={sport!r}) resolved to unknown shape {shape!r}"
        )
        samples = get_all_sample_data_for_league(code, sport, provider)
        for name in names:
            assert name in samples, f"{name!r} unresolved for league {code!r}"


def test_resolve_shape_covers_combat_and_racing(league_records):
    """At least one league exercises each non-default shape.

    Guards against a regression where every league collapses onto "team" (which
    would silently break combat/racing previews).
    """
    shapes_seen = {
        resolve_shape(sport) for _code, _provider, sport in league_records
    }
    assert "combat" in shapes_seen, "no league resolves to the combat shape"
    assert "racing" in shapes_seen, "no league resolves to the racing shape"


# ---------------------------------------------------------------------------
# Sample-event selection (live preview event pick).
# The rule applies to ALL providers: prefer the most-recent FINAL game with two
# teams (so postgame vars populate), else the nearest upcoming/in-progress game.
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)


def _team(name: str) -> Team:
    return Team(
        id=name, provider="espn", name=name, short_name=name,
        abbreviation=name[:3].upper(), league="nba", sport="basketball",
    )


def _sample_event(eid: str, start: datetime, state: str, *, away: bool = True) -> Event:
    return Event(
        id=eid, provider="espn", name=eid, short_name=eid, start_time=start,
        home_team=_team("Home_" + eid),
        away_team=_team("Away_" + eid) if away else None,  # type: ignore[arg-type]
        status=EventStatus(state=state), league="nba", sport="basketball",
    )


class _FakeProvider:
    """Provider exposing the bulk candidate path (like TSDB)."""

    def __init__(self, events):
        self._events = events

    def supports_league(self, league):
        return True

    def get_sample_candidates(self, league):
        return self._events


def _svc(events):
    return SportsDataService([_FakeProvider(events)])


def test_prefers_most_recent_final():
    old_final = _sample_event("old", NOW - timedelta(days=5), "final")
    recent_final = _sample_event("recent", NOW - timedelta(hours=3), "final")
    upcoming = _sample_event("up", NOW + timedelta(days=1), "scheduled")
    ev = _svc([upcoming, old_final, recent_final]).get_sample_event("nba")
    assert ev is not None and ev.id == "recent"


def test_falls_back_to_nearest_upcoming_when_no_final():
    soon = _sample_event("soon", NOW + timedelta(hours=2), "scheduled")
    far = _sample_event("far", NOW + timedelta(days=10), "scheduled")
    ev = _svc([far, soon]).get_sample_event("nba")
    assert ev is not None and ev.id == "soon"


def test_ignores_events_missing_a_team():
    no_away = _sample_event("noaway", NOW - timedelta(hours=1), "final", away=False)
    real = _sample_event("real", NOW - timedelta(days=2), "final")
    ev = _svc([no_away, real]).get_sample_event("nba")
    assert ev is not None and ev.id == "real"


def test_none_when_no_candidates():
    assert _svc([]).get_sample_event("nba") is None


class _OffseasonProvider:
    """No finals in the slate (only upcoming), but a deep look-back finds the
    last completed game — like NFL in June returning the Super Bowl."""

    def __init__(self, upcoming, deep_final):
        self._upcoming = upcoming
        self._deep = deep_final

    def supports_league(self, league):
        return True

    def get_sample_candidates(self, league):
        return self._upcoming

    def get_recent_final(self, league):
        return self._deep


def test_deep_lookback_used_when_no_recent_final():
    upcoming = _sample_event("preseason", NOW + timedelta(days=60), "scheduled")  # 0-0 upcoming
    super_bowl = _sample_event("superbowl", NOW - timedelta(days=130), "final")
    svc = SportsDataService([_OffseasonProvider([upcoming], super_bowl)])
    ev = svc.get_sample_event("nfl")
    assert ev is not None and ev.id == "superbowl"  # prefers the real final over empty upcoming


def test_recent_final_beats_deep_lookback():
    # When the slate already has a final, don't bother with the look-back.
    recent = _sample_event("recent", NOW - timedelta(hours=2), "final")
    old = _sample_event("old", NOW - timedelta(days=200), "final")
    svc = SportsDataService([_OffseasonProvider([recent], old)])
    assert svc.get_sample_event("nfl").id == "recent"
