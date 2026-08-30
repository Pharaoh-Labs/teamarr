"""Channel priority-teams queries.

A priority team floats its channels to the top of a *scope* in the lineup
(see ``channel_numbers.get_all_channels_sorted``):

- ``'all'``    — top of everything (ahead of sport/league order)
- ``'sport'``  — first within its sport (sport order untouched)
- ``'league'`` — first within its league (the default for new teams)

Because pinned blocks partition the lineup *after* it is sorted, the scope
only changes a team's position relative to other channels in the same block.
This is purely an ordering preference and has no connection to the Teams page
or EPG generation. Identity comes from ``team_cache``; channels are matched by
``(sport, team_name)`` against ``managed_channels.home_team``/``away_team``.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

SCOPES = ("all", "sport", "league")
DEFAULT_SCOPE = "league"
# Broadest wins when one team has several rows (one per league it was picked in).
_SCOPE_BREADTH = {"all": 0, "sport": 1, "league": 2}


def _has_scope_column(conn: sqlite3.Connection) -> bool:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(channel_priority_teams)")}
    return "scope" in cols


def _scope_select(conn: sqlite3.Connection) -> str:
    return "scope" if _has_scope_column(conn) else "'all' AS scope"


def get_priority_teams(conn: sqlite3.Connection) -> list[dict]:
    """Return all configured priority teams, newest first."""
    cursor = conn.execute(
        f"""
        SELECT id, provider, provider_team_id, team_name, league, sport, {_scope_select(conn)}
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
    scope: str = DEFAULT_SCOPE,
) -> dict | None:
    """Add a priority team, resolving its name + sport from ``team_cache``.

    The frontend sends only ``(provider, team_id, league)`` (a ``TeamFilterEntry``)
    plus an optional ``scope``; we enrich from the cache so the match key and
    display name stay canonical. Returns the stored row, or ``None`` if the
    team isn't in ``team_cache`` or ``scope`` is invalid.
    Idempotent on ``(provider, provider_team_id, league)`` (re-adding updates scope).
    """
    if scope not in SCOPES:
        logger.warning("[PRIORITY_TEAMS] invalid scope %r", scope)
        return None
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
            (provider, provider_team_id, team_name, league, sport, scope)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, provider_team_id, league) DO UPDATE SET
            team_name = excluded.team_name,
            sport = excluded.sport,
            scope = excluded.scope
        """,
        (provider, provider_team_id, lookup["team_name"], league, lookup["sport"], scope),
    )
    row = _get_row(conn, provider, provider_team_id, league)
    if row:
        # Priority teams float to the top of the lineup; arm a one-shot re-grid so
        # the change applies on the next generation rather than at the daily reset.
        from teamarr.database.channel_numbers import arm_channel_relayout

        arm_channel_relayout(conn)
    return dict(row) if row else None


def _get_row(conn, provider, provider_team_id, league):
    return conn.execute(
        f"""
        SELECT id, provider, provider_team_id, team_name, league, sport, {_scope_select(conn)}
        FROM channel_priority_teams
        WHERE provider = ? AND provider_team_id = ? AND (league IS ? OR league = ?)
        """,
        (provider, provider_team_id, league, league),
    ).fetchone()


def update_priority_team_scope(conn: sqlite3.Connection, team_pk: int, scope: str) -> dict | None:
    """Change how far a priority team floats. Returns the row, or ``None`` if
    the id is unknown or ``scope`` is invalid."""
    if scope not in SCOPES:
        logger.warning("[PRIORITY_TEAMS] invalid scope %r", scope)
        return None
    cursor = conn.execute(
        "UPDATE channel_priority_teams SET scope = ? WHERE id = ?", (scope, team_pk)
    )
    if cursor.rowcount == 0:
        return None
    from teamarr.database.channel_numbers import arm_channel_relayout

    arm_channel_relayout(conn)
    row = conn.execute(
        "SELECT id, provider, provider_team_id, team_name, league, sport, scope "
        "FROM channel_priority_teams WHERE id = ?",
        (team_pk,),
    ).fetchone()
    return dict(row) if row else None


def delete_priority_team(conn: sqlite3.Connection, team_pk: int) -> bool:
    """Delete a priority team by primary key. Returns True if a row was removed."""
    cursor = conn.execute(
        "DELETE FROM channel_priority_teams WHERE id = ?",
        (team_pk,),
    )
    if cursor.rowcount > 0:
        from teamarr.database.channel_numbers import arm_channel_relayout

        arm_channel_relayout(conn)
        return True
    return False


def get_priority_team_match_keys(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """Return ``{(sport_lower, team_name_lower): scope}`` for fast channel matching.

    Sport-scoped name matching gives the "follow my team everywhere it plays"
    behaviour (a club's league + cup channels both float) while sport scoping
    avoids cross-sport name collisions (NFL vs MLB "Cardinals"). A team listed
    several times (one row per league picked) keeps its broadest scope.
    """
    cursor = conn.execute(
        f"SELECT sport, team_name, {_scope_select(conn)} FROM channel_priority_teams"
    )
    keys: dict[tuple[str, str], str] = {}
    for row in cursor.fetchall():
        if not (row["sport"] and row["team_name"]):
            continue
        key = (row["sport"].lower(), row["team_name"].lower())
        scope = row["scope"] if row["scope"] in SCOPES else "all"
        if key not in keys or _SCOPE_BREADTH[scope] < _SCOPE_BREADTH[keys[key]]:
            keys[key] = scope
    return keys
