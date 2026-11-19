from contextlib import contextmanager
from threading import Barrier, get_ident
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.event_group_processor.processor import EventGroupProcessor
from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.consumers.lifecycle.types import StreamProcessResult
from teamarr.database.channels import get_managed_channel
from teamarr.dispatcharr.types import OperationResult


@pytest.mark.parametrize("team_filter", [True, False])
@pytest.mark.parametrize("error", [None, "Channel not found", "Timeout"])
def test_event_channel_deletion_requires_remote_confirmation(db_factory, team_filter, error):
    manager = MagicMock()
    manager.delete_channel.return_value = OperationResult(success=error is None, error=error)
    lifecycle = ChannelLifecycleService(db_factory, MagicMock(), channel_manager=manager)
    with db_factory() as conn:
        channel_id = conn.execute(
            "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name, "
            "dispatcharr_channel_id) VALUES ('123', 'espn', 'teamarr-event-123', 'Game', 100)"
        ).lastrowid
        channel = get_managed_channel(conn, channel_id)
        if team_filter:
            processor = SimpleNamespace(_get_lifecycle_service=lambda: lifecycle)
            deleted = EventGroupProcessor._delete_channel_for_team_filter(
                processor, conn, channel, "team_filter"
            )
        else:
            deleted = lifecycle.delete_managed_channel(conn, channel_id)

        confirmed = error != "Timeout"
        assert deleted is confirmed
        manager.delete_channel.assert_called_once_with(100)
        with db_factory() as nested:
            assert bool(get_managed_channel(nested, channel_id).deleted_at) is confirmed
            history = nested.execute(
                "SELECT change_source FROM managed_channel_history WHERE managed_channel_id = ? "
                "AND change_type = 'deleted'",
                (channel_id,),
            ).fetchall()
        assert [row[0] for row in history] == (
            ["team_filter" if team_filter else "lifecycle"] if confirmed else []
        )


def test_group_lifecycle_can_write_with_a_second_connection(db_factory):
    lifecycle = MagicMock()
    lifecycle._db_factory = db_factory
    processor = SimpleNamespace(
        _get_lifecycle_service=lambda: lifecycle,
        _initial_reassign_done=True,
        _deletions_processed=False,
    )
    group = SimpleNamespace(id=1, m3u_account_id=None, m3u_account_name=None)
    with db_factory() as outer:
        outer.execute("UPDATE settings SET channel_post_buffer_minutes = 73 WHERE id = 1")

        def scheduled_deletions():
            with db_factory() as inner:
                inner.execute("PRAGMA busy_timeout = 0")
                assert (
                    inner.execute(
                        "SELECT channel_post_buffer_minutes FROM settings WHERE id = 1"
                    ).fetchone()[0]
                    == 73
                )
                inner.execute("UPDATE settings SET channel_post_buffer_minutes = 74 WHERE id = 1")
            return StreamProcessResult()

        lifecycle.process_scheduled_deletions.side_effect = scheduled_deletions
        EventGroupProcessor._process_channels(processor, [], group, outer)

        assert (
            outer.execute(
                "SELECT channel_post_buffer_minutes FROM settings WHERE id = 1"
            ).fetchone()[0]
            == 74
        )


def test_scheduled_deletions_parallelize_http_and_retry_failures(db_factory, monkeypatch):
    caller = get_ident()
    db_open = False

    @contextmanager
    def caller_db():
        nonlocal db_open
        assert get_ident() == caller
        db_open = True
        try:
            with db_factory() as conn:
                yield conn
        finally:
            db_open = False

    manager = MagicMock()
    lifecycle = ChannelLifecycleService(caller_db, MagicMock(), channel_manager=manager)
    with db_factory() as conn:
        conn.executemany(
            "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name, "
            "dispatcharr_channel_id) VALUES (?, 'espn', ?, ?, ?)",
            [(str(i), f"teamarr-event-{i}", f"Game {i}", i) for i in range(101, 105)],
        )

    def recalculate(conn):
        conn.execute("UPDATE managed_channels SET scheduled_delete_at = '2000-01-01T00:00:00Z'")

    monkeypatch.setattr(lifecycle, "_recalculate_deletion_times", recalculate)
    barrier = Barrier(4)
    outcomes = {
        101: OperationResult(success=True),
        102: OperationResult(success=False, error="Channel not found"),
        103: OperationResult(success=False, error="Timeout"),
    }

    def delete(channel_id):
        assert get_ident() != caller
        assert not db_open
        barrier.wait(timeout=5)
        if channel_id == 104:
            raise TimeoutError("Request timed out")
        return outcomes[channel_id]

    manager.delete_channel.side_effect = delete
    result = lifecycle.process_scheduled_deletions()

    assert {entry["tvg_id"] for entry in result.deleted} == {
        "teamarr-event-101",
        "teamarr-event-102",
    }
    assert {entry["channel_name"] for entry in result.errors} == {"Game 103", "Game 104"}
    with db_factory() as conn:
        assert [
            row[0]
            for row in conn.execute(
                "SELECT dispatcharr_channel_id FROM managed_channels "
                "WHERE deleted_at IS NULL ORDER BY dispatcharr_channel_id"
            )
        ] == [103, 104]
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM managed_channel_history WHERE change_type = 'deleted'"
            ).fetchone()[0]
            == 2
        )

    manager.delete_channel.reset_mock(side_effect=True)
    manager.delete_channel.return_value = OperationResult(success=True)
    retried = lifecycle.process_scheduled_deletions()
    assert not retried.errors
    assert len(retried.deleted) == 2
    assert {call.args[0] for call in manager.delete_channel.call_args_list} == {103, 104}


def test_scheduled_delete_preserves_a_replaced_remote_mapping(db_factory):
    manager = MagicMock()
    lifecycle = ChannelLifecycleService(db_factory, MagicMock(), channel_manager=manager)
    with db_factory() as conn:
        channel_id = conn.execute(
            "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name, "
            "dispatcharr_channel_id, scheduled_delete_at) "
            "VALUES ('123', 'espn', 'teamarr-event-123', 'Game', 100, '2000-01-01T00:00:00Z')"
        ).lastrowid

    def delete(_dispatcharr_id):
        # Another operation changes the mapping while the original DELETE is in flight.
        with db_factory() as conn:
            conn.execute(
                "UPDATE managed_channels SET dispatcharr_channel_id = 101 WHERE id = ?",
                (channel_id,),
            )
        return OperationResult(success=True)

    manager.delete_channel.side_effect = delete
    result = lifecycle.process_scheduled_deletions()

    assert not result.deleted
    with db_factory() as conn:
        channel = get_managed_channel(conn, channel_id)
        assert channel.dispatcharr_channel_id == 101
        assert channel.deleted_at is None
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM managed_channel_history WHERE change_type = 'deleted'"
            ).fetchone()[0]
            == 0
        )
