"""Regression tests for #514: segmented-channel rotation false positives.

cleanup_deleted_streams builds a stream→event_ids map to detect rotation.
Segment expansion (racing/UFC) writes the session/card code under the
canonical "segment" key, and channel identity is "<event_id>-<segment>".
The map was keyed with the raw classifier field "card_segment" instead —
absent for racing — so every segmented channel's event id (600057440-fp3)
failed the containment check and the channel was deleted and recreated as
"rotated" on every generation run.
"""

from unittest.mock import MagicMock, patch

import pytest

from tests.fakes import FakeChannel, FakeEvent, FakeStream

GROUP_ID = 42


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


def _run_cleanup(service, channels, streams_by_channel, current_streams, matched_streams):
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
            GROUP_ID, current_streams, matched_streams=matched_streams
        )


def _racing_match(stream_id: int, event_id: str, segment: str, name: str) -> dict:
    # Shape produced by expand_racing_segments: canonical "segment" key,
    # no "card_segment" (that field only comes from the UFC classifier).
    return {
        "stream": {"id": stream_id, "name": name},
        "event": FakeEvent(id=event_id, sport="racing", league="f1"),
        "segment": segment,
    }


def test_segment_channel_survives_when_match_carries_segment_key(service):
    """A racing segment channel matched to its own session must not be rotated."""
    channel = FakeChannel(id=7, channel_name="F1 | Practice 3", event_id="600057440-fp3")
    stream = FakeStream(dispatcharr_stream_id=100, source_group_id=GROUP_ID, stream_name="Sky F1")

    result = _run_cleanup(
        service,
        channels=[channel],
        streams_by_channel={7: [stream]},
        current_streams={100: {"name": "Sky F1"}},
        matched_streams=[_racing_match(100, "600057440", "fp3", "Sky F1")],
    )

    service.delete_managed_channel.assert_not_called()
    assert result.deleted == []


def test_segment_channel_still_rotates_on_real_event_change(service):
    """Rotation detection must keep firing when the stream truly moved on."""
    channel = FakeChannel(id=7, channel_name="F1 | Practice 3", event_id="600057440-fp3")
    stream = FakeStream(dispatcharr_stream_id=100, source_group_id=GROUP_ID, stream_name="Sky F1")

    result = _run_cleanup(
        service,
        channels=[channel],
        streams_by_channel={7: [stream]},
        current_streams={100: {"name": "Sky F1"}},
        matched_streams=[_racing_match(100, "600099999", "fp1", "Sky F1")],
    )

    service.delete_managed_channel.assert_called_once()
    assert len(result.deleted) == 1
    assert "rotated" in result.deleted[0]["reason"]


def test_unsegmented_channel_unaffected(service):
    """Plain team-vs-team matches (no segment key) keep the bare event id."""
    channel = FakeChannel(id=8, channel_name="Carlton vs Gold Coast", event_id="38659")
    stream = FakeStream(dispatcharr_stream_id=200, source_group_id=GROUP_ID, stream_name="Fox 504")

    result = _run_cleanup(
        service,
        channels=[channel],
        streams_by_channel={8: [stream]},
        current_streams={200: {"name": "Fox 504"}},
        matched_streams=[
            {
                "stream": {"id": 200, "name": "Fox 504"},
                "event": FakeEvent(id="38659", sport="afl", league="afl"),
            }
        ],
    )

    service.delete_managed_channel.assert_not_called()
    assert result.deleted == []
