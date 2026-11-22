"""The batched stream flush isolates each channel (#1278).

`_flush_pending_stream_pushes` empties its queue and then walks the channels.
The added rows are already committed by then, so an exception escaping one
channel used to leave every later channel's streams in the DB, never PATCHed
to Dispatcharr and with no `stream_added` history. A channel that raises is
now rolled back like a rejected PATCH, counted, and the loop carries on.
"""

import sqlite3
from unittest.mock import MagicMock, call, patch

import pytest

import teamarr.database.channels as channels_db
from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.consumers.lifecycle.types import StreamProcessResult
from teamarr.database.channels import (
    add_stream_to_channel,
    get_channel_streams,
    get_managed_channel,
)
from teamarr.dispatcharr.types import DispatcharrChannel, OperationResult
from tests.fakes import FakeEvent


def _disp_id(n: int) -> int:
    return 100 + n


def _on(n: int) -> int:
    """The stream already on channel n, locally and in Dispatcharr."""
    return 1000 + n


def _new(n: int) -> int:
    """The stream consolidated onto channel n this run."""
    return 2000 + n


def _make_channel(conn, n: int):
    conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name, "
        "dispatcharr_channel_id) VALUES (?, 'espn', ?, ?, ?)",
        (str(n), f"teamarr-event-{n}", f"Game {n}", _disp_id(n)),
    )
    channel_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    add_stream_to_channel(conn, channel_id, _on(n), f"Main {n}", priority=1)
    conn.commit()
    return get_managed_channel(conn, channel_id)


def _service():
    cm = MagicMock()

    def existence(disp_id):
        n = disp_id - 100
        return (
            DispatcharrChannel(
                id=disp_id,
                uuid=f"uuid-{disp_id}",
                name=f"Game {n}",
                channel_number=str(5000 + n),
                tvg_id=f"teamarr-event-{n}",
                channel_group_id=None,
                logo_id=None,
                logo_url=None,
                streams=(_on(n),),
                stream_profile_id=None,
            ),
            False,
        )

    cm.get_channel_existence.side_effect = existence
    cm.update_channel.return_value = OperationResult(success=True)
    sports_service = MagicMock()
    sports_service.get_sport_display_name.return_value = "Football"
    service = ChannelLifecycleService(
        db_factory=MagicMock(),
        sports_service=sports_service,
        channel_manager=cm,
        logo_manager=MagicMock(),
        epg_manager=MagicMock(),
        m3u_manager=MagicMock(),
    )
    service._sync_channel_settings = MagicMock(return_value=StreamProcessResult())
    return service, cm


def _queue(service, conn, channel, stream_id) -> None:
    service._handle_existing_channel(
        conn=conn,
        existing=channel,
        stream={"id": stream_id, "name": f"Feed {stream_id}"},
        event=FakeEvent(),
        effective_mode="consolidate",
        matched_keyword=None,
        group_config={},
        template=None,
    )


def _setup(conn, count: int):
    """`count` channels, each with one new stream queued for the flush."""
    service, cm = _service()
    chans = [_make_channel(conn, n) for n in range(1, count + 1)]
    for n, chan in enumerate(chans, start=1):
        _queue(service, conn, chan, _new(n))
    cm.update_channel.assert_not_called()
    return service, cm, chans


def _history_fails_for(*channel_ids: int):
    """Patch the history write to reject `stream_added` for these channels."""
    real = channels_db.log_channel_history

    def fake(conn, managed_channel_id, change_type, *args, **kwargs):
        if managed_channel_id in channel_ids and change_type == "stream_added":
            raise sqlite3.IntegrityError("history insert rejected")
        return real(conn, managed_channel_id, change_type, *args, **kwargs)

    return patch.object(channels_db, "log_channel_history", side_effect=fake)


def _active(conn, channel_id) -> set[int]:
    return {s.dispatcharr_stream_id for s in get_channel_streams(conn, channel_id)}


def _added_history(conn, channel_id) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM managed_channel_history "
        "WHERE managed_channel_id = ? AND change_type = 'stream_added'",
        (channel_id,),
    ).fetchone()[0]


def _push(n: int):
    return call(_disp_id(n), {"streams": [_on(n), _new(n)]})


def _error_channels(result) -> list[int]:
    return [e["channel_id"] for e in result.errors]


def _added_names(result) -> list[str]:
    return [a["stream"] for a in result.streams_added]


def _assert_rolled_back(conn, chan, n: int) -> None:
    """Same end state as a rejected PATCH: added stream gone, no history."""
    assert _active(conn, chan.id) == {_on(n)}
    assert _added_history(conn, chan.id) == 0


def _assert_pushed(conn, chan, n: int) -> None:
    assert _active(conn, chan.id) == {_on(n), _new(n)}
    assert _added_history(conn, chan.id) == 1


def test_first_channel_failure_does_not_drop_the_second_push(db_conn):
    """The #1278 reproduction."""
    service, cm, (first, second) = _setup(db_conn, 2)
    result = StreamProcessResult()

    with _history_fails_for(first.id):
        service._flush_pending_stream_pushes(db_conn, result)

    assert cm.update_channel.call_args_list == [_push(1), _push(2)]
    _assert_pushed(db_conn, second, 2)
    _assert_rolled_back(db_conn, first, 1)
    assert _added_names(result) == [f"Feed {_new(2)}"]
    assert _error_channels(result) == [first.id]
    assert not db_conn.in_transaction
    assert service._pending_stream_pushes == {}


def test_profile_changes_still_apply_when_one_channel_fails(db_conn, db_factory):
    """Through the driver, on connections that really close (#938)."""
    service, cm, (first, second) = _setup(db_conn, 2)
    service._db_factory = db_factory
    service._apply_pending_profile_changes = MagicMock(return_value={})

    with _history_fails_for(first.id):
        result = service.process_matched_streams([], {})

    # The normal path hands over its connection; the outer except calls bare.
    service._apply_pending_profile_changes.assert_called_once()
    assert len(service._apply_pending_profile_changes.call_args.args) == 1
    assert cm.update_channel.call_args_list == [_push(1), _push(2)]
    _assert_pushed(db_conn, second, 2)
    _assert_rolled_back(db_conn, first, 1)
    assert result.errors == [
        {"channel_id": first.id, "error": "Stream push failed: history insert rejected"}
    ]


def test_failure_on_the_last_channel(db_conn):
    service, cm, (first, second) = _setup(db_conn, 2)
    result = StreamProcessResult()

    with _history_fails_for(second.id):
        service._flush_pending_stream_pushes(db_conn, result)

    assert cm.update_channel.call_args_list == [_push(1), _push(2)]
    _assert_pushed(db_conn, first, 1)
    _assert_rolled_back(db_conn, second, 2)
    assert _error_channels(result) == [second.id]


def test_failure_on_the_only_channel(db_conn):
    service, cm, (only,) = _setup(db_conn, 1)
    result = StreamProcessResult()

    with _history_fails_for(only.id):
        service._flush_pending_stream_pushes(db_conn, result)

    _assert_rolled_back(db_conn, only, 1)
    assert result.streams_added == []
    assert _error_channels(result) == [only.id]


def test_middle_of_three_fails_and_the_others_push_in_order(db_conn):
    service, cm, (first, middle, third) = _setup(db_conn, 3)
    result = StreamProcessResult()

    with _history_fails_for(middle.id):
        service._flush_pending_stream_pushes(db_conn, result)

    assert cm.update_channel.call_args_list == [_push(1), _push(2), _push(3)]
    _assert_pushed(db_conn, first, 1)
    _assert_rolled_back(db_conn, middle, 2)
    _assert_pushed(db_conn, third, 3)
    assert _added_names(result) == [f"Feed {_new(1)}", f"Feed {_new(3)}"]
    assert _error_channels(result) == [middle.id]


def test_partial_history_of_a_failed_channel_is_not_kept(db_conn):
    """Two streams added; the second history write fails after the first ran."""
    service, cm, (first, second) = _setup(db_conn, 2)
    extra = 2901
    _queue(service, db_conn, first, extra)
    result = StreamProcessResult()
    real = channels_db.log_channel_history
    seen = []

    def fake(conn, managed_channel_id, change_type, *args, **kwargs):
        if managed_channel_id == first.id and change_type == "stream_added":
            seen.append(1)
            if len(seen) == 2:
                raise sqlite3.OperationalError("database is locked")
        return real(conn, managed_channel_id, change_type, *args, **kwargs)

    with patch.object(channels_db, "log_channel_history", side_effect=fake):
        service._flush_pending_stream_pushes(db_conn, result)

    assert len(seen) == 2
    _assert_rolled_back(db_conn, first, 1)
    _assert_pushed(db_conn, second, 2)
    assert _added_names(result) == [f"Feed {_new(2)}"]


@pytest.mark.parametrize("raises", [True, False])
def test_client_error_on_one_channel_keeps_the_rest(db_conn, raises):
    """A raised client error and a returned failure end the same way."""
    service, cm, (first, second) = _setup(db_conn, 2)
    result = StreamProcessResult()

    def update_channel(disp_id, _data):
        if disp_id == _disp_id(1):
            if raises:
                raise ConnectionError("connection reset")
            return OperationResult(success=False, error="Timeout")
        return OperationResult(success=True)

    cm.update_channel.side_effect = update_channel

    service._flush_pending_stream_pushes(db_conn, result)

    assert cm.update_channel.call_args_list == [_push(1), _push(2)]
    _assert_rolled_back(db_conn, first, 1)
    _assert_pushed(db_conn, second, 2)
    assert result.errors == [{"channel_id": first.id, "error": "Stream update failed"}]
    assert service._dispatcharr_failure_count == 1


def test_rollback_that_raises_leaves_the_rows_and_continues(db_conn, caplog):
    service, cm, (first, second, third) = _setup(db_conn, 3)
    result = StreamProcessResult()

    with (
        _history_fails_for(first.id),
        patch.object(
            channels_db,
            "remove_stream_from_channel",
            side_effect=sqlite3.OperationalError("database is locked"),
        ),
    ):
        service._flush_pending_stream_pushes(db_conn, result)

    assert cm.update_channel.call_args_list == [_push(1), _push(2), _push(3)]
    # Left as they were for the ordering pass; never reported as added.
    assert _active(db_conn, first.id) == {_on(1), _new(1)}
    assert _added_history(db_conn, first.id) == 0
    _assert_pushed(db_conn, second, 2)
    _assert_pushed(db_conn, third, 3)
    assert _added_names(result) == [f"Feed {_new(2)}", f"Feed {_new(3)}"]
    assert _error_channels(result) == [first.id]
    assert "Could not roll back added streams" in caplog.text
    assert not db_conn.in_transaction


def test_rejected_patch_whose_rollback_raises_still_continues(db_conn):
    service, cm, (first, second) = _setup(db_conn, 2)
    result = StreamProcessResult()
    cm.update_channel.side_effect = lambda disp_id, _data: OperationResult(
        success=disp_id != _disp_id(1), error="Timeout"
    )

    with patch.object(
        channels_db,
        "remove_stream_from_channel",
        side_effect=sqlite3.OperationalError("database is locked"),
    ):
        service._flush_pending_stream_pushes(db_conn, result)

    assert cm.update_channel.call_args_list == [_push(1), _push(2)]
    _assert_pushed(db_conn, second, 2)
    assert _error_channels(result) == [first.id]


def test_run_without_failures_is_unchanged(db_conn):
    """Same PATCH calls, order and payloads as before the isolation."""
    service, cm, chans = _setup(db_conn, 3)
    result = StreamProcessResult()

    service._flush_pending_stream_pushes(db_conn, result)

    assert cm.update_channel.call_args_list == [
        call(101, {"streams": [1001, 2001]}),
        call(102, {"streams": [1002, 2002]}),
        call(103, {"streams": [1003, 2003]}),
    ]
    for n, chan in enumerate(chans, start=1):
        _assert_pushed(db_conn, chan, n)
    assert result.errors == []
    assert result.streams_added == [
        {"stream": f"Feed {_new(n)}", "channel_id": _disp_id(n), "channel_name": f"Game {n}"}
        for n in (1, 2, 3)
    ]
    assert service._dispatcharr_failure_count == 0
