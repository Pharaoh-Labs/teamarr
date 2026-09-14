"""Temporary stream memberships for persistent managed team channels."""

from __future__ import annotations

from datetime import UTC, datetime
from sqlite3 import Connection

# Soft-deleted rows are kept briefly for the run-history/support-bundle view,
# then purged so the table does not grow forever (#826).
_REMOVED_RETENTION = "-7 days"

# One event per channel at a time: the soonest game that is currently inside
# its window. Rows without a stored start (pre-#826) sort last.
_SELECTED_EVENT = """
    SELECT event_id, event_provider FROM active_streams
    ORDER BY event_start IS NULL, event_start, detach_at IS NULL, detach_at,
             event_id, event_provider
    LIMIT 1
"""


def get_assigned_team_streams(
    conn: Connection, team_id: int, now: datetime | None = None
) -> list[dict]:
    """Return the active channel membership for one selected event, deduplicated."""
    timestamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        f"""WITH active_streams AS (
               SELECT * FROM managed_team_channel_streams
               WHERE team_id = ? AND removed_at IS NULL
                 AND (attach_at IS NULL OR attach_at = '' OR attach_at <= ?)
                 AND (detach_at IS NULL OR detach_at > ?)
           ), selected_event AS ({_SELECTED_EVENT}
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


def reconcile_team_streams(
    conn: Connection,
    memberships: list[dict],
    reconcile_group_ids: set[int] | None = None,
    *,
    active_team_ids: set[int] | None = None,
) -> None:
    """Replace this run's desired memberships without expiring channels.

    Only rows whose ``source_group_id`` is in ``reconcile_group_ids`` may be
    marked removed (``None`` = every group). A group that did not report this
    run keeps its rows: absence of evidence is not evidence of absence, and a
    transient source failure must not clear a live game off a channel (#826).
    Rows for teams outside ``active_team_ids`` are always released.
    """
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
        key = (
            row["team_id"], row["dispatcharr_stream_id"], row["event_id"],
            row["event_provider"], row["source_group_id"], row["attach_at"] or "",
        )
        if key in desired:
            continue
        team_gone = active_team_ids is not None and row["team_id"] not in active_team_ids
        group_reported = (
            reconcile_group_ids is None or row["source_group_id"] in reconcile_group_ids
        )
        if not (team_gone or group_reported):
            continue
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
                   priority, event_start, attach_at, detach_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    event_start = excluded.event_start,
                    detach_at = excluded.detach_at,
                   removed_at = NULL,
                   updated_at = CURRENT_TIMESTAMP""",
            (
                item["team_id"], item["dispatcharr_stream_id"], item["event_id"],
                item["event_provider"], item["source_group_id"], item.get("stream_name"),
                item.get("m3u_account_name"), item.get("match_method"),
                item.get("match_type", "event"), item.get("feed_team_id"),
                item.get("feed_side"), item.get("dispatcharr_channel_group"),
                item.get("priority", 999), item.get("event_start"),
                item.get("attach_at") or "", item.get("detach_at"),
            ),
        )

    conn.execute(
        "DELETE FROM managed_team_channel_streams "
        "WHERE removed_at IS NOT NULL AND removed_at < datetime('now', ?)",
        (_REMOVED_RETENTION,),
    )


def active_stream_ids(conn: Connection, team_id: int, now: datetime | None = None) -> list[int]:
    """Return streams for one active event, preserving that event's priority order."""
    now = now or datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        f"""WITH active_streams AS (
               SELECT * FROM managed_team_channel_streams
               WHERE team_id = ? AND removed_at IS NULL
                 AND (attach_at IS NULL OR attach_at = '' OR attach_at <= ?)
                 AND (detach_at IS NULL OR detach_at > ?)
           ), selected_event AS ({_SELECTED_EVENT}
           )
           SELECT dispatcharr_stream_id FROM active_streams
           WHERE (event_id, event_provider) = (
               SELECT event_id, event_provider FROM selected_event
           )
           ORDER BY priority, id""",
        (team_id, timestamp, timestamp),
    ).fetchall()
    return list(dict.fromkeys(row["dispatcharr_stream_id"] for row in rows))
