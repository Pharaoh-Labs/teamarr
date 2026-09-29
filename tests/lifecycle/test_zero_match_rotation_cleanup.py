"""Regression tests for #907: rotated streams survive a zero-match run.

A provider that reuses one Dispatcharr stream id for the next event
(``MAX UK 08: Race 2: WorldSBK …`` → ``MAX UK 08: Shenzhen Open …``) left the
old attachment on the old channel forever, because the whole lifecycle step —
cleanup included — only ran when the group matched at least one stream.

The fix runs cleanup on the zero-match path in ``changed_only`` mode: a
stream still PRESENT in the pool under different content is detached, but
absence from the pool is never read as removal, so the #450 guarantee (a
mis-bound pattern or half-refreshed M3U must not cascade into deletions)
still holds.
"""

from unittest.mock import MagicMock, patch

import pytest

from tests.fakes import FakeChannel, FakeManagedChannel, FakeStream

GROUP_ID = 42
STREAM_ID = 114647
OLD_NAME = "MAX UK 08: Race 2: WorldSBK | Round 10 | Italy @ 27 Sep 02:00 PM GMT-1"
NEW_NAME = "MAX UK 08: Shenzhen Open | Round 2: Zhao Xintong - Scott Donaldson @ 28 Sep"


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


def _run_cleanup(service, channels, streams_by_channel, current_streams, **kwargs):
    remove = MagicMock()
    with (
        patch(
            "teamarr.database.channels.get_managed_channels_for_group",
            return_value=channels,
        ),
        patch(
            "teamarr.database.channels.get_channel_streams",
            side_effect=lambda conn, cid, include_removed=False: streams_by_channel.get(cid, []),
        ),
        patch("teamarr.database.channels.remove_stream_from_channel", remove),
        patch("teamarr.database.channels.update_stream_name"),
        patch("teamarr.database.channels.log_channel_history"),
    ):
        result = service.cleanup_deleted_streams(GROUP_ID, current_streams, **kwargs)
    return result, remove


def _channel(cid=7):
    return FakeChannel(id=cid, channel_name="Türkiye vs Italy", event_id="700001")


def _stream(sid=STREAM_ID, name=OLD_NAME):
    return FakeStream(dispatcharr_stream_id=sid, source_group_id=GROUP_ID, stream_name=name)


def test_rotated_stream_is_detached_on_zero_match_run(service):
    """The reporter's case: same id, new content, no matches → channel goes."""
    result, _ = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_stream()]},
        current_streams={STREAM_ID: {"id": STREAM_ID, "name": NEW_NAME}},
        matched_streams=[],
        changed_only=True,
    )

    service.delete_managed_channel.assert_called_once()
    assert len(result.deleted) == 1
    assert result.deleted[0]["reason"] == "1 content-changed"


def test_rotated_stream_is_removed_but_channel_kept_when_another_stream_is_fine(service):
    """Only the rotated stream leaves; a still-valid sibling keeps the channel."""
    good = _stream(sid=114700, name="MAX UK 09: Türkiye v Italy")
    result, remove = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_stream(), good]},
        current_streams={
            STREAM_ID: {"id": STREAM_ID, "name": NEW_NAME},
            114700: {"id": 114700, "name": "MAX UK 09: Türkiye v Italy"},
        },
        matched_streams=[],
        changed_only=True,
    )

    service.delete_managed_channel.assert_not_called()
    assert result.deleted == []
    remove.assert_called_once()
    assert remove.call_args.args[2] == STREAM_ID


def test_unchanged_stream_untouched_on_zero_match_run(service):
    """A group with no games today loses nothing: equal fingerprints are left alone."""
    result, remove = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_stream()]},
        current_streams={STREAM_ID: {"id": STREAM_ID, "name": OLD_NAME}},
        matched_streams=[],
        changed_only=True,
    )

    service.delete_managed_channel.assert_not_called()
    remove.assert_not_called()
    assert result.deleted == []


def test_missing_stream_is_not_removed_in_changed_only_mode(service):
    """#450 guard: absence from a zero-match pool is not evidence of removal."""
    result, remove = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_stream()]},
        current_streams={999: {"id": 999, "name": "Something else entirely"}},
        matched_streams=[],
        changed_only=True,
    )

    service.delete_managed_channel.assert_not_called()
    remove.assert_not_called()
    assert result.deleted == []


def test_missing_stream_still_removed_in_full_mode(service):
    """The matched-path behavior is unchanged: missing streams still count."""
    result, _ = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_stream()]},
        current_streams={999: {"id": 999, "name": "Something else entirely"}},
        matched_streams=[],
    )

    service.delete_managed_channel.assert_called_once()
    assert result.deleted[0]["reason"] == "1 missing"


def test_legacy_primary_stream_fallback_skipped_in_changed_only_mode(service):
    """A stream-less legacy channel with a vanished primary is left alone too."""
    channel = FakeManagedChannel(id=7, primary_stream_id=STREAM_ID)
    result, _ = _run_cleanup(
        service,
        channels=[channel],
        streams_by_channel={},
        current_streams={999: {"id": 999, "name": "x"}},
        matched_streams=[],
        changed_only=True,
    )

    service.delete_managed_channel.assert_not_called()
    assert result.deleted == []


def test_blank_current_name_is_not_a_change(service):
    """A half-refreshed pool that yields an empty name must not look like rotation."""
    result, remove = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_stream()]},
        current_streams={STREAM_ID: {"id": STREAM_ID, "name": ""}},
        matched_streams=[],
        changed_only=True,
    )

    service.delete_managed_channel.assert_not_called()
    remove.assert_not_called()
