"""Source preview reads the same streams a generation run would (#985).

The preview used to list streams by the row's M3U group. A Dispatcharr
channel-source row has none, so every such row previewed the same unscoped
list instead of its own channel group's streams.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.event_group_processor import EventGroupProcessor
from teamarr.database import get_db, init_db
from teamarr.database.groups import ensure_channel_source_group


@pytest.fixture()
def processor(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    with get_db() as conn:
        ensure_channel_source_group(conn, True, selected_group_ids=[470, 1222])
        rows = {
            r["dispatcharr_channel_group_id"]: r["id"]
            for r in conn.execute(
                "SELECT id, dispatcharr_channel_group_id FROM event_epg_groups "
                "WHERE is_channel_source = 1"
            )
        }
    client = MagicMock()
    proc = EventGroupProcessor(db_factory=get_db, dispatcharr_client=client, service=MagicMock())

    def fetch(group):
        dp = group.dispatcharr_channel_group_id
        return [{"id": dp, "name": f"channel in {dp}", "tvg_id": f"tvg{dp}", "is_stale": False}]

    proc._fetch_channel_source_streams = fetch
    proc.matched_with = []

    def match(streams, group, target_date, resolved_leagues=None):
        proc.matched_with.append(([s["name"] for s in streams], resolved_leagues))
        return SimpleNamespace(
            matched_stream_count=0,
            unmatched_stream_count=len(streams),
            cache_hits=0,
            cache_misses=0,
            results=[],
        )

    proc._match_streams = match
    return proc, rows, client


def test_each_channel_source_row_previews_its_own_streams(processor):
    proc, rows, client = processor
    for dp in (470, 1222):
        result = proc.preview_group(rows[dp], date(2026, 10, 5))
        assert result.errors == []
        assert result.total_streams == 1
    assert [names for names, _ in proc.matched_with] == [["channel in 470"], ["channel in 1222"]]
    # Never the bare M3U listing, which is what returned every stream.
    client.m3u.list_streams.assert_not_called()


def test_a_row_with_no_streams_says_so(processor):
    proc, rows, _ = processor
    proc._fetch_channel_source_streams = lambda group: []
    result = proc.preview_group(rows[470], date(2026, 10, 5))
    assert result.errors == ["No streams found for this source"]
    assert proc.matched_with == []
