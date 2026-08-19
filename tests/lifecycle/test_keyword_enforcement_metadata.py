"""Keyword enforcement must carry matcher metadata when moving a stream (#344).

KeywordEnforcer.enforce() moves a stream between channels by remove+add; the
re-add used to drop match_type/match_method/attach_at/detach_at (and
m3u_account_id), detaching the stream from the epg_match/stream_type ordering
rules and its EPG attach window.
"""

from teamarr.consumers.enforcement.keywords import KeywordEnforcer
from teamarr.database.channels import (
    add_stream_to_channel,
    create_managed_channel,
    get_channel_streams,
)

TEST_GROUP_ID = 999991  # high sentinel — never collides with real groups


def _make_channel(conn, event_id: str, keyword: str | None) -> int:
    return create_managed_channel(
        conn=conn,
        event_epg_group_id=None,
        event_id=event_id,
        event_provider="espn",
        tvg_id=f"tvg-{event_id}-{keyword or 'main'}",
        channel_name=f"Test {event_id} {keyword or 'main'}",
        exception_keyword=keyword,
    )


def test_move_preserves_match_metadata(db_factory):
    with db_factory() as conn:
        conn.execute(
            "INSERT INTO consolidation_exception_keywords (label, match_terms, behavior)"
            " VALUES ('XyzzyKW', 'XyzzyFeed', 'consolidate')"
        )

        main_id = _make_channel(conn, "evt-1", None)
        spanish_id = _make_channel(conn, "evt-1", "XyzzyKW")

        # EPG-matched, time-windowed stream lands on the WRONG (main) channel.
        add_stream_to_channel(
            conn=conn,
            managed_channel_id=main_id,
            dispatcharr_stream_id=42,
            stream_name="ESPN XyzzyFeed HD",
            priority=0,
            source_group_id=TEST_GROUP_ID,
            m3u_account_id=7,
            m3u_account_name="acct",
            match_type="event",
            match_method="epg",
            attach_at="2026-07-11 21:00:00",
            detach_at="2026-07-12 01:00:00",
            dispatcharr_channel_group="Sports",
        )
        conn.commit()

    enforcer = KeywordEnforcer(db_factory=db_factory, channel_manager=None)
    result = enforcer.enforce()

    assert result.streams_moved, "stream should have been moved to the XyzzyKW channel"

    with db_factory() as conn:
        moved = get_channel_streams(conn, spanish_id)
        assert len(moved) == 1
        s = moved[0]
        assert s.match_method == "epg"
        assert s.match_type == "event"
        assert s.m3u_account_id == 7
        assert str(s.attach_at) == "2026-07-11 21:00:00"
        assert str(s.detach_at) == "2026-07-12 01:00:00"
        assert s.dispatcharr_channel_group == "Sports"
        assert s.exception_keyword == "XyzzyKW"
