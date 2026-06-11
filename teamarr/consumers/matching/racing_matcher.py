"""Racing event matcher for motorsports leagues (F1, NASCAR, IndyCar, MotoGP, ...).

Matches streams for racing leagues. These don't have team-vs-team format and,
unlike combat sports, have no reliable event-number/keyword conventions either
- a stream is typically just "F1: Monaco Grand Prix" or "NASCAR Cup - Race".

Matching strategy:
- A race weekend spans multiple days (practice/qualifying/race), so a stream
  matches any racing event whose session window covers the target date - not
  just the event's nominal start date.
- If exactly one racing event covers the date, match it directly (the common
  case - one Grand Prix/race weekend per league per week).
- Otherwise, fuzzy-match the stream text against the event's name, short
  name, and circuit name.
"""

import logging
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz

from teamarr.consumers.matching.classifier import ClassifiedStream, StreamCategory
from teamarr.consumers.matching.result import (
    FailedReason,
    FilteredReason,
    MatchMethod,
    MatchOutcome,
)
from teamarr.consumers.stream_match_cache import StreamMatchCache, event_to_cache_data
from teamarr.core.types import Event
from teamarr.services.sports_data import SportsDataService
from teamarr.utilities.fuzzy_match import normalize_text

logger = logging.getLogger(__name__)

# Minimum fuzzy match score for racing event name matching (0-100)
RACING_MATCH_THRESHOLD = 70

# Minimum fuzzy match score required even in the "single event covering the
# date" case, to reject streams with no real connection to racing at all
# (e.g. cycling/other-sport streams misclassified as racing events).
SINGLE_EVENT_SANITY_THRESHOLD = 50


@dataclass
class RacingMatchContext:
    """Context for racing event matching."""

    stream_name: str
    stream_id: int
    group_id: int
    target_date: date
    generation: int
    user_tz: ZoneInfo
    classified: ClassifiedStream


class RacingMatcher:
    """Matches racing streams (F1, NASCAR, IndyCar, MotoGP, ...) to provider events."""

    def __init__(
        self,
        service: SportsDataService,
        cache: StreamMatchCache,
    ):
        """Initialize matcher.

        Args:
            service: Sports data service for event lookups
            cache: Stream match cache
        """
        self._service = service
        self._cache = cache

    def match(
        self,
        classified: ClassifiedStream,
        league: str,
        target_date: date,
        group_id: int,
        stream_id: int,
        generation: int,
        user_tz: ZoneInfo,
    ) -> MatchOutcome:
        """Match a racing stream to a provider event.

        Args:
            classified: Pre-classified stream (should be RACING_EVENT)
            league: League code (f1, nascar-cup, ...)
            target_date: Date to match events for
            group_id: Event group ID (for caching)
            stream_id: Stream ID (for caching)
            generation: Cache generation counter
            user_tz: User timezone for date validation

        Returns:
            MatchOutcome with result
        """
        if classified.category != StreamCategory.RACING_EVENT:
            return MatchOutcome.filtered(
                FilteredReason.NOT_EVENT,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
                detail="Not a racing stream",
            )

        # Race-weekend streams carry the session's own date (e.g. "Sun 14 Jun"
        # for the race), which may differ from today's batch target_date.
        # Use that date to find the covering event/session when present.
        match_date = classified.normalized.extracted_date or target_date

        ctx = RacingMatchContext(
            stream_name=classified.normalized.original,
            stream_id=stream_id,
            group_id=group_id,
            target_date=match_date,
            generation=generation,
            user_tz=user_tz,
            classified=classified,
        )

        # Check cache first
        cache_result = self._check_cache(ctx)
        if cache_result:
            logger.debug(
                "[CACHE HIT] racing stream=%s matched=%s",
                ctx.stream_name[:50],
                cache_result.event.name if cache_result.event else "None",
            )
            return cache_result

        # Get events for this league (TSDB leagues use cache-only)
        is_tsdb = self._service.get_provider_name(league) == "tsdb"
        events = self._service.get_events(league, ctx.target_date, cache_only=is_tsdb)
        if not events:
            return MatchOutcome.failed(
                FailedReason.NO_RACING_MATCH,
                stream_name=ctx.stream_name,
                stream_id=stream_id,
                detail=f"No {league} events for {ctx.target_date}",
            )

        # Filter to events whose race-weekend window covers the target date
        window_events = [e for e in events if self._covers_date(e, ctx.target_date, user_tz)]

        if not window_events:
            return MatchOutcome.failed(
                FailedReason.NO_RACING_MATCH,
                stream_name=ctx.stream_name,
                stream_id=stream_id,
                detail=f"No {league} events covering {ctx.target_date}",
            )

        result = self._match_to_event(ctx, window_events, league)

        # Cache successful matches
        if result.is_matched and result.event:
            self._cache_result(ctx, result)

        return result

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _covers_date(self, event: Event, target_date: date, user_tz: ZoneInfo) -> bool:
        """Check if a race weekend's session window covers the target date."""
        if not event.sessions:
            return event.start_time.astimezone(user_tz).date() == target_date

        session_dates = {s.start_time.astimezone(user_tz).date() for s in event.sessions}
        session_dates.add(event.start_time.astimezone(user_tz).date())
        return target_date in session_dates

    def _check_cache(self, ctx: RacingMatchContext) -> MatchOutcome | None:
        """Check cache for existing match."""
        entry = self._cache.get(ctx.group_id, ctx.stream_id, ctx.stream_name)
        if not entry:
            return None

        # Touch to keep fresh
        self._cache.touch(ctx.group_id, ctx.stream_id, ctx.stream_name, ctx.generation)

        # Reconstruct event
        from teamarr.consumers.matching.team_matcher import TeamMatcher

        # Reuse reconstruction logic (bit of a hack but avoids duplication)
        matcher = TeamMatcher(self._service, self._cache)
        event = matcher._reconstruct_event(entry.cached_data)

        if not event:
            self._cache.delete(ctx.group_id, ctx.stream_id, ctx.stream_name)
            return None

        # Validate date - cached event's window must still cover target date
        if not self._covers_date(event, ctx.target_date, ctx.user_tz):
            return None

        return MatchOutcome.matched(
            MatchMethod.CACHE,
            event,
            detected_league=entry.league,
            confidence=1.0,
            stream_name=ctx.stream_name,
            stream_id=ctx.stream_id,
            origin_match_method=entry.match_method,  # Original method
        )

    def _match_to_event(
        self,
        ctx: RacingMatchContext,
        events: list[Event],
        league: str,
    ) -> MatchOutcome:
        """Match stream to a racing event."""
        # Fuzzy match against event name / short name / circuit name
        stream_norm = normalize_text(ctx.stream_name)
        best_score = 0
        best_event: Event | None = None

        for event in events:
            for candidate in (event.name, event.short_name, event.circuit_name):
                if not candidate:
                    continue
                score = fuzz.token_set_ratio(stream_norm, normalize_text(candidate))
                if score > best_score:
                    best_score = score
                    best_event = event

        # Strategy 1: Single event covering the date - the common case
        # (one Grand Prix/race weekend per league per week). Still requires a
        # minimal fuzzy similarity sanity check, otherwise streams with no
        # relation to racing at all (e.g. a cycling stage or talk show that
        # got misclassified as a racing event) match to "the only race
        # happening this weekend" purely by elimination.
        if len(events) == 1 and best_score >= SINGLE_EVENT_SANITY_THRESHOLD:
            event = events[0]
            logger.debug(
                "[MATCHED] racing stream=%s -> %s (method=direct, single event, score=%d)",
                ctx.stream_name[:40],
                event.name,
                best_score,
            )
            return MatchOutcome.matched(
                MatchMethod.DIRECT,
                event,
                detected_league=league,
                confidence=1.0,
                stream_name=ctx.stream_name,
                stream_id=ctx.stream_id,
            )

        # Strategy 2: Fuzzy match against multiple candidate events
        if best_event and best_score >= RACING_MATCH_THRESHOLD:
            confidence = best_score / 100.0
            logger.debug(
                "[MATCHED] racing stream=%s -> %s (method=fuzzy, score=%d)",
                ctx.stream_name[:40],
                best_event.name,
                best_score,
            )
            return MatchOutcome.matched(
                MatchMethod.FUZZY,
                best_event,
                detected_league=league,
                confidence=confidence,
                stream_name=ctx.stream_name,
                stream_id=ctx.stream_id,
            )

        logger.debug(
            "[FAILED] racing stream=%s: no match in %d events for %s",
            ctx.stream_name[:40],
            len(events),
            league,
        )
        return MatchOutcome.failed(
            FailedReason.NO_RACING_MATCH,
            stream_name=ctx.stream_name,
            stream_id=ctx.stream_id,
            detail=f"Could not match to any {league} event",
        )

    def _cache_result(self, ctx: RacingMatchContext, result: MatchOutcome) -> None:
        """Cache a successful match."""
        if not result.event:
            return

        cached_data = event_to_cache_data(result.event)

        # Store the original match method so we can show "Cache (origin: fuzzy)" etc.
        match_method_value = result.match_method.value if result.match_method else None

        self._cache.set(
            group_id=ctx.group_id,
            stream_id=ctx.stream_id,
            stream_name=ctx.stream_name,
            event_id=result.event.id,
            league=result.detected_league or result.event.league,
            cached_data=cached_data,
            generation=ctx.generation,
            match_method=match_method_value,
        )
