"""Database CRUD operations for user-defined broadcaster / RSN mappings.

Broadcaster mappings allow users to explicitly attach stream names, regexes,
or tvg-ids to specific teams to resolve multi-team networks (e.g. MASN) or
handle custom provider naming conventions.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection, Row

logger = logging.getLogger(__name__)


@dataclass
class BroadcasterMapping:
    """A user-defined broadcaster / RSN mapping."""

    id: int
    name: str
    pattern: str
    pattern_type: str  # 'regex', 'exact', 'tvg_id', 'channel_id'
    team_id: str  # Team abbreviation or provider team ID (e.g., 'NYY', 'BAL', '110')
    team_name: str | None = None
    league: str = "mlb"
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _row_to_mapping(row: Row) -> BroadcasterMapping:
    """Convert a database row to BroadcasterMapping."""
    return BroadcasterMapping(
        id=row["id"],
        name=row["name"],
        pattern=row["pattern"],
        pattern_type=row["pattern_type"],
        team_id=row["team_id"],
        team_name=row["team_name"],
        league=row["league"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_broadcaster_mappings(
    conn: Connection,
    league: str | None = None,
    active_only: bool = False,
) -> list[BroadcasterMapping]:
    """List all broadcaster mappings, optionally filtered by league/active status."""
    query = "SELECT * FROM team_broadcaster_mappings WHERE 1=1"
    params: list = []

    if league:
        query += " AND LOWER(league) = LOWER(?)"
        params.append(league.strip())

    if active_only:
        query += " AND is_active = 1"

    query += " ORDER BY id ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_mapping(r) for r in rows]


def get_broadcaster_mapping(conn: Connection, mapping_id: int) -> BroadcasterMapping | None:
    """Get a single broadcaster mapping by ID."""
    row = conn.execute(
        "SELECT * FROM team_broadcaster_mappings WHERE id = ?",
        (mapping_id,),
    ).fetchone()
    return _row_to_mapping(row) if row else None


def create_broadcaster_mapping(
    conn: Connection,
    name: str,
    pattern: str,
    pattern_type: str = "regex",
    team_id: str = "",
    league: str = "mlb",
    team_name: str | None = None,
    is_active: bool = True,
) -> BroadcasterMapping:
    """Create a new broadcaster mapping."""
    cursor = conn.execute(
        """
        INSERT INTO team_broadcaster_mappings (
            name, pattern, pattern_type, team_id, team_name, league, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name.strip(),
            pattern.strip(),
            pattern_type.strip(),
            team_id.strip(),
            team_name.strip() if team_name else None,
            league.strip().lower(),
            1 if is_active else 0,
        ),
    )
    conn.commit()
    return get_broadcaster_mapping(conn, cursor.lastrowid)  # type: ignore


def update_broadcaster_mapping(
    conn: Connection,
    mapping_id: int,
    name: str | None = None,
    pattern: str | None = None,
    pattern_type: str | None = None,
    team_id: str | None = None,
    team_name: str | None = None,
    league: str | None = None,
    is_active: bool | None = None,
) -> BroadcasterMapping | None:
    """Update an existing broadcaster mapping."""
    existing = get_broadcaster_mapping(conn, mapping_id)
    if not existing:
        return None

    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name.strip())
    if pattern is not None:
        updates.append("pattern = ?")
        params.append(pattern.strip())
    if pattern_type is not None:
        updates.append("pattern_type = ?")
        params.append(pattern_type.strip())
    if team_id is not None:
        updates.append("team_id = ?")
        params.append(team_id.strip())
    if team_name is not None:
        updates.append("team_name = ?")
        params.append(team_name.strip() if team_name else None)
    if league is not None:
        updates.append("league = ?")
        params.append(league.strip().lower())
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)

    if not updates:
        return existing

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(mapping_id)

    query = f"UPDATE team_broadcaster_mappings SET {', '.join(updates)} WHERE id = ?"
    conn.execute(query, params)
    conn.commit()
    return get_broadcaster_mapping(conn, mapping_id)


def delete_broadcaster_mapping(conn: Connection, mapping_id: int) -> bool:
    """Delete a broadcaster mapping by ID."""
    cursor = conn.execute(
        "DELETE FROM team_broadcaster_mappings WHERE id = ?",
        (mapping_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def match_user_broadcaster(
    text: str,
    league: str,
    user_mappings: list[BroadcasterMapping],
    tvg_id: str | None = None,
    channel_id: int | None = None,
) -> str | None:
    """Match candidate text / stream metadata against user-defined broadcaster mappings.

    Returns the mapped team_id (or team abbreviation) if a match is found.
    """
    if not user_mappings:
        return None

    league_lower = league.lower()
    for mapping in user_mappings:
        if not mapping.is_active or mapping.league.lower() != league_lower:
            continue

        ptype = mapping.pattern_type.lower()
        pat = mapping.pattern

        if ptype == "regex":
            try:
                if re.search(pat, text, re.IGNORECASE):
                    return mapping.team_id
            except re.error:
                continue
        elif ptype == "exact":
            if text.strip().lower() == pat.strip().lower():
                return mapping.team_id
        elif ptype == "tvg_id" and tvg_id:
            if tvg_id.strip().lower() == pat.strip().lower():
                return mapping.team_id
        elif ptype == "channel_id" and channel_id is not None:
            if str(channel_id).strip() == pat.strip():
                return mapping.team_id

    return None
