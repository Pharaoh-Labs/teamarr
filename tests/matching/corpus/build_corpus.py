"""Regenerate the matching regression corpus from a live Teamarr database.

NOT run by CI — this is provenance. The committed `teams.json` / `cases.json`
are the test inputs; this script records exactly how they were produced so they
can be rebuilt or extended when the collision surface changes.

    python tests/matching/corpus/build_corpus.py data/teamarr.db

Why a corpus exists at all (epic goax, bead goax.1): before it, every matcher
change was a blind tune. There were 337 matching tests and essentially every one
pinned a single past bug (#472 short codes, #480 D-backs, #569 shared
nicknames), so the only question we could answer was "did the cases I already
know about still pass?" — never "did precision go up?". Crucially, not one test
asserted that a cross-sport stream must NOT match, which is why a whole class of
false positives shipped unnoticed.

The negative cases are generated, not hand-picked. Any two teams sharing a city
across two leagues are a latent false positive, and there are far more of them
than anyone would think to enumerate: among the six major North American pro
leagues alone, 161 cross-league pairs score >= BOTH_TEAMS_THRESHOLD on name
similarity, topped by "New York Mets" / "New York Jets" at 92.3.
"""

from __future__ import annotations

import itertools
import json
import sqlite3
import sys
from pathlib import Path

from rapidfuzz import fuzz

from teamarr.consumers.matching.constants import BOTH_TEAMS_THRESHOLD
from teamarr.utilities.fuzzy_match import normalize_text

HERE = Path(__file__).parent

# Leagues held in the snapshot. Chosen for collision density rather than
# popularity: the six North American pro leagues supply the same-city crosstalk,
# and the college leagues supply the "Northern Colorado" / "Colorado Rockies"
# qualifier crosstalk — including college-baseball, which shares MLB's sport and
# so cannot be dismissed by a sport-level check.
SNAPSHOT_LEAGUES = (
    "mlb",
    "nhl",
    "nba",
    "nfl",
    "wnba",
    "college-football",
    "mens-college-basketball",
    "college-baseball",
    "eng.1",
    "uefa.champions",
)

PRO_LEAGUES = ("mlb", "nhl", "nba", "nfl", "wnba")


def build_teams(conn: sqlite3.Connection) -> list[list[str | None]]:
    placeholders = ",".join("?" * len(SNAPSHOT_LEAGUES))
    rows = conn.execute(
        f"""
        SELECT DISTINCT team_name, team_short_name, team_abbrev, league, sport
        FROM team_cache
        WHERE league IN ({placeholders}) AND team_name IS NOT NULL AND team_name != ''
        ORDER BY league, team_name
        """,
        SNAPSHOT_LEAGUES,
    ).fetchall()
    return [list(r) for r in rows]


def build_cases(teams: list[list[str | None]]) -> list[dict]:
    """Label the corpus: which league(s) may a two-sided stream name resolve to?

    `expect_supported` is the league a matcher would be right to consider;
    `expect_rejected` is one it must refuse. Both are derived from real team
    membership, so the labels cannot drift from the data.
    """
    by_league: dict[str, list[str]] = {}
    for name, _short, _abbrev, league, _sport in teams:
        by_league.setdefault(league, []).append(name)

    cases: list[dict] = []

    # POSITIVES: two teams that really do share a league must stay matchable.
    # Sampled rather than exhaustive — 755 college-football teams would give
    # 284k pairs and swamp the negatives.
    for league in PRO_LEAGUES:
        names = sorted(by_league.get(league, []))
        for a, b in itertools.islice(itertools.combinations(names, 2), 40):
            cases.append(
                {"side_a": a, "side_b": b, "league": league, "expect": "supported",
                 "tag": f"real fixture in {league}"}
            )

    # NEGATIVES: same-city teams from different leagues. These are exactly the
    # pairs the old scorer accepted, so each one is a shipped-bug candidate.
    pro_teams = [
        (name, league) for name, _s, _a, league, _sp in teams if league in PRO_LEAGUES
    ]
    for (n1, l1), (n2, l2) in itertools.combinations(pro_teams, 2):
        if l1 == l2:
            continue
        if fuzz.token_set_ratio(normalize_text(n1), normalize_text(n2)) < BOTH_TEAMS_THRESHOLD:
            continue
        # n1 and n2 never meet, so BOTH leagues must be refused.
        for league in (l1, l2):
            cases.append(
                {"side_a": n1, "side_b": n2, "league": league, "expect": "rejected",
                 "tag": f"cross-league crosstalk {l1}/{l2}"}
            )

    return cases


def main() -> None:
    db = sys.argv[1] if len(sys.argv) > 1 else "data/teamarr.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    teams = build_teams(conn)
    cases = build_cases(teams)

    (HERE / "teams.json").write_text(json.dumps(teams, separators=(",", ":")))
    (HERE / "cases.json").write_text(json.dumps(cases, indent=0, separators=(",", ":")))

    supported = sum(1 for c in cases if c["expect"] == "supported")
    print(f"teams.json: {len(teams)} rows")
    print(
        f"cases.json: {len(cases)} cases "
        f"({supported} supported, {len(cases) - supported} rejected)"
    )


if __name__ == "__main__":
    main()
