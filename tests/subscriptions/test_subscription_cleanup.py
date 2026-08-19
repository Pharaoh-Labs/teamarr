"""Tests for unsubscribed-league channel cleanup (teamarrv2-psoi).

When followed leagues change while the source group stays enabled, channels for
dropped leagues must be deleted on the next run (immediate-removal policy). The
sweep is conservative: it bails on an empty subscription set and exempts
channel-source/system groups and league-less channels.
"""

from unittest.mock import MagicMock, patch

import pytest

from tests.fakes import FakeChannel, FakeGroup


@pytest.fixture
def processor():
    from teamarr.consumers.event_group_processor import EventGroupProcessor

    with patch("teamarr.consumers.event_group_processor.processor.create_default_service"):
        proc = EventGroupProcessor(db_factory=MagicMock())
    return proc


def _run(processor, groups, channels, subscribed):
    """Drive _cleanup_unsubscribed_leagues with patched data, return deleted ids."""
    lifecycle = MagicMock()
    lifecycle.delete_managed_channel.return_value = True
    processor._resolve_subscription_leagues = MagicMock(return_value=subscribed)
    with (
        patch(
            "teamarr.consumers.event_group_processor.processor.get_all_groups",
            return_value=groups,
        ),
        patch(
            "teamarr.database.channels.get_all_managed_channels",
            return_value=channels,
        ),
    ):
        processor._cleanup_unsubscribed_leagues(MagicMock(), lifecycle)
    return [
        call.args[1] for call in lifecycle.delete_managed_channel.call_args_list
    ]


def test_unsubscribed_league_channel_deleted(processor):
    deleted = _run(
        processor,
        groups=[FakeGroup(id=1)],
        channels=[FakeChannel(id=10, league="nba"), FakeChannel(id=11, league="nhl")],
        subscribed=["nba"],
    )
    assert deleted == [11]  # nhl dropped, nba kept


def test_subscribed_league_channel_kept(processor):
    deleted = _run(
        processor,
        groups=[FakeGroup(id=1)],
        channels=[FakeChannel(id=10, league="NBA")],  # case-insensitive
        subscribed=["nba"],
    )
    assert deleted == []


def test_null_league_channel_exempt(processor):
    deleted = _run(
        processor,
        groups=[FakeGroup(id=1)],
        channels=[FakeChannel(id=10, league=None), FakeChannel(id=11, league="")],
        subscribed=["nba"],
    )
    assert deleted == []


def test_channel_source_group_channels_exempt(processor):
    deleted = _run(
        processor,
        groups=[FakeGroup(id=1), FakeGroup(id=99, is_channel_source=True)],
        channels=[FakeChannel(id=10, league="xyz", event_epg_group_id=99)],
        subscribed=["nba"],
    )
    assert deleted == []  # owned by a channel-source group


def test_empty_subscription_is_a_noop(processor):
    # Resolution miss must never be read as "delete everything".
    deleted = _run(
        processor,
        groups=[FakeGroup(id=1)],
        channels=[FakeChannel(id=10, league="nba"), FakeChannel(id=11, league="nhl")],
        subscribed=[],
    )
    assert deleted == []


def test_disabled_group_not_counted_toward_subscription(processor):
    # Disabled groups don't contribute leagues; their channels are handled by the
    # existing disabled-group cleanup, not here. Only enabled groups define the set.
    lifecycle = MagicMock()
    lifecycle.delete_managed_channel.return_value = True

    def resolve(_conn, group):
        return {1: ["nba"], 2: ["nhl"]}.get(group.id, [])

    processor._resolve_subscription_leagues = MagicMock(side_effect=resolve)
    groups = [FakeGroup(id=1, enabled=True), FakeGroup(id=2, enabled=False)]
    channels = [FakeChannel(id=10, league="nba"), FakeChannel(id=11, league="nhl")]
    with (
        patch(
            "teamarr.consumers.event_group_processor.processor.get_all_groups",
            return_value=groups,
        ),
        patch(
            "teamarr.database.channels.get_all_managed_channels",
            return_value=channels,
        ),
    ):
        processor._cleanup_unsubscribed_leagues(MagicMock(), lifecycle)
    deleted = [c.args[1] for c in lifecycle.delete_managed_channel.call_args_list]
    assert deleted == [11]  # nhl only via disabled group 2 -> not subscribed -> deleted
