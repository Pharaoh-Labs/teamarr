"""Behavior tests for run_full_generation's helper stages
(teamarr/consumers/generation.py — iua3.5 coverage gap, was zero tests).

Each helper is exercised against a real temp database (conftest db fixtures):
- _refresh_m3u_accounts short-circuits without touching Dispatcharr when no
  group has an M3U account.
- _validate_channel_ranges reports external-channel collisions against the
  configured global range (#146) and stays quiet otherwise.
- _apply_stream_ordering applies rules to stream priorities in the DB, runs
  as a window-sync-only pass without rules, and converts internal failures
  into an "error" result key instead of raising (generation must not die).
"""

import json

from teamarr.consumers.generation import (
    _apply_stream_ordering,
    _refresh_m3u_accounts,
    _validate_channel_ranges,
)
from teamarr.services.stream_ordering import NO_MATCH_PRIORITY


def _noop_progress(*args):
    pass


class _ExplodingClient:
    """Fails the test if any Dispatcharr call is attempted."""

    def __getattr__(self, name):
        raise AssertionError(f"Dispatcharr client touched: {name}")


# ---------------------------------------------------------------------------
# _refresh_m3u_accounts
# ---------------------------------------------------------------------------


def test_m3u_refresh_skips_client_when_no_groups_have_accounts(db_factory):
    result = _refresh_m3u_accounts(db_factory, _ExplodingClient())
    assert result == {"refreshed": 0, "skipped": 0, "failed": 0, "account_ids": []}


# ---------------------------------------------------------------------------
# _validate_channel_ranges (#146)
# ---------------------------------------------------------------------------


def test_channel_ranges_no_external_channels(db_factory):
    conflicts = _validate_channel_ranges(db_factory, set())
    assert conflicts["external_channels_detected"] == 0
    assert conflicts["max_external_channel"] == 0
    assert conflicts["group_warnings"] == []


def test_channel_ranges_reports_in_range_collisions(db_factory, db_conn):
    db_conn.execute(
        "UPDATE settings SET channel_range_start = 100, channel_range_end = 200 WHERE id = 1"
    )
    db_conn.commit()

    # 150 collides with the 100-200 range; 5000 is outside it.
    conflicts = _validate_channel_ranges(db_factory, {150, 5000})

    assert conflicts["external_channels_detected"] == 2
    assert conflicts["max_external_channel"] == 5000
    assert len(conflicts["group_warnings"]) == 1
    warning = conflicts["group_warnings"][0]
    assert warning["group_name"] == "Global Range"
    assert warning["range"] == "100-200"
    assert warning["external_collisions"] == 1
    assert warning["available_slots"] == 100  # 101 slots minus the collision


def test_channel_ranges_outside_range_is_not_a_conflict(db_factory, db_conn):
    db_conn.execute(
        "UPDATE settings SET channel_range_start = 100, channel_range_end = 200 WHERE id = 1"
    )
    db_conn.commit()

    conflicts = _validate_channel_ranges(db_factory, {5000, 6000})
    assert conflicts["group_warnings"] == []


# ---------------------------------------------------------------------------
# _apply_stream_ordering
# ---------------------------------------------------------------------------


def _seed_channel_with_streams(conn):
    cur = conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name) "
        "VALUES ('e1', 'espn', 'tvg-1', 'Test Channel')"
    )
    channel_id = cur.lastrowid
    conn.executemany(
        """INSERT INTO managed_channel_streams
           (managed_channel_id, dispatcharr_stream_id, stream_name, priority)
           VALUES (?, ?, ?, ?)""",
        [
            (channel_id, 100, "ESPN 1080p", 0),
            (channel_id, 101, "ESPN 720p", 0),
        ],
    )
    conn.commit()
    return channel_id


def test_ordering_without_rules_is_window_sync_only(db_factory, db_conn):
    _seed_channel_with_streams(db_conn)

    result = _apply_stream_ordering(db_factory, None, _noop_progress)

    assert "error" not in result
    assert result["channels_reordered"] == 0
    assert result["streams_reordered"] == 0
    # Priorities untouched.
    rows = db_conn.execute("SELECT priority FROM managed_channel_streams").fetchall()
    assert [r["priority"] for r in rows] == [0, 0]


def test_ordering_applies_rules_to_db_priorities(db_factory, db_conn):
    _seed_channel_with_streams(db_conn)
    rules = [{"type": "regex", "value": "(?i)1080p", "priority": 1}]
    db_conn.execute(
        "UPDATE settings SET stream_ordering_rules = ? WHERE id = 1", (json.dumps(rules),)
    )
    db_conn.commit()

    result = _apply_stream_ordering(db_factory, None, _noop_progress)

    assert result["channels_reordered"] == 1
    assert result["streams_reordered"] == 2  # both moved off the default 0
    rows = {
        r["dispatcharr_stream_id"]: r["priority"]
        for r in db_conn.execute(
            "SELECT dispatcharr_stream_id, priority FROM managed_channel_streams"
        ).fetchall()
    }
    assert rows[100] == 1  # matched the 1080p rule
    assert rows[101] == NO_MATCH_PRIORITY  # unmatched falls to the bottom


def test_ordering_failure_is_captured_not_raised(db_conn):
    def broken_factory():
        raise RuntimeError("db exploded")

    result = _apply_stream_ordering(broken_factory, None, _noop_progress)
    assert result["error"] == "db exploded"
    assert result["channels_reordered"] == 0
