"""CRUD operations for EPG sources database."""

import json
import logging
from datetime import datetime
from sqlite3 import Connection

logger = logging.getLogger(__name__)


# =============================================================================
# SOURCES
# =============================================================================


def create_source(conn: Connection, name: str, url: str) -> dict:
    cursor = conn.execute(
        "INSERT INTO epg_sources (name, url) VALUES (?, ?)",
        (name, url),
    )
    return get_source(conn, cursor.lastrowid)


def get_source(conn: Connection, source_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM epg_sources WHERE id = ?", (source_id,)
    ).fetchone()
    return dict(row) if row else None


def list_sources(conn: Connection, include_disabled: bool = False) -> list[dict]:
    if include_disabled:
        rows = conn.execute(
            "SELECT * FROM epg_sources ORDER BY name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM epg_sources WHERE enabled = 1 ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


def update_source(conn: Connection, source_id: int, **kwargs) -> dict | None:
    allowed = {"name", "url", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return get_source(conn, source_id)

    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [source_id]
    conn.execute(
        f"UPDATE epg_sources SET {set_clause} WHERE id = ?",
        values,
    )
    return get_source(conn, source_id)


def delete_source(conn: Connection, source_id: int) -> bool:
    cursor = conn.execute("DELETE FROM epg_sources WHERE id = ?", (source_id,))
    return cursor.rowcount > 0


def update_source_fetch_status(
    conn: Connection,
    source_id: int,
    status: str,
    error: str | None = None,
    channel_count: int = 0,
    programme_count: int = 0,
) -> None:
    conn.execute(
        """UPDATE epg_sources
           SET last_fetched_at = ?, last_fetch_status = ?, last_fetch_error = ?,
               channel_count = ?, programme_count = ?, updated_at = ?
           WHERE id = ?""",
        (
            datetime.utcnow().isoformat(),
            status,
            error,
            channel_count,
            programme_count,
            datetime.utcnow().isoformat(),
            source_id,
        ),
    )


# =============================================================================
# CHANNELS
# =============================================================================


def upsert_channels(
    conn: Connection, source_id: int, channels: list[dict]
) -> int:
    """Bulk insert/update channels from parsed XMLTV. Returns count upserted."""
    count = 0
    for ch in channels:
        conn.execute(
            """INSERT INTO epg_channels (source_id, channel_xmltv_id, display_name, icon_url)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(source_id, channel_xmltv_id)
               DO UPDATE SET display_name = excluded.display_name,
                             icon_url = excluded.icon_url""",
            (source_id, ch["xmltv_id"], ch["display_name"], ch.get("icon_url")),
        )
        count += 1

    # Remove channels that no longer exist in the source
    xmltv_ids = [ch["xmltv_id"] for ch in channels]
    if xmltv_ids:
        placeholders = ",".join("?" * len(xmltv_ids))
        conn.execute(
            f"""DELETE FROM epg_channels
                WHERE source_id = ? AND channel_xmltv_id NOT IN ({placeholders})""",
            [source_id] + xmltv_ids,
        )
    else:
        conn.execute("DELETE FROM epg_channels WHERE source_id = ?", (source_id,))

    return count


def list_channels(
    conn: Connection, source_id: int | None = None
) -> list[dict]:
    if source_id is not None:
        rows = conn.execute(
            """SELECT c.*, s.name as source_name
               FROM epg_channels c
               JOIN epg_sources s ON s.id = c.source_id
               WHERE c.source_id = ?
               ORDER BY c.display_name""",
            (source_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT c.*, s.name as source_name
               FROM epg_channels c
               JOIN epg_sources s ON s.id = c.source_id
               ORDER BY s.name, c.display_name"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_channel(conn: Connection, channel_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM epg_channels WHERE id = ?", (channel_id,)
    ).fetchone()
    return dict(row) if row else None


# =============================================================================
# STREAM MAPPINGS
# =============================================================================


def create_mapping(
    conn: Connection,
    epg_channel_id: int,
    dispatcharr_stream_id: int,
    dispatcharr_stream_name: str | None = None,
    m3u_account_id: int | None = None,
) -> dict:
    cursor = conn.execute(
        """INSERT INTO epg_stream_mappings
           (epg_channel_id, dispatcharr_stream_id, dispatcharr_stream_name, m3u_account_id)
           VALUES (?, ?, ?, ?)""",
        (epg_channel_id, dispatcharr_stream_id, dispatcharr_stream_name, m3u_account_id),
    )
    return get_mapping(conn, cursor.lastrowid)


def get_mapping(conn: Connection, mapping_id: int) -> dict | None:
    row = conn.execute(
        """SELECT m.*, c.display_name as epg_channel_name,
                  c.channel_xmltv_id, c.source_id,
                  s.name as source_name, s.url as source_url
           FROM epg_stream_mappings m
           JOIN epg_channels c ON c.id = m.epg_channel_id
           JOIN epg_sources s ON s.id = c.source_id
           WHERE m.id = ?""",
        (mapping_id,),
    ).fetchone()
    return dict(row) if row else None


def list_mappings(conn: Connection, enabled_only: bool = True) -> list[dict]:
    where = "WHERE m.enabled = 1" if enabled_only else ""
    rows = conn.execute(
        f"""SELECT m.*, c.display_name as epg_channel_name,
                   c.channel_xmltv_id, c.source_id,
                   s.name as source_name, s.url as source_url
            FROM epg_stream_mappings m
            JOIN epg_channels c ON c.id = m.epg_channel_id
            JOIN epg_sources s ON s.id = c.source_id
            {where}
            ORDER BY s.name, c.display_name"""
    ).fetchall()
    return [dict(r) for r in rows]


def delete_mapping(conn: Connection, mapping_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM epg_stream_mappings WHERE id = ?", (mapping_id,)
    )
    return cursor.rowcount > 0


def toggle_mapping(conn: Connection, mapping_id: int, enabled: bool) -> dict | None:
    conn.execute(
        "UPDATE epg_stream_mappings SET enabled = ? WHERE id = ?",
        (1 if enabled else 0, mapping_id),
    )
    return get_mapping(conn, mapping_id)


# =============================================================================
# PROGRAMMES
# =============================================================================


def replace_programmes(
    conn: Connection, channel_id: int, programmes: list[dict]
) -> int:
    """Delete existing programmes for channel and insert fresh ones."""
    conn.execute("DELETE FROM epg_programmes WHERE channel_id = ?", (channel_id,))

    count = 0
    for p in programmes:
        categories = json.dumps(p.get("categories", [])) if p.get("categories") else None
        conn.execute(
            """INSERT INTO epg_programmes
               (channel_id, title, start_time, stop_time, description, subtitle, categories)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                channel_id,
                p["title"],
                p["start"],
                p["stop"],
                p.get("description"),
                p.get("subtitle"),
                categories,
            ),
        )
        count += 1
    return count


def list_programmes(
    conn: Connection,
    channel_id: int,
    start_after: str | None = None,
    end_before: str | None = None,
    limit: int = 500,
) -> list[dict]:
    conditions = ["channel_id = ?"]
    params: list = [channel_id]

    if start_after:
        conditions.append("stop_time > ?")
        params.append(start_after)
    if end_before:
        conditions.append("start_time < ?")
        params.append(end_before)

    where = " AND ".join(conditions)
    params.append(limit)

    rows = conn.execute(
        f"""SELECT * FROM epg_programmes
            WHERE {where}
            ORDER BY start_time
            LIMIT ?""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def search_programmes(
    conn: Connection,
    title_pattern: str,
    channel_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    conditions = ["p.title LIKE ?"]
    params: list = [f"%{title_pattern}%"]

    if channel_id is not None:
        conditions.append("p.channel_id = ?")
        params.append(channel_id)

    where = " AND ".join(conditions)
    params.append(limit)

    rows = conn.execute(
        f"""SELECT p.*, c.display_name as channel_name, s.name as source_name
            FROM epg_programmes p
            JOIN epg_channels c ON c.id = p.channel_id
            JOIN epg_sources s ON s.id = c.source_id
            WHERE {where}
            ORDER BY p.start_time
            LIMIT ?""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


# =============================================================================
# MANAGED CHANNELS (tracking what was created in main DB)
# =============================================================================


def record_managed_channel(
    conn: Connection,
    mapping_id: int,
    event_id: str,
    event_provider: str,
    main_db_channel_id: int | None = None,
    programme_title: str | None = None,
    programme_start: str | None = None,
    programme_stop: str | None = None,
) -> dict:
    cursor = conn.execute(
        """INSERT INTO epg_managed_channels
           (mapping_id, event_id, event_provider, main_db_channel_id,
            programme_title, programme_start, programme_stop)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            mapping_id,
            event_id,
            event_provider,
            main_db_channel_id,
            programme_title,
            programme_start,
            programme_stop,
        ),
    )
    row = conn.execute(
        "SELECT * FROM epg_managed_channels WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return dict(row)


def list_managed_channels(
    conn: Connection, mapping_id: int | None = None
) -> list[dict]:
    if mapping_id is not None:
        rows = conn.execute(
            "SELECT * FROM epg_managed_channels WHERE mapping_id = ? ORDER BY programme_start",
            (mapping_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM epg_managed_channels ORDER BY programme_start"
        ).fetchall()
    return [dict(r) for r in rows]


def clear_managed_channels(conn: Connection, mapping_id: int | None = None) -> int:
    if mapping_id is not None:
        cursor = conn.execute(
            "DELETE FROM epg_managed_channels WHERE mapping_id = ?", (mapping_id,)
        )
    else:
        cursor = conn.execute("DELETE FROM epg_managed_channels")
    return cursor.rowcount
