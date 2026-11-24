"""Take a stream off one managed channel, and put it back (#1173).

The removal is the soft-removed stream row itself, marked ``user_removed``.
Every path that attaches a stream to a channel checks that marker, so the
stream stays off until the user undoes it or the channel retires. An event
channel's marker goes with the channel; a team channel outlives its games, so
its marker covers the game the stream was carrying.

No connection is held across a Dispatcharr request (#735), and a failed
request leaves nothing stored, so the dashboard and Dispatcharr never disagree
about a removal.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class StreamNotOnChannel(Exception):
    """The channel does not exist, or the stream is not in the stated state on it."""


class DispatcharrUpdateFailed(Exception):
    """Dispatcharr refused or did not answer the stream-list update."""


def _remote_streams(channel_manager: Any, dispatcharr_channel_id: int | None) -> list[int] | None:
    """The channel's live stream list, or None when there is no channel to change.

    None means Dispatcharr is not configured, the channel was never created
    there, or Dispatcharr confirmed it is gone. A read that failed is none of
    those: it is refused, so a removal is never stored that Dispatcharr did
    not hear about.
    """
    if channel_manager is None or not dispatcharr_channel_id:
        return None
    try:
        remote, confirmed_absent = channel_manager.get_channel_existence(
            dispatcharr_channel_id, use_cache=False
        )
    except Exception as exc:
        raise DispatcharrUpdateFailed(f"could not read the channel: {exc}") from exc
    if remote is None:
        if confirmed_absent:
            return None
        raise DispatcharrUpdateFailed("could not read the channel")
    return list(remote.streams or ())


def _push(channel_manager: Any, dispatcharr_channel_id: int, streams: list[int]) -> None:
    try:
        result = channel_manager.update_channel(dispatcharr_channel_id, {"streams": streams})
    except Exception as exc:
        raise DispatcharrUpdateFailed(str(exc)) from exc
    if not result.success:
        raise DispatcharrUpdateFailed(result.error or "Dispatcharr update failed")


def _in_window(attach_at: Any, detach_at: Any, now: datetime) -> bool:
    """Whether a membership is active now. No window = always."""
    if not attach_at:
        return True
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    return str(attach_at) <= stamp and (not detach_at or stamp < str(detach_at))


# ---------------------------------------------------------------------------
# Event channels
# ---------------------------------------------------------------------------


def remove_event_stream(
    db_factory: Callable, channel_manager: Any, channel_id: int, stream_id: int
) -> str | None:
    """Remove a stream from an event channel. Returns the stream's name."""
    from teamarr.database.channels import (
        USER_REMOVED_REASON,
        get_channel_streams,
        get_managed_channel,
        log_channel_history,
        remove_stream_from_channel,
    )

    with db_factory() as conn:
        channel = get_managed_channel(conn, channel_id)
        if not channel or channel.deleted_at:
            raise StreamNotOnChannel(f"Channel {channel_id} not found")
        rows = [
            s for s in get_channel_streams(conn, channel_id) if s.dispatcharr_stream_id == stream_id
        ]
        if not rows:
            raise StreamNotOnChannel(f"Stream {stream_id} is not on channel {channel_id}")
        stream_name = rows[0].stream_name
        dispatcharr_channel_id = channel.dispatcharr_channel_id

    remote = _remote_streams(channel_manager, dispatcharr_channel_id)
    if remote is not None and dispatcharr_channel_id and stream_id in remote:
        _push(channel_manager, dispatcharr_channel_id, [s for s in remote if s != stream_id])

    with db_factory() as conn:
        remove_stream_from_channel(conn, channel_id, stream_id, reason=USER_REMOVED_REASON)
        log_channel_history(
            conn=conn,
            managed_channel_id=channel_id,
            change_type="stream_removed",
            change_source="manual",
            notes=f"Stream '{stream_name}' ({stream_id}) removed by the user",
        )
    logger.info(
        "[CHANNELS] Stream %d ('%s') removed from channel %d by the user",
        stream_id,
        stream_name,
        channel_id,
    )
    return stream_name


def restore_event_stream(
    db_factory: Callable, channel_manager: Any, channel_id: int, stream_id: int
) -> str | None:
    """Undo a user's removal on an event channel. Returns the stream's name."""
    from teamarr.database.channels import (
        get_managed_channel,
        get_user_removed_streams,
        log_channel_history,
        restore_user_removed_stream,
    )

    with db_factory() as conn:
        channel = get_managed_channel(conn, channel_id)
        if not channel or channel.deleted_at:
            raise StreamNotOnChannel(f"Channel {channel_id} not found")
        rows = [
            s
            for s in get_user_removed_streams(conn, channel_id)
            if s.dispatcharr_stream_id == stream_id
        ]
        if not rows:
            raise StreamNotOnChannel(
                f"Stream {stream_id} was not removed from channel {channel_id}"
            )
        row = rows[0]
        dispatcharr_channel_id = channel.dispatcharr_channel_id

    # Appended, not re-sorted: the ordering pass of the next run places it,
    # and a live event's first stream is left where viewers have it (#232).
    # A time-shared stream outside its slot is restored in the database only;
    # the window sync attaches it when the slot opens.
    remote = _remote_streams(channel_manager, dispatcharr_channel_id)
    if (
        remote is not None
        and dispatcharr_channel_id
        and stream_id not in remote
        and _in_window(row.attach_at, row.detach_at, datetime.now(UTC))
    ):
        _push(channel_manager, dispatcharr_channel_id, [*remote, stream_id])

    with db_factory() as conn:
        restore_user_removed_stream(conn, channel_id, stream_id)
        log_channel_history(
            conn=conn,
            managed_channel_id=channel_id,
            change_type="stream_added",
            change_source="manual",
            notes=f"Stream '{row.stream_name}' ({stream_id}) restored by the user",
        )
    logger.info(
        "[CHANNELS] Stream %d ('%s') restored to channel %d by the user",
        stream_id,
        row.stream_name,
        channel_id,
    )
    return row.stream_name


# ---------------------------------------------------------------------------
# Team channels
# ---------------------------------------------------------------------------


def _owned_team_channel(conn: Any, team_id: int) -> dict:
    from teamarr.database.managed_team_channels import list_owned_enabled_managed_team_channels

    for channel in list_owned_enabled_managed_team_channels(conn):
        if int(channel["team_id"]) == team_id:
            return channel
    raise StreamNotOnChannel(f"Team channel {team_id} not found")


def _apply_team_change(
    db_factory: Callable,
    channel_manager: Any,
    team_id: int,
    stream_id: int,
    *,
    removing: bool,
) -> None:
    """Store a team-channel change, push the resulting list, undo on failure.

    A team channel shows one game's streams at a time, so what the channel
    should hold after the change is a database question (the next game may
    take over); the list is computed from the stored rows rather than edited
    in place. That makes this the one path that writes before it pushes, so
    a failed push puts the rows back.
    """
    from teamarr.database.managed_team_channel_streams import (
        active_stream_ids,
        mark_team_stream_rows,
        remove_team_stream_by_user,
        restore_team_stream_by_user,
    )

    with db_factory() as conn:
        channel = _owned_team_channel(conn, team_id)
        change = remove_team_stream_by_user if removing else restore_team_stream_by_user
        row_ids = change(conn, team_id, stream_id)
        if not row_ids:
            state = "is not on" if removing else "was not removed from"
            raise StreamNotOnChannel(f"Stream {stream_id} {state} team channel {team_id}")
        ordered = active_stream_ids(conn, team_id)
    dispatcharr_channel_id = channel["dispatcharr_channel_id"]
    try:
        remote = _remote_streams(channel_manager, dispatcharr_channel_id)
        if remote is not None and remote != ordered:
            _push(channel_manager, dispatcharr_channel_id, ordered)
    except Exception:
        with db_factory() as conn:
            mark_team_stream_rows(conn, row_ids, removed=not removing)
        raise
    logger.info(
        "[TEAM_CHANNEL] Stream %d %s team %d by the user",
        stream_id,
        "removed from" if removing else "restored to",
        team_id,
    )


def remove_team_stream(
    db_factory: Callable, channel_manager: Any, team_id: int, stream_id: int
) -> None:
    """Remove a stream from a team channel for the game it is carrying."""
    _apply_team_change(db_factory, channel_manager, team_id, stream_id, removing=True)


def restore_team_stream(
    db_factory: Callable, channel_manager: Any, team_id: int, stream_id: int
) -> None:
    """Undo a user's removal on a team channel."""
    _apply_team_change(db_factory, channel_manager, team_id, stream_id, removing=False)
