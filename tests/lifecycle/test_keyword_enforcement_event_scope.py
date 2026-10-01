"""Keyword enforcement resolves its target by EVENT, across event groups (#929).

Channel identity is event-scoped: an event's main channel and its keyword
channels are found across every source group (`find_existing_channel`). The
enforcer's lookup was keyed on the event group as well, so when the main and
keyword channels came from different groups a stream attached before the
keyword existed could not see its keyword channel, resolved its target to the
channel it was already on, and was counted correct. On a live install
`Steelers @ Browns (Prime Vision …)` sat on both `NFL | PIT/CLE` and
`NFL | PIT/CLE (Prime Vision)`, with the step reporting 0 moved and no log.
"""

import logging

from teamarr.consumers.enforcement.keywords import KeywordEnforcer
from teamarr.database.channels import (
    add_stream_to_channel,
    create_managed_channel,
    get_channel_streams,
)
from teamarr.database.groups import create_group

STREAM = "NFL Game Pass 02: Steelers @ Browns (Prime Vision with Next Gen Stats)"


def _keyword(conn, label="Prime Vision", terms="prime vision, primevision"):
    conn.execute(
        "INSERT INTO consolidation_exception_keywords (label, match_terms, behavior)"
        " VALUES (?, ?, 'consolidate')",
        (label, terms),
    )


def _channel(conn, group_id, keyword=None, event_id="401872964", feed_team_id=None):
    return create_managed_channel(
        conn=conn,
        event_epg_group_id=group_id,
        event_id=event_id,
        event_provider="espn",
        tvg_id=f"tvg-{event_id}-{keyword or 'main'}-{feed_team_id or 'x'}-{group_id}",
        channel_name=f"NFL | PIT/CLE{f' ({keyword})' if keyword else ''}",
        exception_keyword=keyword,
        feed_team_id=feed_team_id,
    )


def _attach(conn, channel_id, stream_id=4332190, name=STREAM, source_group_id=None):
    add_stream_to_channel(
        conn=conn,
        managed_channel_id=channel_id,
        dispatcharr_stream_id=stream_id,
        stream_name=name,
        priority=0,
        source_group_id=source_group_id,
    )


def _stream_ids(conn, channel_id):
    return [s.dispatcharr_stream_id for s in get_channel_streams(conn, channel_id)]


def test_stream_moves_to_a_keyword_channel_from_another_group(db_factory):
    with db_factory() as conn:
        _keyword(conn)
        g_main = create_group(conn, name="Dispatcharr Channels", leagues=["nfl"])
        g_pass = create_group(conn, name="NFL Game Pass", leagues=["nfl"])
        main = _channel(conn, g_main)
        vision = _channel(conn, g_pass, "Prime Vision")
        _attach(conn, main, source_group_id=g_pass)  # attached before the keyword existed
        conn.commit()

    result = KeywordEnforcer(db_factory=db_factory, channel_manager=None).enforce()

    assert result.moved_count == 1
    with db_factory() as conn:
        assert _stream_ids(conn, main) == []
        assert _stream_ids(conn, vision) == [4332190]


def test_the_reported_state_stream_on_both_channels_is_cleaned_up(db_factory):
    """Three groups, as on the live install; the creator had already attached
    the stream to the new keyword channel, so only the removal is owed and the
    target must not gain a second row."""
    with db_factory() as conn:
        _keyword(conn)
        _keyword(conn, "4K", "4k, uhd")
        g_main = create_group(conn, name="Dispatcharr Channels", leagues=["nfl"])
        g_4k = create_group(conn, name="Sports | NFL", leagues=["nfl"])
        g_pass = create_group(conn, name="NFL Game Pass", leagues=["nfl"])
        main = _channel(conn, g_main)
        four_k = _channel(conn, g_4k, "4K")
        vision = _channel(conn, g_pass, "Prime Vision")
        _attach(conn, main, source_group_id=g_pass)
        _attach(conn, vision, source_group_id=g_pass)
        conn.commit()

    result = KeywordEnforcer(db_factory=db_factory, channel_manager=None).enforce()

    assert result.moved_count == 1
    with db_factory() as conn:
        assert _stream_ids(conn, main) == []
        assert _stream_ids(conn, vision) == [4332190]
        assert _stream_ids(conn, four_k) == []


def test_another_events_keyword_channel_is_never_a_target(db_factory):
    with db_factory() as conn:
        _keyword(conn)
        group = create_group(conn, name="NFL", leagues=["nfl"])
        main = _channel(conn, group)
        other_event = _channel(conn, group, "Prime Vision", event_id="999")
        _attach(conn, main)
        conn.commit()

    result = KeywordEnforcer(db_factory=db_factory, channel_manager=None).enforce()

    # No keyword channel for THIS event: falls back to main, where it already is.
    assert result.moved_count == 0
    with db_factory() as conn:
        assert _stream_ids(conn, main) == [4332190]
        assert _stream_ids(conn, other_event) == []


def test_feed_separated_event_keeps_the_stream_on_its_own_feed(db_factory):
    """An event with HOME and AWAY channels has two channels per keyword; the
    stream goes to the keyword channel of the feed it is leaving."""
    with db_factory() as conn:
        _keyword(conn)
        g_a = create_group(conn, name="A", leagues=["nfl"])
        g_b = create_group(conn, name="B", leagues=["nfl"])
        away_main = _channel(conn, g_a, feed_team_id="23")
        home_vision = _channel(conn, g_b, "Prime Vision", feed_team_id="5")
        away_vision = _channel(conn, g_b, "Prime Vision", feed_team_id="23")
        _attach(conn, away_main)
        conn.commit()

    KeywordEnforcer(db_factory=db_factory, channel_manager=None).enforce()

    with db_factory() as conn:
        assert _stream_ids(conn, away_vision) == [4332190]
        assert _stream_ids(conn, home_vision) == []
        assert _stream_ids(conn, away_main) == []


def test_unkeyworded_stream_returns_to_a_main_channel_in_another_group(db_factory):
    with db_factory() as conn:
        _keyword(conn)
        g_main = create_group(conn, name="Main", leagues=["nfl"])
        g_pass = create_group(conn, name="Pass", leagues=["nfl"])
        main = _channel(conn, g_main)
        vision = _channel(conn, g_pass, "Prime Vision")
        _attach(conn, vision, stream_id=7, name="NFL 04: Steelers @ Browns")
        conn.commit()

    result = KeywordEnforcer(db_factory=db_factory, channel_manager=None).enforce()

    assert result.moved_count == 1
    with db_factory() as conn:
        assert _stream_ids(conn, main) == [7]
        assert _stream_ids(conn, vision) == []


def test_no_target_is_logged_not_silent(db_factory, caplog):
    """A stream with no keyword on a keyword channel, and the event has no
    main channel to return it to: the miss used to be recorded in a list
    nobody read."""
    with db_factory() as conn:
        _keyword(conn)
        group = create_group(conn, name="Pass", leagues=["nfl"])
        vision = _channel(conn, group, "Prime Vision")
        _attach(conn, vision, stream_id=7, name="NFL 04: Steelers @ Browns")
        conn.commit()

    with caplog.at_level(logging.WARNING, logger="teamarr.consumers.enforcement.keywords"):
        result = KeywordEnforcer(db_factory=db_factory, channel_manager=None).enforce()

    assert result.moved_count == 0
    assert len(result.errors) == 1
    assert "No target channel" in caplog.text
    with db_factory() as conn:
        assert _stream_ids(conn, vision) == [7]
