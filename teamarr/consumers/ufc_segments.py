"""UFC card segment handling.

Expands UFC events into segment-based channels (Early Prelims, Prelims, Main Card).
Streams are routed to correct segment channel based on detected card_segment.

Segment timing comes from ESPN bout-level data:
- PPV events: 3 segments (early_prelims, prelims, main_card)
- Fight Night: 2 segments (prelims, main_card)

Timezone disambiguation uses three-tier priority:
1. Timezone indicator extracted from stream name (e.g., "9PM ET")
2. Group-configured stream_timezone
3. User's configured timezone (fallback)
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import (
    ClassifiedStream,
    detect_card_segment,
    is_combat_sports_excluded,
)
from teamarr.consumers.matching.normalizer import TZ_ABBREVIATION_MAP
from teamarr.core.types import Event
from teamarr.utilities.tz import get_user_timezone

logger = logging.getLogger(__name__)

# Display names for segment suffixes in channel names
SEGMENT_DISPLAY_NAMES: dict[str, str] = {
    "early_prelims": "Early Prelims",
    "prelims": "Prelims",
    "main_card": "",  # Main card = no suffix (default channel)
    "combined": "",  # Combined streams go to main card channel
}

# Segment codes ordered from earliest to latest
SEGMENT_ORDER = ["early_prelims", "prelims", "main_card"]

# Maximum distance (in minutes) for time-based segment detection
# If stream time is more than this far from any segment, ignore the time
MAX_SEGMENT_TIME_DISTANCE_MINUTES = 60


def canonicalize_segment(detected: str, event: Event) -> str:
    """Validate detected segment against ESPN's segment_times.

    If ESPN has segment data, ensures the detected segment exists.
    If not, maps to the closest valid segment.

    Args:
        detected: Segment detected from stream name
        event: UFC Event with segment_times from ESPN

    Returns:
        Validated segment code that exists in ESPN's data
    """
    # If no ESPN segment data, trust the detection
    if not event.segment_times:
        return detected

    espn_segments = set(event.segment_times.keys())

    # If detected segment exists in ESPN data, use it
    if detected in espn_segments:
        return detected

    # Map to closest valid segment
    # Priority: try to find the next available segment in order
    detected_idx = SEGMENT_ORDER.index(detected) if detected in SEGMENT_ORDER else -1

    if detected_idx >= 0:
        # Try segments at same position or later first
        for segment in SEGMENT_ORDER[detected_idx:]:
            if segment in espn_segments:
                logger.info(
                    "[UFC_SEGMENTS] Mapped '%s' to '%s' (not in ESPN data: %s)",
                    detected,
                    segment,
                    sorted(espn_segments),
                )
                return segment
        # Fall back to earlier segments
        for segment in reversed(SEGMENT_ORDER[:detected_idx]):
            if segment in espn_segments:
                logger.info(
                    "[UFC_SEGMENTS] Mapped '%s' to '%s' (not in ESPN data: %s)",
                    detected,
                    segment,
                    sorted(espn_segments),
                )
                return segment

    # Last resort: use main_card if available, else first available
    if "main_card" in espn_segments:
        logger.warning("[UFC_SEGMENTS] Unknown segment '%s', defaulting to main_card", detected)
        return "main_card"

    fallback = next(iter(espn_segments))
    logger.warning("[UFC_SEGMENTS] Unknown segment '%s', defaulting to '%s'", detected, fallback)
    return fallback


def extract_time_and_tz_from_stream(stream_name: str) -> tuple[time | None, str | None]:
    """Extract time and timezone from stream name for segment disambiguation.

    Looks for common time patterns in stream names:
    - "5:30 PM ET", "5:30PM EST", "5:30pm"
    - "10pm ET", "10 pm", "10PM"
    - "22:30" (24-hour format)

    Args:
        stream_name: Raw stream name

    Returns:
        Tuple of (extracted time, IANA timezone name or None)
    """
    if not stream_name:
        return None, None

    # Build TZ abbreviation pattern from normalizer's map
    tz_abbrevs = "|".join(re.escape(k) for k in TZ_ABBREVIATION_MAP.keys())

    extracted_time = None
    extracted_tz = None

    # Pattern 1: 12-hour format with minutes - "5:30 PM ET", "5:30PM EST"
    match = re.search(
        rf"\b(\d{{1,2}}):(\d{{2}})\s*(am|pm)\s*({tz_abbrevs})?\b",
        stream_name,
        re.IGNORECASE,
    )
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        ampm = match.group(3).upper()
        tz_abbrev = match.group(4)
        if ampm == "PM" and hour < 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        extracted_time = time(hour, minute)
        if tz_abbrev:
            extracted_tz = TZ_ABBREVIATION_MAP.get(tz_abbrev.upper())
        return extracted_time, extracted_tz

    # Pattern 2: 12-hour format without minutes - "10pm ET", "10 pm EST"
    match = re.search(
        rf"\b(\d{{1,2}})\s*(am|pm)\s*({tz_abbrevs})?\b",
        stream_name,
        re.IGNORECASE,
    )
    if match:
        hour = int(match.group(1))
        ampm = match.group(2).upper()
        tz_abbrev = match.group(3)
        if ampm == "PM" and hour < 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        extracted_time = time(hour, 0)
        if tz_abbrev:
            extracted_tz = TZ_ABBREVIATION_MAP.get(tz_abbrev.upper())
        return extracted_time, extracted_tz

    # Pattern 3: 24-hour format - "22:30" (no TZ typically)
    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", stream_name)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        # Only use if it looks like a time (not like "UFC 324")
        # Times typically have hours >= 10 or are early morning (< 6)
        if hour >= 10 or hour < 6:
            extracted_time = time(hour, minute)
            return extracted_time, None

    return None, None


# Backwards compatibility alias
def extract_time_from_stream(stream_name: str) -> time | None:
    """Extract time from stream name (without timezone).

    Deprecated: Use extract_time_and_tz_from_stream for timezone support.
    """
    extracted_time, _ = extract_time_and_tz_from_stream(stream_name)
    return extracted_time


@dataclass
class SegmentInfo:
    """Information about a UFC card segment."""

    code: str  # "early_prelims", "prelims", "main_card"
    display_name: str  # "Early Prelims", "Prelims", ""
    start_time: datetime
    end_time: datetime


def is_ufc_event(event: Event | None) -> bool:
    """Check if event is a UFC/MMA event that should have segment handling."""
    if not event:
        return False
    return event.sport == "mma" and event.league == "ufc"


def get_stream_segment(stream: dict, classified: ClassifiedStream | None = None) -> str | None:
    """Get segment code for a stream.

    Args:
        stream: Stream dict with 'name' key
        classified: Optional pre-classified stream with card_segment

    Returns:
        Segment code or None if no segment detected
    """
    # Use pre-classified segment if available
    if classified and classified.card_segment:
        return classified.card_segment

    # Detect from stream name
    stream_name = stream.get("name", "")
    return detect_card_segment(stream_name)


def should_exclude_stream(stream: dict) -> bool:
    """Check if UFC stream should be excluded (weigh-in, press conference, etc.)."""
    stream_name = stream.get("name", "")
    return is_combat_sports_excluded(stream_name)


def get_segment_display_suffix(segment: str | None) -> str:
    """Get display suffix for channel name.

    Args:
        segment: Segment code ("early_prelims", "prelims", "main_card")

    Returns:
        Display suffix (e.g., " - Early Prelims") or empty string
    """
    if not segment:
        return ""

    display = SEGMENT_DISPLAY_NAMES.get(segment, "")
    if display:
        return f" - {display}"
    return ""


def determine_segment_from_time(
    stream_time: time,
    event: Event,
    extracted_tz: str | None = None,
    group_tz: str | None = None,
) -> str | None:
    """Determine segment from stream time when no keyword detected.

    Matches stream time to the closest ESPN segment start time.
    Used when a stream has a time in its name but no segment keyword.

    Args:
        stream_time: Time extracted from stream name
        event: UFC Event with segment_times from ESPN (UTC)
        extracted_tz: IANA timezone name extracted from stream (tier 1)
        group_tz: Group-configured stream_timezone (tier 2)

    Returns:
        Segment code or None if can't determine
    """

    if not event.segment_times:
        return None

    # Three-tier timezone resolution
    effective_tz: ZoneInfo | None = None
    tz_source = "user"

    if extracted_tz:
        try:
            effective_tz = ZoneInfo(extracted_tz)
            tz_source = f"stream ({extracted_tz})"
        except (KeyError, ValueError):
            pass

    if not effective_tz and group_tz:
        try:
            effective_tz = ZoneInfo(group_tz)
            tz_source = f"group ({group_tz})"
        except (KeyError, ValueError):
            pass

    if not effective_tz:
        effective_tz = get_user_timezone()
        tz_source = "user"

    # Get reference date from first available segment
    ref_dt = next(iter(event.segment_times.values()))
    event_date = ref_dt.date()

    # Convert stream time to UTC for comparison
    stream_dt_local = datetime.combine(event_date, stream_time, tzinfo=effective_tz)
    stream_dt_utc = stream_dt_local.astimezone(ZoneInfo("UTC"))

    # Find closest segment
    best_segment = None
    best_distance = float("inf")

    for segment_code, segment_dt in event.segment_times.items():
        distance = abs((stream_dt_utc - segment_dt).total_seconds())
        if distance < best_distance:
            best_distance = distance
            best_segment = segment_code

    if best_segment:
        best_distance_min = best_distance // 60
        # Reject if time is too far from any segment
        if best_distance_min > MAX_SEGMENT_TIME_DISTANCE_MINUTES:
            logger.debug(
                "[UFC_SEGMENTS] Time %s too far from any segment (dist=%d min > %d max), ignoring",
                stream_time,
                best_distance_min,
                MAX_SEGMENT_TIME_DISTANCE_MINUTES,
            )
            return None

        logger.info(
            "[UFC_SEGMENTS] Determined segment '%s' from time %s (tz=%s, dist=%d min)",
            best_segment,
            stream_time,
            tz_source,
            best_distance_min,
        )

    return best_segment


def disambiguate_prelims_by_time(
    detected_segment: str,
    stream_time: time | None,
    event: Event,
    extracted_tz: str | None = None,
    group_tz: str | None = None,
) -> str:
    """Disambiguate "prelims" segment based on stream time.

    If a stream says "prelims" but has a time in its name that's closer to
    early_prelims, reassign to early_prelims.

    Uses three-tier timezone priority for interpreting stream time:
    1. Timezone extracted from stream name (e.g., "9PM ET" → America/New_York)
    2. Group-configured stream_timezone
    3. User's configured timezone (fallback)

    Args:
        detected_segment: Segment detected from stream name ("prelims")
        stream_time: Time extracted from stream name
        event: UFC Event with segment_times from ESPN (UTC)
        extracted_tz: IANA timezone name extracted from stream (tier 1)
        group_tz: Group-configured stream_timezone (tier 2)

    Returns:
        Disambiguated segment code
    """

    # Only disambiguate "prelims" - other segments are unambiguous
    if detected_segment != "prelims":
        return detected_segment

    # Need stream time and ESPN segment data to disambiguate
    if not stream_time or not event.segment_times:
        return detected_segment

    # Need both early_prelims and prelims times for comparison
    early_prelims_dt = event.segment_times.get("early_prelims")
    prelims_dt = event.segment_times.get("prelims")

    if not early_prelims_dt or not prelims_dt:
        return detected_segment

    # Three-tier timezone resolution for stream time:
    # 1. Extracted from stream name (highest priority)
    # 2. Group-configured stream_timezone
    # 3. User timezone (fallback)
    effective_tz: ZoneInfo | None = None
    tz_source = "user"

    if extracted_tz:
        try:
            effective_tz = ZoneInfo(extracted_tz)
            tz_source = f"stream ({extracted_tz})"
        except (KeyError, ValueError):
            pass

    if not effective_tz and group_tz:
        try:
            effective_tz = ZoneInfo(group_tz)
            tz_source = f"group ({group_tz})"
        except (KeyError, ValueError):
            pass

    if not effective_tz:
        effective_tz = get_user_timezone()
        tz_source = "user"

    # Convert stream time to datetime in effective timezone, then to UTC for comparison
    # ESPN segment times are in UTC
    event_date = early_prelims_dt.date()
    stream_dt_local = datetime.combine(event_date, stream_time, tzinfo=effective_tz)
    stream_dt_utc = stream_dt_local.astimezone(ZoneInfo("UTC"))

    # Calculate time differences in seconds
    def datetime_distance(dt1: datetime, dt2: datetime) -> int:
        """Calculate absolute distance in seconds, handling day boundaries."""
        diff = abs((dt1 - dt2).total_seconds())
        return int(diff)

    dist_to_early = datetime_distance(stream_dt_utc, early_prelims_dt)
    dist_to_prelims = datetime_distance(stream_dt_utc, prelims_dt)

    # Simple "closest to" logic - assign to whichever segment is closer
    if dist_to_early < dist_to_prelims:
        logger.info(
            "[UFC_SEGMENTS] Disambiguated 'prelims' → 'early_prelims' "
            "(stream=%s tz=%s, early=%s, prelims=%s, dist=%d/%d min)",
            stream_time,
            tz_source,
            early_prelims_dt.strftime("%H:%M UTC"),
            prelims_dt.strftime("%H:%M UTC"),
            dist_to_early // 60,
            dist_to_prelims // 60,
        )
        return "early_prelims"

    return detected_segment


def get_segment_times(
    event: Event,
    segment: str,
    sport_durations: dict[str, float] | None = None,
) -> tuple[datetime, datetime]:
    """Get exact start/end times for a segment from ESPN bout-level data.

    Uses event.segment_times populated from ESPN API. Falls back to estimation
    only if ESPN data is not available (should be rare).

    Args:
        event: UFC Event with segment_times from ESPN
        segment: Segment code ("early_prelims", "prelims", "main_card")
        sport_durations: Optional duration settings (for fallback only)

    Returns:
        Tuple of (start_time, end_time)
    """
    mma_duration = (sport_durations or {}).get("mma", 5.0)

    # Use exact ESPN segment times if available
    if event.segment_times and segment in event.segment_times:
        start_time = event.segment_times[segment]

        # End time = next segment's start, or estimated duration for last segment
        segment_list = [s for s in SEGMENT_ORDER if s in event.segment_times]
        try:
            seg_idx = segment_list.index(segment)
            if seg_idx < len(segment_list) - 1:
                # Not the last segment - end at next segment's start
                next_segment = segment_list[seg_idx + 1]
                end_time = event.segment_times[next_segment]
            else:
                # Last segment - use estimated duration
                # Main card typically runs 2-3 hours
                end_time = start_time + timedelta(hours=mma_duration / 2)
        except ValueError:
            end_time = start_time + timedelta(hours=mma_duration / 3)

        return start_time, end_time

    # Fallback: estimate if no ESPN data (should be rare)
    logger.warning(
        "[UFC_SEGMENTS] No ESPN segment_times for event %s segment %s, using estimates",
        event.id,
        segment,
    )
    return _estimate_segment_times_fallback(event, segment, mma_duration)


def _estimate_segment_times_fallback(
    event: Event,
    segment: str,
    mma_duration: float,
) -> tuple[datetime, datetime]:
    """Fallback estimation when ESPN data is not available."""
    if event.main_card_start:
        if segment == "early_prelims":
            prelims_start = event.main_card_start - timedelta(hours=1.5)
            return event.start_time, prelims_start
        elif segment == "prelims":
            prelims_start = event.main_card_start - timedelta(hours=1.5)
            if event.start_time > prelims_start:
                prelims_start = event.start_time
            return prelims_start, event.main_card_start
        else:
            main_duration = timedelta(hours=mma_duration / 2)
            return event.main_card_start, event.main_card_start + main_duration

    # No main_card_start - crude estimation
    segment_duration = timedelta(hours=mma_duration / 3)
    if segment == "early_prelims":
        return event.start_time, event.start_time + segment_duration
    elif segment == "prelims":
        start = event.start_time + segment_duration
        return start, start + segment_duration
    else:
        start = event.start_time + 2 * segment_duration
        return start, start + segment_duration


def expand_ufc_segments(
    matched_streams: list[dict],
    sport_durations: dict[str, float] | None = None,
    stream_timezone: str | None = None,
) -> list[dict]:
    """Expand UFC matched streams into segment-based channels.

    Groups UFC streams by detected segment and creates separate channel
    entries for each segment. Non-UFC streams pass through unchanged.

    Args:
        matched_streams: List of {'stream': ..., 'event': ...} dicts
        sport_durations: Optional sport duration settings
        stream_timezone: Group-configured timezone for stream time interpretation

    Returns:
        Expanded list with UFC streams grouped by segment
    """
    result = []

    # Group UFC streams by event ID and segment
    # {event_id: {segment: [streams]}}
    ufc_by_segment: dict[str, dict[str, list[dict]]] = {}

    for match in matched_streams:
        event = match.get("event")
        stream = match.get("stream", {})

        # Non-UFC events pass through — normalize card_segment → segment
        if not is_ufc_event(event):
            card_seg = match.get("card_segment")
            if card_seg and "segment" not in match:
                match["segment"] = card_seg
                match["segment_display"] = SEGMENT_DISPLAY_NAMES.get(card_seg, "")
            result.append(match)
            continue

        # is_ufc_event returned True, so event is a non-None UFC Event.
        assert event is not None

        # Check for excluded streams (weigh-ins, etc.)
        if should_exclude_stream(stream):
            logger.debug(
                "[UFC_SEGMENTS] Excluding stream '%s' (non-event content)",
                stream.get("name", "")[:50],
            )
            continue

        # Use pre-detected segment from classifier, or detect from stream name
        segment = match.get("card_segment") or get_stream_segment(stream)
        stream_name = stream.get("name", "")

        # Combined streams go to main_card
        if segment == "combined":
            segment = "main_card"

        # If no segment keyword detected, try to determine from time
        if not segment:
            stream_time, extracted_tz = extract_time_and_tz_from_stream(stream_name)
            if stream_time:
                segment = determine_segment_from_time(
                    stream_time,
                    event,
                    extracted_tz=extracted_tz,
                    group_tz=stream_timezone,
                )

        # Default to main_card if still no segment
        if not segment:
            segment = "main_card"

        # Disambiguate "prelims" using time if available
        # Streams labeled "prelims" might actually be early prelims based on time
        # Uses three-tier TZ: extracted from stream > group setting > user TZ
        if segment == "prelims":
            stream_time, extracted_tz = extract_time_and_tz_from_stream(stream_name)
            if stream_time:
                segment = disambiguate_prelims_by_time(
                    segment,
                    stream_time,
                    event,
                    extracted_tz=extracted_tz,
                    group_tz=stream_timezone,
                )

        # Validate against ESPN's segment data - ensures segment exists
        segment = canonicalize_segment(segment, event)

        event_id = event.id
        if event_id not in ufc_by_segment:
            ufc_by_segment[event_id] = {}
        if segment not in ufc_by_segment[event_id]:
            ufc_by_segment[event_id][segment] = []

        ufc_by_segment[event_id][segment].append(match)

    # Create segment entries for each UFC event
    for event_id, segments in ufc_by_segment.items():
        # Get the event from any stream (they all have the same event)
        first_match = next(iter(next(iter(segments.values()))))
        event = first_match.get("event")
        # Every match grouped into ufc_by_segment carries its UFC Event.
        assert event is not None

        # Create entry for each discovered segment
        for segment in SEGMENT_ORDER:
            if segment not in segments:
                continue

            streams_for_segment = segments[segment]
            if not streams_for_segment:
                continue

            # Get exact segment timing from ESPN data
            start_time, end_time = get_segment_times(event, segment, sport_durations)

            # Create segment entry with metadata
            for match in streams_for_segment:
                segment_match = {
                    "stream": match.get("stream"),
                    "event": event,
                    "segment": segment,
                    "segment_display": SEGMENT_DISPLAY_NAMES.get(segment, ""),
                    "segment_start": start_time,
                    "segment_end": end_time,
                }
                result.append(segment_match)

            logger.debug(
                "[UFC_SEGMENTS] Event %s segment '%s': %d streams, %s - %s",
                event_id,
                segment,
                len(streams_for_segment),
                start_time.strftime("%H:%M"),
                end_time.strftime("%H:%M"),
            )

    # Log summary
    ufc_count = sum(len(streams) for segs in ufc_by_segment.values() for streams in segs.values())
    segment_count = sum(len(segs) for segs in ufc_by_segment.values())
    if ufc_count > 0:
        logger.info(
            "[UFC_SEGMENTS] Expanded %d UFC streams into %d segment channels",
            ufc_count,
            segment_count,
        )

    return result
