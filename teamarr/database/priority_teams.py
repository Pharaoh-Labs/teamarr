"""Channel priority-teams queries.

A priority team floats its channels to the top of the global channel list,
ahead of all sport/league/time ordering (see ``channel_numbers.get_all_channels_sorted``).
This is purely an ordering preference and has no connection to the Teams page
or EPG generation. Identity comes from ``team_cache``; channels are matched by
``(sport, team_name)`` against ``managed_channels.home_team``/``away_team``.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def get_priority_teams(conn: sqlite3.Connection) -> list[dict]:
    """Return all configured priority teams, newest first."""
    cursor = conn.execute(
        """
        SELECT id, provider, provider_team_id, team_name, league, sport
        FROM channel_priority_teams
        ORDER BY sport, team_name
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def add_priority_team(
    conn: sqlite3.Connection,
    *,
    provider: str,
    provider_team_id: str,
    league: str | None,
) -> dict | None:
    """Add a priority team, resolving its name + sport from ``team_cache``.

    The frontend sends only ``(provider, team_id, league)`` (a ``TeamFilterEntry``);
    we enrich from the cache so the match key and display name stay canonical.
    Returns the stored row, or ``None`` if the team isn't in ``team_cache``.
    Idempotent on ``(provider, provider_team_id, league)``.
    """
    lookup = conn.execute(
        """
        SELECT team_name, sport FROM team_cache
        WHERE provider = ? AND provider_team_id = ?
          AND (league = ? OR ? IS NULL)
        LIMIT 1
        """,
        (provider, provider_team_id, league, league),
    ).fetchone()
    if lookup is None:
        logger.warning(
            "[PRIORITY_TEAMS] No team_cache row for provider=%s team_id=%s league=%s",
            provider,
            provider_team_id,
            league,
        )
        return None

    conn.execute(
        """
        INSERT INTO channel_priority_teams
            (provider, provider_team_id, team_name, league, sport)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(provider, provider_team_id, league) DO UPDATE SET
            team_name = excluded.team_name,
            sport = excluded.sport
        """,
        (provider, provider_team_id, lookup["team_name"], league, lookup["sport"]),
    )
    row = conn.execute(
        """
        SELECT id, provider, provider_team_id, team_name, league, sport
        FROM channel_priority_teams
        WHERE provider = ? AND provider_team_id = ? AND (league IS ? OR league = ?)
        """,
        (provider, provider_team_id, league, league),
    ).fetchone()
    return dict(row) if row else None


def delete_priority_team(conn: sqlite3.Connection, team_pk: int) -> bool:
    """Delete a priority team by primary key. Returns True if a row was removed."""
    cursor = conn.execute(
        "DELETE FROM channel_priority_teams WHERE id = ?",
        (team_pk,),
    )
    return cursor.rowcount > 0


def get_priority_team_match_keys(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """Return ``(sport_lower, team_name_lower)`` keys for fast channel matching.

    Sport-scoped name matching gives the "follow my team everywhere it plays"
    behaviour (a club's league + cup channels both float) while sport scoping
    avoids cross-sport name collisions (NFL vs MLB "Cardinals").
    """
    cursor = conn.execute("SELECT sport, team_name FROM channel_priority_teams")
    return {
        (row["sport"].lower(), row["team_name"].lower())
        for row in cursor.fetchall()
        if row["sport"] and row["team_name"]
    }
