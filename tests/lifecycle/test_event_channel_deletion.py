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
