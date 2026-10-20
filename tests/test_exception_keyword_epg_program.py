# ruff: noqa: E501  — captured programme titles are the fixtures
"""Exception keywords read the matched EPG programme, not just the stream name (#829).

An EPG-matched linear stream is named for its network ("ESPN 2"); the
ManningCast evidence lives only in the guide programme, so a "Peyton and Eli"
keyword never fired on the stream name alone.
"""

from __future__ import annotations

from datetime import UTC, datetime

from teamarr.consumers.enforcement.keywords import KeywordEnforcer
from teamarr.consumers.matching.epg_matcher import build_match_input
from teamarr.database.channels import (
    add_stream_to_channel,
    create_managed_channel,
    get_channel_streams,
    update_stream_program_title,
)
from teamarr.database.channels.keywords import check_exception_keyword
from teamarr.database.exception_keywords import ExceptionKeyword
from teamarr.dispatcharr.types import DispatcharrProgram

MANNINGCAST = ExceptionKeyword(
    id=1, label="ManningCast", match_terms="Peyton and Eli, ManningCast", behavior="consolidate"
)
SPANISH = ExceptionKeyword(
    id=2, label="Spanish", match_terms="Spanish, En Español, (ESP)", behavior="consolidate"
)
KEYWORDS = [MANNINGCAST, SPANISH]

EVENT = "Denver Broncos at Kansas City Chiefs"
PROGRAM = (
    "NFL Football | Monday Night Football with Peyton and Eli: Denver Broncos at Kansas City Chiefs"
)


class TestCheck:
    def test_programme_title_fires_when_stream_name_does_not(self):
        assert check_exception_keyword("ESPN 2", KEYWORDS, EVENT) == (None, None)
        assert check_exception_keyword("ESPN 2", KEYWORDS, EVENT, PROGRAM) == (
            "ManningCast",
            "consolidate",
        )

    def test_stream_name_wins_over_programme(self):
        # Keyword order would pick ManningCast first; the stream's own name
        # is the more direct evidence and is searched first.
        assert check_exception_keyword("ESPN Deportes (ESP)", KEYWORDS, EVENT, PROGRAM) == (
            "Spanish",
            "consolidate",
        )

    def test_event_name_guard_applies_to_programme(self):
        # #803: a term the event is named with never fires, wherever it appears.
        assert check_exception_keyword(
            "Sky Sports F1",
            KEYWORDS,
            "Tag Heuer Spanish Grand Prix",
            "F1 | Spanish Grand Prix: Race",
        ) == (None, None)

    def test_superscript_live_marker_is_stripped_before_matching(self):
        program = DispatcharrProgram(
            id=1,
            title="NFL Football - Monday Night Football with Peyton and Eli: Denver Broncos at Kansas City Chiefs ᴸᶦᵛᵉ",
            sub_title=None,
            start_time=datetime(2026, 9, 14, 0, 15, tzinfo=UTC).isoformat(),
            end_time=datetime(2026, 9, 14, 3, 30, tzinfo=UTC).isoformat(),
            tvg_id="espn2.us",
        )
        text = build_match_input(program)
        assert "ᴸ" not in text
        assert check_exception_keyword("ESPN 2", KEYWORDS, EVENT, text)[0] == "ManningCast"


def _make_channel(conn, keyword: str | None) -> int:
    return create_managed_channel(
        conn=conn,
        event_epg_group_id=None,
        event_id="evt-829",
        event_provider="espn",
        tvg_id=f"tvg-evt-829-{keyword or 'main'}",
        channel_name=f"Broncos @ Chiefs {keyword or 'main'}",
        exception_keyword=keyword,
        event_name=EVENT,
    )


def _keyword_row(conn):
    conn.execute(
        "INSERT INTO consolidation_exception_keywords (label, match_terms, behavior)"
        " VALUES ('XyzzyCast', 'Xyzzy and Plugh', 'consolidate')"
    )


def test_enforcement_keeps_programme_keyword_stream_on_keyword_channel(db_factory):
    """Without the persisted programme text, enforcement moved it back to main."""
    with db_factory() as conn:
        _keyword_row(conn)
        _make_channel(conn, None)
        kw_id = _make_channel(conn, "XyzzyCast")
        add_stream_to_channel(
            conn=conn,
            managed_channel_id=kw_id,
            dispatcharr_stream_id=829,
            stream_name="ESPN 2",
            priority=0,
            match_method="epg",
            exception_keyword="XyzzyCast",
            epg_program_title="Monday Night Football with Xyzzy and Plugh | Denver Broncos at Kansas City Chiefs",
        )
        conn.commit()

    result = KeywordEnforcer(db_factory=db_factory, channel_manager=None).enforce()

    assert not result.streams_moved
    with db_factory() as conn:
        assert [s.dispatcharr_stream_id for s in get_channel_streams(conn, kw_id)] == [829]


def test_enforcement_moves_main_stream_and_carries_programme_text(db_factory):
    with db_factory() as conn:
        _keyword_row(conn)
        main_id = _make_channel(conn, None)
        kw_id = _make_channel(conn, "XyzzyCast")
        add_stream_to_channel(
            conn=conn,
            managed_channel_id=main_id,
            dispatcharr_stream_id=830,
            stream_name="ESPN 2",
            priority=0,
            match_method="epg",
            epg_program_title="Monday Night Football with Xyzzy and Plugh",
        )
        conn.commit()

    result = KeywordEnforcer(db_factory=db_factory, channel_manager=None).enforce()

    assert result.streams_moved
    with db_factory() as conn:
        moved = get_channel_streams(conn, kw_id)
        assert [s.dispatcharr_stream_id for s in moved] == [830]
        assert moved[0].epg_program_title == "Monday Night Football with Xyzzy and Plugh"


def test_update_stream_program_title_only_writes_changes(db_factory):
    with db_factory() as conn:
        ch = _make_channel(conn, None)
        add_stream_to_channel(
            conn=conn, managed_channel_id=ch, dispatcharr_stream_id=831, stream_name="ESPN 2"
        )
        assert update_stream_program_title(conn, ch, 831, "MNF | Broncos at Chiefs") is True
        assert update_stream_program_title(conn, ch, 831, "MNF | Broncos at Chiefs") is False
        assert get_channel_streams(conn, ch)[0].epg_program_title == "MNF | Broncos at Chiefs"
