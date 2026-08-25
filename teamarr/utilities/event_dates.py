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
  everything providers return; providers never decide date membership
  themselves.
- :func:`provider_day_buckets` says which provider-day fetches make up the
  superset that filter runs over. Asking a provider to OVER-return is not
  enough when the API buckets server-side (#601) — the union has to be built
  on the fetch side.
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


def provider_day_buckets(target_date: date) -> list[date]:
    """Provider-day buckets that can hold events belonging to the user's day.

    :func:`user_day_window` decides membership, but the *fetch* is not free to
    ignore calendars: server-side day-bucketed APIs (ESPN's scoreboard
    ``?dates=``, MLB Stats) file an event under **their** calendar day, so a
    provider asked for ``target_date`` returns only its own bucket. When the
    two calendars disagree — a user far from the API's home region — an event
    is filtered out of day D (past the end of the local window) and never
    fetched under day D+1 (the provider files it under D). It falls through
    both ends and becomes invisible at every lookahead (#601).

    Fetching D-1..D+1 and unioning restores the ±1-day superset the seam
    assumes. One day either side is sufficient exactly while::

        offset_user - offset_provider <= 24h - EVENT_TAIL_HOURS   (i.e. 21h)
        offset_provider - offset_user <= 24h

    The first bound binds. ESPN buckets around US Eastern (~UTC-4), so even a
    UTC+14 user sits at 18h — safe, but with only 3h of headroom, and resting
    on a provider bucketing offset nobody writes down. A provider that buckets
    further east than ESPN would silently reopen the hole, so widen the span
    here rather than assume ±1 day is inherently enough (#601).
    """
    return [
        target_date - timedelta(days=1),
        target_date,
        target_date + timedelta(days=1),
    ]


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
