"""Event card matcher for combat sports.

Matches streams for UFC, Boxing, and other event-card sports.
These don't have team-vs-team format but instead match by:
- Event number (UFC 315)
- Event keywords (Main Card, Prelims)
- Fighter names (fallback)
"""

import logging
import re
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

# Minimum fuzzy match score for fighter name matching (0-100)
# Same threshold used for team matching in team_matcher.py
FIGHTER_MATCH_THRESHOLD = 75


@dataclass
class EventMatchContext:
    """Context for event card matching."""

    stream_name: str
    stream_id: int
    group_id: int
    target_date: date
    generation: int
    user_tz: ZoneInfo
    classified: ClassifiedStream


class EventCardMatcher:
    """Matches event card streams (UFC, Boxing) to provider events.

    Event cards are identified by:
    - Event number: "UFC 315", "PFL 5"
    - Keywords: "Main Card", "Prelims", "Early Prelims"
    - Event name patterns

    Unlike team sports, combat sports typically have one event per date,
    so matching is simpler - we just need to confirm it's the right event.
    """

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
        """Match an event card stream to a provider event.

        Args:
            classified: Pre-classified stream (should be EVENT_CARD)
            league: League code (ufc, boxing)
            target_date: Date to match events for
            group_id: Event group ID (for caching)
            stream_id: Stream ID (for caching)
            generation: Cache generation counter
            user_tz: User timezone for date validation

        Returns:
            MatchOutcome with result
        """
        if classified.category != StreamCategory.EVENT_CARD:
            return MatchOutcome.filtered(
                FilteredReason.NOT_EVENT,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
                detail="Not an event card stream",
            )

        ctx = EventMatchContext(
            stream_name=classified.normalized.original,
            stream_id=stream_id,
            group_id=group_id,
            target_date=target_date,
            generation=generation,
            user_tz=user_tz,
            classified=classified,
        )

        # Check cache first
        cache_result = self._check_cache(ctx)
        if cache_result:
            logger.debug(
                "[CACHE HIT] event_card stream=%s matched=%s",
                ctx.stream_name[:50],
                cache_result.event.name if cache_result.event else "None",
            )
            return cache_result

        # Get events for this league (TSDB leagues use cache-only)
        is_tsdb = self._service.get_provider_name(league) == "tsdb"
        events = self._service.get_events(league, target_date, cache_only=is_tsdb)
        if not events:
            return MatchOutcome.failed(
                FailedReason.NO_EVENT_CARD_MATCH,
                stream_name=ctx.stream_name,
                stream_id=stream_id,
                detail=f"No {league} events for {target_date}",
            )

        # Filter to events on target date
        date_events = [e for e in events if e.start_time.astimezone(user_tz).date() == target_date]

        if not date_events:
            return MatchOutcome.failed(
                FailedReason.NO_EVENT_CARD_MATCH,
                stream_name=ctx.stream_name,
                stream_id=stream_id,
                detail=f"No {league} events on {target_date}",
            )

        # Try to match
        result = self._match_to_event_card(ctx, date_events, league)

        # Cache successful matches
        if result.is_matched and result.event:
            self._cache_result(ctx, result)

        return result

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _check_cache(self, ctx: EventMatchContext) -> MatchOutcome | None:
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

        # Validate date
        event_date = event.start_time.astimezone(ctx.user_tz).date()
        if event_date != ctx.target_date:
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

    def _match_to_event_card(
        self,
        ctx: EventMatchContext,
        events: list[Event],
        league: str,
    ) -> MatchOutcome:
        """Match stream to an event card."""
        event_hint = ctx.classified.event_hint

        # Strategy 1: Match by event number (UFC 315)
        # Uses word-boundary matching to avoid "UFC 32" matching "UFC 325"
        event_num = None
        if event_hint:
            event_num = self._extract_event_number(event_hint)
            if event_num:
                # Build regex pattern with word boundaries for precise matching
                # e.g., "UFC 325" should match "UFC 325: Main Event" but not "UFC 3250"
                pattern = re.compile(
                    r"\b" + re.escape(event_num) + r"\b",
                    re.IGNORECASE,
                )
                for event in events:
                    if pattern.search(event.name):
                        logger.debug(
                            "[MATCHED] event_card stream=%s -> %s (method=event_number)",
                            ctx.stream_name[:40],
                            event.name,
                        )
                        return MatchOutcome.matched(
                            MatchMethod.KEYWORD,
                            event,
                            detected_league=league,
                            confidence=1.0,
                            stream_name=ctx.stream_name,
                            stream_id=ctx.stream_id,
                        )
                # Event number in stream but no matching event on this date
                logger.debug(
                    "[FAILED] event_card stream=%s: event number '%s' not found in %d events",
                    ctx.stream_name[:40],
                    event_num,
                    len(events),
                )

        # Strategy 2: Fighter name matching (fallback)
        # Only attempt if fighters were extracted during classification via separator detection
        # This prevents false positives on streams without explicit fighter names
        extracted_fighter1 = ctx.classified.team1
        extracted_fighter2 = ctx.classified.team2

        if extracted_fighter1 or extracted_fighter2:
            # Use fuzzy matching (same approach as team_vs_team)
            for event in events:
                home_name = event.home_team.name if event.home_team else ""
                away_name = event.away_team.name if event.away_team else ""

                if not home_name and not away_name:
                    continue

                # Normalize names for comparison
                home_norm = normalize_text(home_name)
                away_norm = normalize_text(away_name)

                best_score = 0
                matched_fighter = None

                # Score extracted fighters against event fighters
                for fighter in [extracted_fighter1, extracted_fighter2]:
                    if not fighter:
                        continue
                    fighter_norm = normalize_text(fighter)

                    # Try against both event fighters
                    for _event_fighter, event_fighter_norm in [
                        (home_name, home_norm),
                        (away_name, away_norm),
                    ]:
                        if not event_fighter_norm:
                            continue
                        score = fuzz.token_set_ratio(fighter_norm, event_fighter_norm)
                        if score > best_score:
                            best_score = score
                            matched_fighter = fighter

                if best_score >= FIGHTER_MATCH_THRESHOLD:
                    confidence = best_score / 100.0
                    logger.debug(
                        "[MATCHED] event_card stream=%s -> %s (method=fuzzy_fighter, "
                        "'%s' score=%d)",
                        ctx.stream_name[:40],
                        event.name,
                        matched_fighter,
                        best_score,
                    )
                    return MatchOutcome.matched(
                        MatchMethod.FUZZY,
                        event,
                        detected_league=league,
                        confidence=confidence,
                        stream_name=ctx.stream_name,
                        stream_id=ctx.stream_id,
                    )

        # Strategy 3: Fuzzy event name matching
        # For named events without a standard number (e.g. "UFC at the White House").
        if not event_num:
            stream_norm = normalize_text(ctx.stream_name)
            # Strip generic/noise words to ensure the stream has a distinct name.
            stream_norm_clean = re.sub(
                r'\b(ufc|mma|boxing|prelims|main card|early prelims'
                r'|live|event|ppv|pm|am|et|pt|ct|mt)\b',
                '',
                stream_norm
            ).strip()

            if stream_norm_clean and len(stream_norm_clean) > 3:
                best_score = 0
                best_event = None

                for event in events:
                    event_norm = normalize_text(event.name)
                    # Match on the DISTINCTIVE (noise-stripped) stream name with
                    # token_set_ratio. Matching the raw stream with
                    # partial_token_set_ratio scored 100 for any event sharing the
                    # league token ("ufc") — so it picked an arbitrary event. Using
                    # stream_norm_clean + token_set_ratio requires real name overlap.
                    score = fuzz.token_set_ratio(stream_norm_clean, event_norm)
                    if score > best_score:
                        best_score = score
                        best_event = event

                if best_score >= FIGHTER_MATCH_THRESHOLD and best_event:
                    confidence = best_score / 100.0
                    logger.debug(
                        "[MATCHED] event_card stream=%s -> %s (method=fuzzy_event_name, score=%d)",
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

        # No match found
        logger.debug(
            "[FAILED] event_card stream=%s: no match in %d events for %s",
            ctx.stream_name[:40],
            len(events),
            league,
        )
        return MatchOutcome.failed(
            FailedReason.NO_EVENT_CARD_MATCH,
            stream_name=ctx.stream_name,
            stream_id=ctx.stream_id,
            detail=f"Could not match to any {league} event",
        )

    def _extract_event_number(self, hint: str) -> str | None:
        """Extract event identifier from hint.

        Args:
            hint: Event hint like "UFC 315" or "PFL 5"

        Returns:
            Normalized event identifier or None
        """
        if not hint:
            return None

        # UFC 315, UFC FN 45
        match = re.search(
            r"(ufc\s*(?:fn|fight\s*night)?\s*\d+)",
            hint,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).upper().replace("  ", " ")

        # PFL 5, Bellator 300
        match = re.search(
            r"((?:pfl|bellator|one\s*fc)\s*\d+)",
            hint,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).upper()

        return None

    def _cache_result(self, ctx: EventMatchContext, result: MatchOutcome) -> None:
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
