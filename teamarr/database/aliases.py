"""Database CRUD operations for team aliases.

Team aliases map user-defined stream names to provider team IDs
for edge cases where automatic matching fails.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection, Row

logger = logging.getLogger(__name__)


@dataclass
class TeamAlias:
    """A user-defined team alias."""

    id: int
    alias: str
    league: str
    provider: str
    team_id: str
    team_name: str
    created_at: datetime | None = None


def _row_to_alias(row: Row) -> TeamAlias:
    """Convert a database row to TeamAlias."""
    return TeamAlias(
        id=row["id"],
        alias=row["alias"],
        league=row["league"],
        provider=row["provider"],
        team_id=row["team_id"],
        team_name=row["team_name"],
        created_at=row["created_at"],
    )


def get_alias(conn: Connection, alias_id: int) -> TeamAlias | None:
    """Get a single alias by ID."""
    row = conn.execute(
        "SELECT * FROM team_aliases WHERE id = ?",
        (alias_id,),
    ).fetchone()
    return _row_to_alias(row) if row else None


def get_alias_by_text(
    conn: Connection,
    text: str,
    league: str,
) -> TeamAlias | None:
    """Look up alias by text and league.

    Args:
        conn: Database connection
        text: Normalized alias text to search for
        league: League code

    Returns:
        TeamAlias if found, None otherwise
    """
    row = conn.execute(
        """
        SELECT * FROM team_aliases
        WHERE LOWER(alias) = LOWER(?) AND LOWER(league) = LOWER(?)
        """,
        (text.strip(), league.strip()),
    ).fetchone()
    return _row_to_alias(row) if row else None


def list_aliases(
    conn: Connection,
    league: str | None = None,
    provider: str | None = None,
) -> list[TeamAlias]:
    """List all aliases, optionally filtered.

    Args:
        conn: Database connection
        league: Optional league filter
        provider: Optional provider filter

    Returns:
        List of TeamAlias objects
    """
    query = "SELECT * FROM team_aliases WHERE 1=1"
    params: list = []

    if league:
        query += " AND LOWER(league) = LOWER(?)"
        params.append(league)

    if provider:
        query += " AND provider = ?"
        params.append(provider)

    query += " ORDER BY league, alias"

    rows = conn.execute(query, params).fetchall()
    return [_row_to_alias(row) for row in rows]


def create_alias(
    conn: Connection,
    alias: str,
    league: str,
    team_id: str,
    team_name: str,
    provider: str = "espn",
) -> TeamAlias:
    """Create a new team alias.

    Args:
        conn: Database connection
        alias: The alias text (will be normalized)
        league: League code
        team_id: Provider's team ID
        team_name: Provider's team name
        provider: Provider name (default: espn)

    Returns:
        Created TeamAlias

    Raises:
        sqlite3.IntegrityError: If alias already exists for this league
    """
    # Normalize alias
    normalized_alias = alias.strip().lower()

    cursor = conn.execute(
        """
        INSERT INTO team_aliases (alias, league, provider, team_id, team_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        (normalized_alias, league.lower(), provider, team_id, team_name),
    )
    conn.commit()

    new_id = cursor.lastrowid
    assert new_id is not None  # just-inserted row always has a rowid
    return TeamAlias(
        id=new_id,
        alias=normalized_alias,
        league=league.lower(),
        provider=provider,
        team_id=team_id,
        team_name=team_name,
        created_at=datetime.now(),
    )


def update_alias(
    conn: Connection,
    alias_id: int,
    alias: str | None = None,
    league: str | None = None,
    team_id: str | None = None,
    team_name: str | None = None,
    provider: str | None = None,
) -> TeamAlias | None:
    """Update an existing alias.

    Args:
        conn: Database connection
        alias_id: ID of alias to update
        alias: New alias text (optional)
        league: New league code (optional)
        team_id: New team ID (optional)
        team_name: New team name (optional)
        provider: New provider (optional)

    Returns:
        Updated TeamAlias or None if not found
    """
    updates = []
    params = []

    if alias is not None:
        updates.append("alias = ?")
        params.append(alias.strip().lower())

    if league is not None:
        updates.append("league = ?")
        params.append(league.lower())

    if team_id is not None:
        updates.append("team_id = ?")
        params.append(team_id)

    if team_name is not None:
        updates.append("team_name = ?")
        params.append(team_name)

    if provider is not None:
        updates.append("provider = ?")
        params.append(provider)

    if not updates:
        return get_alias(conn, alias_id)

    params.append(alias_id)

    conn.execute(
        f"UPDATE team_aliases SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()

    return get_alias(conn, alias_id)


def delete_alias(conn: Connection, alias_id: int) -> bool:
    """Delete an alias by ID.

    Args:
        conn: Database connection
        alias_id: ID of alias to delete

    Returns:
        True if deleted, False if not found
    """
    cursor = conn.execute(
        "DELETE FROM team_aliases WHERE id = ?",
        (alias_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def bulk_create_aliases(
    conn: Connection,
    aliases: list[dict],
) -> tuple[int, int]:
    """Bulk create aliases, skipping duplicates.

    Args:
        conn: Database connection
        aliases: List of dicts with alias, league, team_id, team_name, provider

    Returns:
        Tuple of (created_count, skipped_count)
    """
    created = 0
    skipped = 0

    for a in aliases:
        try:
            create_alias(
                conn,
                alias=a["alias"],
                league=a["league"],
                team_id=a["team_id"],
                team_name=a["team_name"],
                provider=a.get("provider", "espn"),
            )
            created += 1
        except Exception as e:
            logger.debug("[ALIAS] Skipped '%s': %s", a.get("alias"), e)
            skipped += 1

    return created, skipped


def export_aliases(conn: Connection) -> list[dict]:
    """Export all aliases as dicts for JSON export.

    Args:
        conn: Database connection

    Returns:
        List of alias dicts
    """
    aliases = list_aliases(conn)
    return [
        {
            "alias": a.alias,
            "league": a.league,
            "provider": a.provider,
            "team_id": a.team_id,
            "team_name": a.team_name,
        }
        for a in aliases
    ]
