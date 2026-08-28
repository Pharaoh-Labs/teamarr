"""Tests for ChannelManager.count_channels_by_group (#631).

The channel-source group picker used to filter on Dispatcharr's
``m3u_accounts`` link, which is set for ANY group name a playlist carries —
including groups Dispatcharr auto-creates on import — so it silently hid the
groups users had curated channels into. "Holds channels" is the honest test,
and it must agree with what the scan scopes on: the channel's own
``channel_group_id``, with Teamarr's OUTPUT channels excluded.
"""

from types import SimpleNamespace

from teamarr.dispatcharr.managers.channels import ChannelManager


def _manager(channels: list[dict]) -> ChannelManager:
    client = SimpleNamespace(
        _base_url="http://fake:9191",
        paginated_get=lambda path, error_context=None: channels,
    )
    return ChannelManager(client)


CURATED_A = {"id": 10, "channel_group_id": 1}
CURATED_B = {"id": 11, "channel_group_id": 1}
CURATED_C = {"id": 12, "channel_group_id": 2}
MANAGED = {"id": 900, "channel_group_id": 3}


def test_counts_channels_per_group():
    counts = _manager([CURATED_A, CURATED_B, CURATED_C]).count_channels_by_group()
    assert counts == {1: 2, 2: 1}


def test_group_holding_only_teamarr_channels_reads_empty():
    # Teamarr's channels are OUTPUT — a group with nothing else is not a source.
    counts = _manager([CURATED_A, MANAGED]).count_channels_by_group(
        exclude_channel_ids={900}
    )
    assert counts == {1: 1}
    assert 3 not in counts


def test_excluded_channel_does_not_inflate_a_shared_group():
    managed_in_curated_group = {"id": 901, "channel_group_id": 1}
    counts = _manager([CURATED_A, managed_in_curated_group]).count_channels_by_group(
        exclude_channel_ids={901}
    )
    assert counts == {1: 1}


def test_ungrouped_channels_are_skipped():
    counts = _manager(
        [CURATED_A, {"id": 13, "channel_group_id": None}, {"id": 14}]
    ).count_channels_by_group()
    assert counts == {1: 1}


def test_no_channels_yields_no_groups():
    assert _manager([]).count_channels_by_group() == {}
