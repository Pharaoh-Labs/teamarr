"""Tests for ChannelManager.get_channel_maps slot-claiming exclusion (#512).

The stream->channel map is single-slot last-write-wins. Teamarr's own output
channels must not claim slots for streams they share with curated channels —
otherwise, once the attach window opens and Teamarr attaches a shared stream,
the next run's channel-source pool loses the stream ("Teamarr-managed") and
cleanup cascades into delete/recreate churn on alternating cycles.
"""

from types import SimpleNamespace

from teamarr.dispatcharr.managers.channels import ChannelManager


def _manager(channels: list[dict]) -> ChannelManager:
    client = SimpleNamespace(
        _base_url="http://fake:9191",
        paginated_get=lambda path, error_context=None: channels,
    )
    return ChannelManager(client)


CURATED = {"id": 10, "uuid": "aa-bb", "epg_data_id": 1, "streams": [500, 501]}
MANAGED = {"id": 900, "uuid": "cc-dd", "epg_data_id": None, "streams": [500]}


def test_excluded_channel_does_not_claim_shared_stream_slot():
    # Managed channel paginates AFTER the curated one → last-write-wins would
    # normally hand stream 500's slot to it. Exclusion keeps the curated claim.
    mgr = _manager([CURATED, MANAGED])
    stream_map, uuid_map = mgr.get_channel_maps(exclude_channel_ids={900})

    assert stream_map[500]["id"] == 10
    assert stream_map[501]["id"] == 10
    # Excluded channels still appear in the uuid index (loopback resolution).
    assert uuid_map["cc-dd"]["id"] == 900


def test_stream_only_on_excluded_channel_absent_from_map():
    mgr = _manager([{"id": 900, "uuid": "cc-dd", "streams": [777]}])
    stream_map, _ = mgr.get_channel_maps(exclude_channel_ids={900})
    assert 777 not in stream_map


def test_no_exclusion_keeps_last_write_wins():
    mgr = _manager([CURATED, MANAGED])
    stream_map, _ = mgr.get_channel_maps()
    assert stream_map[500]["id"] == 900  # documented pre-existing behavior


def test_get_stream_channel_map_passes_exclusion_through():
    mgr = _manager([CURATED, MANAGED])
    stream_map = mgr.get_stream_channel_map(exclude_channel_ids={900})
    assert stream_map[500]["id"] == 10
