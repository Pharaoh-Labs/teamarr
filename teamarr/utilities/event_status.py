"""Event status utilities.

Single source of truth for determining event final status.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.core import Event

# Where a provider's "time not announced" placeholder is midnight (ESPN).
PLACEHOLDER_TIMEZONE = ZoneInfo("America/New_York")


def unannounced_day_start(placeholder: datetime) -> datetime:
    """Start of the game's day in the user's timezone, for an unannounced time (#995).

    A provider with no start time to give sends midnight Eastern of the game's
    date. Only the date in that timestamp is information. Read as an instant
    it lands on the previous evening for anyone west of Eastern, so the game
    is anchored to midnight of that same calendar date where the user is.
    """
    from teamarr.config import get_user_timezone

    day = placeholder.astimezone(PLACEHOLDER_TIMEZONE).date()
    # UTC like every other event start: arithmetic between two datetimes in
    # one zone is wall-clock in Python and miscounts a day with a clock change.
    return datetime(day.year, day.month, day.day, tzinfo=get_user_timezone()).astimezone(UTC)


def event_programme_start(event: Event, pregame_minutes: float = 0) -> datetime:
    """When the event's own programme starts: its start less the pregame lead-in.

    A game with no announced time gets no lead-in — its programme is the day.
    """
    if getattr(event, "time_tbd", False):
        return event.start_time
    return event.start_time - timedelta(minutes=pregame_minutes)


def event_end_time(event: Event, duration_hours: float) -> datetime:
    """When the event ends: its start plus the duration that applies to it.

    A game with no announced time (#995) is an all-day placeholder: it runs to
    the next midnight in the user's timezone, whatever the duration. Every
    span calculation for an event (programme, filler, channel deletion) must
    come through here, or the placeholder day and the filler around it overlap.
    """
    if getattr(event, "time_tbd", False):
        from teamarr.utilities.tz import to_user_tz

        local = to_user_tz(event.start_time)
        next_day = (local + timedelta(days=1)).date()
        return datetime(
            next_day.year, next_day.month, next_day.day, tzinfo=local.tzinfo
        ).astimezone(UTC)
    return event.start_time + timedelta(hours=duration_hours)


def is_event_final(event: Event) -> bool:
    """Check if an event is final/completed.

    This is the SINGLE SOURCE OF TRUTH for final status detection.
    Use this function everywhere final status needs to be checked.

    Checks multiple indicators because different providers use different values:
    - ESPN: "final", "post" (soccer uses STATUS_FULL_TIME -> "final")
    - TSDB: "final" (from "ft", "aet", "finished")
    - HockeyTech: "final" (from "Final", "Final OT", "Final SO")
    - Cricbuzz: "final" (from "complete", "finished")

    Args:
        event: Event to check

    Returns:
        True if event is final/completed, False otherwise
    """
    if not event or not event.status:
        return False

    status_state = event.status.state.lower() if event.status.state else ""
    status_detail = event.status.detail.lower() if event.status.detail else ""

    # Check state for common final indicators
    if status_state in ("final", "post", "completed"):
        return True

    # Check detail for "final" (e.g., "Final", "Final OT", "Final - 3OT")
    if "final" in status_detail:
        return True

    return False
