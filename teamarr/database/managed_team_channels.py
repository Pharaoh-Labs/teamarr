"""Persistence for Teamarr-owned persistent Team EPG channels."""

from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection


@dataclass(frozen=True)
class ManagedTeamChannel:
    team_id: int
    dispatcharr_channel_id: int | None
    dispatcharr_uuid: str | None
    channel_number: int
    sync_status: str
    sync_message: str | None
    last_verified_at: str | None


def _row_to_channel(row) -> ManagedTeamChannel:
    return ManagedTeamChannel(
        team_id=int(row["team_id"]),
        dispatcharr_channel_id=row["dispatcharr_channel_id"],
        dispatcharr_uuid=row["dispatcharr_uuid"],
        channel_number=int(row["channel_number"]),
        sync_status=row["sync_status"],
        sync_message=row["sync_message"],
        last_verified_at=row["last_verified_at"],
    )


def get_managed_team_channel(conn: Connection, team_id: int) -> ManagedTeamChannel | None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'managed_team_channels'"
    ).fetchone()
    if not exists:
        return None
    row = conn.execute(
        "SELECT * FROM managed_team_channels WHERE team_id = ?", (team_id,)
    ).fetchone()
    return _row_to_channel(row) if row else None


def list_managed_team_channels(conn: Connection) -> list[ManagedTeamChannel]:
    rows = conn.execute(
        "SELECT * FROM managed_team_channels ORDER BY channel_number, team_id"
    ).fetchall()
    return [_row_to_channel(row) for row in rows]


def list_enabled_managed_teams(conn: Connection) -> list[dict]:
    """Return opted-in active teams with any persisted ownership mapping."""
    rows = conn.execute(
        """
        SELECT t.*, mtc.dispatcharr_channel_id, mtc.dispatcharr_uuid,
               mtc.channel_number AS allocated_channel_number,
               mtc.sync_status, mtc.sync_message, mtc.last_verified_at
        FROM teams t
        LEFT JOIN managed_team_channels mtc ON mtc.team_id = t.id
        WHERE t.active = 1 AND t.managed_channel_enabled = 1
        ORDER BY t.team_name, t.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_owned_enabled_managed_team_channels(conn: Connection) -> list[dict]:
    """Return active opted-in teams with a locally-owned channel mapping."""
    rows = conn.execute(
        """
        SELECT t.id AS team_id, t.channel_id, t.team_name, t.team_logo_url,
               t.channel_logo_url, t.primary_league, t.sport,
               mtc.dispatcharr_channel_id, mtc.dispatcharr_uuid,
               mtc.channel_number, mtc.sync_status, mtc.created_at, mtc.updated_at
        FROM managed_team_channels mtc
        JOIN teams t ON t.id = mtc.team_id
        WHERE t.active = 1 AND t.managed_channel_enabled = 1
        ORDER BY t.team_name, t.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_disabled_managed_team_channels(conn: Connection) -> list[dict]:
    """Return owned channels whose team is no longer eligible for management."""
    rows = conn.execute(
        """
        SELECT t.id AS team_id, t.active, t.managed_channel_enabled,
               mtc.dispatcharr_channel_id, mtc.dispatcharr_uuid
        FROM managed_team_channels mtc
        JOIN teams t ON t.id = mtc.team_id
        WHERE t.active = 0 OR t.managed_channel_enabled = 0
        """
    ).fetchall()
    return [dict(row) for row in rows]


def upsert_managed_team_channel(
    conn: Connection,
    *,
    team_id: int,
    dispatcharr_channel_id: int | None,
    dispatcharr_uuid: str | None,
    channel_number: int,
    sync_status: str,
    sync_message: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO managed_team_channels (
            team_id, dispatcharr_channel_id, dispatcharr_uuid, channel_number,
            sync_status, sync_message, last_verified_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(team_id) DO UPDATE SET
            dispatcharr_channel_id = excluded.dispatcharr_channel_id,
            dispatcharr_uuid = excluded.dispatcharr_uuid,
            channel_number = excluded.channel_number,
            sync_status = excluded.sync_status,
            sync_message = excluded.sync_message,
            last_verified_at = excluded.last_verified_at,
            updated_at = excluded.updated_at
        """,
        (
            team_id,
            dispatcharr_channel_id,
            dispatcharr_uuid,
            channel_number,
            sync_status,
            sync_message,
        ),
    )


def delete_managed_team_channel(conn: Connection, team_id: int) -> bool:
    cursor = conn.execute("DELETE FROM managed_team_channels WHERE team_id = ?", (team_id,))
    return cursor.rowcount > 0
