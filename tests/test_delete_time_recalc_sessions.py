"""Delete-time recalc must not clobber a session-aware end estimate (#522).

`_recalculate_deletion_times` exists to apply *timing policy* changes
(same_day vs after_event, buffer minutes) to live channels. It re-derived the
event *end* from `event_date + sport_duration`, which cannot see sessions —
and because it OVERWRITES `scheduled_delete_at`, a multi-day race weekend got
its delete time pulled back to just after Friday practice.

Policy still applies to the stored end; only the end itself is no longer
guessed when we already computed a better one at creation.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from dateutil import parser

from teamarr.consumers.lifecycle.cleanup import ChannelCleanup
from teamarr.database.connection import get_db, init_db

# Race weekend: practice Friday, race Sunday.
PRACTICE_START = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)
RACE_END = datetime(2026, 5, 3, 21, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TZ", "UTC")
    init_db()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) "
            'VALUES (999992, \'test-recalc\', \'["f1"]\')'
        )
        conn.commit()
    yield


def _add_channel(channel_id: int, event_end_estimate: datetime | None) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO managed_channels
               (id, event_id, event_provider, tvg_id, event_epg_group_id, channel_name,
                event_date, event_end_estimate, scheduled_delete_at, sport, league)
               VALUES (?, ?, 'espn', ?, 999992, 'Race', ?, ?, ?, 'racing', 'f1')""",
            (
                channel_id,
                f"evt-{channel_id}",
                f"tvg-{channel_id}",
                PRACTICE_START.isoformat(),
                event_end_estimate.isoformat() if event_end_estimate else None,
                # Whatever creation stored; recalc decides whether to change it.
                (RACE_END + timedelta(minutes=30)).isoformat(),
            ),
        )
        conn.commit()


def _cleanup(post_buffer_minutes: int = 30) -> ChannelCleanup:
    obj = ChannelCleanup.__new__(ChannelCleanup)
    obj._db_factory = get_db
    timing = MagicMock()
    timing.delete_timing = "after_event"
    timing.post_buffer_minutes = post_buffer_minutes
    timing.sport_durations = {"racing": 3}
    timing.default_duration_hours = 3
    obj._timing_manager = timing
    return obj


def _stored_delete(channel_id: int) -> datetime:
    with get_db() as conn:
        row = conn.execute(
            "SELECT scheduled_delete_at FROM managed_channels WHERE id = ?", (channel_id,)
        ).fetchone()
    return parser.parse(str(row["scheduled_delete_at"]))


def test_session_aware_estimate_is_not_clobbered(db):
    """The regression: recalc must not pull a race weekend back to Friday."""
    _add_channel(1, event_end_estimate=RACE_END)

    with get_db() as conn:
        ChannelCleanup._recalculate_deletion_times(_cleanup(), conn)
        conn.commit()

    assert _stored_delete(1) == RACE_END + timedelta(minutes=30)


def test_policy_change_still_applies_to_the_stored_end(db):
    """Recalc keeps doing its actual job — a buffer change must take effect."""
    _add_channel(2, event_end_estimate=RACE_END)

    with get_db() as conn:
        ChannelCleanup._recalculate_deletion_times(_cleanup(post_buffer_minutes=90), conn)
        conn.commit()

    assert _stored_delete(2) == RACE_END + timedelta(minutes=90)


def test_null_estimate_falls_back_to_the_naive_derivation(db):
    """Pre-column rows keep today's behaviour rather than being guessed at."""
    _add_channel(3, event_end_estimate=None)

    with get_db() as conn:
        ChannelCleanup._recalculate_deletion_times(_cleanup(), conn)
        conn.commit()

    naive_end = PRACTICE_START + timedelta(hours=3)
    assert _stored_delete(3) == naive_end + timedelta(minutes=30)
