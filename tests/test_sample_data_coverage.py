"""Coverage guard for template-variable preview sample data.

The template builder's live preview resolves every variable through a precedence
chain (curated SAMPLE_DATA -> inline registry sample -> category auto-default,
see teamarr/templates/sample_data.py). Because the chain always yields a value,
a newly-registered variable is auto-adopted into previews without a separate
edit here. These tests guarantee that property and guard against two
regressions: an unresolved variable, and a niche shape/league leaking another
sport's identity (the old "fall back to the first sport" behavior).

League -> shape resolution is data-driven: it reads each league's real
sport/provider from a freshly initialized database rather than any hardcoded
list, so these tests also exercise resolve_profile_for_league() against the live
schema.
"""

import sqlite3

import pytest

from teamarr.database.connection import init_db
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
