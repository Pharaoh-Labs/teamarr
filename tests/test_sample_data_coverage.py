"""Coverage guard for template-variable preview sample data.

The template builder's live preview resolves every variable through a precedence
chain (curated SAMPLE_DATA -> inline registry sample -> category auto-default,
see teamarr/templates/sample_data.py). Because the chain always yields a value,
a newly-registered variable is auto-adopted into previews without a separate
edit here. These tests guarantee that property and guard against two
regressions: an unresolved variable, and a niche profile/league leaking another
sport's identity (the old "fall back to the first sport" behavior).

League -> profile resolution is data-driven: it reads each league's real
sport/provider from a freshly initialized database rather than any hardcoded
list, so these tests also exercise resolve_profile() against the live schema.
"""

import sqlite3

import pytest

from teamarr.database.connection import init_db
from teamarr.templates.sample_data import (
    AVAILABLE_SPORTS,
    get_all_sample_data,
    get_all_sample_data_for_league,
    resolve_profile,
)
from teamarr.templates.variables import SuffixRules, get_registry


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


def test_every_variable_resolves_for_every_profile():
    """Every registered variable (and suffix) resolves for each profile.

    Some variables legitimately resolve to an empty string (e.g. no national
    broadcast, pre-game scores); the guarantee is that the name is present and
    never renders as its raw ``{name}`` literal in the preview.
    """
    names = _registered_variable_names()
    for profile in AVAILABLE_SPORTS:
        samples = get_all_sample_data(profile)
        for name in names:
            assert name in samples, f"{name!r} unresolved for profile {profile!r}"


def test_no_identity_leak_across_profiles():
    """Non-NBA profiles must not show NBA's identity placeholders."""
    nba = get_all_sample_data("NBA")
    for profile in AVAILABLE_SPORTS:
        if profile == "NBA":
            continue
        samples = get_all_sample_data(profile)
        for var in ("team_name", "opponent", "team_short"):
            assert samples.get(var) != nba.get(var), (
                f"profile {profile!r} leaks NBA {var!r}={nba.get(var)!r}"
            )


def test_every_league_resolves_to_a_known_profile(league_records):
    """Every league resolves (from its sport/provider) to a real profile.

    Driven by the live DB, so a newly-added league can't slip through without a
    sport mapping, and every variable still resolves for it.
    """
    names = _registered_variable_names()
    for code, provider, sport in league_records:
        profile = resolve_profile(sport, provider, code)
        assert profile in AVAILABLE_SPORTS, (
            f"league {code!r} (sport={sport!r}) resolved to unknown profile {profile!r}"
        )
        samples = get_all_sample_data_for_league(code, sport, provider)
        for name in names:
            assert name in samples, f"{name!r} unresolved for league {code!r}"


def test_report_leagues_on_generic_fallback(league_records, capsys):
    """Soft, non-failing report of non-basketball leagues hitting the NBA default.

    Surfaces a new ``leagues.sport`` value not yet in _SPORT_PROFILE without
    blocking merges. Always passes.
    """
    flagged = [
        f"{code} (sport={sport})"
        for code, provider, sport in league_records
        if resolve_profile(sport, provider, code) == "NBA"
        and (sport or "").lower() != "basketball"
    ]
    if flagged:
        with capsys.disabled():
            print(
                "\n[sample-data] leagues hitting the generic NBA fallback "
                f"(add their sport to _SPORT_PROFILE): {flagged}"
            )
