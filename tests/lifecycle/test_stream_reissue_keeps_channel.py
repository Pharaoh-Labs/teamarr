"""A re-issued stream must not cost the event its channel (#955).

Some providers move a game to a new slot every hour under a new stream id
(``NHL GP 06 | Blackhawks @ Sabres`` → ``NHL GP 10 | …`` → ``NHL GP 09 | …``).
Cleanup runs before the create step, saw the channel's only stream missing and
deleted the channel; the create step then made a new one for the same event a
second later. The event always had a channel, but a different Dispatcharr
channel each run — 42 times in two weeks on a live install.

When the run that finds a channel's streams gone has also matched another
stream to the same event, the channel is kept and only the stale stream is
removed; the create step attaches the replacement to the channel it finds.
"""

from unittest.mock import MagicMock, patch

import pytest

from tests.fakes import FakeChannel, FakeStream, make_event

GROUP_ID = 77
OLD_ID, NEW_ID = 4353105, 4354326
OLD_NAME = "NHL GP 06 | Blackhawks @ Sabres (2026-10-03 23:00:00)"
NEW_NAME = "NHL GP 10 | Blackhawks @ Sabres (2026-10-03 23:00:00)"
EVENT_ID = "401800001"


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


def _run(service, streams, current_streams, matched, mode="consolidate"):
    remove = MagicMock()
    channel = FakeChannel(id=7, channel_name="NHL | CHI/BUF", event_id=EVENT_ID)
    with (
        patch("teamarr.database.channels.get_managed_channels_for_group", return_value=[channel]),
        patch(
            "teamarr.database.channels.get_channel_streams",
            side_effect=lambda conn, cid, include_removed=False: streams,
        ),
        patch("teamarr.database.channels.remove_stream_from_channel", remove),
        patch("teamarr.database.channels.update_stream_name"),
        patch("teamarr.database.channels.log_channel_history"),
        patch(
            "teamarr.database.channel_numbers.get_global_consolidation_mode", return_value=mode
        ),
    ):
        result = service.cleanup_deleted_streams(GROUP_ID, current_streams, matched_streams=matched)
    return result, remove


def _old():
    return FakeStream(dispatcharr_stream_id=OLD_ID, source_group_id=GROUP_ID, stream_name=OLD_NAME)


def _match(stream_id, name, event_id=EVENT_ID):
    return {"stream": {"id": stream_id, "name": name}, "event": make_event(id=event_id)}


def test_channel_is_kept_when_the_replacement_matched_this_run(service):
    result, remove = _run(
        service,
        streams=[_old()],
        current_streams={NEW_ID: {"id": NEW_ID, "name": NEW_NAME}},
        matched=[_match(NEW_ID, NEW_NAME)],
    )

    service.delete_managed_channel.assert_not_called()
    assert result.deleted == []
    remove.assert_called_once()
    assert remove.call_args.args[2] == OLD_ID
    service._remove_stream_from_dispatcharr_channel.assert_called_once_with(100, OLD_ID)


def test_channel_is_deleted_when_nothing_matches_the_event_any_more(service):
    """The replacement is for a different game: this event has lost its stream."""
    result, _ = _run(
        service,
        streams=[_old()],
        current_streams={NEW_ID: {"id": NEW_ID, "name": "NHL GP 10 | Oilers @ Flames"}},
        matched=[_match(NEW_ID, "NHL GP 10 | Oilers @ Flames", event_id="401899999")],
    )

    service.delete_managed_channel.assert_called_once()
    assert result.deleted[0]["reason"] == "1 missing"


def test_a_stream_that_rotated_away_is_not_its_own_replacement(service):
    """Same id now carries another game, and no other stream has this event."""
    result, _ = _run(
        service,
        streams=[_old()],
        current_streams={OLD_ID: {"id": OLD_ID, "name": "NHL GP 06 | Oilers @ Flames"}},
        matched=[_match(OLD_ID, "NHL GP 06 | Oilers @ Flames", event_id="401899999")],
    )

    service.delete_managed_channel.assert_called_once()
    assert result.deleted[0]["reason"] == "1 rotated"


def test_separate_mode_still_deletes(service):
    """Each stream owns its channel there: the replacement gets a new one."""
    result, _ = _run(
        service,
        streams=[_old()],
        current_streams={NEW_ID: {"id": NEW_ID, "name": NEW_NAME}},
        matched=[_match(NEW_ID, NEW_NAME)],
        mode="separate",
    )

    service.delete_managed_channel.assert_called_once()
    assert len(result.deleted) == 1
