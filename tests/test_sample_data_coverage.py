"""Coverage guard for template-variable preview sample data.

The template builder's live preview resolves every variable through a precedence
chain (curated SAMPLE_DATA -> inline registry sample -> category auto-default,
see teamarr/templates/sample_data.py). Because the chain always yields a value,
a newly-registered variable is auto-adopted into previews without a separate
edit here. These tests guarantee that property and guard against two
regressions: an unresolved variable, and a niche profile/league leaking another
sport's identity (the old "fall back to the first sport" behavior).
"""

import re
from pathlib import Path

from teamarr.templates.sample_data import (
    AVAILABLE_SPORTS,
    get_all_sample_data,
    get_all_sample_data_for_league,
    resolve_profile_for_league,
)
from teamarr.templates.variables import SuffixRules, get_registry

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "teamarr/database/schema.sql"


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


def _schema_league_codes() -> list[str]:
    """League codes from schema.sql's leagues INSERT block."""
    text = _SCHEMA_PATH.read_text()
    block = re.search(
        r"INSERT OR REPLACE INTO leagues.*?VALUES(.*?);", text, re.S
    )
    assert block, "Could not locate leagues INSERT block in schema.sql"
    return re.findall(r"^\s*\('([a-z0-9._-]+)',", block.group(1), re.M)


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


def test_every_schema_league_resolves_to_a_known_profile():
    """Every league in schema.sql maps to a real profile and resolves samples."""
    names = _registered_variable_names()
    for code in _schema_league_codes():
        profile = resolve_profile_for_league(code)
        assert profile in AVAILABLE_SPORTS, (
            f"league {code!r} resolved to unknown profile {profile!r}"
        )
        samples = get_all_sample_data_for_league(code)
        for name in names:
            assert name in samples, f"{name!r} unresolved for league {code!r}"


def test_report_leagues_on_generic_fallback(capsys):
    """Soft, non-failing report of leagues using the generic NBA fallback.

    Surfaces curation gaps (a new league whose sport-derived profile is wrong)
    without blocking merges. Always passes.
    """
    from teamarr.templates.sample_data import LEAGUE_SAMPLE_PROFILES
    from teamarr.utilities.sports import get_sport_from_league

    flagged = [
        code
        for code in _schema_league_codes()
        if code not in LEAGUE_SAMPLE_PROFILES
        and resolve_profile_for_league(code) == "NBA"
        and get_sport_from_league(code) == "Sports"
    ]
    if flagged:
        with capsys.disabled():
            print(
                "\n[sample-data] leagues on generic NBA fallback "
                f"(consider LEAGUE_SAMPLE_PROFILES): {flagged}"
            )
