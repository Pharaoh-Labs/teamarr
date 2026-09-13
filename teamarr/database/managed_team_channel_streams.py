"""Temporary stream memberships for persistent managed team channels."""

from __future__ import annotations

from datetime import UTC, datetime
from sqlite3 import Connection


def get_assigned_team_streams(
    conn: Connection, team_id: int, now: datetime | None = None
) -> list[dict]:
    """Return the active channel membership for one selected event, deduplicated."""
    timestamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """WITH active_streams AS (
               SELECT * FROM managed_team_channel_streams
               WHERE team_id = ? AND removed_at IS NULL
                 AND (attach_at IS NULL OR attach_at <= ?)
                 AND (detach_at IS NULL OR detach_at > ?)
           ), selected_event AS (
               SELECT event_id, event_provider FROM active_streams
               ORDER BY detach_at IS NULL, detach_at, event_id, event_provider
               LIMIT 1
           ), ranked_streams AS (
               SELECT *, ROW_NUMBER() OVER (
                   PARTITION BY dispatcharr_stream_id ORDER BY priority, id
               ) AS stream_rank
               FROM active_streams
               WHERE (event_id, event_provider) = (
                   SELECT event_id, event_provider FROM selected_event
               )
           )
           SELECT * FROM ranked_streams WHERE stream_rank = 1
           ORDER BY priority, id""",
        (team_id, timestamp, timestamp),
    ).fetchall()
    return [dict(row) for row in rows]


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
                   source_group_id, stream_name, m3u_account_name, match_method,
                   match_type, feed_team_id, feed_side, dispatcharr_channel_group,
                   priority, attach_at, detach_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, dispatcharr_stream_id, event_id, event_provider,
                            source_group_id, attach_at) DO UPDATE SET
                    stream_name = excluded.stream_name,
                    m3u_account_name = excluded.m3u_account_name,
                    match_method = excluded.match_method,
                    match_type = excluded.match_type,
                    feed_team_id = excluded.feed_team_id,
                    feed_side = excluded.feed_side,
                    dispatcharr_channel_group = excluded.dispatcharr_channel_group,
                    priority = excluded.priority,
                    detach_at = excluded.detach_at,
                   removed_at = NULL,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                item["team_id"], item["dispatcharr_stream_id"], item["event_id"],
                item["event_provider"], item["source_group_id"], item.get("stream_name"),
                item.get("m3u_account_name"), item.get("match_method"),
                item.get("match_type", "event"), item.get("feed_team_id"),
                item.get("feed_side"), item.get("dispatcharr_channel_group"),
                item.get("priority", 999), item.get("attach_at") or "", item.get("detach_at"),
            ),
        )


def active_stream_ids(conn: Connection, team_id: int, now: datetime | None = None) -> list[int]:
    """Return streams for one active event, preserving that event's priority order."""
    now = now or datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """WITH active_streams AS (
               SELECT * FROM managed_team_channel_streams
               WHERE team_id = ? AND removed_at IS NULL
                 AND (attach_at IS NULL OR attach_at <= ?)
                 AND (detach_at IS NULL OR detach_at > ?)
           ), selected_event AS (
               SELECT event_id, event_provider FROM active_streams
               ORDER BY detach_at IS NULL, detach_at, event_id, event_provider
               LIMIT 1
           )
           SELECT dispatcharr_stream_id FROM active_streams
           WHERE (event_id, event_provider) = (
               SELECT event_id, event_provider FROM selected_event
           )
           ORDER BY priority, id""",
        (team_id, timestamp, timestamp),
    ).fetchall()
    return list(dict.fromkeys(row["dispatcharr_stream_id"] for row in rows))
