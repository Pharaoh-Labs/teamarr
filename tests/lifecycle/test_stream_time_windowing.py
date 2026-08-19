"""Tests for time-windowed stream membership (teamarrv2-183.5).

Covers compute_stream_window() and the window-aware active set returned by
get_ordered_stream_ids() — the mechanism that lets one linear stream rotate
across event channels, attached only during its EPG program slot.
"""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest

from teamarr.consumers.lifecycle.timing import compute_stream_window, is_stream_in_window
from teamarr.database.channels.streams import (
    get_ordered_stream_ids,
    update_stream_window,
)

BASE = datetime(2026, 6, 1, 18, 0, 0, tzinfo=UTC)


# ============================================================ compute_stream_window


def test_window_none_for_no_program_slot():
    assert compute_stream_window(None, None, 60, 60) == (None, None)
    assert compute_stream_window(BASE, None, 60, 60) == (None, None)
    assert compute_stream_window(None, BASE, 60, 60) == (None, None)


def test_window_applies_buffers_and_formats_sqlite_utc():
    start = BASE  # 18:00
    end = BASE + timedelta(hours=3)  # 21:00
    attach, detach = compute_stream_window(start, end, 60, 30)
    assert attach == "2026-06-01 17:00:00"  # 18:00 - 60m
    assert detach == "2026-06-01 21:30:00"  # 21:00 + 30m


def test_window_converts_to_utc():
    est = datetime(2026, 6, 1, 13, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    # 13:00 EST == 18:00 UTC
    attach, detach = compute_stream_window(est, est + timedelta(hours=1), 0, 0)
    assert attach == "2026-06-01 18:00:00"
    assert detach == "2026-06-01 19:00:00"


def test_window_zero_buffers():
    attach, detach = compute_stream_window(BASE, BASE + timedelta(hours=2), 0, 0)
    assert attach == "2026-06-01 18:00:00"
    assert detach == "2026-06-01 20:00:00"


def test_window_buffers_apply_unclipped_through_overlap():
    # Clipping was removed (bead 6qx): buffers always apply in full, even when
    # the widened window would overlap a neighbouring program. The user owns the
    # buffer values and accepts a stream being a member of two channels at once.
    start, end = BASE, BASE + timedelta(hours=2)  # 18:00-20:00
    attach, detach = compute_stream_window(start, end, 1440, 1440)
    assert attach == "2026-05-31 18:00:00"  # 24h before start, no clipping
    assert detach == "2026-06-02 20:00:00"  # 24h after end, no clipping


# ============================================================ is_stream_in_window


def test_in_window_null_attach_always_active():
    # Full-life (name-matched) streams have no window → always active.
    assert is_stream_in_window(None, None) is True
    assert is_stream_in_window(None, "2026-06-01 21:00:00") is True


def test_in_window_inside_slot():
    assert (
        is_stream_in_window(
            "2026-06-01 17:00:00", "2026-06-01 21:00:00", now="2026-06-01 18:00:00"
        )
        is True
    )


def test_in_window_before_slot_excluded():
    # The "Attach before" buffer: out-of-window before attach_at → inactive.
    assert (
        is_stream_in_window(
            "2026-06-01 17:00:00", "2026-06-01 21:00:00", now="2026-06-01 16:59:00"
        )
        is False
    )


def test_in_window_after_slot_excluded():
    assert (
        is_stream_in_window(
            "2026-06-01 17:00:00", "2026-06-01 21:00:00", now="2026-06-01 21:00:00"
        )
        is False
    )


def test_in_window_attach_boundary_inclusive():
    assert (
        is_stream_in_window(
            "2026-06-01 17:00:00", "2026-06-01 21:00:00", now="2026-06-01 17:00:00"
        )
        is True
    )


# ======================================================== get_ordered_stream_ids gating


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE managed_channel_streams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            managed_channel_id INTEGER,
            dispatcharr_stream_id INTEGER,
            priority INTEGER DEFAULT 0,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            removed_at TEXT,
            attach_at TEXT,
            detach_at TEXT
        )"""
    )
    return c


def _add(conn, stream_id, priority=0, attach_at=None, detach_at=None, removed_at=None):
    conn.execute(
        "INSERT INTO managed_channel_streams "
        "(managed_channel_id, dispatcharr_stream_id, priority, attach_at, detach_at, removed_at) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        (stream_id, priority, attach_at, detach_at, removed_at),
    )
    conn.commit()


def test_null_window_always_active(conn):
    _add(conn, 100)  # full-life, no window
    assert get_ordered_stream_ids(conn, 1, now="2026-06-01 18:00:00") == [100]
    # active regardless of when "now" is
    assert get_ordered_stream_ids(conn, 1, now="2030-01-01 00:00:00") == [100]


def test_in_window_stream_active(conn):
    _add(conn, 200, attach_at="2026-06-01 17:00:00", detach_at="2026-06-01 21:00:00")
    assert get_ordered_stream_ids(conn, 1, now="2026-06-01 18:00:00") == [200]


def test_before_window_excluded(conn):
    _add(conn, 200, attach_at="2026-06-01 17:00:00", detach_at="2026-06-01 21:00:00")
    assert get_ordered_stream_ids(conn, 1, now="2026-06-01 16:59:00") == []


def test_after_window_excluded(conn):
    _add(conn, 200, attach_at="2026-06-01 17:00:00", detach_at="2026-06-01 21:00:00")
    # half-open window: detach_at itself is excluded
    assert get_ordered_stream_ids(conn, 1, now="2026-06-01 21:00:00") == []


def test_attach_boundary_inclusive(conn):
    _add(conn, 200, attach_at="2026-06-01 17:00:00", detach_at="2026-06-01 21:00:00")
    assert get_ordered_stream_ids(conn, 1, now="2026-06-01 17:00:00") == [200]


def test_removed_stream_never_active(conn):
    _add(conn, 200, attach_at="2026-06-01 17:00:00", detach_at="2026-06-01 21:00:00",
         removed_at="2026-06-01 17:30:00")
    assert get_ordered_stream_ids(conn, 1, now="2026-06-01 18:00:00") == []


def test_mixed_streams_only_in_window_plus_fulllife(conn):
    # ESPN rotating: full-life dedicated stream + a windowed linear stream
    _add(conn, 100, priority=0)  # dedicated, always on
    _add(conn, 200, priority=1, attach_at="2026-06-01 17:00:00", detach_at="2026-06-01 21:00:00")
    _add(conn, 300, priority=2, attach_at="2026-06-01 23:00:00", detach_at="2026-06-02 02:00:00")
    # at 18:00 only 100 (full-life) + 200 (in window); 300 is later
    assert get_ordered_stream_ids(conn, 1, now="2026-06-01 18:00:00") == [100, 200]
    # at 23:30 only 100 + 300
    assert get_ordered_stream_ids(conn, 1, now="2026-06-01 23:30:00") == [100, 300]


def test_priority_order_preserved(conn):
    _add(conn, 300, priority=2)
    _add(conn, 100, priority=0)
    _add(conn, 200, priority=1)
    assert get_ordered_stream_ids(conn, 1, now="2026-06-01 18:00:00") == [100, 200, 300]


def test_same_stream_rotates_across_channels_one_day(conn):
    # The defining behavior of time-shared linear (183.5, checklist #5): ONE
    # physical stream (e.g. "ESPN", dispatcharr_stream_id=500) attached to THREE
    # different event channels across a single day — active in each only during
    # that program's window, detached from the first, RE-ATTACHED to the next,
    # including a window that crosses midnight.
    def add_to(channel_id, attach_at, detach_at):
        conn.execute(
            "INSERT INTO managed_channel_streams "
            "(managed_channel_id, dispatcharr_stream_id, priority, attach_at, detach_at) "
            "VALUES (?, 500, 0, ?, ?)",
            (channel_id, attach_at, detach_at),
        )

    add_to(10, "2026-06-01 18:00:00", "2026-06-01 21:00:00")  # game 1
    add_to(20, "2026-06-01 22:00:00", "2026-06-01 23:30:00")  # game 2
    add_to(30, "2026-06-01 23:45:00", "2026-06-02 02:30:00")  # game 3, crosses midnight
    conn.commit()

    # 19:00 — stream lives only in channel 10
    assert get_ordered_stream_ids(conn, 10, now="2026-06-01 19:00:00") == [500]
    assert get_ordered_stream_ids(conn, 20, now="2026-06-01 19:00:00") == []
    assert get_ordered_stream_ids(conn, 30, now="2026-06-01 19:00:00") == []

    # 21:30 — game 1 over, game 2 not yet started: detached everywhere (the gap)
    assert get_ordered_stream_ids(conn, 10, now="2026-06-01 21:30:00") == []
    assert get_ordered_stream_ids(conn, 20, now="2026-06-01 21:30:00") == []

    # 22:30 — re-attached to channel 20, gone from 10
    assert get_ordered_stream_ids(conn, 20, now="2026-06-01 22:30:00") == [500]
    assert get_ordered_stream_ids(conn, 10, now="2026-06-01 22:30:00") == []

    # 00:30 next day — re-attached to channel 30 (window spans midnight)
    assert get_ordered_stream_ids(conn, 30, now="2026-06-02 00:30:00") == [500]
    assert get_ordered_stream_ids(conn, 20, now="2026-06-02 00:30:00") == []


# ======================================================== update_stream_window (bead 095)


def _window_of(conn, stream_id):
    row = conn.execute(
        "SELECT attach_at, detach_at FROM managed_channel_streams "
        "WHERE dispatcharr_stream_id = ? AND removed_at IS NULL",
        (stream_id,),
    ).fetchone()
    return (row["attach_at"], row["detach_at"])


def test_update_window_recomputes_after_buffer_change(conn):
    # Stream attached with an old (narrow) window; a buffer change widens it.
    _add(conn, 200, attach_at="2026-06-01 17:00:00", detach_at="2026-06-01 21:00:00")
    changed = update_stream_window(
        conn, 1, 200, "2026-06-01 16:00:00", "2026-06-01 22:00:00"
    )
    assert changed is True
    assert _window_of(conn, 200) == ("2026-06-01 16:00:00", "2026-06-01 22:00:00")


def test_update_window_noop_when_unchanged(conn):
    _add(conn, 200, attach_at="2026-06-01 17:00:00", detach_at="2026-06-01 21:00:00")
    changed = update_stream_window(
        conn, 1, 200, "2026-06-01 17:00:00", "2026-06-01 21:00:00"
    )
    assert changed is False  # null-safe equality guard: no row touched


def test_update_window_ignores_removed_stream(conn):
    _add(conn, 200, attach_at="2026-06-01 17:00:00", detach_at="2026-06-01 21:00:00",
         removed_at="2026-06-01 17:30:00")
    changed = update_stream_window(
        conn, 1, 200, "2026-06-01 16:00:00", "2026-06-01 22:00:00"
    )
    assert changed is False


def test_update_window_can_set_from_null(conn):
    # A stream that was full-life (NULL) gains a real window on a later run.
    _add(conn, 200)
    changed = update_stream_window(
        conn, 1, 200, "2026-06-01 17:00:00", "2026-06-01 21:00:00"
    )
    assert changed is True
    assert _window_of(conn, 200) == ("2026-06-01 17:00:00", "2026-06-01 21:00:00")
