"""Regression tests for #512: channel-source cleanup must not read pool
absence as "removed from source".

The hidden Dispatcharr-channels group's candidate pool is DERIVED from the
stream->channel map, not an authoritative M3U listing. When the pool builder
lost a stream (a Teamarr channel had stolen its map slot inside the attach
window), cleanup treated it as missing-from-M3U, deleted the channel, and the
recreate seeded from the other provider — an A/B oscillation every cycle.
With is_channel_source=True the missing-branch is skipped entirely; rotation
detection still applies.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

GROUP_ID = 1


@pytest.fixture
def service():
    from teamarr.consumers.lifecycle.service import ChannelLifecycleService

    svc = ChannelLifecycleService(
        db_factory=MagicMock(),
        sports_service=MagicMock(),
        channel_manager=MagicMock(),
    )
    svc._remove_stream_from_dispatcharr_channel = MagicMock(return_value=True)
    svc.delete_managed_channel = MagicMock(return_value=True)
    return svc


def _channel(cid, event_id, name="Ch"):
    return SimpleNamespace(
        id=cid,
        dispatcharr_channel_id=1000 + cid,
        channel_number=cid,
        channel_name=name,
        event_id=event_id,
        primary_stream_id=None,
    )


def _stream(sid, name):
    return SimpleNamespace(
        dispatcharr_stream_id=sid,
        source_group_id=GROUP_ID,
        stream_name=name,
    )


def _run_cleanup(service, channels, streams_by_channel, current_streams, matched, **kwargs):
    with (
        patch(
            "teamarr.database.channels.get_managed_channels_for_group",
            return_value=channels,
        ),
        patch(
            "teamarr.database.channels.get_channel_streams",
            side_effect=lambda conn, cid, include_removed=False: streams_by_channel.get(cid, []),
        ),
        patch("teamarr.database.channels.remove_stream_from_channel"),
        patch("teamarr.database.channels.update_stream_name"),
        patch("teamarr.database.channels.log_channel_history"),
    ):
        return service.cleanup_deleted_streams(
            GROUP_ID, current_streams, matched_streams=matched, **kwargs
        )


def _match(sid, event_id, name):
    return {
        "stream": {"id": sid, "name": name},
        "event": SimpleNamespace(id=event_id),
    }


def test_pool_absence_does_not_delete_channel_source_channel(service):
    """The #512 flap: all of a channel's streams vanish from the derived pool
    (their map slots were stolen by the in-window attachment) — the channel
    must survive."""
    channel = _channel(7, "38659", "Carlton vs Gold Coast")
    streams = [_stream(100, "Fox Sports 504"), _stream(101, "Fox Footy")]

    result = _run_cleanup(
        service,
        channels=[channel],
        streams_by_channel={7: streams},
        current_streams={},  # pool lost every stream this cycle
        matched=[],
        is_channel_source=True,
    )

    service.delete_managed_channel.assert_not_called()
    assert result.deleted == []


def test_same_pool_absence_still_deletes_for_regular_group(service):
    """Regular M3U groups keep missing-from-M3U semantics unchanged."""
    channel = _channel(7, "38659", "Carlton vs Gold Coast")
    streams = [_stream(100, "Fox Sports 504")]

    result = _run_cleanup(
        service,
        channels=[channel],
        streams_by_channel={7: streams},
        current_streams={},
        matched=[],
    )

    service.delete_managed_channel.assert_called_once()
    assert len(result.deleted) == 1


def test_channel_source_rotation_still_detected(service):
    """Skipping the missing-branch must not disable rotation cleanup."""
    channel = _channel(8, "38659", "Carlton vs Gold Coast")
    streams = [_stream(100, "Fox Sports 504")]

    result = _run_cleanup(
        service,
        channels=[channel],
        streams_by_channel={8: streams},
        current_streams={100: {"name": "Fox Sports 504"}},
        matched=[_match(100, "99999", "Fox Sports 504")],  # moved to another event
        is_channel_source=True,
    )

    service.delete_managed_channel.assert_called_once()
    assert len(result.deleted) == 1
    assert "rotated" in result.deleted[0]["reason"]
