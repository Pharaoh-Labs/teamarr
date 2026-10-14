"""User decisions for advisory source-health recommendations."""

from datetime import datetime, timedelta
from sqlite3 import Connection

from teamarr.utilities.tz import now_utc, to_db_utc

SNOOZE_DAYS = 30


def set_source_health_decision(
    conn: Connection,
    group_id: int,
    decision: str,
    *,
    last_matched_at: str | None = None,
    now: datetime | None = None,
) -> None:
    """Keep a recommendation until new matching activity, or snooze it 30 days."""
    if decision not in ("keep", "snooze"):
        raise ValueError(f"Unsupported source-health decision: {decision}")
    now = now or now_utc()
    snoozed_until = None
    baseline = None
    if decision == "keep":
        baseline = last_matched_at
    else:
        snoozed_until = to_db_utc(now + timedelta(days=SNOOZE_DAYS))
    conn.execute(
        """INSERT INTO source_health_decisions
               (group_id, decision, decided_at, baseline_last_matched_at, snoozed_until)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(group_id) DO UPDATE SET
               decision = excluded.decision,
               decided_at = excluded.decided_at,
               baseline_last_matched_at = excluded.baseline_last_matched_at,
               snoozed_until = excluded.snoozed_until""",
        (group_id, decision, to_db_utc(now), baseline, snoozed_until),
    )
    conn.commit()


def clear_source_health_decision(conn: Connection, group_id: int) -> bool:
    """Restore a kept/snoozed source to the active review list."""
    cursor = conn.execute("DELETE FROM source_health_decisions WHERE group_id = ?", (group_id,))
    conn.commit()
    return cursor.rowcount > 0


def record_league_event_activity(
    conn: Connection,
    league_codes: set[str],
    *,
    now: datetime | None = None,
    reset_after_days: int = 21,
) -> None:
    """Record a positive-event activity streak independently of stream matches."""
    if not league_codes:
        return
    now = now or now_utc()
    stamp = to_db_utc(now)
    gap_cutoff = to_db_utc(now - timedelta(days=reset_after_days))
    for code in league_codes:
        normalized = code.strip().lower()
        if not normalized:
            continue
        conn.execute(
            """INSERT INTO league_event_activity
                   (league_code, activity_started_at, last_observed_at)
               VALUES (?, ?, ?)
               ON CONFLICT(league_code) DO UPDATE SET
                   activity_started_at = CASE
                       WHEN league_event_activity.last_observed_at < ?
                       THEN excluded.activity_started_at
                       ELSE league_event_activity.activity_started_at
                   END,
                   last_observed_at = excluded.last_observed_at""",
            (normalized, stamp, stamp, gap_cutoff),
        )
