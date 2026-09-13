"""Temporary stream memberships for persistent managed team channels."""

from __future__ import annotations

from datetime import UTC, datetime
from sqlite3 import Connection


def reconcile_team_streams(conn: Connection, memberships: list[dict]) -> None:
    """Replace the current generation's desired memberships without expiring channels."""
    desired = {
        (
            item["team_id"],
            item["dispatcharr_stream_id"],
            item["event_id"],
            item["event_provider"],
            item["source_group_id"],
            item.get("attach_at") or "",
        )
        for item in memberships
    }
    existing = conn.execute(
        """SELECT id, team_id, dispatcharr_stream_id, event_id, event_provider,
                  source_group_id, attach_at
           FROM managed_team_channel_streams WHERE removed_at IS NULL"""
    ).fetchall()
    for row in existing:
        key = tuple(row[name] for name in row.keys() if name != "id")
        if key not in desired:
            conn.execute(
                "UPDATE managed_team_channel_streams "
                "SET removed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )

    for item in memberships:
        conn.execute(
            """INSERT INTO managed_team_channel_streams (
                   team_id, dispatcharr_stream_id, event_id, event_provider,
                   source_group_id, match_method, attach_at, detach_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(team_id, dispatcharr_stream_id, event_id, event_provider,
                           source_group_id, attach_at) DO UPDATE SET
                   match_method = excluded.match_method,
                   detach_at = excluded.detach_at,
                   removed_at = NULL,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                item["team_id"], item["dispatcharr_stream_id"], item["event_id"],
                item["event_provider"], item["source_group_id"], item.get("match_method"),
                item.get("attach_at") or "", item.get("detach_at"),
            ),
        )


def active_stream_ids(conn: Connection, team_id: int, now: datetime | None = None) -> list[int]:
    """Return deduplicated stream ids whose half-open windows are active now."""
    now = now or datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT dispatcharr_stream_id FROM managed_team_channel_streams
           WHERE team_id = ? AND removed_at IS NULL
             AND (attach_at IS NULL OR attach_at <= ?)
             AND (detach_at IS NULL OR detach_at > ?)
           ORDER BY id""",
        (team_id, timestamp, timestamp),
    ).fetchall()
    return list(dict.fromkeys(row["dispatcharr_stream_id"] for row in rows))
