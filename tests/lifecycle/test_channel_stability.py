"""Tests for channel numbering stability modes (gap / strict) and the daily reset.

Covers the invariants behind stable channel numbers across an event's lifecycle:
- gap:    new channels slot into a free number in their sorted neighbourhood;
          existing (locked) channels never move; freed slots are reused.
- strict: new channels append to the end of the used range so nothing is displaced.
- reset:  the full re-layout (the only time locked channels move) re-grids by priority.
- gating: should_run_channel_reset fires once per day at/after the configured time.
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from teamarr.database import channel_numbers as cn


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE settings (
          id INTEGER PRIMARY KEY,
          channel_range_start INTEGER DEFAULT 101,
          channel_range_end INTEGER,
          global_channel_mode TEXT DEFAULT 'auto',
          league_channel_starts TEXT DEFAULT '{}',
          global_consolidation_mode TEXT DEFAULT 'consolidate',
          channel_stability_mode TEXT DEFAULT 'compact',
          channel_gap_size INTEGER DEFAULT 1,
          channel_daily_reset_enabled INTEGER DEFAULT 1,
          channel_daily_reset_time TEXT DEFAULT '04:00',
          last_channel_reset_at TEXT,
          force_channel_relayout_pending INTEGER DEFAULT 0
        );
        CREATE TABLE event_epg_groups (id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 1);
        CREATE TABLE managed_channels (
          id INTEGER PRIMARY KEY, dispatcharr_channel_id INTEGER, channel_number TEXT,
          channel_number_locked INTEGER DEFAULT 0, channel_name TEXT, event_epg_group_id INTEGER,
          primary_stream_id INTEGER, event_id TEXT, sport TEXT, league TEXT,
          home_team TEXT, away_team TEXT, event_date TEXT, exception_keyword TEXT,
          created_at TEXT, deleted_at TEXT
        );
        CREATE TABLE channel_sort_priorities (
          id INTEGER PRIMARY KEY, sport TEXT, league_code TEXT, sort_priority INTEGER,
          created_at TEXT, updated_at TEXT
        );
        CREATE TABLE channel_priority_teams (id INTEGER PRIMARY KEY, sport TEXT, team_name TEXT);
        INSERT INTO settings (id) VALUES (1);
        """
    )
    return conn


def _add(conn, cid, name, number, locked, event_date, event_id, keyword=None):
    conn.execute(
        """INSERT INTO managed_channels
           (id, channel_name, channel_number, channel_number_locked,
            event_date, event_id, exception_keyword, sport, league)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'football', 'nfl')""",
        (cid, name, number, locked, event_date, event_id, keyword),
    )


def _numbers(conn):
    rows = conn.execute(
        "SELECT channel_name, channel_number FROM managed_channels "
        "WHERE deleted_at IS NULL ORDER BY CAST(channel_number AS INT)"
    ).fetchall()
    return {r["channel_name"]: int(r["channel_number"]) for r in rows}


def _set_mode(conn, mode, gap=1):
    conn.execute(
        "UPDATE settings SET channel_stability_mode = ?, channel_gap_size = ?",
        (mode, gap),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# gap mode
# ---------------------------------------------------------------------------


def test_gap_new_channel_slots_into_neighbourhood(db):
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "104", 1, "2026-06-18 12:00:00", "e2")
    # New channel sorts (by time) between A and B; provisional number is irrelevant.
    _add(db, 3, "NEW", "500", 0, "2026-06-18 11:00:00", "e3")
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert nums["A"] == 101  # locked, unmoved
    assert nums["B"] == 104  # locked, unmoved
    assert 101 < nums["NEW"] < 104  # slotted into the gap


def test_gap_reuses_freed_slot(db):
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "104", 1, "2026-06-18 12:00:00", "e2")
    db.commit()
    # A ends → its slot (101) is freed; a new earliest event should reclaim it.
    db.execute("UPDATE managed_channels SET deleted_at = 'x' WHERE id = 1")
    _add(db, 3, "NEW", "500", 0, "2026-06-18 09:00:00", "e3")
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert nums["NEW"] == 101
    assert nums["B"] == 104  # untouched


def test_gap_locked_channels_never_move_on_sticky(db):
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "104", 1, "2026-06-18 12:00:00", "e2")
    db.commit()
    result = cn.reassign_all_channels(db)
    assert result["channels_moved"] == 0
    assert _numbers(db) == {"A": 101, "B": 104}


def test_gap_initial_placement_leaves_gaps(db):
    # All-new channels (nothing locked yet) must space out on the grid so late
    # events have room to slot in — not pack contiguously.
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "A", "500", 0, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "501", 0, "2026-06-18 12:00:00", "e2")
    _add(db, 3, "C", "502", 0, "2026-06-18 14:00:00", "e3")
    db.commit()

    cn.reassign_all_channels(db)
    assert _numbers(db) == {"A": 101, "B": 104, "C": 107}


def test_gap_late_feed_extends_event_contiguously(db):
    # Feeds of one game are discovered across runs: the base feed locks first, then
    # home/away feeds appear later. A late feed must extend the event's run into the
    # gap reserved right after it (102/103) — NOT jump a full gap_size away (105),
    # which scatters one game's feeds across the channel list.
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "GAME", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "GAME (Home)", "102", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 3, "GAME (Away)", "500", 0, "2026-06-18 10:00:00", "e1")  # new feed
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert nums["GAME"] == 101 and nums["GAME (Home)"] == 102  # anchors untouched
    assert nums["GAME (Away)"] == 103  # contiguous, not 105 (a full gap away)


def test_gap_invalidated_lock_is_replaced(db):
    # A locked channel whose number fell outside the range (e.g. range was
    # shrunk) is re-gridded on the next sticky run, not stranded until reset.
    db.execute("UPDATE settings SET channel_range_end = 110")
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "OUT", "9999", 1, "2026-06-18 12:00:00", "e2")  # out of range
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert nums["A"] == 101  # valid anchor, untouched
    assert 101 < nums["OUT"] <= 110  # pulled back into range


# ---------------------------------------------------------------------------
# strict mode
# ---------------------------------------------------------------------------


def test_strict_new_channel_appends_to_end(db):
    _set_mode(db, "strict")
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "102", 1, "2026-06-18 12:00:00", "e2")
    # New event sorts FIRST by time, but strict must append it to the end.
    _add(db, 3, "NEW", "500", 0, "2026-06-18 08:00:00", "e3")
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert nums["A"] == 101
    assert nums["B"] == 102
    assert nums["NEW"] == 103  # appended, did not displace A/B


# ---------------------------------------------------------------------------
# event feeds — home/away/regular stay contiguous (no gap between them)
# ---------------------------------------------------------------------------


def test_gap_sticky_feeds_placed_as_contiguous_block(db):
    # A new event's feeds (same event_id) must land on adjacent numbers, even in
    # gap mode — the gap belongs between events, not between feeds of one game.
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "104", 1, "2026-06-18 12:00:00", "e2")
    _add(db, 3, "NEW-Home", "500", 0, "2026-06-18 11:00:00", "e3")
    _add(db, 4, "NEW-Away", "501", 0, "2026-06-18 11:00:00", "e3")
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert nums["A"] == 101 and nums["B"] == 104  # anchors untouched
    # Both feeds slot into the 102/103 gap, adjacent, nothing between them.
    assert {nums["NEW-Home"], nums["NEW-Away"]} == {102, 103}


def test_gap_sticky_feed_block_appends_together_when_gap_too_small(db):
    # 3 feeds can't fit in a 2-slot gap → the whole block appends past the frontier,
    # still contiguous, without splitting or displacing the anchors.
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "104", 1, "2026-06-18 12:00:00", "e2")
    _add(db, 3, "F1", "500", 0, "2026-06-18 11:00:00", "e3")
    _add(db, 4, "F2", "501", 0, "2026-06-18 11:00:00", "e3")
    _add(db, 5, "F3", "502", 0, "2026-06-18 11:00:00", "e3")
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert nums["A"] == 101 and nums["B"] == 104
    feeds = sorted([nums["F1"], nums["F2"], nums["F3"]])
    assert feeds == [feeds[0], feeds[0] + 1, feeds[0] + 2]  # contiguous
    assert feeds[0] > 104  # appended past the anchors, none displaced


def test_gap_sticky_multi_feed_block_then_full_gap(db):
    # Sticky initial placement: a 3-feed event packs 101-103, and the next event
    # starts a full gap *after* the block end (103 + 3 = 106) — the inter-event gap
    # follows the whole home/away block instead of being measured from its first slot.
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "H", "500", 0, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "A", "501", 0, "2026-06-18 10:00:00", "e1")
    _add(db, 3, "R", "502", 0, "2026-06-18 10:00:00", "e1")
    _add(db, 4, "Solo", "503", 0, "2026-06-18 12:00:00", "e2")
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert sorted([nums["H"], nums["A"], nums["R"]]) == [101, 102, 103]
    assert nums["Solo"] == 106  # full gap after the block end (103 + gap)


def test_strict_feeds_append_contiguously(db):
    _set_mode(db, "strict")
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "Home", "500", 0, "2026-06-18 12:00:00", "e2")
    _add(db, 3, "Away", "501", 0, "2026-06-18 12:00:00", "e2")
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert nums["A"] == 101
    assert {nums["Home"], nums["Away"]} == {102, 103}


def test_gap_sticky_keyword_variants_stay_contiguous(db):
    # An exception keyword breaks a stream out onto its own channel, but that
    # channel shares the event's event_id — so the main channel and its keyword
    # variant(s) must be placed as one contiguous block, just like home/away feeds.
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "104", 1, "2026-06-18 12:00:00", "e2")
    _add(db, 3, "NEW", "500", 0, "2026-06-18 11:00:00", "e3")
    _add(db, 4, "NEW (Spanish)", "501", 0, "2026-06-18 11:00:00", "e3", keyword="Spanish")
    db.commit()

    cn.reassign_all_channels(db)
    nums = _numbers(db)
    assert nums["A"] == 101 and nums["B"] == 104  # anchors untouched
    # Main channel + keyword variant slot into the 102/103 gap, adjacent.
    assert {nums["NEW"], nums["NEW (Spanish)"]} == {102, 103}
    # Main channel sorts before the keyword variant.
    assert nums["NEW"] < nums["NEW (Spanish)"]


def test_gap_reset_keyword_variant_contiguous_with_gap_between_events(db):
    # Reset: a main + keyword channel for one event pack adjacently (101-102), and
    # the next event starts a full gap *after* the block's end (102 + 3 = 105).
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "Main", "200", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "Main (Spanish)", "201", 1, "2026-06-18 10:00:00", "e1", keyword="Spanish")
    _add(db, 3, "Solo", "150", 1, "2026-06-18 12:00:00", "e2")
    db.commit()

    cn.reassign_all_channels(db, force_reset=True)
    nums = _numbers(db)
    assert nums["Main"] == 101 and nums["Main (Spanish)"] == 102  # adjacent block
    assert nums["Solo"] == 105  # full gap after the block end (102 + gap)


def test_gap_reset_feeds_contiguous_with_gap_between_events(db):
    # Reset: a 3-feed event packs 101-103, and the next event starts a full gap
    # *after* the block's end (103 + 3 = 106) — the gap follows the block instead
    # of being eaten by the extra feeds; feeds themselves are never spaced apart.
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "H", "200", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "A", "201", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 3, "R", "202", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 4, "Solo", "150", 1, "2026-06-18 12:00:00", "e2")
    db.commit()

    cn.reassign_all_channels(db, force_reset=True)
    nums = _numbers(db)
    assert sorted([nums["H"], nums["A"], nums["R"]]) == [101, 102, 103]
    assert nums["Solo"] == 106  # full gap after the block end (103 + gap)


def test_gap_reset_two_feed_event_then_gap(db):
    # A 2-feed event packs 101-102, then a full gap follows the block end
    # (102 + 3 = 105) — same inter-event spacing regardless of block width.
    _set_mode(db, "gap", gap=3)
    _add(db, 1, "H", "200", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "A", "201", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 3, "Solo", "150", 1, "2026-06-18 12:00:00", "e2")
    db.commit()

    cn.reassign_all_channels(db, force_reset=True)
    nums = _numbers(db)
    assert sorted([nums["H"], nums["A"]]) == [101, 102]
    assert nums["Solo"] == 105  # full gap after the block end (102 + gap)


# ---------------------------------------------------------------------------
# daily reset
# ---------------------------------------------------------------------------


def test_reset_relayout_regrids_by_priority(db):
    _set_mode(db, "gap", gap=3)
    # Out-of-order numbers; reset should re-grid by event time at 101, 104, 107.
    _add(db, 1, "A", "120", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "101", 1, "2026-06-18 12:00:00", "e2")
    _add(db, 3, "C", "150", 1, "2026-06-18 14:00:00", "e3")
    db.commit()

    cn.reassign_all_channels(db, force_reset=True)
    nums = _numbers(db)
    assert nums == {"A": 101, "B": 104, "C": 107}
    # Reset stamps last_channel_reset_at so the daily gate closes.
    stamp = db.execute("SELECT last_channel_reset_at FROM settings WHERE id = 1").fetchone()[0]
    assert stamp is not None


def test_strict_reset_is_contiguous(db):
    _set_mode(db, "strict")
    _add(db, 1, "A", "120", 1, "2026-06-18 10:00:00", "e1")
    _add(db, 2, "B", "101", 1, "2026-06-18 12:00:00", "e2")
    db.commit()
    cn.reassign_all_channels(db, force_reset=True)
    assert _numbers(db) == {"A": 101, "B": 102}


# ---------------------------------------------------------------------------
# reset gating
# ---------------------------------------------------------------------------


def test_compact_mode_never_resets(db):
    _set_mode(db, "compact")
    assert cn.should_run_channel_reset(db) is False
    assert cn.is_sticky_mode(db) is False


def test_reset_fires_first_run_after_window(db):
    _set_mode(db, "gap", gap=3)
    db.execute("UPDATE settings SET channel_daily_reset_time = '00:00'")  # always passed today
    db.commit()
    # No prior reset → should fire.
    assert cn.should_run_channel_reset(db) is True


def test_reset_does_not_refire_same_day(db):
    _set_mode(db, "gap", gap=3)
    db.execute("UPDATE settings SET channel_daily_reset_time = '00:00'")
    # Already reset earlier today.
    db.execute(
        "UPDATE settings SET last_channel_reset_at = ?",
        (datetime.now().isoformat(),),
    )
    db.commit()
    assert cn.should_run_channel_reset(db) is False


def test_reset_refires_next_day(db):
    _set_mode(db, "gap", gap=3)
    db.execute("UPDATE settings SET channel_daily_reset_time = '00:00'")
    db.execute(
        "UPDATE settings SET last_channel_reset_at = ?",
        ((datetime.now() - timedelta(days=1)).isoformat(),),
    )
    db.commit()
    assert cn.should_run_channel_reset(db) is True


def test_reset_disabled_never_fires(db):
    _set_mode(db, "gap", gap=3)
    db.execute(
        "UPDATE settings SET channel_daily_reset_time = '00:00', "
        "channel_daily_reset_enabled = 0"
    )
    db.commit()
    assert cn.should_run_channel_reset(db) is False


def test_sticky_mode_detection(db):
    _set_mode(db, "gap")
    assert cn.is_sticky_mode(db) is True
    _set_mode(db, "strict")
    assert cn.is_sticky_mode(db) is True
    # Manual global mode overrides stability (per-league sequential).
    db.execute("UPDATE settings SET global_channel_mode = 'manual'")
    db.commit()
    assert cn.is_sticky_mode(db) is False


# ---------------------------------------------------------------------------
# one-shot manual / auto-armed re-grid
# ---------------------------------------------------------------------------


def test_armed_relayout_fires_before_window(db):
    # Armed re-grid bypasses the daily time gate (reset time in the future today).
    _set_mode(db, "gap", gap=3)
    db.execute("UPDATE settings SET channel_daily_reset_time = '23:59'")
    db.execute(
        "UPDATE settings SET last_channel_reset_at = ?",
        (datetime.now().isoformat(),),  # already reset today → time gate would block
    )
    db.commit()
    assert cn.should_run_channel_reset(db) is False
    assert cn.arm_channel_relayout(db) is True
    assert cn.should_run_channel_reset(db) is True


def test_armed_relayout_bypasses_reset_disabled(db):
    # An explicit re-grid runs even when the daily auto-reset is turned off.
    _set_mode(db, "gap", gap=3)
    db.execute("UPDATE settings SET channel_daily_reset_enabled = 0")
    db.commit()
    assert cn.should_run_channel_reset(db) is False
    cn.arm_channel_relayout(db)
    assert cn.should_run_channel_reset(db) is True


def test_armed_relayout_ignored_in_compact(db):
    _set_mode(db, "compact")
    cn.arm_channel_relayout(db)
    assert cn.should_run_channel_reset(db) is False


def test_reset_clears_armed_flag(db):
    # Running the re-layout consumes the one-shot flag so it won't refire.
    _set_mode(db, "gap", gap=3)
    db.execute("UPDATE settings SET channel_daily_reset_enabled = 0")
    db.commit()
    cn.arm_channel_relayout(db)
    _add(db, 1, "A", "101", 1, "2026-06-18 10:00:00", "e1")
    db.commit()

    cn.reassign_all_channels(db, force_reset=cn.should_run_channel_reset(db))
    assert cn.should_run_channel_reset(db) is False
    row = db.execute(
        "SELECT force_channel_relayout_pending FROM settings WHERE id = 1"
    ).fetchone()
    assert not row[0]


# ---------------------------------------------------------------------------
# Auto-arm on settings changes (teamarrv2-kc43)
# ---------------------------------------------------------------------------


def _pending(conn) -> bool:
    row = conn.execute(
        "SELECT force_channel_relayout_pending FROM settings WHERE id = 1"
    ).fetchone()
    return bool(row[0])


def test_range_change_arms_relayout_in_sticky_mode(db):
    # Moving the range only takes effect at re-layout (locked channels stay
    # put), so a range change must queue the one-shot re-grid.
    from teamarr.database.settings.update import update_lifecycle_settings

    _set_mode(db, "gap", gap=3)
    db.commit()

    assert update_lifecycle_settings(db, channel_range_start=2000)
    assert _pending(db)


def test_range_end_change_arms_relayout_in_sticky_mode(db):
    from teamarr.database.settings.update import update_lifecycle_settings

    _set_mode(db, "strict")
    db.commit()

    assert update_lifecycle_settings(db, channel_range_end=5000)
    assert _pending(db)


def test_unchanged_range_does_not_arm(db):
    # The UI full-PUTs the settings object — saving the same values must not
    # queue a re-grid.
    from teamarr.database.settings.update import update_lifecycle_settings

    _set_mode(db, "gap", gap=3)
    db.execute("UPDATE settings SET channel_range_start = 101, channel_range_end = NULL")
    db.commit()

    assert update_lifecycle_settings(db, channel_range_start=101, channel_range_end=None)
    assert not _pending(db)


def test_range_change_does_not_arm_in_compact_mode(db):
    # Compact re-sorts every run — the range change takes effect immediately,
    # no re-grid needed.
    from teamarr.database.settings.update import update_lifecycle_settings

    _set_mode(db, "compact")
    db.commit()

    assert update_lifecycle_settings(db, channel_range_start=2000)
    assert not _pending(db)


def test_range_change_does_not_arm_in_manual_mode(db):
    from teamarr.database.settings.update import update_lifecycle_settings

    _set_mode(db, "gap", gap=3)
    db.execute("UPDATE settings SET global_channel_mode = 'manual'")
    db.commit()

    assert update_lifecycle_settings(db, channel_range_start=2000)
    assert not _pending(db)


def test_switch_to_compact_clears_armed_flag(db):
    # An armed re-grid is meaningless in compact mode — leaving the sticky
    # modes drops it so it doesn't linger as stale queued state.
    from teamarr.database.settings.update import update_channel_numbering_settings

    _set_mode(db, "gap", gap=3)
    db.commit()
    cn.arm_channel_relayout(db)
    assert _pending(db)

    assert update_channel_numbering_settings(db, channel_stability_mode="compact")
    assert not _pending(db)


def test_switch_between_sticky_modes_keeps_arming(db):
    # gap -> strict is a layout change: it arms (not clears) the re-grid.
    from teamarr.database.settings.update import update_channel_numbering_settings

    _set_mode(db, "gap", gap=3)
    db.commit()

    assert update_channel_numbering_settings(db, channel_stability_mode="strict")
    assert _pending(db)
