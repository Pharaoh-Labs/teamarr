"""Provider group (conference/division) cache access (#91, epic y5l8).

Stores the ESPN core-API season tree's conference groups and their team
membership, refreshed alongside the team cache. Read paths serve the Team
Importer's conference filter and the dynamic channel-group ``{conference}``
wildcard. Framed generically as provider groups so pro divisions can share
the tables later.
"""

import logging
from sqlite3 import Connection

logger = logging.getLogger(__name__)


def save_provider_groups(
    conn: Connection,
    provider: str,
    league: str,
    season: int,
    groups: list[dict],
) -> int:
    """Replace a league's cached groups with a fresh tree snapshot.

    Args:
        groups: [{"key", "name", "abbrev", "team_ids": [...]}, ...]

    Returns:
        Number of groups saved.
    """
    conn.execute(
        "DELETE FROM provider_group_members WHERE group_cache_id IN "
        "(SELECT id FROM provider_group_cache WHERE provider = ? AND league = ?)",
        (provider, league),
    )
    conn.execute(
        "DELETE FROM provider_group_cache WHERE provider = ? AND league = ?",
        (provider, league),
    )
    for group in groups:
        cursor = conn.execute(
            """INSERT INTO provider_group_cache
               (provider, league, group_key, group_name, group_abbrev, season)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (provider, league, group["key"], group["name"], group.get("abbrev"), season),
        )
        group_cache_id = cursor.lastrowid
        conn.executemany(
            "INSERT OR IGNORE INTO provider_group_members "
            "(group_cache_id, provider_team_id) VALUES (?, ?)",
            [(group_cache_id, team_id) for team_id in group.get("team_ids", [])],
        )
    conn.commit()
    return len(groups)


def get_league_groups(conn: Connection, league: str) -> list[dict]:
    """A league's cached groups with member team ids, alphabetical.

    Returns [] for leagues with no cached tree (the UI hides the filter).
    """
    rows = conn.execute(
        """SELECT g.id, g.group_key, g.group_name, g.group_abbrev, g.season
           FROM provider_group_cache g
           WHERE g.league = ?
           ORDER BY g.group_name""",
        (league,),
    ).fetchall()
    groups = []
    for row in rows:
        member_rows = conn.execute(
            "SELECT provider_team_id FROM provider_group_members WHERE group_cache_id = ?",
            (row["id"],),
        ).fetchall()
        groups.append(
            {
                "key": row["group_key"],
                "name": row["group_name"],
                "abbrev": row["group_abbrev"],
                "season": row["season"],
                "team_ids": [m["provider_team_id"] for m in member_rows],
                "team_count": len(member_rows),
            }
        )
    return groups


def get_team_group(
    conn: Connection, provider: str, league: str, provider_team_id: str
) -> dict | None:
    """The group (conference) a team belongs to in a league, or None."""
    row = conn.execute(
        """SELECT g.group_name, g.group_abbrev
           FROM provider_group_cache g
           JOIN provider_group_members m ON m.group_cache_id = g.id
           WHERE g.provider = ? AND g.league = ? AND m.provider_team_id = ?""",
        (provider, league, provider_team_id),
    ).fetchone()
    if row is None:
        return None
    return {"name": row["group_name"], "abbrev": row["group_abbrev"]}
