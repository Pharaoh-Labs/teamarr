"""Corpus-scale measurement of the fixture gate (epic goax, bead goax.1).

The point-fix tests elsewhere in tests/matching/ each pin one historical bug.
This one measures the gate over the whole collision surface, and it is asymmetric
on purpose:

* A **false veto** — refusing a league where the two teams really do play — costs
  the user a channel that should have appeared. Zero tolerance.
* A **missed veto** — failing to reject a cross-league pair — is only a return to
  the old behaviour, where the scoring ladder still gets its say. Measured and
  floored, not required to be perfect.

So `test_no_false_vetoes` asserts an absolute, and `test_crosstalk_rejection_rate`
asserts a floor that ratchets up as the resolver improves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teamarr.consumers.matching.identity import TeamIdentityIndex

CORPUS = Path(__file__).parent / "corpus"


def _load(name: str):
    return json.loads((CORPUS / name).read_text())


@pytest.fixture(scope="module")
def index() -> TeamIdentityIndex:
    rows = [tuple(r) for r in _load("teams.json")]
    return TeamIdentityIndex(rows)


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return _load("cases.json")


@pytest.fixture(scope="module")
def outcomes(index: TeamIdentityIndex, cases: list[dict]) -> list[tuple[dict, set[str] | None]]:
    return [(c, index.fixture_leagues(c["side_a"], c["side_b"])) for c in cases]


def test_corpus_is_present(cases: list[dict], index: TeamIdentityIndex) -> None:
    """Guards against a truncated or unregenerated fixture silently passing."""
    assert len(index) > 1000
    assert sum(1 for c in cases if c["expect"] == "supported") >= 100
    assert sum(1 for c in cases if c["expect"] == "rejected") >= 100


def test_no_false_vetoes(outcomes) -> None:
    """A league where both teams genuinely play must never be refused."""
    failures = [
        f"{c['side_a']} vs {c['side_b']} in {c['league']} -> {sorted(leagues)}"
        for c, leagues in outcomes
        if c["expect"] == "supported" and leagues is not None and c["league"] not in leagues
    ]
    assert not failures, "fixture gate rejected real fixtures:\n" + "\n".join(failures[:20])


def test_crosstalk_rejection_rate(outcomes) -> None:
    """Most same-city cross-league pairs should be refused outright.

    The floor is deliberately below the observed rate so ordinary team-cache
    churn cannot turn this red; raise it when the resolver genuinely improves.
    """
    negatives = [(c, lg) for c, lg in outcomes if c["expect"] == "rejected"]
    rejected = [c for c, lg in negatives if lg is not None and c["league"] not in lg]
    rate = len(rejected) / len(negatives)
    # Measured at 100% (322/322) when this landed; floored at 95% for headroom.
    assert rate >= 0.95, (
        f"crosstalk rejection fell to {rate:.1%} ({len(rejected)}/{len(negatives)})"
    )


@pytest.mark.parametrize(
    ("side_a", "side_b", "league", "expect_rejected", "why"),
    [
        # The two streams from the original report.
        ("Tampa Bay Lightning", "Detroit Red Wings", "mlb", True, "NHL stream on an MLB source"),
        ("Northern Colorado", "Eastern Washington", "mlb", True, "NCAA stream on an MLB source"),
        # ...and the same streams offered to a source that SHOULD take them.
        ("Tampa Bay Lightning", "Detroit Red Wings", "nhl", False, "NHL stream, NHL source"),
        ("Tampa Bay Rays", "Detroit Tigers", "mlb", False, "the legitimate MLB stream"),
        # Ambiguous abbreviations must stay ambiguous — resolvable by EITHER
        # league, so the schedule (i.e. which events exist) decides.
        ("TB", "DET", "mlb", False, "TB/DET reads as Rays/Tigers"),
        ("TB", "DET", "nhl", False, "TB/DET also reads as Lightning/Red Wings"),
        # Scored 92.3 as strings — the worst pair in the pro leagues.
        ("New York Mets", "New York Jets", "mlb", True, "two real teams that never meet"),
        ("Philadelphia 76ers", "Philadelphia Flyers", "nba", True, "86.5 same-city trap"),
        # Regression guards for the fixes this must not undo.
        ("Arizona D-backs", "Colorado Rockies", "mlb", False, "#480 alias must survive"),
        ("SF Giants", "LA Dodgers", "mlb", False, "#569 four-way Giants tie"),
        ("NY Giants", "Dallas Cowboys", "nfl", False, "#569 same tie, NFL reading"),
        ("Los Angeles Angels", "Los Angeles Dodgers", "mlb", False, "both real MLB teams"),
        # #619: partial labels, hijacked codes and bare-city aliases are readings
        # of the pro team too, never a veto against it.
        ("Milwaukee", "New York Mets", "mlb", False, "#619 city-only side (Panthers short_name)"),
        ("Los Angeles Dodgers", "Atlanta", "mlb", False, "#619 bare-city TEAM_ALIASES key"),
        ("Kansas City", "Toronto", "mlb", False, "#619 both sides city-only"),
        ("SEA", "STL", "mlb", False, "#619 code stored as a TSDB short_name"),
        ("UTAH", "WSH", "nba", False, "#619 full name that is another team's city"),
        ("Kansas City", "Toronto", "nhl", True, "#619 ...but no NHL team in Kansas City"),
    ],
)
def test_reported_and_regression_cases(
    index: TeamIdentityIndex, side_a, side_b, league, expect_rejected, why
) -> None:
    leagues = index.fixture_leagues(side_a, side_b)
    rejected = leagues is not None and league not in leagues
    assert rejected is expect_rejected, (
        f"{why}: {side_a} vs {side_b} in {league} -> "
        f"{'rejected' if rejected else 'allowed'} (leagues={leagues})"
    )
