"""A windowed channel pushes only when its active set differs (#1115).

Before #712 the ordering pass could not see Dispatcharr's order, so a channel
carrying a time-windowed (EPG-matched) stream was pushed every run to be sure
each window open and close had landed. Since #712 the pass reads the real order
and compares; a window flip is a difference it already sees. The blind push
survives only for a run that could not read the order at all.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from teamarr.consumers.generation import _apply_stream_ordering
from teamarr.dispatcharr.types import DispatcharrChannel, OperationResult

D_ID = 700
FMT = "%Y-%m-%d %H:%M:%S"


def _stamp(hours: float) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).strftime(FMT)


def _seed(conn, streams: list[tuple[int, str | None, str | None]]):
    """One channel; ``streams`` is (stream_id, attach_at, detach_at) in priority order."""
    conn.execute(
        """INSERT INTO managed_channels
           (id, event_id, event_provider, tvg_id, channel_name,
            channel_number, dispatcharr_channel_id, dispatcharr_uuid)
           VALUES (1, '1001', 'espn', 'teamarr-event-1001', 'Windowed', '5001', ?, 'uuid-700')""",
        (D_ID,),
    )
    for priority, (sid, attach_at, detach_at) in enumerate(streams):
        conn.execute(
            """INSERT INTO managed_channel_streams
               (managed_channel_id, dispatcharr_stream_id, stream_name, priority,
                attach_at, detach_at)
               VALUES (1, ?, ?, ?, ?, ?)""",
            (sid, f"Stream {sid}", priority, attach_at, detach_at),
        )
    conn.commit()


def _manager(dispatcharr_streams: list[int] | None):
    cm = MagicMock()
    if dispatcharr_streams is None:
        cm.get_channels.side_effect = RuntimeError("Dispatcharr unreachable")
    else:
        cm.get_channels.return_value = [
            DispatcharrChannel(
                id=D_ID,
                uuid="uuid-700",
                name="Windowed",
                channel_number="5001",
                tvg_id="teamarr-event-1001",
                streams=tuple(dispatcharr_streams),
            )
        ]
    cm.update_channel.return_value = OperationResult(success=True)
    return cm


def _run(db_factory, cm):
    with patch("teamarr.consumers.generation.ChannelManager", return_value=cm):
        return _apply_stream_ordering(db_factory, MagicMock(), MagicMock())


def _pushed(cm):
    return [call.args[1]["streams"] for call in cm.update_channel.call_args_list]


# Stream 2 is the linear feed: a game stream (1), the feed inside its window (2),
# and a feed whose window has not opened yet (3).
INSIDE = (2, _stamp(-1), _stamp(+2))
NOT_YET = (3, _stamp(+1), _stamp(+4))
CLOSED = (2, _stamp(-3), _stamp(-1))


def test_steady_state_windowed_channel_pushes_nothing(db_factory, db_conn):
    _seed(db_conn, [(1, None, None), INSIDE, NOT_YET])
    cm = _manager([1, 2])  # Dispatcharr already holds the active set

    result = _run(db_factory, cm)

    assert _pushed(cm) == []
    assert result["windows_synced"] == 0
    assert result["order_drift_synced"] == 0


def test_window_opening_pushes_the_feed_in(db_factory, db_conn):
    _seed(db_conn, [(1, None, None), INSIDE])
    cm = _manager([1])  # the window opened since the last push

    result = _run(db_factory, cm)

    assert _pushed(cm) == [[1, 2]]
    assert result["windows_synced"] == 1


def test_window_closing_pushes_the_feed_out(db_factory, db_conn):
    _seed(db_conn, [(1, None, None), CLOSED])
    cm = _manager([1, 2])  # Dispatcharr still lists the feed

    result = _run(db_factory, cm)

    assert _pushed(cm) == [[1]]
    assert result["windows_synced"] == 1


def test_unreadable_dispatcharr_order_still_pushes_blind(db_factory, db_conn):
    """Without the comparison the old every-run push is the safe behaviour."""
    _seed(db_conn, [(1, None, None), INSIDE])
    cm = _manager(None)

    result = _run(db_factory, cm)

    assert _pushed(cm) == [[1, 2]]
    assert result["windows_synced"] == 1


def test_plain_channel_in_sync_is_still_not_pushed(db_factory, db_conn):
    _seed(db_conn, [(1, None, None), (2, None, None)])
    cm = _manager([1, 2])

    result = _run(db_factory, cm)

    assert _pushed(cm) == []
    assert result["windows_synced"] == 0
