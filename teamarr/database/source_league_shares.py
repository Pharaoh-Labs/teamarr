"""Which leagues each source's matched streams resolved to (#1110).

Read from the last generation run's per-stream match details
(``epg_matched_streams``): for every source, the distinct streams it matched
per league. The share is that league's count over the source's matched
streams — matched, never the source's total stream count — so a 100% chip
means "everything this source matched was this league", whatever its
coverage. One run is a snapshot (an EPL source reads as Champions League on
a Champions League night); the maintainer chose the last run over a window
so the chips say what the most recent run saw, and the run timestamp rides
along so the reader knows when that was.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from sqlite3 import Connection


@dataclass(frozen=True)
class LeagueShare:
    league: str
    display_name: str
    sport: str
    sport_display_name: str
    count: int
    share: float

    def to_dict(self) -> dict:
        return {
            "league": self.league,
            "display_name": self.display_name,
            "sport": self.sport,
            "sport_display_name": self.sport_display_name,
            "count": self.count,
            "share": self.share,
        }


def _league_names(conn: Connection) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """(league -> display name, league -> sport, sport -> display name)."""
    names: dict[str, str] = {}
    sports: dict[str, str] = {}
    for row in conn.execute("SELECT league_slug, league_name, sport FROM league_cache"):
        if row["league_name"]:
            names[row["league_slug"]] = row["league_name"]
        if row["sport"]:
            sports[row["league_slug"]] = row["sport"]
    # Configured leagues win, labelled the way {league} is: the short alias
    # when there is one ("NHL", "UCL"), else the display name.
    for row in conn.execute("SELECT league_code, display_name, league_alias, sport FROM leagues"):
        label = row["league_alias"] or row["display_name"]
        if label:
            names[row["league_code"]] = label
        if row["sport"]:
            sports[row["league_code"]] = row["sport"]
    sport_names: dict[str, str] = {}
    for row in conn.execute("SELECT sport_code, display_name FROM sports"):
        if row["display_name"]:
            sport_names[row["sport_code"]] = row["display_name"]
    return names, sports, sport_names


def get_group_league_shares(conn: Connection) -> tuple[str | None, dict[int, list[LeagueShare]]]:
    """``(run_timestamp, {group_id: [LeagueShare, ...] by share desc})``.

    The run is the latest one that recorded any match detail; a source absent
    from the result matched nothing in it. Excluded matches (wrong date,
    league not included) do not count: they never reached a channel.
    """
    run = conn.execute("SELECT MAX(run_id) AS r FROM epg_matched_streams").fetchone()
    run_id = run["r"] if run else None
    if run_id is None:
        return None, {}
    stamp = conn.execute(
        "SELECT COALESCE(completed_at, started_at) AS at FROM processing_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    run_at = stamp["at"] if stamp else None

    rows = conn.execute(
        """SELECT group_id, detected_league, COUNT(DISTINCT stream_id) AS n
           FROM epg_matched_streams
           WHERE run_id = ? AND exclusion_reason IS NULL AND detected_league IS NOT NULL
           GROUP BY group_id, detected_league""",
        (run_id,),
    ).fetchall()
    if not rows:
        return run_at, {}

    names, sports, sport_names = _league_names(conn)
    counts: dict[int, dict[str, int]] = defaultdict(dict)
    for r in rows:
        counts[r["group_id"]][r["detected_league"]] = r["n"]

    result: dict[int, list[LeagueShare]] = {}
    for group_id, per_league in counts.items():
        total = sum(per_league.values())
        shares = []
        for league, n in per_league.items():
            sport = sports.get(league, "")
            shares.append(
                LeagueShare(
                    league=league,
                    display_name=names.get(league, league),
                    sport=sport,
                    sport_display_name=sport_names.get(sport, sport.title() if sport else ""),
                    count=n,
                    share=round(n / total, 3),
                )
            )
        shares.sort(key=lambda s: (-s.count, s.league))
        result[group_id] = shares
    return run_at, result
