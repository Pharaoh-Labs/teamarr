"""Database operations for teams.

CRUD operations for the teams table.
"""

import json
import logging
from sqlite3 import Connection

from teamarr.database.leagues import get_league_display, get_league_id

logger = logging.getLogger(__name__)


def _parse_leagues(leagues_str: str | None) -> list[str]:
    """Parse leagues JSON string to list."""
    if not leagues_str:
        return []
    try:
        return json.loads(leagues_str)
    except (json.JSONDecodeError, TypeError):
        return []


def _row_to_dict(row) -> dict:
    """Convert database row to dict with parsed leagues."""
    data = dict(row)
    data["leagues"] = _parse_leagues(data.get("leagues"))
    return data


def list_teams(conn: Connection, active_only: bool = False) -> list[dict]:
    """List all teams.

    Args:
        conn: Database connection
        active_only: If True, only return active teams

    Returns:
        List of team dicts with parsed leagues
    """
    if active_only:
        cursor = conn.execute("SELECT * FROM teams WHERE active = 1 ORDER BY team_name")
    else:
        cursor = conn.execute("SELECT * FROM teams ORDER BY team_name")
    return [_row_to_dict(row) for row in cursor.fetchall()]


def get_team(conn: Connection, team_id: int) -> dict | None:
    """Get a team by ID.

    Args:
        conn: Database connection
        team_id: Team ID

    Returns:
        Team dict with parsed leagues, or None if not found
    """
    cursor = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
    row = cursor.fetchone()
    return _row_to_dict(row) if row else None


def get_team_xmltv(conn: Connection, team_id: int) -> dict | None:
    """Get the generated XMLTV content and timestamp for a team's channel.

    Args:
        conn: Database connection
        team_id: Team ID

    Returns:
        Dict with ``xmltv_content`` and ``updated_at``, or None if not generated yet.
    """
    row = conn.execute(
        "SELECT xmltv_content, updated_at FROM team_epg_xmltv WHERE team_id = ?",
        (team_id,),
    ).fetchone()
    return dict(row) if row else None


def create_team(
    conn: Connection,
    provider: str,
    provider_team_id: str,
    primary_league: str,
    leagues_json: str,
    sport: str,
    team_name: str,
    team_abbrev: str | None,
    team_logo_url: str | None,
    team_color: str | None,
    channel_id: str | None,
    channel_logo_url: str | None,
    template_id: int | None,
    active: bool,
) -> dict:
    """Create a new team.

    Args:
        conn: Database connection
        provider: Provider name
        provider_team_id: Provider's team ID
        primary_league: Primary league code
        leagues_json: JSON string of league codes
        sport: Sport code
        team_name: Team display name
        team_abbrev: Team abbreviation
        team_logo_url: Team logo URL
        team_color: Team color
        channel_id: Channel ID
        channel_logo_url: Channel logo URL
        template_id: Template ID
        active: Whether team is active

    Returns:
        Created team dict with parsed leagues
    """
    cursor = conn.execute(
        """
        INSERT INTO teams (
            provider, provider_team_id, primary_league, leagues, sport,
            team_name, team_abbrev, team_logo_url, team_color,
            channel_id, channel_logo_url, template_id, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider,
            provider_team_id,
            primary_league,
            leagues_json,
            sport,
            team_name,
            team_abbrev,
            team_logo_url,
            team_color,
            channel_id,
            channel_logo_url,
            template_id,
            active,
        ),
    )
    team_id = cursor.lastrowid
    assert team_id is not None  # just-inserted row always has a rowid
    logger.info("[CREATED] Team id=%d name=%s", team_id, team_name)
    team = get_team(conn, team_id)
    assert team is not None  # just inserted, row must exist
    return team


def update_team(conn: Connection, team_id: int, updates: dict) -> dict | None:
    """Update a team.

    Handles XMLTV cleanup when team is deactivated.

    Args:
        conn: Database connection
        team_id: Team ID
        updates: Dict of field names to new values (already serialized)

    Returns:
        Updated team dict, or None if team not found
    """
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [team_id]

    cursor = conn.execute(f"UPDATE teams SET {set_clause} WHERE id = ?", values)
    if cursor.rowcount == 0:
        return None

    # Clean up XMLTV content when team is deactivated
    if updates.get("active") is False:
        conn.execute("DELETE FROM team_epg_xmltv WHERE team_id = ?", (team_id,))

    logger.info("[UPDATED] Team id=%d fields=%s", team_id, list(updates.keys()))
    return get_team(conn, team_id)


def delete_team(conn: Connection, team_id: int) -> bool:
    """Delete a team and its associated XMLTV content.

    Args:
        conn: Database connection
        team_id: Team ID

    Returns:
        True if deleted, False if team not found
    """
    cursor = conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    if cursor.rowcount == 0:
        return False
    conn.execute("DELETE FROM team_epg_xmltv WHERE team_id = ?", (team_id,))
    logger.info("[DELETED] Team id=%d", team_id)
    return True


def bulk_update_channel_ids(
    conn: Connection,
    team_ids: list[int],
    format_template: str,
) -> tuple[int, list[str]]:
    """Bulk update channel IDs based on a format template.

    Supported format variables:
    - {team_name_pascal}: Team name in PascalCase
    - {team_abbrev}: Team abbreviation lowercase
    - {team_name}: Team name lowercase with dashes
    - {provider_team_id}: Provider's team ID
    - {league_id}: League code lowercase
    - {league}: League display name
    - {sport}: Sport name lowercase

    Args:
        conn: Database connection
        team_ids: List of team IDs to update
        format_template: Format string with placeholders

    Returns:
        Tuple of (updated_count, errors list)
    """
    import re


    def to_pascal_case(name: str) -> str:
        return "".join(
            word.capitalize()
            for word in "".join(c if c.isalnum() or c.isspace() else "" for c in name).split()
        )

    updated_count = 0
    errors: list[str] = []

    for team_id in team_ids:
        try:
            team_data = get_team(conn, team_id)
            if not team_data:
                errors.append(f"Team ID {team_id} not found")
                continue

            team_name = team_data.get("team_name", "")
            primary_league = team_data.get("primary_league", "")

            league_display = get_league_display(conn, primary_league)
            league_id = get_league_id(conn, primary_league)

            channel_id = format_template
            channel_id = channel_id.replace("{team_name_pascal}", to_pascal_case(team_name))
            channel_id = channel_id.replace(
                "{team_abbrev}", (team_data.get("team_abbrev") or "").lower()
            )
            channel_id = channel_id.replace("{team_name}", team_name.lower().replace(" ", "-"))
            channel_id = channel_id.replace(
                "{provider_team_id}", str(team_data.get("provider_team_id") or "")
            )
            channel_id = channel_id.replace("{league_id}", league_id)
            channel_id = channel_id.replace("{league}", league_display)
            channel_id = channel_id.replace("{sport}", (team_data.get("sport") or "").lower())

            if (
                "{team_name_pascal}" in format_template
                or "{league}" in format_template
            ):
                channel_id = re.sub(r"[^a-zA-Z0-9.-]+", "", channel_id)
            else:
                channel_id = re.sub(r"[^a-z0-9.-]+", "-", channel_id)
                channel_id = re.sub(r"-+", "-", channel_id)
                channel_id = channel_id.strip("-")

            if not channel_id:
                errors.append(f"Generated empty channel ID for team '{team_name}'")
                continue

            conn.execute(
                "UPDATE teams SET channel_id = ? WHERE id = ?",
                (channel_id, team_id),
            )
            updated_count += 1

        except Exception as e:
            errors.append(f"Error updating team ID {team_id}: {str(e)}")

    return updated_count, errors
