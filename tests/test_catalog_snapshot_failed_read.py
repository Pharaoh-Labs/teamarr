"""A failed managed-id read is never built into the run-wide catalog snapshot (#1201)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.event_group_processor.stream_fetcher import (
    dispatcharr_catalog_inputs,
    managed_channel_ids,
)


def _broken_db():
    raise RuntimeError("database is locked")


def _processor(db_factory):
    channels = MagicMock()
    channels.get_epg_data_list.return_value = []
    channels.get_channel_maps.return_value = ({}, {})
    return SimpleNamespace(
        _db_factory=db_factory, _dispatcharr_client=SimpleNamespace(channels=channels)
    )


def test_a_single_request_still_gets_an_empty_set():
    assert managed_channel_ids(_broken_db) == set()


def test_strict_raises():
    with pytest.raises(RuntimeError):
        managed_channel_ids(_broken_db, strict=True)


def test_failed_read_is_not_cached_and_the_next_call_retries():
    processor = _processor(_broken_db)

    with pytest.raises(RuntimeError):
        dispatcharr_catalog_inputs(processor)

    assert getattr(processor, "_dispatcharr_catalog_cache", None) is None
    # No channel map was built without the exclusion.
    processor._dispatcharr_client.channels.get_channel_maps.assert_not_called()
