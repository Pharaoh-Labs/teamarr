"""Team vs Team stream matcher.

Matches streams that contain team matchups (vs/@/at) to provider events.
Supports two modes:
- Single-league: Search only the authoritative league (team EPG)
- Multi-league: Detect league hint, search enabled leagues (event EPG)
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz

from teamarr.consumers.matching import MATCH_WINDOW_DAYS
from teamarr.consumers.matching.classifier import ClassifiedStream, StreamCategory
from teamarr.consumers.matching.constants import (
    BOTH_TEAMS_THRESHOLD,
    HIGH_CONFIDENCE_THRESHOLD,
)
from teamarr.consumers.matching.country_resolver import CountryNameResolver
from teamarr.consumers.matching.normalizer import normalize_for_matching
from teamarr.consumers.matching.result import (
    FailedReason,
    FilteredReason,
    MatchMethod,
    MatchOutcome,
)
from teamarr.consumers.stream_match_cache import StreamMatchCache, event_to_cache_data
from teamarr.core.types import Event, Team
from teamarr.services.sports_data import SportsDataService
from teamarr.utilities.constants import TEAM_ALIASES
from teamarr.utilities.fuzzy_match import get_matcher, normalize_text

logger = logging.getLogger(__name__)

# EPG anchored matching (bead t5e). A live broadcast's EPG program starts at ~the
# event's official start; encores/replays/"classic" re-airs and the next game in a
# series air later. When an anchor instant is supplied (the program's start), a
# candidate event must fall within this tolerance of it to match — the definitive,
# category-independent guard against binding a stream to an encore or the wrong
# occurrence.
#
# 90 minutes (chosen 2026-06-03): a team-sport event always runs >90 min, so the
# earliest an encore can START is >90 min after the live start — outside the gate.
# Meanwhile ±90 min absorbs the usual broadcast-vs-scheduled-start skew (pre-game
# lead-in). Tighter than an hours-wide window on purpose: it also excludes the
# OTHER game of a same-day doubleheader (hours apart). Trade-off: if a provider's
# guide lists the live program >90 min off the event start, that event simply gets
# no EPG stream (safe no-match) rather than a wrong-occurrence bind.
ANCHOR_MATCH_TOLERANCE_SECONDS = 90 * 60


def _sport_hint_matches(sport_hint: str | list[str], event_sport: str) -> bool:
    """Check if a sport hint matches an event's sport.

    Handles both single hints ("Hockey") and multi-sport hints
    (["Soccer", "Football"]) for ambiguous terms.
    """
    event_lower = event_sport.lower()
    if isinstance(sport_hint, list):
        return event_lower in [s.lower() for s in sport_hint]
    return event_lower == sport_hint.lower()


# Type alias for user-defined aliases: (alias_text, league) -> team_name
UserAliasCache = dict[tuple[str, str], str]


@dataclass
class MatchContext:
    """Context for a matching attempt."""

    stream_name: str
    stream_id: int
    group_id: int
    target_date: date
    generation: int
    user_tz: ZoneInfo
    classified: ClassifiedStream  # From classifier

    # Optional fields (must come after required fields)
    stream_tz: ZoneInfo | None = None  # TZ for stream dates
    team1: str | None = None  # Extracted team names (from classifier)
    team2: str | None = None

    # EPG matching (bead t5e): absolute broadcast instant of the matched program.
    # When set, same-team candidate events are ranked by absolute time proximity
    # to this anchor (nearest wins, tolerance-bounded) instead of by calendar
    # date — so a series game whose title repeats across nights, or a post-game
    # encore airing, binds to the correct occurrence. The match cache is bypassed
    # for anchored matches (same title, different instants must not collide).
    anchor_dt: "datetime | None" = None

    # Sport durations for ongoing event detection (hours)
    sport_durations: dict[str, float] = field(default_factory=dict)

    def is_event_in_search_window(self, event: "Event") -> bool:
        """Check if an event falls within the 30-day search window for matching.

        V2 uses full 30-day cache for matching to support stats tracking.
        The lifecycle layer will categorize matched-but-past events as EXCLUDED,
        allowing users to see that streams matched correctly even if events are over.

        Final/completed status is NOT checked here - lifecycle handles exclusions.
        """
        event_start = event.start_time.astimezone(self.user_tz)
        event_date = event_start.date()

        earliest_date = self.target_date - timedelta(days=MATCH_WINDOW_DAYS)

        return event_date >= earliest_date


class TeamMatcher:
    """Matches team-vs-team streams to provider events.

    Flow:
    1. Check user-corrected cache (pinned)
    2. Check algorithmic cache
    3. Match via: aliases → patterns → fuzzy
    4. Validate date
    5. Cache result
    """

    def __init__(
        self,
        service: SportsDataService,
        cache: StreamMatchCache,
        db_factory: Any = None,
        days_ahead: int = 3,
    ):
        """Initialize matcher.

        Args:
            service: Sports data service for event/team lookups
            cache: Stream match cache
            db_factory: Optional database factory for alias lookups
            days_ahead: Days to look ahead for events (default 3)
        """
        self._service = service
        self._cache = cache
        self._db = db_factory
        self._fuzzy = get_matcher()
        self._days_ahead = days_ahead
        # Load user-defined aliases from database
        # Forward cache: (alias, league) -> canonical
        self._user_aliases: UserAliasCache = self._load_user_aliases()
        # Reverse cache: alias -> [(canonical, league), ...]
        # Enables finding canonical name without knowing league first
        self._reverse_aliases: dict[str, list[tuple[str, str]]] = self._build_reverse_cache()
        # Locale-aware country name resolver (e.g. "brasil" → "Brazil")
        self._country_resolver = CountryNameResolver()

    def reload_aliases(self) -> None:
        """Reload aliases from database.

        Call this after alias CRUD operations to update the in-memory caches.
        Rebuilds both the forward cache (alias, league) -> canonical and
        the reverse cache alias -> [(canonical, league), ...].
        """
        self._user_aliases = self._load_user_aliases()
        self._reverse_aliases = self._build_reverse_cache()
        logger.info(
            "[ALIAS] Reloaded aliases: %d forward, %d reverse entries",
            len(self._user_aliases),
            len(self._reverse_aliases),
        )

    def match_single_league(
        self,
        classified: ClassifiedStream,
        league: str,
        target_date: date,
        group_id: int,
        stream_id: int,
        generation: int,
        user_tz: ZoneInfo,
        sport_durations: dict[str, float] | None = None,
        stream_tz: ZoneInfo | None = None,
        anchor_dt: "datetime | None" = None,
    ) -> MatchOutcome:
        """Single-league matching - search only the specified league.

        Used for team EPG where the league is known from the team config.

        Args:
            classified: Pre-classified stream
            league: Authoritative league code
            target_date: Date to match events for
            group_id: Event group ID (for caching)
            stream_id: Stream ID (for caching)
            generation: Cache generation counter
            user_tz: User timezone for date validation
            sport_durations: Sport duration settings for ongoing event detection
            stream_tz: Timezone for interpreting stream dates (from stream or group)

        Returns:
            MatchOutcome with result
        """
        if classified.category != StreamCategory.TEAM_VS_TEAM:
            return MatchOutcome.filtered(
                FilteredReason.NOT_EVENT,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
            )

        ctx = MatchContext(
            stream_name=classified.normalized.original,
            stream_id=stream_id,
            group_id=group_id,
            target_date=target_date,
            generation=generation,
            user_tz=user_tz,
            stream_tz=stream_tz,
            classified=classified,
            team1=classified.team1,
            team2=classified.team2,
            sport_durations=sport_durations or {},
            anchor_dt=anchor_dt,
        )

        # Check cache first
        cache_result = self._check_cache(ctx)
        if cache_result:
            return cache_result

        # Fetch events from MATCH_WINDOW_DAYS back to days_ahead
        # - Today + future: fetch from API (ESPN)
        # - Past: always use cache
        # - TSDB leagues: always cache-only
        is_tsdb = self._service.get_provider_name(league) == "tsdb"
        events = []
        for offset in range(-MATCH_WINDOW_DAYS, self._days_ahead + 1):
            fetch_date = target_date + timedelta(days=offset)
            # Today and future: fetch from API; Past/TSDB: cache only
            cache_only = is_tsdb or offset < 0
            events.extend(self._service.get_events(league, fetch_date, cache_only=cache_only))

        if not events:
            return MatchOutcome.failed(
                FailedReason.NO_EVENT_FOUND,
                stream_name=ctx.stream_name,
                stream_id=stream_id,
                detail=f"No events in {league} for {target_date}",
                parsed_team1=ctx.team1,
                parsed_team2=ctx.team2,
            )

        # Try to match (is_event_ongoing filters out completed yesterday events)
        result = self._match_against_events(ctx, events, league)

        # Cache successful matches
        if result.is_matched and result.event:
            self._cache_result(ctx, result)

        return result

    def match_multi_league(
        self,
        classified: ClassifiedStream,
        enabled_leagues: list[str],
        target_date: date,
        group_id: int,
        stream_id: int,
        generation: int,
        user_tz: ZoneInfo,
        sport_durations: dict[str, float] | None = None,
        prefetched_events: dict[str, list["Event"]] | None = None,
        stream_tz: ZoneInfo | None = None,
        anchor_dt: "datetime | None" = None,
    ) -> MatchOutcome:
        """Multi-league matching with league hint detection.

        Used for event EPG groups with multiple leagues configured.

        Strategy:
        1. Check cache
        2. Detect league hint from stream name
           - If hint not in enabled_leagues → FILTERED:LEAGUE_NOT_INCLUDED
           - If hint in enabled_leagues → search only that league
        3. If no hint, search all enabled leagues
        4. Match and cache

        Args:
            classified: Pre-classified stream
            enabled_leagues: List of league codes enabled for this group
            target_date: Date to match events for
            group_id: Event group ID (for caching)
            stream_id: Stream ID (for caching)
            generation: Cache generation counter
            user_tz: User timezone for date validation
            sport_durations: Sport duration settings for ongoing event detection
            prefetched_events: Optional pre-fetched events by league (for performance)
            stream_tz: Timezone for interpreting stream dates (from stream or group)

        Returns:
            MatchOutcome with result
        """
        if classified.category != StreamCategory.TEAM_VS_TEAM:
            return MatchOutcome.filtered(
                FilteredReason.NOT_EVENT,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
            )

        ctx = MatchContext(
            stream_name=classified.normalized.original,
            stream_id=stream_id,
            group_id=group_id,
            target_date=target_date,
            generation=generation,
            user_tz=user_tz,
            stream_tz=stream_tz,
            classified=classified,
            team1=classified.team1,
            team2=classified.team2,
            sport_durations=sport_durations or {},
            anchor_dt=anchor_dt,
        )

        # Check cache first
        cache_result = self._check_cache(ctx)
        if cache_result:
            return cache_result

        # Detect league hint (can be single league or list for umbrella brands like EFL)
        league_hint = classified.league_hint

        if league_hint:
            # Normalize to list for uniform handling
            hint_leagues = [league_hint] if isinstance(league_hint, str) else league_hint
            # Filter to only leagues that are enabled for this group
            valid_leagues = [lg for lg in hint_leagues if lg in enabled_leagues]

            if not valid_leagues:
                # None of the hinted leagues are enabled
                hint_display = (
                    league_hint if isinstance(league_hint, str) else ", ".join(league_hint)
                )
                return MatchOutcome.filtered(
                    FilteredReason.LEAGUE_NOT_INCLUDED,
                    stream_name=ctx.stream_name,
                    stream_id=stream_id,
                    detail=f"League '{hint_display}' not in enabled leagues",
                )
            # Narrow search to valid hinted leagues
            leagues_to_search = valid_leagues
        else:
            # No hint, search all enabled leagues
            leagues_to_search = enabled_leagues

        # Use prefetched events if available (much faster for multi-stream matching)
        # Otherwise, fetch events: use full 30-day cache for matching
        all_events: list[tuple[str, Event]] = []

        if prefetched_events:
            # Use pre-fetched events (already fetched once for all streams)
            for league in leagues_to_search:
                for event in prefetched_events.get(league, []):
                    all_events.append((league, event))
        else:
            # Fallback: fetch events per-stream (slower, used when no prefetch)
            for league in leagues_to_search:
                is_tsdb = self._service.get_provider_name(league) == "tsdb"
                for offset in range(-MATCH_WINDOW_DAYS, self._days_ahead + 1):
                    fetch_date = target_date + timedelta(days=offset)
                    # Today and future: fetch from API; Past/TSDB: cache only
                    cache_only = is_tsdb or offset < 0
                    events = self._service.get_events(league, fetch_date, cache_only=cache_only)
                    for event in events:
                        all_events.append((league, event))

        if not all_events:
            return MatchOutcome.failed(
                FailedReason.NO_EVENT_FOUND,
                stream_name=ctx.stream_name,
                stream_id=stream_id,
                detail=f"No events in any league for {target_date}",
                parsed_team1=ctx.team1,
                parsed_team2=ctx.team2,
            )

        # Try to match against all events
        result = self._match_against_multi_league_events(ctx, all_events)

        # If match failed with NO_EVENT_FOUND, try reverse alias resolution
        # This handles cases where classifier couldn't detect league but user has aliases
        if result.is_failed and result.failed_reason == FailedReason.NO_EVENT_FOUND:
            retry_result = self._try_reverse_alias_match(ctx, all_events, leagues_to_search)
            if retry_result and retry_result.is_matched:
                result = retry_result

        # Cache successful matches
        if result.is_matched and result.event:
            self._cache_result(ctx, result)

        return result

    def match_team_only(
        self,
        classified: ClassifiedStream,
        enabled_leagues: list[str],
        target_date: date,
        group_id: int,
        stream_id: int,
        generation: int,
        user_tz: ZoneInfo,
        sport_durations: dict[str, float] | None = None,
        prefetched_events: dict[str, list[Event]] | None = None,
        stream_tz: ZoneInfo | None = None,
        anchor_dt: "datetime | None" = None,
    ) -> list[MatchOutcome]:
        """Match a single-team branded stream (TEAM_ONLY) to all its events in the window.

        Unlike TEAM_VS_TEAM, the stream carries one team's brand (e.g.
        "NHL | Toronto Maple Leafs") and should be added to every event where
        that team plays within the date window. Returns one MatchOutcome per
        matched event so the caller can fan out to multiple channels.

        Args:
            classified: Pre-classified stream (category must be TEAM_ONLY)
            enabled_leagues: League codes subscribed for this group
            target_date: Date to anchor the search window
            group_id: Event group ID (for caching)
            stream_id: Stream ID (for caching)
            generation: Cache generation counter
            user_tz: User timezone for date validation
            sport_durations: Sport duration settings
            prefetched_events: Optional pre-fetched events by league
            stream_tz: Timezone for interpreting stream dates

        Returns:
            List of MatchOutcome — one per matched event, or a single
            filtered/failed outcome if nothing matched.
        """
        if classified.category != StreamCategory.TEAM_ONLY:
            return [MatchOutcome.filtered(
                FilteredReason.NOT_EVENT,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
            )]

        stream_name = classified.normalized.original

        # Narrow search by league hint (same logic as match_multi_league)
        league_hint = classified.league_hint
        if league_hint:
            hint_leagues = [league_hint] if isinstance(league_hint, str) else league_hint
            valid_leagues = [lg for lg in hint_leagues if lg in enabled_leagues]
            if not valid_leagues:
                hint_display = (
                    league_hint if isinstance(league_hint, str) else ", ".join(league_hint)
                )
                return [MatchOutcome.filtered(
                    FilteredReason.LEAGUE_NOT_INCLUDED,
                    stream_name=stream_name,
                    stream_id=stream_id,
                    detail=f"League '{hint_display}' not in enabled leagues",
                )]
            leagues_to_search = valid_leagues
        else:
            leagues_to_search = enabled_leagues

        # Narrow date window to ±2 days to minimise false positives.
        window_days = 2
        all_events: list[tuple[str, Event]] = []
        if prefetched_events:
            for league in leagues_to_search:
                for event in prefetched_events.get(league, []):
                    event_date = event.start_time.astimezone(user_tz).date()
                    if abs((event_date - target_date).days) <= window_days:
                        all_events.append((league, event))
        else:
            is_tsdb_map = {
                lg: self._service.get_provider_name(lg) == "tsdb"
                for lg in leagues_to_search
            }
            for league in leagues_to_search:
                for offset in range(-window_days, window_days + 1):
                    fetch_date = target_date + timedelta(days=offset)
                    cache_only = is_tsdb_map[league] or offset < 0
                    events = self._service.get_events(league, fetch_date, cache_only=cache_only)
                    for event in events:
                        all_events.append((league, event))

        if not all_events:
            return [MatchOutcome.failed(
                FailedReason.NO_EVENT_FOUND,
                stream_name=stream_name,
                stream_id=stream_id,
                detail=f"No events in window ±{window_days}d for {target_date}",
                parsed_team1=classified.team1,
            )]

        team_norm = normalize_for_matching(classified.team1) if classified.team1 else None
        if not team_norm:
            return [MatchOutcome.failed(
                FailedReason.TEAMS_NOT_PARSED,
                stream_name=stream_name,
                stream_id=stream_id,
                detail="No team candidate extracted",
            )]

        matched_outcomes: list[MatchOutcome] = []
        seen_event_ids: set[str] = set()

        for league, event in all_events:
            if event.id in seen_event_ids:
                continue

            # EPG anchored matching (bead t5e): gate to the live occurrence near
            # the program's broadcast instant (excludes encores / wrong night).
            if anchor_dt is not None:
                anchor_skew = abs((event.start_time - anchor_dt).total_seconds())
                if anchor_skew > ANCHOR_MATCH_TOLERANCE_SECONDS:
                    continue
            score, _side = self._score_single_team_against_event(team_norm, event)
            if score is None:
                continue
            seen_event_ids.add(event.id)
            logger.debug(
                "[TEAM_ONLY] Matched: stream_id=%d team='%s' event=%s league=%s conf=%.0f%%",
                stream_id,
                classified.team1,
                event.id,
                league,
                score,
            )
            matched_outcomes.append(MatchOutcome.matched(
                MatchMethod.FUZZY,
                event,
                detected_league=league,
                confidence=score / 100.0,
                stream_name=stream_name,
                stream_id=stream_id,
                parsed_team1=classified.team1,
            ))

        if matched_outcomes:
            return matched_outcomes

        return [MatchOutcome.failed(
            FailedReason.NO_EVENT_FOUND,
            stream_name=stream_name,
            stream_id=stream_id,
            detail=f"No event found for team '{classified.team1}'",
            parsed_team1=classified.team1,
        )]

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _check_cache(self, ctx: MatchContext) -> MatchOutcome | None:
        """Check cache for existing match.

        User-corrected entries are always trusted (pinned).
        Algorithmic entries are validated against date.
        """
        # Anchored (EPG) matches are keyed only by title in the cache, but two
        # programs with the same title (a series' Game 1/Game 2, or a live airing
        # + its encore) must resolve to different events by their own instant.
        # Skip the cache so each program is matched fresh against its anchor.
        if ctx.anchor_dt is not None:
            return None

        entry = self._cache.get(ctx.group_id, ctx.stream_id, ctx.stream_name)
        if not entry:
            return None

        # Touch the cache entry to keep it fresh
        self._cache.touch(ctx.group_id, ctx.stream_id, ctx.stream_name, ctx.generation)

        # Reconstruct event from cached data
        event = self._reconstruct_event(entry.cached_data)
        if not event:
            # Cache entry is invalid
            logger.debug(
                "[MATCH_CACHE] Invalid: failed to reconstruct event for stream=%d", ctx.stream_id
            )
            self._cache.delete(ctx.group_id, ctx.stream_id, ctx.stream_name)
            return None

        # User-corrected entries are pinned - always trust them regardless of date
        if entry.user_corrected:
            logger.debug(
                "[CACHE_HIT] stream_id=%d event=%s (user corrected)",
                ctx.stream_id,
                event.id,
            )
            return MatchOutcome.matched(
                MatchMethod.USER_CORRECTED,
                event,
                detected_league=entry.league,
                confidence=1.0,
                stream_name=ctx.stream_name,
                stream_id=ctx.stream_id,
                parsed_team1=ctx.team1,
                parsed_team2=ctx.team2,
            )

        # V1 Parity: Cached events from yesterday should be re-matched to get fresh status.
        # The cached event has OLD status from when it was cached, which may have
        # changed to "final". Re-matching ensures we get current status from ESPN.
        event_date = event.start_time.astimezone(ctx.user_tz).date()
        if event_date < ctx.target_date:
            # Event is from a previous day - invalidate cache to get fresh status
            logger.debug(
                "[MATCH_CACHE] Stale: event from %s < target %s", event_date, ctx.target_date
            )
            return None

        # Today's events: use cache (final status handled in _outcome_to_result)
        if event_date != ctx.target_date:
            logger.debug(
                "[MATCH_CACHE] Mismatch: event from %s != target %s", event_date, ctx.target_date
            )
            return None

        logger.debug(
            "[CACHE_HIT] stream_id=%d event=%s",
            ctx.stream_id,
            event.id,
        )
        return MatchOutcome.matched(
            MatchMethod.CACHE,
            event,
            detected_league=entry.league,
            confidence=1.0,
            stream_name=ctx.stream_name,
            stream_id=ctx.stream_id,
            parsed_team1=ctx.team1,
            parsed_team2=ctx.team2,
            origin_match_method=entry.match_method,  # Original method (fuzzy, alias, etc.)
        )

    def _match_against_events(
        self,
        ctx: MatchContext,
        events: list[Event],
        league: str,
    ) -> MatchOutcome:
        """Try to match classified stream against events in a single league.

        Uses whole-name token_set_ratio matching with the following strategy:
        1. Try alias match first (100% confidence for known abbreviations)
        2. Fall back to token_set_ratio between extracted teams and event name
        3. If no match, strip parentheticals from raw names and retry
           (handles noise like "(Baseball)", "(Available outside Ottawa Region)"
           without breaking legitimate disambiguators like "Miami (OH)")
        4. Rank by: score > time proximity > date proximity
        """
        team1_normalized = normalize_for_matching(ctx.team1) if ctx.team1 else None
        team2_normalized = normalize_for_matching(ctx.team2) if ctx.team2 else None

        if not team1_normalized and not team2_normalized:
            return MatchOutcome.failed(
                FailedReason.TEAMS_NOT_PARSED,
                stream_name=ctx.stream_name,
                stream_id=ctx.stream_id,
                detail="No team names extracted",
            )

        # Pre-compute parenthetical-stripped versions from RAW names for fallback.
        # normalize_for_matching strips parens as punctuation, so we must strip
        # from the raw names first, then normalize — otherwise the fallback
        # can never detect that parentheticals were removed.
        fallback_t1, fallback_t2, has_stripped_fallback = self._prepare_stripped_fallback(
            ctx.team1, ctx.team2, team1_normalized, team2_normalized
        )

        # Check if we have date validation from the stream
        has_date_validation = ctx.classified.normalized.extracted_date is not None

        best_match: Event | None = None
        best_method: MatchMethod = MatchMethod.FUZZY
        best_confidence: float = 0.0
        best_is_future: bool = False  # Whether best match is today or future
        best_date_distance: int = 999  # Absolute days from target_date
        best_time_distance: int = 999999  # Seconds from stream time (for doubleheaders)
        best_anchor_dist: int = 999999999  # Seconds from EPG anchor (bead t5e)

        for event in events:
            # Validate event is within search window (lifecycle handles exclusions)
            if not ctx.is_event_in_search_window(event):
                continue

            # EPG anchored matching (bead t5e): the candidate must air within the
            # tolerance of the program's broadcast instant, else it is a different
            # occurrence — an encore/replay or the next game in the series. This is
            # the definitive, category-independent guard against encore binding.
            anchor_dist = 0
            if ctx.anchor_dt is not None:
                anchor_dist = abs(int((event.start_time - ctx.anchor_dt).total_seconds()))
                if anchor_dist > ANCHOR_MATCH_TOLERANCE_SECONDS:
                    continue

            event_date = event.start_time.astimezone(ctx.user_tz).date()

            # Check for date mismatch from stream (if extracted)
            # Use stream_tz if available - the date in the stream name is in the provider's timezone
            if ctx.classified.normalized.extracted_date:
                # Get event date in the stream's timezone (or user_tz as fallback)
                compare_tz = ctx.stream_tz or ctx.user_tz
                event_date_in_stream_tz = event.start_time.astimezone(compare_tz).date()
                if ctx.classified.normalized.extracted_date != event_date_in_stream_tz:
                    continue

            # Check for sport mismatch from stream (if detected)
            # Skip when league hint is present - league is more specific and avoids
            # sport naming inconsistencies (e.g., "Football" vs "soccer")
            if ctx.classified.sport_hint and not ctx.classified.league_hint:
                if not _sport_hint_matches(ctx.classified.sport_hint, event.sport):
                    continue

            # Try alias match first (100% confidence)
            match_result = self._check_alias_match(team1_normalized, team2_normalized, event)

            # Fall back to whole-name matching using extracted teams
            if not match_result:
                match_result = self._match_teams_to_event(
                    team1_normalized, team2_normalized, event, has_date_validation
                )

            # Fallback: retry with parentheticals stripped from raw names
            # Handles noise like "(Baseball)", "(03.10 /4PM PT)" without
            # breaking legitimate disambiguators like "Miami (OH)" (tried above)
            if not match_result and has_stripped_fallback:
                match_result = self._match_teams_to_event(
                    fallback_t1, fallback_t2, event, has_date_validation
                )

            if match_result:
                method, score = match_result

                # Calculate date metrics for comparison
                days_from_target = (event_date - ctx.target_date).days
                is_future = days_from_target >= 0  # Today or future
                abs_distance = abs(days_from_target)

                # Calculate time proximity for doubleheader disambiguation
                # Use stream_tz if available - the time in stream name is in provider's timezone
                time_distance = 999999
                if ctx.classified.normalized.extracted_time:
                    time_tz = ctx.stream_tz or ctx.user_tz
                    ref_date = event.start_time.astimezone(time_tz).date()
                    stream_dt = datetime.combine(
                        ref_date, ctx.classified.normalized.extracted_time, tzinfo=time_tz
                    )
                    time_distance = abs(
                        int((event.start_time.astimezone(time_tz) - stream_dt).total_seconds())
                    )

                # Ranking: score > time proximity > future over past > date proximity.
                # For EPG anchored matches, nearest to the program instant wins
                # outright (the encore/series guard already gated the candidates).
                is_better = False
                if score > best_confidence:
                    is_better = True
                elif score == best_confidence:
                    if ctx.anchor_dt is not None:
                        is_better = anchor_dist < best_anchor_dist
                    elif time_distance < best_time_distance:
                        # Closer to stream time wins (doubleheader case)
                        is_better = True
                    elif time_distance == best_time_distance:
                        if is_future and not best_is_future:
                            # Future beats past
                            is_better = True
                        elif is_future == best_is_future and abs_distance < best_date_distance:
                            # Same future/past status, prefer closer
                            is_better = True

                if is_better:
                    best_match = event
                    best_method = method
                    best_confidence = score
                    best_is_future = is_future
                    best_date_distance = abs_distance
                    best_time_distance = time_distance
                    best_anchor_dist = anchor_dist

        if best_match:
            logger.debug(
                "[MATCHED] stream_id=%d method=%s event=%s confidence=%.0f%%",
                ctx.stream_id,
                best_method.value,
                best_match.id,
                best_confidence,
            )
            return MatchOutcome.matched(
                best_method,
                best_match,
                detected_league=league,
                confidence=best_confidence / 100.0,  # Convert to 0-1
                stream_name=ctx.stream_name,
                stream_id=ctx.stream_id,
                parsed_team1=ctx.team1,
                parsed_team2=ctx.team2,
            )

        # No match found
        if team1_normalized and not team2_normalized:
            reason = FailedReason.TEAM2_NOT_FOUND
        elif team2_normalized and not team1_normalized:
            reason = FailedReason.TEAM1_NOT_FOUND
        else:
            reason = FailedReason.NO_EVENT_FOUND

        logger.debug(
            "[FAILED] stream_id=%d reason=%s teams=%s/%s",
            ctx.stream_id,
            reason.value,
            ctx.team1,
            ctx.team2,
        )
        return MatchOutcome.failed(
            reason,
            stream_name=ctx.stream_name,
            stream_id=ctx.stream_id,
            parsed_team1=ctx.team1,
            parsed_team2=ctx.team2,
        )

    def _match_against_multi_league_events(
        self,
        ctx: MatchContext,
        events: list[tuple[str, Event]],
    ) -> MatchOutcome:
        """Try to match against events from multiple leagues.

        Uses whole-name token_set_ratio matching with the following strategy:
        1. Try alias match first (100% confidence for known abbreviations)
        2. Fall back to token_set_ratio between extracted teams and event name
        3. If no match, strip parentheticals from raw names and retry
           (handles noise like "(Baseball)", "(Available outside Ottawa Region)"
           without breaking legitimate disambiguators like "Miami (OH)")
        4. Rank by: score > time proximity > date proximity
        """
        team1_normalized = normalize_for_matching(ctx.team1) if ctx.team1 else None
        team2_normalized = normalize_for_matching(ctx.team2) if ctx.team2 else None

        if not team1_normalized and not team2_normalized:
            return MatchOutcome.failed(
                FailedReason.TEAMS_NOT_PARSED,
                stream_name=ctx.stream_name,
                stream_id=ctx.stream_id,
                detail="No team names extracted",
            )

        # Pre-compute parenthetical-stripped versions from RAW names for fallback.
        # normalize_for_matching strips parens as punctuation, so we must strip
        # from the raw names first, then normalize — otherwise the fallback
        # can never detect that parentheticals were removed.
        fallback_t1, fallback_t2, has_stripped_fallback = self._prepare_stripped_fallback(
            ctx.team1, ctx.team2, team1_normalized, team2_normalized
        )

        # Check if we have date validation from the stream
        has_date_validation = ctx.classified.normalized.extracted_date is not None

        best_match: Event | None = None
        best_league: str | None = None
        best_method: MatchMethod = MatchMethod.FUZZY
        best_confidence: float = 0.0
        best_is_future: bool = False  # Whether best match is today or future
        best_date_distance: int = 999  # Absolute days from target_date
        best_time_distance: int = 999999  # Seconds from stream time (for doubleheaders)
        best_anchor_dist: int = 999999999  # Seconds from EPG anchor (bead t5e)

        for league, event in events:
            # Validate event is within search window (lifecycle handles exclusions)
            if not ctx.is_event_in_search_window(event):
                continue

            # EPG anchored matching (bead t5e): the candidate must air within the
            # tolerance of the program's broadcast instant, else it is a different
            # occurrence — an encore/replay or the next game in the series. This is
            # the definitive, category-independent guard against encore binding.
            anchor_dist = 0
            if ctx.anchor_dt is not None:
                anchor_dist = abs(int((event.start_time - ctx.anchor_dt).total_seconds()))
                if anchor_dist > ANCHOR_MATCH_TOLERANCE_SECONDS:
                    continue

            event_date = event.start_time.astimezone(ctx.user_tz).date()

            # Check for date mismatch from stream (if extracted)
            # Use stream_tz if available - the date in the stream name is in the provider's timezone
            if ctx.classified.normalized.extracted_date:
                # Get event date in the stream's timezone (or user_tz as fallback)
                compare_tz = ctx.stream_tz or ctx.user_tz
                event_date_in_stream_tz = event.start_time.astimezone(compare_tz).date()
                if ctx.classified.normalized.extracted_date != event_date_in_stream_tz:
                    continue

            # Check for sport mismatch from stream (if detected)
            # Skip when league hint is present - league is more specific and avoids
            # sport naming inconsistencies (e.g., "Football" vs "soccer")
            if ctx.classified.sport_hint and not ctx.classified.league_hint:
                if not _sport_hint_matches(ctx.classified.sport_hint, event.sport):
                    continue

            # Try alias match first (100% confidence)
            match_result = self._check_alias_match(team1_normalized, team2_normalized, event)

            # Fall back to whole-name matching using extracted teams
            if not match_result:
                match_result = self._match_teams_to_event(
                    team1_normalized, team2_normalized, event, has_date_validation
                )

            # Fallback: retry with parentheticals stripped from raw names
            # Handles noise like "(Baseball)", "(03.10 /4PM PT)" without
            # breaking legitimate disambiguators like "Miami (OH)" (tried above)
            if not match_result and has_stripped_fallback:
                match_result = self._match_teams_to_event(
                    fallback_t1, fallback_t2, event, has_date_validation
                )

            if match_result:
                method, score = match_result

                # Calculate date metrics for comparison
                days_from_target = (event_date - ctx.target_date).days
                is_future = days_from_target >= 0  # Today or future
                abs_distance = abs(days_from_target)

                # Calculate time proximity for doubleheader disambiguation
                # Use stream_tz if available - the time in stream name is in provider's timezone
                time_distance = 999999
                if ctx.classified.normalized.extracted_time:
                    time_tz = ctx.stream_tz or ctx.user_tz
                    ref_date = event.start_time.astimezone(time_tz).date()
                    stream_dt = datetime.combine(
                        ref_date, ctx.classified.normalized.extracted_time, tzinfo=time_tz
                    )
                    time_distance = abs(
                        int((event.start_time.astimezone(time_tz) - stream_dt).total_seconds())
                    )

                # Ranking: score > time proximity > future over past > date proximity.
                # For EPG anchored matches, nearest to the program instant wins
                # outright (the encore/series guard already gated the candidates).
                is_better = False
                if score > best_confidence:
                    is_better = True
                elif score == best_confidence:
                    if ctx.anchor_dt is not None:
                        is_better = anchor_dist < best_anchor_dist
                    elif time_distance < best_time_distance:
                        # Closer to stream time wins (doubleheader case)
                        is_better = True
                    elif time_distance == best_time_distance:
                        if is_future and not best_is_future:
                            # Future beats past
                            is_better = True
                        elif is_future == best_is_future and abs_distance < best_date_distance:
                            # Same future/past status, prefer closer
                            is_better = True

                if is_better:
                    best_match = event
                    best_league = league
                    best_method = method
                    best_confidence = score
                    best_is_future = is_future
                    best_date_distance = abs_distance
                    best_anchor_dist = anchor_dist
                    best_time_distance = time_distance

        if best_match and best_league:
            logger.debug(
                "[MATCHED] stream_id=%d method=%s event=%s league=%s confidence=%.0f%%",
                ctx.stream_id,
                best_method.value,
                best_match.id,
                best_league,
                best_confidence,
            )
            return MatchOutcome.matched(
                best_method,
                best_match,
                detected_league=best_league,
                confidence=best_confidence / 100.0,
                stream_name=ctx.stream_name,
                stream_id=ctx.stream_id,
                parsed_team1=ctx.team1,
                parsed_team2=ctx.team2,
            )

        # No match found
        if team1_normalized and not team2_normalized:
            reason = FailedReason.TEAM2_NOT_FOUND
        elif team2_normalized and not team1_normalized:
            reason = FailedReason.TEAM1_NOT_FOUND
        else:
            reason = FailedReason.NO_EVENT_FOUND

        logger.debug(
            "[FAILED] stream_id=%d reason=%s teams=%s/%s",
            ctx.stream_id,
            reason.value,
            ctx.team1,
            ctx.team2,
        )
        return MatchOutcome.failed(
            reason,
            stream_name=ctx.stream_name,
            stream_id=ctx.stream_id,
            parsed_team1=ctx.team1,
            parsed_team2=ctx.team2,
        )

    def _check_abbreviation_match(
        self,
        team1: str | None,
        team2: str | None,
        event: Event,
    ) -> tuple[MatchMethod, float] | None:
        """Check if stream teams exactly match event team abbreviations as tokens.

        Handles tournament-style streams where team codes appear as tokens:
        "SWE" matches abbreviation "SWE", "ITA (M Group B)" contains token "ita"
        matching "ITA".

        Requires both abbreviations to be >= 3 chars to avoid matching 2-letter codes
        (SF, NE, KC) that are more likely to appear as noise tokens.
        """
        home_abbr = (
            normalize_text(event.home_team.abbreviation)
            if event.home_team.abbreviation
            else ""
        )
        away_abbr = (
            normalize_text(event.away_team.abbreviation)
            if event.away_team.abbreviation
            else ""
        )

        if not home_abbr or not away_abbr or len(home_abbr) < 3 or len(away_abbr) < 3:
            return None

        t1_tokens = set(normalize_text(team1).split()) if team1 else set()
        t2_tokens = set(normalize_text(team2).split()) if team2 else set()

        # Both teams must match different event teams
        if team1 and team2:
            opt1 = home_abbr in t1_tokens and away_abbr in t2_tokens
            opt2 = away_abbr in t1_tokens and home_abbr in t2_tokens
            if opt1 or opt2:
                return (MatchMethod.FUZZY, 100.0)
        elif team1:
            if home_abbr in t1_tokens or away_abbr in t1_tokens:
                return (MatchMethod.FUZZY, 100.0)
        elif team2:
            if home_abbr in t2_tokens or away_abbr in t2_tokens:
                return (MatchMethod.FUZZY, 100.0)

        return None

    def _match_teams_to_event(
        self,
        team1: str | None,
        team2: str | None,
        event: Event,
        has_date_validation: bool = False,
    ) -> tuple[MatchMethod, float] | None:
        """Match extracted team names against event teams.

        When both teams are extracted, requires BOTH to match different event teams.
        This prevents "Marist vs Sacred Heart" from matching "Jessup vs Sacred Heart"
        just because one team name overlaps.

        Args:
            team1: First extracted team name (normalized)
            team2: Second extracted team name (normalized)
            event: Event to match against
            has_date_validation: True if stream has extracted date (lower threshold)

        Returns:
            Tuple of (method, confidence) if matched, None otherwise
        """
        # Try exact abbreviation token match (tournament/international streams)
        abbr_result = self._check_abbreviation_match(team1, team2, event)
        if abbr_result:
            return abbr_result

        # Try fuzzy matching with team names
        return self._score_teams_against_event(team1, team2, event)

    @staticmethod
    def _strip_parentheticals(name: str) -> str:
        """Strip parenthetical content from team name.

        Used as fallback when matching fails with parentheticals intact.
        Example: "Ottawa (Available outside region)" → "Ottawa"
                 "Texas State (Baseball) (03.10 /4PM PT)" → "Texas State"
        """
        return re.sub(r"\s*\([^)]*\)", "", name).strip()

    def _prepare_stripped_fallback(
        self,
        raw_team1: str | None,
        raw_team2: str | None,
        norm_team1: str | None,
        norm_team2: str | None,
    ) -> tuple[str | None, str | None, bool]:
        """Pre-compute parenthetical-stripped team names for fallback matching.

        Strips parentheticals from the RAW (pre-normalization) team names, then
        normalizes the result. This is necessary because normalize_for_matching()
        removes parentheses as punctuation, flattening "(Baseball)" into extra
        tokens rather than removing the content entirely.

        Returns:
            Tuple of (stripped_t1, stripped_t2, has_fallback) where has_fallback
            is True if the stripped versions differ from the originals.
        """
        fallback_t1 = norm_team1
        fallback_t2 = norm_team2

        if raw_team1 and "(" in raw_team1:
            stripped = self._strip_parentheticals(raw_team1)
            if stripped:
                fallback_t1 = normalize_for_matching(stripped)

        if raw_team2 and "(" in raw_team2:
            stripped = self._strip_parentheticals(raw_team2)
            if stripped:
                fallback_t2 = normalize_for_matching(stripped)

        has_fallback = fallback_t1 != norm_team1 or fallback_t2 != norm_team2
        return fallback_t1, fallback_t2, has_fallback

    def _score_teams_against_event(
        self,
        team1: str | None,
        team2: str | None,
        event: Event,
    ) -> tuple[MatchMethod, float] | None:
        """Score team names against event teams.

        When both teams are extracted, requires BOTH to match different event teams.

        Args:
            team1: First extracted team name
            team2: Second extracted team name
            event: Event to match against

        Returns:
            Tuple of (method, confidence) if matched, None otherwise
        """
        # Normalize event team names for comparison
        home_normalized = normalize_text(event.home_team.name)
        away_normalized = normalize_text(event.away_team.name)

        # Note: Pipe-separated content (e.g., "Sacramento Kings | Golden 1 Center")
        # is handled naturally by token_set_ratio which finds best token overlap.
        # No explicit pipe resolution needed - "Sacramento Kings" tokens will match.

        if team1 and team2:
            # BOTH teams extracted - require both to match different event teams
            t1_norm = normalize_text(team1)
            t2_norm = normalize_text(team2)

            # Score each stream team against each event team
            t1_vs_home = fuzz.token_set_ratio(t1_norm, home_normalized)
            t1_vs_away = fuzz.token_set_ratio(t1_norm, away_normalized)
            t2_vs_home = fuzz.token_set_ratio(t2_norm, home_normalized)
            t2_vs_away = fuzz.token_set_ratio(t2_norm, away_normalized)

            # Try both valid assignments (each stream team matches a different event team)
            # Option 1: team1 → home, team2 → away
            # Option 2: team1 → away, team2 → home
            # Use min() to require BOTH teams to have good matches
            option1_score = min(t1_vs_home, t2_vs_away)
            option2_score = min(t1_vs_away, t2_vs_home)

            best_score = max(option1_score, option2_score)

            # Use dedicated threshold for both-teams matching (lower because min() is strict)
            if best_score >= BOTH_TEAMS_THRESHOLD:
                return (MatchMethod.FUZZY, best_score)
            return None

        elif team1 or team2:
            # Only ONE team extracted - fall back to matching against full event name
            # Use stricter threshold since we have less confidence
            single_team = team1 or team2
            single_norm = normalize_text(single_team)
            event_name = f"{event.home_team.name} vs {event.away_team.name}"
            event_norm = normalize_text(event_name)

            score = fuzz.token_set_ratio(single_norm, event_norm)

            # For single-team matches, always require high confidence
            if score >= HIGH_CONFIDENCE_THRESHOLD:
                return (MatchMethod.FUZZY, score)
            return None

        return None

    def _score_single_team_against_event(
        self,
        team_norm: str,
        event: "Event",
    ) -> tuple[float, str] | tuple[None, None]:
        """Score a single team name against an event's home and away teams.

        For TEAM_ONLY streams. Returns the best score and which side matched,
        but only when the team clearly matches ONE side and not the other.
        This guards against the (practically impossible) case where the same
        team name scores high on both sides of an event.

        Args:
            team_norm: Normalized candidate team name from the stream
            event: Event to match against

        Returns:
            (score, side) where side is "home" or "away", or (None, None)
        """
        home_norm = normalize_text(event.home_team.name)
        away_norm = normalize_text(event.away_team.name)

        home_score = fuzz.token_set_ratio(team_norm, home_norm)
        away_score = fuzz.token_set_ratio(team_norm, away_norm)

        home_matches = home_score >= HIGH_CONFIDENCE_THRESHOLD
        away_matches = away_score >= HIGH_CONFIDENCE_THRESHOLD

        # Require exactly one side to match (not both)
        if home_matches and not away_matches:
            return home_score, "home"
        if away_matches and not home_matches:
            return away_score, "away"

        return None, None

    def _resolve_alias(self, team_name: str, league: str | None) -> str | None:
        """Resolve a team name to its canonical form via alias lookup.

        Priority:
        1. Built-in aliases (TEAM_ALIASES constant) - league-agnostic
        2. User-defined aliases (database) - league-specific
        3. International country name auto-resolution (e.g. "brasil" → "Brazil")

        Args:
            team_name: The team name to look up
            league: The league code for user-defined alias lookup

        Returns:
            Canonical team name if alias found, None otherwise
        """
        normalized = team_name.lower()

        # First check built-in aliases (league-agnostic)
        canonical = TEAM_ALIASES.get(normalized)
        if canonical:
            return canonical

        # Then check user-defined aliases (league-specific)
        if league and self._user_aliases:
            user_canonical = self._lookup_user_alias(normalized, league)
            if user_canonical:
                return user_canonical

        # Finally, try automatic country name resolution for national-team sports
        country_canonical = self._country_resolver.resolve(team_name)
        if country_canonical:
            logger.debug(
                "[ALIAS] Country name resolved: %r → %r", team_name, country_canonical
            )
            return country_canonical

        return None

    def _check_alias_match(
        self,
        team1: str | None,
        team2: str | None,
        event: Event,
    ) -> tuple[MatchMethod, float] | None:
        """Check if extracted teams match via alias lookup.

        Aliases provide 100% confidence matches for known abbreviations:
        "Man U" → "Manchester United"

        Checks both built-in aliases (constants.py) and user-defined aliases
        (database). User-defined aliases are league-specific.

        Args:
            team1: First extracted team name (normalized)
            team2: Second extracted team name (normalized)
            event: Event to match against

        Returns:
            Tuple of (ALIAS, 100.0) if both teams match via alias, None otherwise
        """
        if not team1 and not team2:
            return None

        # Generate patterns for alias checking
        home_patterns = self._fuzzy.generate_team_patterns(event.home_team)
        away_patterns = self._fuzzy.generate_team_patterns(event.away_team)

        # Get event league for user-defined alias lookup
        event_league = event.league

        team1_match = False
        team2_match = False

        # Check team1 against aliases (built-in first, then user-defined)
        if team1:
            canonical = self._resolve_alias(team1, event_league)
            if canonical:
                if any(canonical in tp.pattern for tp in home_patterns):
                    team1_match = True
                elif any(canonical in tp.pattern for tp in away_patterns):
                    team1_match = True

        # Check team2 against aliases (built-in first, then user-defined)
        if team2:
            canonical = self._resolve_alias(team2, event_league)
            if canonical:
                if any(canonical in tp.pattern for tp in home_patterns):
                    team2_match = True
                elif any(canonical in tp.pattern for tp in away_patterns):
                    team2_match = True

        # Need both teams to match via alias (if both were extracted)
        if team1 and team2:
            if team1_match and team2_match:
                return (MatchMethod.ALIAS, 100.0)
        elif team1 and team1_match:
            return (MatchMethod.ALIAS, 100.0)
        elif team2 and team2_match:
            return (MatchMethod.ALIAS, 100.0)

        return None

    def _load_user_aliases(self) -> UserAliasCache:
        """Load user-defined aliases from database into memory cache.

        Aliases are keyed by (alias_text, league) for efficient lookup.
        Called once at matcher initialization.

        Returns:
            Dict mapping (alias, league) -> team_name
        """
        if not self._db:
            return {}

        try:
            from teamarr.database.aliases import list_aliases

            with self._db() as conn:
                aliases = list_aliases(conn)

            cache: UserAliasCache = {}
            for alias in aliases:
                # Key by (normalized alias, normalized league)
                key = (alias.alias.lower(), alias.league.lower())
                cache[key] = alias.team_name.lower()

            if cache:
                logger.debug("[ALIAS] Loaded %d user-defined aliases from database", len(cache))
            return cache

        except Exception as e:
            logger.warning("[ALIAS] Failed to load user aliases from database: %s", e)
            return {}

    def _build_reverse_cache(self) -> dict[str, list[tuple[str, str]]]:
        """Build reverse alias lookup: alias_text -> [(canonical, league), ...]

        Enables finding canonical name without knowing league first.
        This is critical for multi-league groups where the classifier can't
        detect the league from the stream name.

        Returns:
            Dict mapping normalized alias to list of (canonical_name, league) tuples
        """
        reverse: dict[str, list[tuple[str, str]]] = {}
        for (alias, league), canonical in self._user_aliases.items():
            if alias not in reverse:
                reverse[alias] = []
            reverse[alias].append((canonical, league))

        if reverse:
            logger.debug(
                "[ALIAS] Built reverse cache with %d unique aliases",
                len(reverse),
            )
        return reverse

    def _reverse_resolve_alias(self, team_name: str) -> list[tuple[str, str | None]]:
        """Resolve team name to ALL canonical forms via reverse lookup.

        Returns all matching aliases across all leagues, enabling the caller
        to try matching against each candidate. This is the key to solving
        the multi-league matching problem when league_hint is None.

        Args:
            team_name: Extracted team name to check

        Returns:
            List of (canonical_name, league) tuples. League is None for built-in aliases.
            Empty list if no alias found.
        """
        if not team_name:
            return []

        results: list[tuple[str, str | None]] = []
        normalized = team_name.lower()

        # Check built-in aliases first (already league-agnostic)
        canonical = TEAM_ALIASES.get(normalized)
        if canonical:
            results.append((canonical, None))

        # Check reverse cache - returns ALL leagues where this alias exists
        if self._reverse_aliases:
            matches = self._reverse_aliases.get(normalized, [])
            results.extend(matches)

        return results

    def _try_reverse_alias_match(
        self,
        ctx: MatchContext,
        events: list[tuple[str, Event]],
        enabled_leagues: list[str],
    ) -> MatchOutcome | None:
        """Try matching with reverse alias resolution.

        When initial matching fails and we don't know the league, check if either
        team name is a user-defined alias. If so, we get both the canonical name
        AND the league from the alias, then retry matching with that information.

        Args:
            ctx: Match context with team names
            events: List of (league, event) tuples to match against
            enabled_leagues: List of enabled league codes

        Returns:
            Successful MatchOutcome if reverse alias helps, None otherwise
        """
        if not ctx.team1 and not ctx.team2:
            return None

        # Try reverse alias resolution for both teams
        team1_aliases = self._reverse_resolve_alias(ctx.team1) if ctx.team1 else []
        team2_aliases = self._reverse_resolve_alias(ctx.team2) if ctx.team2 else []

        if not team1_aliases and not team2_aliases:
            return None

        # Collect candidate leagues from aliases (only those that are enabled)
        candidate_leagues: set[str] = set()
        for _canonical, league in team1_aliases + team2_aliases:
            if league and league.lower() in [lg.lower() for lg in enabled_leagues]:
                candidate_leagues.add(league.lower())

        logger.debug(
            "[REVERSE_ALIAS] team1=%s → %s, team2=%s → %s, candidates=%s",
            ctx.team1,
            team1_aliases,
            ctx.team2,
            team2_aliases,
            candidate_leagues,
        )

        if not candidate_leagues and not any(lg is None for _, lg in team1_aliases + team2_aliases):
            # No enabled leagues from aliases and no built-in aliases
            return None

        # Filter events to candidate leagues (if any league-specific aliases found)
        if candidate_leagues:
            league_events = [(lg, ev) for lg, ev in events if lg.lower() in candidate_leagues]
        else:
            league_events = events

        if not league_events:
            return None

        # Try each alias combination until one matches
        # Use original team name if no alias, otherwise try each alias
        team1_candidates = team1_aliases if team1_aliases else [(ctx.team1, None)]
        team2_candidates = team2_aliases if team2_aliases else [(ctx.team2, None)]

        for canonical1, _league1 in team1_candidates:
            for canonical2, _league2 in team2_candidates:
                # Build retry context with resolved names
                retry_ctx = MatchContext(
                    stream_name=ctx.stream_name,
                    stream_id=ctx.stream_id,
                    group_id=ctx.group_id,
                    target_date=ctx.target_date,
                    generation=ctx.generation,
                    user_tz=ctx.user_tz,
                    stream_tz=ctx.stream_tz,
                    classified=ctx.classified,
                    team1=canonical1,
                    team2=canonical2,
                    sport_durations=ctx.sport_durations,
                )

                retry_result = self._match_against_multi_league_events(retry_ctx, league_events)

                if retry_result.is_matched:
                    logger.info(
                        "[REVERSE_ALIAS_MATCH] stream_id=%d '%s/%s' → '%s/%s' in %s",
                        ctx.stream_id,
                        ctx.team1,
                        ctx.team2,
                        canonical1,
                        canonical2,
                        retry_result.detected_league,
                    )
                    # Update parsed team info to show original stream names
                    retry_result.parsed_team1 = ctx.team1
                    retry_result.parsed_team2 = ctx.team2
                    return retry_result

        return None

    def _lookup_user_alias(self, team_name: str, league: str) -> str | None:
        """Look up a team name in user-defined aliases.

        Args:
            team_name: The team name to look up (will be normalized)
            league: The league code to filter by

        Returns:
            Canonical team name if alias found, None otherwise
        """
        if not self._user_aliases:
            return None

        key = (team_name.lower(), league.lower())
        return self._user_aliases.get(key)

    def _disambiguate_by_time(
        self,
        events: list[Event],
        stream_time: time,
        user_tz: ZoneInfo,
    ) -> Event:
        """Pick event closest to stream time for doubleheaders."""
        if len(events) <= 1:
            return events[0] if events else None

        # Combine stream time with event date
        ref_date = events[0].start_time.astimezone(user_tz).date()
        stream_dt = datetime.combine(ref_date, stream_time, tzinfo=user_tz)

        return min(events, key=lambda e: abs(e.start_time.astimezone(user_tz) - stream_dt))

    def _cache_result(self, ctx: MatchContext, result: MatchOutcome) -> None:
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

    def _reconstruct_event(self, cached_data: dict[str, Any]) -> Event | None:
        """Reconstruct Event from cached dict."""
        try:
            # Handle datetime parsing
            start_time = cached_data.get("start_time")
            if isinstance(start_time, str):
                start_time = datetime.fromisoformat(start_time)

            # Reconstruct teams (use `or {}` to handle explicit None values)
            home_data = cached_data.get("home_team") or {}
            away_data = cached_data.get("away_team") or {}

            home_team = Team(
                id=home_data.get("id", ""),
                provider=home_data.get("provider", ""),
                name=home_data.get("name", ""),
                short_name=home_data.get("short_name", ""),
                abbreviation=home_data.get("abbreviation", ""),
                league=home_data.get("league", ""),
                sport=home_data.get("sport", ""),
                logo_url=home_data.get("logo_url"),
                color=home_data.get("color"),
            )

            away_team = Team(
                id=away_data.get("id", ""),
                provider=away_data.get("provider", ""),
                name=away_data.get("name", ""),
                short_name=away_data.get("short_name", ""),
                abbreviation=away_data.get("abbreviation", ""),
                league=away_data.get("league", ""),
                sport=away_data.get("sport", ""),
                logo_url=away_data.get("logo_url"),
                color=away_data.get("color"),
            )

            from teamarr.core.types import EventStatus

            status_data = cached_data.get("status") or {}
            status = EventStatus(
                state=status_data.get("state", "scheduled"),
                detail=status_data.get("detail"),
                period=status_data.get("period"),
                clock=status_data.get("clock"),
            )

            # Handle broadcast/broadcasts field compatibility
            broadcast_val = cached_data.get("broadcasts") or cached_data.get("broadcast")
            broadcasts = (
                broadcast_val
                if isinstance(broadcast_val, list)
                else [broadcast_val]
                if broadcast_val
                else []
            )

            # Reconstruct Venue from dict if present
            from teamarr.core.types import Venue

            venue_data = cached_data.get("venue")
            venue = None
            if venue_data:
                if isinstance(venue_data, dict):
                    venue = Venue(
                        name=venue_data.get("name", ""),
                        city=venue_data.get("city"),
                        state=venue_data.get("state"),
                        country=venue_data.get("country"),
                    )
                else:
                    venue = venue_data  # Already a Venue

            # Reconstruct segment_times for UFC events
            # Use `or {}` to handle both missing key AND explicit None value
            segment_times_data = cached_data.get("segment_times") or {}
            segment_times = {}
            for seg_name, seg_time in segment_times_data.items():
                if isinstance(seg_time, str):
                    segment_times[seg_name] = datetime.fromisoformat(seg_time)
                elif seg_time is not None:
                    segment_times[seg_name] = seg_time

            # Parse main_card_start if present
            main_card_start = cached_data.get("main_card_start")
            if isinstance(main_card_start, str):
                main_card_start = datetime.fromisoformat(main_card_start)

            # Reconstruct racing sessions, if present
            from teamarr.core.types import RacingResult, RacingSession

            sessions = []
            for session_data in cached_data.get("sessions") or []:
                session_start = session_data.get("start_time")
                if isinstance(session_start, str):
                    session_start = datetime.fromisoformat(session_start)
                results = [
                    RacingResult(
                        driver_name=r.get("driver_name", ""),
                        team_name=r.get("team_name"),
                        position=r.get("position"),
                        grid_position=r.get("grid_position"),
                        points=r.get("points"),
                        fastest_lap=r.get("fastest_lap", False),
                        status=r.get("status"),
                    )
                    for r in session_data.get("results") or []
                ]
                sessions.append(
                    RacingSession(
                        code=session_data.get("code", ""),
                        name=session_data.get("name", ""),
                        start_time=session_start,
                        results=results,
                    )
                )

            # Self-heal stale cache rows: every modern provider populates
            # short_name (falling back to the full name when no shorter form
            # exists), so a row with name set but short_name empty is data
            # written before the field flowed end-to-end. Treat as cache miss
            # so the matcher re-fetches and re-caches with proper data.
            for team in (home_team, away_team):
                if team.name and not team.short_name:
                    logger.debug(
                        "[MATCH_CACHE] Stale: team %r has name but no short_name; "
                        "invalidating",
                        team.name,
                    )
                    return None

            return Event(
                id=cached_data.get("id", ""),
                provider=cached_data.get("provider", ""),
                name=cached_data.get("name", ""),
                short_name=cached_data.get("short_name"),
                start_time=start_time,
                home_team=home_team,
                away_team=away_team,
                status=status,
                league=cached_data.get("league", ""),
                sport=cached_data.get("sport", ""),
                season_type=cached_data.get("season_type"),
                venue=venue,
                broadcasts=broadcasts,
                segment_times=segment_times,
                main_card_start=main_card_start,
                circuit_name=cached_data.get("circuit_name"),
                sessions=sessions,
            )
        except Exception as e:
            logger.warning("[MATCH_CACHE] Failed to reconstruct event from cache: %s", e)
            return None
