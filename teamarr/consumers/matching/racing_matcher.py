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
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz

from teamarr.consumers.matching.classifier import (
    ClassifiedStream,
    StreamCategory,
    has_racing_text_evidence,
)
from teamarr.consumers.matching.result import (
    FailedReason,
    FilteredReason,
    MatchMethod,
    MatchOutcome,
)
from teamarr.consumers.racing_segments import (
    RACING_ANCHOR_TOLERANCE_SECONDS,
    get_session_times,
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

# EPG path only: how far a program's broadcast instant may sit from a
# session's [start, end] window and still count as covering that session.
# Date coverage alone is not enough for EPG titles: a program whose text
# merely NAMES racing (e.g. the animated movie "Grand Prix of Europe" airing
# on a kids' channel, or a filler/stub "Coming up:" blurb) can otherwise bind
# to "the one race covering this date" regardless of what hour it airs — a
# program landing hours away from every real session is not a broadcast of
# that event.
# (Value lives in racing_segments, shared with EPG session scoping; re-exported
# here for the anchor-gate usage below and existing importers.)

# Plausible season years in stream/programme text (1950 — F1's first season —
# through 2049). Deliberately NOT \d{4}: resolutions ("2160p"), bitrates and
# channel numbers must not read as years.
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


def _years_in_text(text: str) -> set[int]:
    """All plausible season years mentioned in ``text``."""
    return {int(m) for m in _YEAR_RE.findall(text)}


def _augment_compounds(normalized: str) -> str:
    """Append fused adjacent-token bigrams to a normalized string.

    Guides and providers disagree on compound-word spelling ("Faith Fest
    250" vs "FaithFest 250"), leaving token-based scoring with only the
    tokens both spellings share. Adding each adjacent pair fused as an
    extra token lets either spelling grow the other's compound form, so
    the pair scores as related without loosening the threshold.
    """
    tokens = normalized.split()
    return " ".join(tokens + [a + b for a, b in zip(tokens, tokens[1:], strict=False)])


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
    anchor_dt: "datetime | None" = None
    sport_durations: "dict[str, float] | None" = None


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
        anchor_dt: "datetime | None" = None,
        sport_durations: "dict[str, float] | None" = None,
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
        # EPG programmes rarely carry a date in their text, but always carry
        # their broadcast instant — fall back to the programme's own date so
        # a Friday session can bind as soon as the guide publishes it, rather
        # than waiting for the run date to reach the race weekend. The
        # anchor_dt gate below still enforces real session proximity.
        match_date = classified.normalized.extracted_date
        if match_date is None:
            match_date = anchor_dt.astimezone(user_tz).date() if anchor_dt else target_date

        ctx = RacingMatchContext(
            stream_name=classified.normalized.original,
            stream_id=stream_id,
            group_id=group_id,
            target_date=match_date,
            generation=generation,
            user_tz=user_tz,
            classified=classified,
            anchor_dt=anchor_dt,
            sport_durations=sport_durations,
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

        # Season-year gate: text naming a year that isn't a candidate event's
        # year is archival, not coverage. FAST channels air classic races
        # around the current weekend ("2008 Belgian Grand Prix" started 33
        # minutes into 2026 qualifying — inside anchor tolerance, carrying
        # racing text evidence, and a near-perfect fuzzy match). A text with
        # no year (the normal case) is unaffected; any mentioned year
        # matching the event keeps it ("... Indycar 2026 (2026-07-19 ...)").
        years = _years_in_text(ctx.stream_name)
        if years:
            window_events = [e for e in window_events if e.start_time.year in years]
            if not window_events:
                return MatchOutcome.failed(
                    FailedReason.NO_RACING_MATCH,
                    stream_name=ctx.stream_name,
                    stream_id=stream_id,
                    detail=(
                        f"Text names year(s) {sorted(years)} matching no "
                        f"{league} event covering {ctx.target_date} (archival?)"
                    ),
                )

        # EPG path only: further gate to events with a session actually airing
        # near the program's broadcast instant, not just sharing a date.
        if anchor_dt is not None:
            window_events = [
                e for e in window_events
                if self._covers_instant(e, anchor_dt, sport_durations)
            ]
            if not window_events:
                return MatchOutcome.failed(
                    FailedReason.NO_RACING_MATCH,
                    stream_name=ctx.stream_name,
                    stream_id=stream_id,
                    detail=f"No {league} session airing near {anchor_dt.isoformat()}",
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

    def _covers_instant(
        self,
        event: Event,
        anchor_dt: "datetime",
        sport_durations: "dict[str, float] | None",
    ) -> bool:
        """True if some session of ``event`` is actually airing near ``anchor_dt``.

        Unlike `_covers_date` (calendar-date granularity, used for the plain
        stream-name path where the whole weekend is a legitimate match target),
        this checks each session's real [start, end] window (padded by
        RACING_ANCHOR_TOLERANCE_SECONDS) — the EPG path needs this tighter
        bound because a program merely NAMING racing (a movie with "Grand
        Prix" in the title, a filler/stub blurb) would otherwise bind to any
        session of the week's only covering event regardless of how many
        hours away it actually airs.
        """
        if not event.sessions:
            return abs((event.start_time - anchor_dt).total_seconds()) <= (
                RACING_ANCHOR_TOLERANCE_SECONDS
            )

        tolerance = timedelta(seconds=RACING_ANCHOR_TOLERANCE_SECONDS)
        for session in event.sessions:
            start, end = get_session_times(event, session.code, sport_durations)
            if start - tolerance <= anchor_dt <= end + tolerance:
                return True
        return False

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

        # Season-year gate, same as match(): a cached archival bind ("2008
        # Belgian Grand Prix" cached before the gate existed) must not keep
        # resurrecting through the cache.
        years = _years_in_text(ctx.stream_name)
        if years and event.start_time.year not in years:
            self._cache.delete(ctx.group_id, ctx.stream_id, ctx.stream_name)
            return None

        # EPG path only: cached match must still have a session airing near
        # this program's instant (see match()'s anchor_dt gate above).
        if ctx.anchor_dt is not None and not self._covers_instant(
            event, ctx.anchor_dt, ctx.sport_durations
        ):
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
        # Fuzzy match against event name / short name / circuit name.
        # venue.country is tracked separately: token_set_ratio scores a bare
        # country subset at 100, so as a peer candidate it would let a
        # low-specificity country hit outrank a real name match on another
        # event. It only backs up the single-event sanity check and a
        # unique-country fallback below (country-named streams, e.g.
        # "NASCAR Cup Series at Mexico City").
        stream_norm = normalize_text(ctx.stream_name)
        # Compound-spelling tolerance: score the plain normalized forms AND
        # bigram-augmented forms, taking the best. The augmented pass only
        # ever helps when adjacent tokens fuse into the other side's
        # compound spelling ("Faith Fest" -> "faithfest"); unrelated pairs
        # score LOWER augmented (more non-shared tokens), and max() keeps
        # their plain score, so no existing accept/reject flips.
        stream_aug = _augment_compounds(stream_norm)
        best_score = 0
        best_event: Event | None = None
        country_scores: dict[str, float] = {}

        for event in events:
            for candidate in (event.name, event.short_name, event.circuit_name):
                if not candidate:
                    continue
                cand_norm = normalize_text(candidate)
                score = max(
                    fuzz.token_set_ratio(stream_norm, cand_norm),
                    fuzz.token_set_ratio(stream_aug, _augment_compounds(cand_norm)),
                )
                if score > best_score:
                    best_score = score
                    best_event = event
            country = event.venue.country if event.venue else None
            if country:
                country_scores[event.id] = fuzz.token_set_ratio(
                    stream_norm, normalize_text(country)
                )

        # Strategy 1: Single event covering the date - the common case
        # (one Grand Prix/race weekend per league per week). Still requires a
        # minimal fuzzy similarity sanity check, otherwise streams with no
        # relation to racing at all (e.g. a cycling stage or talk show that
        # got misclassified as a racing event) match to "the only race
        # happening this weekend" purely by elimination. The country score
        # counts here: with one covering event there's no ambiguity for it
        # to create.
        #
        # The score alone isn't a reliable bar: generic venue words
        # ("Speedway", "International Circuit", ...) can clear it on a
        # single shared token with zero real connection to the event, so a
        # stream also needs actual textual evidence it's the right racing
        # series before Strategy 1 is allowed to fire.
        if len(events) == 1 and best_score < SINGLE_EVENT_SANITY_THRESHOLD:
            best_score = max(best_score, country_scores.get(events[0].id, 0))
        if (
            len(events) == 1
            and best_score >= SINGLE_EVENT_SANITY_THRESHOLD
            and has_racing_text_evidence(ctx.stream_name)
        ):
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

        # Strategy 3: unique-country fallback. Only when exactly one covering
        # event's venue country clears the threshold — a country shared by two
        # events this window (e.g. a doubleheader weekend) stays ambiguous and
        # must not match.
        country_hits = [
            (eid, score) for eid, score in country_scores.items()
            if score >= RACING_MATCH_THRESHOLD
        ]
        if len(country_hits) == 1:
            event = next(e for e in events if e.id == country_hits[0][0])
            logger.debug(
                "[MATCHED] racing stream=%s -> %s (method=fuzzy, venue country, score=%d)",
                ctx.stream_name[:40],
                event.name,
                country_hits[0][1],
            )
            return MatchOutcome.matched(
                MatchMethod.FUZZY,
                event,
                detected_league=league,
                confidence=country_hits[0][1] / 100.0,
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
