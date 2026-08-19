"""Tests for stream-level disabled-group cleanup (teamarrv2-5xou).

Disabling a source group must detach only that group's streams and delete a
channel only when nothing else feeds it — so consolidated/multi-source channels
survive when one of several contributing groups is disabled.
"""

from unittest.mock import MagicMock, patch

import pytest

from tests.fakes import FakeChannel, FakeGroup, FakeStream


@pytest.fixture
def service():
    from teamarr.consumers.lifecycle.service import ChannelLifecycleService

    svc = ChannelLifecycleService(
        db_factory=MagicMock(),
        sports_service=MagicMock(),
        channel_manager=MagicMock(),
    )
    # Observe the side effects rather than hitting Dispatcharr/DB.
    svc._remove_stream_from_dispatcharr_channel = MagicMock(return_value=True)
    svc.delete_managed_channel = MagicMock(return_value=True)
    return svc


def _run(service, groups, channels_for_group, streams_by_channel):
    with (
        patch(
            "teamarr.database.groups.get_all_groups",
            return_value=groups,
        ),
        patch(
            "teamarr.database.channels.get_managed_channels_for_group",
            side_effect=lambda conn, gid, include_deleted=False: channels_for_group.get(gid, []),
        ),
        patch(
            "teamarr.database.channels.get_channel_streams",
            side_effect=lambda conn, cid, include_removed=False: streams_by_channel.get(cid, []),
        ),
        patch("teamarr.database.channels.remove_stream_from_channel") as rm,
    ):
        result = service.cleanup_disabled_groups()
    return result, rm


def test_multi_source_channel_survives_when_one_group_disabled(service):
    # Channel fed by disabled group 38 AND enabled groups 52, 40.
    ch = FakeChannel(id=10)
    result, rm = _run(
        service,
        groups=[FakeGroup(id=38, name="NHL Backup", enabled=False)],
        channels_for_group={38: [ch]},
        streams_by_channel={
            10: [
                FakeStream(dispatcharr_stream_id=1, source_group_id=38),
                FakeStream(dispatcharr_stream_id=2, source_group_id=52),
                FakeStream(dispatcharr_stream_id=3, source_group_id=40),
            ]
        },
    )
    # Only group 38's stream detached; channel NOT deleted.
    assert result["detached"] == 1
    rm.assert_called_once()
    assert rm.call_args.args[2] == 1  # dispatcharr_stream_id of group-38 stream
    service.delete_managed_channel.assert_not_called()
    assert result["deleted"] == []


def test_single_source_channel_deleted(service):
    ch = FakeChannel(id=11)
    result, _ = _run(
        service,
        groups=[FakeGroup(id=38, name="NHL Backup", enabled=False)],
        channels_for_group={38: [ch]},
        streams_by_channel={11: [FakeStream(dispatcharr_stream_id=9, source_group_id=38)]},
    )
    assert result["detached"] == 1
    service.delete_managed_channel.assert_called_once()
    assert service.delete_managed_channel.call_args.args[1] == 11


def test_provenance_only_channel_with_other_streams_survives(service):
    # Returned because provenance == 38, but all its active streams are from other
    # (enabled) groups. Nothing to detach; must not be deleted.
    ch = FakeChannel(id=12)
    result, rm = _run(
        service,
        groups=[FakeGroup(id=38, enabled=False)],
        channels_for_group={38: [ch]},
        streams_by_channel={
            12: [
                FakeStream(dispatcharr_stream_id=4, source_group_id=52),
                FakeStream(dispatcharr_stream_id=5, source_group_id=40),
            ]
        },
    )
    assert result["detached"] == 0
    rm.assert_not_called()
    service.delete_managed_channel.assert_not_called()


def test_no_disabled_groups_is_noop(service):
    result, rm = _run(
        service,
        groups=[FakeGroup(id=1, enabled=True)],
        channels_for_group={},
        streams_by_channel={},
    )
    assert result == {"deleted": [], "detached": 0, "errors": []}
    rm.assert_not_called()
    service.delete_managed_channel.assert_not_called()
