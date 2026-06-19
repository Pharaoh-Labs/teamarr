"""Tests for ManagedChannelStream.from_row stream_stats JSON handling.

The DB stores stream_stats as a JSON string; from_row decodes it to a dict,
tolerates malformed JSON (→ None), and passes a dict through unchanged.
"""

from teamarr.database.channels.types import ManagedChannelStream


def _row(stream_stats):
    return {
        "id": 1,
        "managed_channel_id": 1,
        "dispatcharr_stream_id": 100,
        "stream_stats": stream_stats,
    }


def test_valid_json_string_decoded_to_dict():
    s = ManagedChannelStream.from_row(_row('{"resolution": "1920x1080"}'))
    assert s.stream_stats == {"resolution": "1920x1080"}


def test_invalid_json_string_becomes_none():
    s = ManagedChannelStream.from_row(_row("{not valid json"))
    assert s.stream_stats is None


def test_dict_passthrough():
    s = ManagedChannelStream.from_row(_row({"source_fps": 60}))
    assert s.stream_stats == {"source_fps": 60}


def test_missing_stats_is_none():
    row = {"id": 1, "managed_channel_id": 1, "dispatcharr_stream_id": 100}
    assert ManagedChannelStream.from_row(row).stream_stats is None
    assert ManagedChannelStream.from_row(_row(None)).stream_stats is None
