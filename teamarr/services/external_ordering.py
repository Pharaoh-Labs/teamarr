"""Persistent ordering ownership and the recoverable external-write protocol."""

import hashlib
import json
from contextlib import contextmanager

from teamarr.database import get_db
from teamarr.services.ordering_lock import ProcessLock


class OrderingConflict(ValueError):
    pass


def preserve_live_order(live: list[int], desired: list[int]) -> list[int]:
    """Keep surviving live members in place, then append newly desired members."""
    wanted = set(desired)
    survivors = [stream for stream in live if stream in wanted]
    present = set(survivors)
    return survivors + [stream for stream in desired if stream not in present]


def find_channel(conn, channel_id: int):
    """Include plugins, disabled teams and deleted rows: ambiguity fails closed."""
    matches = []
    for table, key in (("managed_channels", "id"), ("managed_team_channels", "team_id")):
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE dispatcharr_channel_id = ?", (channel_id,)
        ):
            matches.append((table, key, dict(row)))
    if len(matches) > 1:
        raise OrderingConflict("Dispatcharr channel has multiple Teamarr ownership records")
    if matches and matches[0][2].get("deleted_at"):
        raise OrderingConflict("Dispatcharr channel has a retired Teamarr ownership record")
    return matches[0] if matches else None


@contextmanager
def channel_order_lock(channel_id: int):
    # Independent lock instances still contend through flock, including threads.
    lock = ProcessLock(f"channel-{channel_id}-order")
    if not lock.acquire(blocking=False):
        raise OrderingConflict("Channel ordering is busy")
    try:
        yield
    finally:
        lock.release()


def prepare_internal_order(manager, channel_id: int, desired: list[int]) -> list[int]:
    """Final network boundary; never trust a cached order on an external channel.

    The caller holds channel_order_lock through the remote write. Read-only DB
    access is deliberate: lifecycle callers can already hold a SQLite writer.
    """
    with get_db() as conn:
        match = find_channel(conn, channel_id)
    if not match or match[2]["ordering_owner"] == "teamarr":
        return desired
    if match[2]["external_order_pending"] is not None:
        raise OrderingConflict("External order is uncertain; retry the external PUT first")
    live = manager.get_channel(channel_id, use_cache=False)
    if live is None:
        raise OrderingConflict("Cannot read live externally ordered channel")
    return preserve_live_order(list(live.streams), desired)


def persist_positions(conn, match, streams: list[int]) -> None:
    table, key, row = match
    if table == "managed_channels":
        membership_table, membership_key = "managed_channel_streams", "managed_channel_id"
    else:
        membership_table, membership_key = "managed_team_channel_streams", "team_id"
    for priority, stream_id in enumerate(streams):
        conn.execute(
            f"UPDATE {membership_table} SET priority = ? WHERE {membership_key} = ? "
            "AND dispatcharr_stream_id = ? AND removed_at IS NULL",
            (priority, row[key], stream_id),
        )
    digest = hashlib.sha256(json.dumps(streams).encode()).hexdigest()
    conn.execute(
        f"UPDATE {table} SET stream_order_hash = ?, external_order_pending = NULL WHERE {key} = ?",
        (digest, row[key]),
    )


def apply_external_order(channel_id: int, streams: list[int], manager, db_factory=get_db):
    """Called under generation AND channel locks. Intent commits before HTTP.

    Pending intent fences all automatic writes after a failure/crash. A retry
    repeats the same idempotent full replacement then finishes local state.
    """
    with db_factory() as conn:
        match = find_channel(conn, channel_id)
    if match is None:
        return {"managed": False, "applied": False}
    if manager is None:
        raise RuntimeError("Dispatcharr is unavailable")
    live = manager.get_channel(channel_id, use_cache=False)
    if live is None:
        raise RuntimeError("Cannot read Dispatcharr channel membership")
    table, key, row = match
    with db_factory() as conn:
        membership_table, membership_key = (
            ("managed_channel_streams", "managed_channel_id")
            if table == "managed_channels"
            else ("managed_team_channel_streams", "team_id")
        )
        # Previously removed local candidates may be restored (manual undo).
        # A caller cannot invent a match or activate a future/expired window.
        window = (
            "(attach_at IS NULL OR (attach_at <= datetime('now') AND datetime('now') < detach_at))"
            if table == "managed_channels"
            else "(attach_at IS NULL OR attach_at = '' OR attach_at <= datetime('now')) "
            "AND (detach_at IS NULL OR detach_at > datetime('now'))"
        )
        candidates = conn.execute(
            f"SELECT * FROM {membership_table} WHERE {membership_key} = ? AND {window}",
            (row[key],),
        ).fetchall()
        if table == "managed_team_channels" and candidates:
            chosen = min(
                [r for r in candidates if r["removed_at"] is None] or candidates,
                key=lambda r: (
                    r["event_start"] is None,
                    r["event_start"] or "",
                    r["detach_at"] is None,
                    r["detach_at"] or "",
                    r["event_id"],
                    r["event_provider"],
                ),
            )
            candidates = [
                r
                for r in candidates
                if (r["event_id"], r["event_provider"])
                == (chosen["event_id"], chosen["event_provider"])
            ]
        allowed = {r["dispatcharr_stream_id"] for r in candidates}
        unsupported = set(streams) - allowed
        if unsupported:
            raise ValueError(f"Unsupported membership additions: {sorted(unsupported)}")
        previous = json.loads(row["external_order_pending"] or "null")
        active_local = {r["dispatcharr_stream_id"] for r in candidates if r["removed_at"] is None}
        removed = (set(live.streams) | active_local) - set(streams)
        if previous:
            removed |= set(previous["removed"]) - set(streams)
        intent = {"streams": streams, "removed": sorted(removed)}
        conn.execute(
            f"UPDATE {table} SET ordering_owner = 'podium', external_order_pending = ? "
            f"WHERE {key} = ?",
            (json.dumps(intent), row[key]),
        )
    result = manager.update_channel(channel_id, {"streams": streams}, external_order=True)
    if not result.success:
        raise RuntimeError(result.error or "Dispatcharr order write failed")
    # HTTP success alone is insufficient when Dispatcharr silently changes it.
    confirmed = manager.get_channel(channel_id, use_cache=False)
    if confirmed is None or list(confirmed.streams) != streams:
        raise RuntimeError("Dispatcharr did not confirm the submitted stream order")
    with db_factory() as conn:
        membership_table, membership_key = (
            ("managed_channel_streams", "managed_channel_id")
            if table == "managed_channels"
            else ("managed_team_channel_streams", "team_id")
        )
        # Future windows remain intact, even when they reuse a live stream ID.
        removed_ids = {
            r["id"] for r in candidates if r["dispatcharr_stream_id"] in intent["removed"]
        }
        removal_reason = ", remove_reason = 'external_order'" if table == "managed_channels" else ""
        for removed_id in removed_ids:
            conn.execute(
                f"UPDATE {membership_table} SET removed_at = CURRENT_TIMESTAMP{removal_reason} "
                "WHERE id = ? AND removed_at IS NULL",
                (removed_id,),
            )
        for stream_id in streams:
            stream_rows = [r for r in candidates if r["dispatcharr_stream_id"] == stream_id]
            active_rows = [r for r in stream_rows if r["removed_at"] is None]
            # Do not resurrect every historical attachment of the same stream.
            # Keep current provenance, or restore the newest eligible record.
            restored = active_rows or [max(stream_rows, key=lambda r: r["id"])]
            for candidate_id in [r["id"] for r in restored]:
                conn.execute(
                    f"UPDATE {membership_table} SET removed_at = NULL"
                    + (", remove_reason = NULL" if table == "managed_channels" else "")
                    + " WHERE id = ?",
                    (candidate_id,),
                )
        persist_positions(conn, match, streams)
    return {"managed": True, "applied": True}
