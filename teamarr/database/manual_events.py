"""Durable supplemental fixtures. No provider fetches or external channel writes."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from teamarr.core import Event
from teamarr.database.provider_cache import dict_to_event, event_to_dict
from teamarr.utilities.event_dates import EVENT_TAIL_HOURS, event_intersects

MANUAL_EVENT_PREFIX = "manual:"


def get_manual_event(conn: sqlite3.Connection, event_id: str, league: str) -> Event | None:
    row = conn.execute(
        "SELECT event_data FROM manual_events WHERE id = ? AND league = ?",
        (event_id, league),
    ).fetchone()
    return dict_to_event(json.loads(row["event_data"])) if row else None


def list_manual_events(conn: sqlite3.Connection, league: str | None = None) -> list[Event]:
    """Management view includes cancelled fixtures, unlike matching candidates."""
    where, params = ("WHERE league = ?", (league,)) if league else ("", ())
    rows = conn.execute(
        f"SELECT event_data FROM manual_events {where} ORDER BY start_time, id", params
    ).fetchall()
    return [dict_to_event(json.loads(row["event_data"])) for row in rows]


def manual_events_in_window(
    conn: sqlite3.Connection, league: str, window: tuple[datetime, datetime]
) -> list[Event]:
    """Use the same user-day seam and plausible tail as provider fixtures."""
    start, end = window
    rows = conn.execute(
        """SELECT event_data FROM manual_events
           WHERE league = ? AND status = 'scheduled' AND start_time > ? AND start_time < ?
           ORDER BY start_time, id""",
        (
            league,
            (start - timedelta(hours=EVENT_TAIL_HOURS)).astimezone(UTC).isoformat(),
            end.astimezone(UTC).isoformat(),
        ),
    ).fetchall()
    events = [dict_to_event(json.loads(row["event_data"])) for row in rows]
    return [event for event in events if event_intersects(event, window)]


def save_manual_event(conn: sqlite3.Connection, event: Event) -> None:
    conn.execute(
        """INSERT INTO manual_events (id, league, start_time, status, event_data)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               start_time = excluded.start_time, status = excluded.status,
               event_data = excluded.event_data, updated_at = CURRENT_TIMESTAMP""",
        (
            event.id,
            event.league,
            event.start_time.astimezone(UTC).isoformat(),
            event.status.state,
            json.dumps(event_to_dict(event)),
        ),
    )
    # In the same transaction as the fixture. A newly added schedule must get a
    # fresh chance at streams that previously failed. Preserve corrections/skips.
    conn.execute(
        "DELETE FROM stream_match_cache WHERE event_id = '__FAILED__' AND user_corrected = 0"
    )
    conn.execute(
        "DELETE FROM stream_match_cache WHERE event_id = ? AND user_corrected = 0", (event.id,)
    )
