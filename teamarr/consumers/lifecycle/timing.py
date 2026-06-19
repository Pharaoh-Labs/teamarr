"""Channel lifecycle timing decisions.

Handles when to create and delete event channels based on timing rules.

Create timing options:
- same_day: Create at midnight (00:00) of event day
- before_event: Create event_start - pre_buffer_minutes

Delete timing options:
- same_day: Delete at 23:59 of event end date. If event crosses midnight,
  uses event_end + post_buffer_minutes instead to avoid 23hr stale window.
- after_event: Delete at event_end + post_buffer_minutes
"""

import logging
from datetime import UTC, datetime, timedelta

from teamarr.consumers.matching.result import ExcludedReason
from teamarr.core import Event
from teamarr.utilities.event_status import is_event_final
from teamarr.utilities.sports import get_sport_duration
from teamarr.utilities.time_blocks import crosses_midnight
from teamarr.utilities.tz import now_user, to_user_tz

from .types import CreateTiming, DeleteTiming, LifecycleDecision

logger = logging.getLogger(__name__)

# SQLite-native UTC timestamp format ("YYYY-MM-DD HH:MM:SS"), directly
# comparable to datetime('now') for time-windowed stream membership gating.
_SQLITE_UTC_FMT = "%Y-%m-%d %H:%M:%S"


def compute_stream_window(
    program_start: datetime | None,
    program_end: datetime | None,
    pre_buffer_minutes: int,
    post_buffer_minutes: int,
) -> tuple[str | None, str | None]:
    """Compute the (attach_at, detach_at) window for a time-shared linear stream.

    Used by epic teamarrv2-183.5: an EPG-matched linear stream attaches to an
    event channel only near game time and detaches after. The window is the
    matched EPG program slot widened by the global stream buffers:

        attach = program_start - pre_buffer
        detach = program_end + post_buffer

    The buffers apply unclipped: if two programs on the same channel overlap once
    widened, the stream is simply a member of both event channels during the
    overlap (bead teamarrv2-6qx — the user owns the buffer values and accepts
    overlap).

    Returns SQLite-native UTC strings (comparable to datetime('now')), or
    (None, None) when there is no program slot — meaning full-life membership
    (the default for dedicated/name-matched streams; behavior unchanged).
    """
    if program_start is None or program_end is None:
        return None, None
    attach = program_start - timedelta(minutes=pre_buffer_minutes)
    detach = program_end + timedelta(minutes=post_buffer_minutes)
    return (
        attach.astimezone(UTC).strftime(_SQLITE_UTC_FMT),
        detach.astimezone(UTC).strftime(_SQLITE_UTC_FMT),
    )


def is_stream_in_window(
    attach_at: str | None,
    detach_at: str | None,
    now: str | None = None,
) -> bool:
    """Whether a time-windowed stream is active right now.

    Mirrors the SQL gate in ``get_ordered_stream_ids``: a stream with no window
    (``attach_at`` IS NULL — full-life, the default) is always active; otherwise
    it is active only when ``attach_at <= now < detach_at``. All three values are
    SQLite-native UTC strings ("YYYY-MM-DD HH:MM:SS"), which are lexicographically
    comparable. ``now`` defaults to the current UTC instant.

    Used by the channel-creation path so a brand-new channel whose sole source is
    an out-of-window EPG stream is not pushed live to Dispatcharr before its
    attach window opens (bead teamarrv2-uye).
    """
    if not attach_at:
        return True
    if now is None:
        now = datetime.now(UTC).strftime(_SQLITE_UTC_FMT)
    if not detach_at:
        return now >= attach_at
    return attach_at <= now < detach_at


class ChannelLifecycleManager:
    """Manages event channel creation and deletion timing.

    Usage:
        manager = ChannelLifecycleManager(
            create_timing='same_day',
            delete_timing='after_event',
            pre_buffer_minutes=60,
            post_buffer_minutes=60,
            default_duration_hours=3.0,
            sport_durations={'basketball': 3.0, 'football': 3.5},
            include_final_events=False,
        )

        # Check if channel should be created
        decision = manager.should_create_channel(event)
        if decision.should_act:
            create_channel(event)

        # Check if channel should be deleted
        decision = manager.should_delete_channel(event)
        if decision.should_act:
            delete_channel(event)
    """

    def __init__(
        self,
        create_timing: CreateTiming = "same_day",
        delete_timing: DeleteTiming = "same_day",
        pre_buffer_minutes: int = 60,
        post_buffer_minutes: int = 60,
        default_duration_hours: float = 3.0,
        sport_durations: dict[str, float] | None = None,
        include_final_events: bool = False,
    ):
        self.create_timing = create_timing
        self.delete_timing = delete_timing
        self.pre_buffer_minutes = pre_buffer_minutes
        self.post_buffer_minutes = post_buffer_minutes
        self.default_duration_hours = default_duration_hours
        self.sport_durations = sport_durations or {}
        self.include_final_events = include_final_events

    def should_create_channel(
        self,
        event: Event,
        stream_exists: bool = False,
    ) -> LifecycleDecision:
        """Determine if a channel should be created for this event.

        Args:
            event: The event to check
            stream_exists: Whether a matching stream currently exists

        Returns:
            LifecycleDecision with should_act and reason
        """
        # Calculate create threshold
        create_threshold = self._calculate_create_threshold(event)
        now = now_user()

        # Check if we're past delete threshold (prevents create-then-delete)
        delete_threshold = self._calculate_delete_threshold(event)
        if delete_threshold and now >= delete_threshold:
            logger.debug(
                "[SKIP CREATE] event=%s: past delete threshold (%s)",
                event.id,
                delete_threshold.strftime("%m/%d %I:%M %p"),
            )
            return LifecycleDecision(
                False,
                f"Past delete threshold ({delete_threshold.strftime('%m/%d %I:%M %p')})",
                delete_threshold,
            )

        if now >= create_threshold:
            logger.debug(
                "[CREATED] event=%s: threshold reached (%s)",
                event.id,
                create_threshold.strftime("%m/%d %I:%M %p"),
            )
            return LifecycleDecision(
                True,
                f"Create threshold reached ({create_threshold.strftime('%m/%d %I:%M %p')})",
                create_threshold,
            )

        logger.debug(
            "[SKIP CREATE] event=%s: before threshold (%s)",
            event.id,
            create_threshold.strftime("%m/%d %I:%M %p"),
        )
        return LifecycleDecision(
            False,
            f"Before create threshold ({create_threshold.strftime('%m/%d %I:%M %p')})",
            create_threshold,
        )

    def should_delete_channel(
        self,
        event: Event,
        stream_exists: bool = True,
    ) -> LifecycleDecision:
        """Determine if a channel should be deleted for this event.

        Args:
            event: The event to check
            stream_exists: Whether a matching stream currently exists

        Returns:
            LifecycleDecision with should_act and reason
        """
        # Calculate delete threshold
        delete_threshold = self._calculate_delete_threshold(event)
        if not delete_threshold:
            logger.debug("[SKIP DELETE] event=%s: could not calculate delete time", event.id)
            return LifecycleDecision(False, "Could not calculate delete time")

        now = now_user()

        if now >= delete_threshold:
            logger.debug(
                "[DELETED] event=%s: threshold reached (%s)",
                event.id,
                delete_threshold.strftime("%m/%d %I:%M %p"),
            )
            return LifecycleDecision(
                True,
                f"Delete threshold reached ({delete_threshold.strftime('%m/%d %I:%M %p')})",
                delete_threshold,
            )

        logger.debug(
            "[SKIP DELETE] event=%s: before threshold (%s)",
            event.id,
            delete_threshold.strftime("%m/%d %I:%M %p"),
        )
        return LifecycleDecision(
            False,
            f"Before delete threshold ({delete_threshold.strftime('%m/%d %I:%M %p')})",
            delete_threshold,
        )

    def _calculate_create_threshold(self, event: Event) -> datetime:
        """Calculate when channel should be created.

        - same_day: Midnight (00:00) of event day
        - before_event: event_start - pre_buffer_minutes
        """
        event_start = to_user_tz(event.start_time)

        if self.create_timing == "before_event":
            return event_start - timedelta(minutes=self.pre_buffer_minutes)

        # same_day: start of event day (midnight)
        return event_start.replace(hour=0, minute=0, second=0, microsecond=0)

    def _calculate_delete_threshold(self, event: Event) -> datetime | None:
        """Calculate when channel should be deleted.

        - after_event: event_end + post_buffer_minutes (always event-anchored)
        - same_day: End of day (23:59) of event end date. If event crosses
          midnight, uses event_end + post_buffer_minutes instead to avoid
          the ~23hr stale window problem.

        Uses sport-specific duration when available.
        """
        event_start = to_user_tz(event.start_time)
        event_end = self.get_event_end_time(event)

        if self.delete_timing == "after_event":
            return event_end + timedelta(minutes=self.post_buffer_minutes)

        # same_day mode
        if crosses_midnight(event_start, event_end):
            # Midnight crossover fix: use event_end + buffer to avoid 23hr stale window
            return event_end + timedelta(minutes=self.post_buffer_minutes)

        # Normal: end of day 23:59:59
        return datetime.combine(
            event_end.date(),
            datetime.max.time(),
        ).replace(tzinfo=event_end.tzinfo)

    def calculate_delete_time(self, event: Event) -> datetime | None:
        """Calculate scheduled delete time for an event."""
        return self._calculate_delete_threshold(event)

    def get_event_end_time(self, event: Event) -> datetime:
        """Calculate estimated event end time using sport-specific duration.

        Racing events anchor `event.start_time` to the first session (e.g.
        Friday practice), which would otherwise make a multi-day race weekend
        look "over" as soon as practice ends. For events with sessions, use
        the last session's start time + its duration instead.
        """
        if event.sessions:
            from teamarr.consumers.racing_segments import _session_duration_hours

            last_session = max(event.sessions, key=lambda s: s.start_time)
            duration_hours = _session_duration_hours(
                last_session.code, self.sport_durations, event.league, event.name
            )
            return to_user_tz(last_session.start_time) + timedelta(hours=duration_hours)

        duration_hours = get_sport_duration(
            event.sport, self.sport_durations, self.default_duration_hours
        )
        return to_user_tz(event.start_time) + timedelta(hours=duration_hours)

    def event_crosses_midnight(self, event: Event) -> bool:
        """Check if event crosses midnight."""
        start = to_user_tz(event.start_time)
        end = self.get_event_end_time(event)
        return crosses_midnight(start, end)

    def categorize_event_timing(self, event: Event) -> ExcludedReason | None:
        """Categorize why a matched event would be excluded.

        This is called AFTER successful matching to determine if the event
        falls outside the lifecycle window. Returns None if the event is
        eligible for channel creation.

        Lifecycle Rules:
        1. Exclude if before create timing → BEFORE_WINDOW
        2. Exclude if after delete timing → EVENT_PAST
        3. Final events outside lifecycle window → EVENT_FINAL (always)
        4. Final events within lifecycle window → honor include_final_events

        Args:
            event: The matched event to categorize

        Returns:
            ExcludedReason if event should be excluded, None if eligible
        """
        now = now_user()

        # Calculate lifecycle window thresholds
        delete_threshold = self._calculate_delete_threshold(event)
        create_threshold = self._calculate_create_threshold(event)

        # Detailed logging for debugging lifecycle timing issues
        event_end = self.get_event_end_time(event)
        status_state = event.status.state if event.status else "N/A"
        logger.debug(
            "[LIFECYCLE] event=%s start=%s end=%s status=%s delete_threshold=%s now=%s",
            event.id,
            event.start_time.strftime("%m/%d %H:%M") if event.start_time else "N/A",
            event_end.strftime("%m/%d %H:%M") if event_end else "N/A",
            status_state,
            delete_threshold.strftime("%m/%d %H:%M") if delete_threshold else "N/A",
            now.strftime("%m/%d %H:%M"),
        )

        # Check if we're past delete threshold (event lifecycle is over)
        if delete_threshold and now >= delete_threshold:
            logger.debug("[EXCLUDED] event=%s: past lifecycle window (EVENT_PAST)", event.id)
            return ExcludedReason.EVENT_PAST

        # Check if we're before create threshold (too early)
        if create_threshold and now < create_threshold:
            logger.debug("[EXCLUDED] event=%s: before lifecycle window (BEFORE_WINDOW)", event.id)
            return ExcludedReason.BEFORE_WINDOW

        # At this point, we're within the lifecycle window (create <= now < delete)
        # Now check if event is final

        # Use unified final status check
        final = is_event_final(event)
        final_source = "status" if final else None

        # Time-based fallback: if event end + 2hr buffer is in past, treat as final
        # This catches stale cached events that still show old status
        if not final:
            event_end_with_buffer = event_end + timedelta(hours=2)
            if now > event_end_with_buffer:
                final = True
                final_source = "time_fallback"
                logger.debug(
                    "[LIFECYCLE] event=%s: time fallback triggered (end+2hr=%s < now=%s)",
                    event.id,
                    event_end_with_buffer.strftime("%m/%d %H:%M"),
                    now.strftime("%m/%d %H:%M"),
                )

        # Final events within lifecycle window → honor include_final_events setting
        if final and not self.include_final_events:
            logger.debug(
                "[EXCLUDED] event=%s: event is final via %s (EVENT_FINAL)",
                event.id,
                final_source,
            )
            return ExcludedReason.EVENT_FINAL

        # Event is within lifecycle window and passes all checks
        logger.debug(
            "[INCLUDED] event=%s: within lifecycle window, eligible (final=%s, include_final=%s)",
            event.id,
            final,
            self.include_final_events,
        )
        return None
