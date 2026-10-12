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
    cursor = conn.execute(
        "DELETE FROM source_health_decisions WHERE group_id = ?", (group_id,)
    )
    conn.commit()
    return cursor.rowcount > 0
