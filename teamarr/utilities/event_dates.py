"""User-day windows and event/window intersection (#590).

Calendar dates must not cross the provider boundary. A requested
``target_date`` is a **user-local** calendar day; providers, however, receive
dates from APIs bucketed by *someone else's* calendar (UTC, the venue, the
API's home region). Comparing those calendars directly is the bug class
behind #345 and #588.

The structure that ends it:

- :func:`user_day_window` converts the user-local day to a UTC interval —
  the ONLY place the user's timezone is consulted for date membership.
- :func:`event_intersects` decides membership with pure instant arithmetic —
  no timezone code at all.
- The service layer (``sports_data.get_events``) applies the filter to
  everything providers return, so providers only need to OVER-return
  (±1-day raw supersets); they never decide date membership themselves.
"""

from datetime import UTC, date, datetime, time, timedelta

from teamarr.core import Event
from teamarr.utilities.tz import get_user_timezone

# How long an event plausibly runs past its last known start time, so a
# late start spills into the day it crosses into (a 23:00 game belongs to
# both days). Matches the tail previously hardcoded in ESPN's UFC coverage
# filter (#345), which this module supersedes.
EVENT_TAIL_HOURS = 3.0


def user_day_window(target_date: date) -> tuple[datetime, datetime]:
    """The UTC half-open interval [start, end) of ``target_date`` in user tz.

    DST-safe: a 23- or 25-hour local day yields exactly that window.
    """
    tz = get_user_timezone()
    start = datetime.combine(target_date, time.min, tzinfo=tz)
    end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def event_times(event: Event) -> list[datetime]:
    """Every known instant of an event: segment starts, session starts, start.

    Naive datetimes are treated as UTC (providers hand us aware UTC; naive
    only appears in legacy paths and tests).
    """
    times: list[datetime] = []
    for t in (getattr(event, "segment_times", None) or {}).values():
        if t is not None:
            times.append(t)
    for session in getattr(event, "sessions", None) or []:
        if session.start_time is not None:
            times.append(session.start_time)
    if event.start_time is not None:
        times.append(event.start_time)
    return [t if t.tzinfo is not None else t.replace(tzinfo=UTC) for t in times]


def event_intersects(event: Event, window: tuple[datetime, datetime]) -> bool:
    """Whether the event's plausible broadcast span touches ``window``.

    The span runs from the earliest known instant to the latest known
    instant plus :data:`EVENT_TAIL_HOURS`. Events with no known times can't
    be placed on any day and are excluded.
    """
    times = event_times(event)
    if not times:
        return False
    first = min(times)
    last = max(times) + timedelta(hours=EVENT_TAIL_HOURS)
    start, end = window
    # Strict on both edges: a span that only touches a boundary instant
    # (e.g. a tail ending exactly at midnight) has zero overlap with the day.
    return first < end and last > start
