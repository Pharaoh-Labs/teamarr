"""Unified stream matcher - the main entry point for stream matching.

Replaces CachedMatcher and MultiLeagueMatcher with a cleaner architecture:
1. Classify streams (placeholder, team_vs_team, event_card)
2. Route to appropriate matcher
3. Track results with MatchOutcome system
4. Handle caching with method tracking

Usage:
    from teamarr.consumers.matching import StreamMatcher

    matcher = StreamMatcher(
        service=sports_data_service,
        db_factory=get_db,
        group_id=1,
        search_leagues=["nfl", "nba"],
    )

    result = matcher.match_all(streams, target_date)
    matcher.purge_stale()
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.config import get_user_timezone
from teamarr.consumers.matching.classifier import (
    ClassifiedStream,
    CustomRegexConfig,
    StreamCategory,
    classify_stream,
)
from teamarr.consumers.matching.constants import MATCH_WINDOW_DAYS
from teamarr.consumers.matching.epg_index import EPGProgramIndex
from teamarr.consumers.matching.epg_matcher import build_match_input, should_attempt
from teamarr.consumers.matching.event_matcher import EventCardMatcher
from teamarr.consumers.matching.racing_matcher import RacingMatcher
from teamarr.consumers.matching.result import (
    ExcludedReason,
    FailedReason,
    FilteredReason,
    MatchMethod,
    MatchOutcome,
    ResultAggregator,
)
from teamarr.consumers.matching.team_matcher import TeamMatcher
from teamarr.consumers.stream_match_cache import (
    StreamMatchCache,
    get_generation_counter,
    increment_generation_counter,
)
from teamarr.core import Event
from teamarr.database.leagues import get_league
from teamarr.services import SportsDataService
from teamarr.utilities.event_status import is_event_final

logger = logging.getLogger(__name__)


@dataclass
class MatchedStreamResult:
    """Result of matching a single stream.

    This is the business-level result that combines:
    - Match outcome from MatchOutcome
    - Inclusion decision (business rules)
    - Classification data from ClassifiedStream
    """

    stream_name: str
    stream_id: int

    # Match outcome
    matched: bool
    event: Event | None = None
    league: str | None = None

    # Inclusion decision
    included: bool = False
    exclusion_reason: str | None = None  # Human-readable string

    # Method tracking
    match_method: MatchMethod | None = None
    confidence: float = 0.0
    from_cache: bool = False
    origin_match_method: str | None = None  # For cache hits: original method (fuzzy, alias, etc.)

    # EPG matches: the program's broadcast slot, used by the lifecycle layer
    # (183.5) as the attach/detach window for time-shared linear streams.
    epg_program_start: datetime | None = None
    epg_program_end: datetime | None = None

    # Classification info
    category: StreamCategory | None = None
    parsed_team1: str | None = None
    parsed_team2: str | None = None
    detected_league: str | None = None
    card_segment: str | None = None  # For UFC: "early_prelims", "prelims", "main_card"

    # Exception handling
    exception_keyword: str | None = None

    # Feed separation
    feed_hint: str | None = None  # "home" or "away" if detected

    # Detailed reason enums from MatchOutcome (preserved for type-safe access)
    failed_reason: FailedReason | None = None
    filtered_reason: FilteredReason | None = None
    excluded_reason: ExcludedReason | None = None
    detail: str | None = None  # Additional context from matching

    @property
    def is_exception(self) -> bool:
        return self.exception_keyword is not None


@dataclass
class BatchMatchResult:
    """Result of matching a batch of streams."""

    results: list[MatchedStreamResult] = field(default_factory=list)
    target_date: date | None = None
    leagues_searched: list[str] = field(default_factory=list)
    include_leagues: list[str] = field(default_factory=list)

    # Cache stats
    cache_hits: int = 0
    cache_misses: int = 0

    # Aggregated stats
    aggregator: ResultAggregator = field(default_factory=ResultAggregator)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def matched_count(self) -> int:
        """Count of matched *results* — match VOLUME, not stream coverage.

        One source stream can yield many matched results (a linear/EPG stream
        legitimately matches many events/day; TEAM_ONLY templates also fan out),
        so this can exceed the number of streams. Use ``matched_stream_count``
        for a 0–100% coverage rate; use this for "matches produced".
        """
        return sum(1 for r in self.results if r.matched)

    @property
    def matched_stream_count(self) -> int:
        """Count of distinct source streams that matched ≥1 event (coverage numerator)."""
        return len({r.stream_id for r in self.results if r.matched})

    @property
    def unmatched_stream_count(self) -> int:
        """Distinct source streams with no match (coverage; excludes exceptions).

        A stream whose name failed but whose EPG program matched counts as
        matched, so it is excluded here via set difference — a stream is never
        counted in both matched and unmatched.
        """
        matched_ids = {r.stream_id for r in self.results if r.matched}
        candidate_ids = {r.stream_id for r in self.results if not r.is_exception}
        return len(candidate_ids - matched_ids)

    @property
    def included_count(self) -> int:
        """Count of streams that will be included in output (matched AND not excluded)."""
        return sum(1 for r in self.results if r.included)

    @property
    def unmatched_count(self) -> int:
        """Count of streams that failed to match."""
        return sum(1 for r in self.results if not r.matched and not r.is_exception)

    @property
    def excluded_count(self) -> int:
        """Count of streams that matched but were excluded."""
        return sum(1 for r in self.results if r.matched and not r.included)

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0


class StreamMatcher:
    """Unified stream matcher with classification and caching.

    Matches streams to events using:
    1. Classification: placeholder, team_vs_team, event_card
    2. Routing: TeamMatcher for team sports, EventCardMatcher for UFC/boxing
    3. Caching: fingerprint cache with method tracking
    """

    def __init__(
        self,
        service: SportsDataService,
        db_factory,
        group_id: int,
        search_leagues: list[str],
        include_leagues: list[str] | None = None,
        include_final_events: bool = False,
        sport_durations: dict[str, float] | None = None,
        user_tz: ZoneInfo | None = None,
        generation: int | None = None,
        custom_regex_teams: str | None = None,
        custom_regex_teams_enabled: bool = False,
        custom_regex_date: str | None = None,
        custom_regex_date_enabled: bool = False,
        custom_regex_month: str | None = None,
        custom_regex_month_enabled: bool = False,
        custom_regex_day: str | None = None,
        custom_regex_day_enabled: bool = False,
        custom_regex_time: str | None = None,
        custom_regex_time_enabled: bool = False,
        custom_regex_league: str | None = None,
        custom_regex_league_enabled: bool = False,
        days_ahead: int | None = None,
        shared_events: dict[str, tuple[list[Event], bool]] | None = None,
        stream_timezone: str | None = None,
        feed_home_terms: list[str] | None = None,
        feed_away_terms: list[str] | None = None,
        team_streams_enabled: bool = False,
        epg_index: "EPGProgramIndex | None" = None,
    ):
        """Initialize the matcher.

        Args:
            service: Sports data service
            db_factory: Database connection factory
            group_id: Event group ID for cache fingerprints
            search_leagues: Leagues to search for events
            include_leagues: Whitelist of leagues to include (None = all search_leagues)
            include_final_events: Include completed events
            sport_durations: Sport duration settings
            user_tz: User timezone for date calculations
            generation: Cache generation counter (if None, will be fetched/incremented)
            custom_regex_teams: Custom regex pattern for extracting team names
            custom_regex_teams_enabled: Whether custom regex for teams is enabled
            custom_regex_date: Custom regex pattern for extracting date
            custom_regex_date_enabled: Whether custom regex for date is enabled
            custom_regex_time: Custom regex pattern for extracting time
            custom_regex_time_enabled: Whether custom regex for time is enabled
            custom_regex_league: Custom regex pattern for extracting league hint
            custom_regex_league_enabled: Whether custom regex for league is enabled
            days_ahead: Days to look ahead for events (if None, loaded from settings)
            shared_events: Shared events cache dict (keyed by "league:date") to reuse
                           across multiple matchers in a single generation run.
                           Values are (events, was_cache_only) tuples where was_cache_only
                           indicates if the result came from a cache-only lookup.
            stream_timezone: IANA timezone for interpreting stream dates (group setting)
            feed_home_terms: Terms indicating home feed (e.g., ["HOME"])
            feed_away_terms: Terms indicating away feed (e.g., ["AWAY"])
        """
        self._service = service
        self._db_factory = db_factory
        self._group_id = group_id
        self._search_leagues = search_leagues
        self._include_leagues = set(include_leagues or search_leagues)
        self._include_final_events = include_final_events
        self._sport_durations = sport_durations or {}
        self._user_tz = user_tz or get_user_timezone()

        # Stream timezone (group setting) - convert IANA string to ZoneInfo
        self._stream_tz: ZoneInfo | None = None
        if stream_timezone:
            try:
                self._stream_tz = ZoneInfo(stream_timezone)
            except (KeyError, ValueError):
                logger.warning("[MATCHER] Invalid stream_timezone: %s", stream_timezone)

        # Load days_ahead from settings if not provided
        if days_ahead is None:
            with db_factory() as conn:
                row = conn.execute(
                    "SELECT event_match_days_ahead FROM settings WHERE id = 1"
                ).fetchone()
                days_ahead = (
                    row["event_match_days_ahead"] if row and row["event_match_days_ahead"] else 3
                )
        self._days_ahead = days_ahead

        # Custom regex configuration - create if any pattern is enabled
        has_custom_regex = (
            (custom_regex_teams_enabled and custom_regex_teams)
            or (custom_regex_date_enabled and custom_regex_date)
            or (custom_regex_month_enabled and custom_regex_month)
            or (custom_regex_day_enabled and custom_regex_day)
            or (custom_regex_time_enabled and custom_regex_time)
            or (custom_regex_league_enabled and custom_regex_league)
        )
        self._custom_regex = (
            CustomRegexConfig(
                teams_pattern=custom_regex_teams,
                teams_enabled=custom_regex_teams_enabled,
                date_pattern=custom_regex_date,
                date_enabled=custom_regex_date_enabled,
                month_pattern=custom_regex_month,
                month_enabled=custom_regex_month_enabled,
                day_pattern=custom_regex_day,
                day_enabled=custom_regex_day_enabled,
                time_pattern=custom_regex_time,
                time_enabled=custom_regex_time_enabled,
                league_pattern=custom_regex_league,
                league_enabled=custom_regex_league_enabled,
            )
            if has_custom_regex
            else None
        )

        # Feed separation terms
        self._feed_home_terms = feed_home_terms
        self._feed_away_terms = feed_away_terms
        self._team_streams_enabled = team_streams_enabled

        # Initialize cache
        self._cache = StreamMatchCache(db_factory)
        # Use provided generation or fetch current
        self._generation = generation or get_generation_counter(db_factory)
        self._generation_provided = generation is not None

        # Initialize sub-matchers
        self._team_matcher = TeamMatcher(
            service, self._cache, days_ahead=self._days_ahead, db_factory=db_factory
        )
        self._event_matcher = EventCardMatcher(service, self._cache)
        self._racing_matcher = RacingMatcher(service, self._cache)

        # League event types cache
        self._league_event_types: dict[str, str] = {}

        # Shared events cache (cross-matcher in a single generation run)
        # Keys are "league:date" strings, values are (events, was_cache_only) tuples
        self._shared_events = shared_events

        # Prefetched events (populated in match_all for multi-league matching)
        self._prefetched_events: dict[str, list[Event]] | None = None

        # EPG program index (epic teamarrv2-183). When present (group opted in
        # via 183.6), the matcher augments name matching with EPG-title matching
        # for streams carrying a tvg_id. None = no EPG matching (default).
        self._epg_index = epg_index

    def match_all(
        self,
        streams: list[dict],
        target_date: date,
        progress_callback: Callable | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> BatchMatchResult:
        """Match all streams to events.

        Args:
            streams: List of dicts with 'id' and 'name' keys
            target_date: Date to match events for
            progress_callback: Optional callback(current, total, stream_name, matched)
            status_callback: Optional callback(status_message) for status updates

        Returns:
            BatchMatchResult with all results
        """
        logger.debug(
            "[STARTED] Stream matching: %d streams, %d leagues, date=%s",
            len(streams),
            len(self._search_leagues),
            target_date,
        )

        # Only increment generation if not provided from parent run
        # (When called as part of full EPG generation, generation is shared across groups)
        if not self._generation_provided:
            self._generation = increment_generation_counter(self._db_factory)

        # Load league event types
        self._load_league_event_types()

        # Prefetch events for multi-league matching (significant performance boost)
        # This fetches events ONCE for all streams instead of per-stream
        if len(self._search_leagues) > 1:
            self._prefetch_events(target_date, status_callback=status_callback)
        else:
            self._prefetched_events = None

        result = BatchMatchResult(
            target_date=target_date,
            leagues_searched=self._search_leagues,
            include_leagues=list(self._include_leagues),
        )

        total_streams = len(streams)
        for idx, stream in enumerate(streams, 1):
            stream_id = stream.get("id", 0)
            stream_name = stream.get("name", "")

            match_results = self._match_single(
                stream_id=stream_id,
                stream_name=stream_name,
                target_date=target_date,
            )

            # EPG augmentation (epic 183.4): for streams carrying a tvg_id in an
            # EPG-enabled group, also match via EPG program titles and reconcile.
            tvg_id = stream.get("tvg_id")
            if self._epg_index is not None and tvg_id:
                epg_results = self._match_via_epg(
                    stream_id=stream_id,
                    stream_name=stream_name,
                    tvg_id=tvg_id,
                    target_date=target_date,
                )
                match_results = self._reconcile_epg(match_results, epg_results, tvg_id)

            # Track cache stats and accumulate (TEAM_ONLY may return multiple results)
            any_matched = False
            for match_result in match_results:
                if match_result.from_cache:
                    result.cache_hits += 1
                else:
                    result.cache_misses += 1
                result.results.append(match_result)
                if match_result.matched:
                    any_matched = True

            # Report per-stream progress (report once per source stream)
            if progress_callback:
                progress_callback(idx, total_streams, stream_name, any_matched)

        logger.info(
            "[COMPLETED] Stream matching: %d/%d matched (%d included), cache_hit_rate=%.1f%%",
            result.matched_count,
            result.total,
            result.included_count,
            result.cache_hit_rate * 100,
        )

        return result

    def _prefetch_events(
        self,
        target_date: date,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Prefetch all events for multi-league matching.

        For groups with many leagues (e.g., 278 leagues), fetching events
        per-stream is extremely slow (278 leagues × 15 days × 400 streams).
        Instead, fetch all events ONCE and reuse for all streams.

        Strategy:
        - Check shared_events first (reuse from prior groups in same generation)
        - Past dates: always cache-only (for stats tracking)
        - Today: fetch from API for group's configured leagues, cache for others
        - Future days: fetch from API ONLY for group's configured leagues
        - TSDB leagues: always cache-only

        Results are stored in shared_events (if provided) for reuse by subsequent
        matchers within the same generation run.

        Args:
            target_date: Target date for event matching
            status_callback: Optional callback(status_message) for status updates
        """
        self._prefetched_events = {}
        total_events = 0
        shared_hits = 0
        service_calls = 0

        total_leagues = len(self._search_leagues)
        num_dates = MATCH_WINDOW_DAYS + self._days_ahead + 1
        total_leagues * num_dates

        for league_idx, league in enumerate(self._search_leagues):
            league_events: list[Event] = []
            is_tsdb = self._service.get_provider_name(league) == "tsdb"
            is_group_league = league in self._include_leagues

            # Range: from -MATCH_WINDOW_DAYS to +days_ahead (inclusive)
            for offset in range(-MATCH_WINDOW_DAYS, self._days_ahead + 1):
                fetch_date = target_date + timedelta(days=offset)
                shared_key = f"{league}:{fetch_date.isoformat()}"

                # Cache-only rules:
                # - TSDB (non-subscribed): cache-only to avoid rate limits
                # - TSDB (subscribed): fetch from API like any other provider
                # - Older past (2+ days): always cache-only
                # - Yesterday: fetch from API (today's 30min TTL expires
                #   before next day's run can use it as cache)
                # - Future days: only fetch from API for group's configured leagues
                # - Today: fetch from API for group's leagues, cache for others
                if (is_tsdb and not is_group_league) or offset < -1:
                    cache_only = True
                elif offset == -1:
                    # Yesterday: fetch from API for group's leagues
                    cache_only = not is_group_league
                elif offset > 0:
                    # Future days: only fetch from API for group's leagues
                    cache_only = not is_group_league
                else:
                    # Today: fetch from API for group's leagues, cache for others
                    cache_only = not is_group_league

                # Check shared events cache first (from prior groups in same run)
                if self._shared_events is not None and shared_key in self._shared_events:
                    shared_events, was_cache_only = self._shared_events[shared_key]

                    # Use shared result if:
                    # - It has events (data is valid regardless of how it was fetched)
                    # - OR it was fetched with API available (empty is legitimate)
                    # - OR current group doesn't need this league anyway
                    # Don't use if: empty + was_cache_only + we need this league
                    # (empty from cache miss shouldn't block groups that need API data)
                    if shared_events or not was_cache_only or not is_group_league:
                        league_events.extend(shared_events)
                        shared_hits += 1
                        continue
                    # Fall through to fetch fresh if empty cache-only result
                    # and this group actually needs the league

                events = self._service.get_events(league, fetch_date, cache_only=cache_only)
                service_calls += 1
                league_events.extend(events)

                # Store result in shared cache for subsequent matchers
                # Include was_cache_only flag so later groups can decide whether to re-fetch
                if self._shared_events is not None:
                    self._shared_events[shared_key] = (events, cache_only)

            if league_events:
                self._prefetched_events[league] = league_events
                total_events += len(league_events)

            # Report progress periodically (every 20 leagues or at end)
            if status_callback and (league_idx % 20 == 0 or league_idx == total_leagues - 1):
                int((league_idx + 1) / total_leagues * 100)
                status_callback(
                    f"Prefetching events: {league_idx + 1}/{total_leagues} leagues "
                    f"({total_events} events, {shared_hits} reused)"
                )

        logger.debug(
            f"Prefetched {total_events} events from {len(self._prefetched_events)} leagues "
            f"(window: -{MATCH_WINDOW_DAYS} to +{self._days_ahead} days, "
            f"shared_hits={shared_hits}, service_calls={service_calls})"
        )

    def _match_single(
        self,
        stream_id: int,
        stream_name: str,
        target_date: date,
    ) -> list[MatchedStreamResult]:
        """Match a single stream. Returns a list — usually one element, but TEAM_ONLY
        streams can fan out to multiple results (one per matched event)."""
        # Step 1: Classify the stream
        # Determine event type from configured leagues
        league_event_type = self._get_dominant_event_type()

        classified = classify_stream(
            stream_name, league_event_type, self._custom_regex,
            self._feed_home_terms, self._feed_away_terms,
        )

        # Step 2: Handle placeholders (streams that couldn't be classified)
        # Note: Placeholder pattern detection and unsupported sports filtering
        # is now handled by StreamFilter before streams reach the matcher.
        # This handles streams that passed filtering but still can't be classified
        # (e.g., no separator found, no custom regex match).
        if classified.category == StreamCategory.PLACEHOLDER:
            return [MatchedStreamResult(
                stream_name=stream_name,
                stream_id=stream_id,
                matched=False,
                included=False,
                category=StreamCategory.PLACEHOLDER,
                exclusion_reason="unclassifiable",
            )]

        # Step 3: Gate TEAM_ONLY when disabled, then route by category
        if classified.category == StreamCategory.TEAM_ONLY and not self._team_streams_enabled:
            return [MatchedStreamResult(
                stream_name=stream_name,
                stream_id=stream_id,
                matched=False,
                included=False,
                category=StreamCategory.PLACEHOLDER,
                exclusion_reason="team_streams_disabled",
            )]

        outcomes = self._route_to_outcomes(classified, stream_id, target_date)
        return [
            self._outcome_to_result(
                outcome=o,
                stream_id=stream_id,
                stream_name=stream_name,
                classified=classified,
            )
            for o in outcomes
        ]

    def _route_to_outcomes(
        self,
        classified: ClassifiedStream,
        stream_id: int,
        target_date: date,
        anchor_dt: "datetime | None" = None,
    ) -> list[MatchOutcome]:
        """Route a classified stream to the right sub-matcher, returning outcomes.

        Shared by the stream-name path (_match_single) and the EPG-title path
        (_match_via_epg) so both reuse the exact same TeamMatcher/EventCardMatcher
        logic. EVENT_CARD and TEAM_VS_TEAM yield one outcome; TEAM_ONLY may fan
        out to several (one per matched event). Callers handle PLACEHOLDER and
        TEAM_ONLY-disabled gating before reaching here.

        anchor_dt (EPG path only): the program's broadcast instant, used to gate
        candidate events to the live occurrence (bead t5e).
        """
        if classified.category == StreamCategory.EVENT_CARD:
            return [self._match_event_card(classified, stream_id, target_date)]
        if classified.category == StreamCategory.RACING_EVENT:
            return [self._match_racing_event(classified, stream_id, target_date)]
        if classified.category == StreamCategory.TEAM_ONLY:
            return self._match_team_only(classified, stream_id, target_date, anchor_dt=anchor_dt)
        # TEAM_VS_TEAM
        return [
            self._match_team_vs_team(classified, stream_id, target_date, anchor_dt=anchor_dt)
        ]

    def _match_via_epg(
        self,
        stream_id: int,
        stream_name: str,
        tvg_id: str,
        target_date: date,
    ) -> list[MatchedStreamResult]:
        """Match a stream to events via its EPG program titles (epic 183.4).

        Walks every program on the stream's guide channel (from the injected
        EPGProgramIndex), feeds each program's title+sub_title through the SAME
        classify_stream -> TeamMatcher pipeline used for stream names, and emits
        one matched result per program (a linear channel legitimately matches
        MANY events/day). Each result carries the program's broadcast window for
        the lifecycle layer.

        Cross-run caching comes for free: TeamMatcher caches on
        (group_id, stream_id, input_string), so each distinct program title is
        memoized without a separate fingerprint layer. Only MATCHED outcomes are
        returned — non-games self-reject in the pipeline.
        """
        # Keyed by matched event id so that when several programs match the SAME
        # event (e.g. a pre-game block + the game itself both pass the anchor
        # gate), we keep only the one whose start is nearest the event — the live
        # broadcast — giving a deterministic, correctly-anchored window (bead
        # t5e). Different events on the same channel keep distinct keys.
        best_by_event: dict[str, tuple[float, MatchedStreamResult]] = {}
        league_event_type = self._get_dominant_event_type()

        # Full sorted timeline for this tvg_id. A linear channel legitimately
        # matches many programs/day; each matched program's broadcast slot drives
        # its own attach/detach window in the lifecycle layer.
        programs = self._epg_index.programs_for(tvg_id)
        attempted = 0
        skipped_non_event = 0
        for program in programs:
            if not should_attempt(program):
                skipped_non_event += 1
                continue
            attempted += 1

            classified = classify_stream(
                build_match_input(program), league_event_type, self._custom_regex,
                self._feed_home_terms, self._feed_away_terms,
            )
            if classified.category == StreamCategory.PLACEHOLDER:
                continue
            if classified.category == StreamCategory.TEAM_ONLY and not self._team_streams_enabled:
                continue

            # Anchor matching to the program's own broadcast instant (bead t5e).
            # EPG titles carry no date/time, so a program would otherwise match
            # purely by team names — and a series game whose title repeats across
            # nights, or a post-game encore/replay, would bind to the wrong
            # occurrence and anchor its attach/detach window to the wrong slot.
            # The matcher gates candidate events to those airing within
            # ANCHOR_MATCH_TOLERANCE of this instant (live broadcast only).
            for outcome in self._route_to_outcomes(
                classified, stream_id, target_date, anchor_dt=program.start_dt
            ):
                if not outcome.is_matched:
                    continue
                # Tag as EPG and attach the program's broadcast window (183.5).
                outcome.match_method = MatchMethod.EPG
                outcome.epg_program_start = program.start_dt
                outcome.epg_program_end = program.end_dt
                # Diagnostic: program slot vs matched event time. A large skew
                # (Δ) is the tell-tale of a wrong-occurrence bind (bead t5e) —
                # the program and the event it matched are hours/days apart.
                ev = outcome.event
                ev_start = getattr(ev, "start_time", None)
                ev_id = getattr(ev, "id", None)
                skew_s = (
                    abs((ev_start - program.start_dt).total_seconds())
                    if ev_start is not None and program.start_dt is not None
                    else 0.0
                )
                logger.debug(
                    "[EPG_MATCH] tvg=%s stream='%s' prog='%s' @%s -> event=%s '%s' @%s (Δ=%dm)",
                    tvg_id,
                    stream_name[:32],
                    build_match_input(program)[:48],
                    program.start_dt.isoformat() if program.start_dt else "?",
                    ev_id or "?",
                    (getattr(ev, "short_name", None) or getattr(ev, "name", None) or "?")[:32],
                    ev_start.isoformat() if ev_start is not None else "?",
                    round(skew_s / 60),
                )
                # Keep the nearest-to-event program per event (live over pre-game).
                prev = best_by_event.get(ev_id)
                if prev is None or skew_s < prev[0]:
                    best_by_event[ev_id] = (
                        skew_s,
                        self._outcome_to_result(
                            outcome=outcome,
                            stream_id=stream_id,
                            stream_name=stream_name,
                            classified=classified,
                        ),
                    )

        results = [r for _, r in best_by_event.values()]
        if programs:
            logger.info(
                "[EPG_MATCH] tvg=%s stream='%s': %d program(s), %d attempted, "
                "%d non-event skipped, %d event(s) matched",
                tvg_id,
                stream_name[:32],
                len(programs),
                attempted,
                skipped_non_event,
                len(results),
            )
        return results

    def _reconcile_epg(
        self,
        name_results: list[MatchedStreamResult],
        epg_results: list[MatchedStreamResult],
        tvg_id: str,
    ) -> list[MatchedStreamResult]:
        """Reconcile stream-name matches with EPG matches for one stream.

        Policy (user-confirmed 2026-06-01):
        - LINEAR tvg_id (multiple programs/day) + EPG matched -> EPG results win
          (time-windowed); the linear name-match is unreliable and discarded.
        - LINEAR + no EPG match -> keep the name result (usually unmatched).
        - DEDICATED tvg_id -> keep the name match; EPG only fills in when the
          name found nothing (a static-named single-event stream).
        """
        epg_matched = [r for r in epg_results if r.matched]
        if self._epg_index.is_linear(tvg_id):
            return epg_matched if epg_matched else name_results
        name_matched = any(r.matched for r in name_results)
        if not name_matched and epg_matched:
            return epg_matched
        return name_results

    def _match_team_vs_team(
        self,
        classified: ClassifiedStream,
        stream_id: int,
        target_date: date,
        anchor_dt: "datetime | None" = None,
    ) -> MatchOutcome:
        """Match a team-vs-team stream."""
        # Determine effective stream timezone for date/time comparison
        # Priority: extracted TZ from stream > group setting > None (use user_tz as fallback)
        stream_tz = self._stream_tz
        if classified.normalized.extracted_tz:
            try:
                stream_tz = ZoneInfo(classified.normalized.extracted_tz)
            except (KeyError, ValueError):
                pass  # Keep group setting or None

        # Determine if single-league or multi-league matching
        if len(self._search_leagues) == 1:
            league = self._search_leagues[0]
            return self._team_matcher.match_single_league(
                classified=classified,
                league=league,
                target_date=target_date,
                group_id=self._group_id,
                stream_id=stream_id,
                generation=self._generation,
                user_tz=self._user_tz,
                sport_durations=self._sport_durations,
                stream_tz=stream_tz,
                anchor_dt=anchor_dt,
            )
        else:
            return self._team_matcher.match_multi_league(
                classified=classified,
                enabled_leagues=self._search_leagues,
                target_date=target_date,
                group_id=self._group_id,
                stream_id=stream_id,
                generation=self._generation,
                user_tz=self._user_tz,
                sport_durations=self._sport_durations,
                prefetched_events=self._prefetched_events,
                stream_tz=stream_tz,
                anchor_dt=anchor_dt,
            )

    def _match_team_only(
        self,
        classified: ClassifiedStream,
        stream_id: int,
        target_date: date,
        anchor_dt: "datetime | None" = None,
    ) -> list[MatchOutcome]:
        """Match a single-team branded stream, returning one outcome per matched event."""
        stream_tz = self._stream_tz
        if classified.normalized.extracted_tz:
            try:
                stream_tz = ZoneInfo(classified.normalized.extracted_tz)
            except (KeyError, ValueError):
                pass

        return self._team_matcher.match_team_only(
            classified=classified,
            enabled_leagues=list(self._include_leagues),
            target_date=target_date,
            group_id=self._group_id,
            stream_id=stream_id,
            generation=self._generation,
            user_tz=self._user_tz,
            sport_durations=self._sport_durations,
            prefetched_events=self._prefetched_events,
            stream_tz=stream_tz,
            anchor_dt=anchor_dt,
        )

    def _match_event_card(
        self,
        classified: ClassifiedStream,
        stream_id: int,
        target_date: date,
    ) -> MatchOutcome:
        """Match an event card stream (UFC, boxing)."""
        # Find the event card league in our search leagues
        event_card_leagues = [
            lg for lg in self._search_leagues if self._league_event_types.get(lg) == "event_card"
        ]

        if not event_card_leagues:
            return MatchOutcome.filtered(
                FilteredReason.LEAGUE_NOT_INCLUDED,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
                detail="No event card leagues configured",
            )

        # Try each event card league
        for league in event_card_leagues:
            outcome = self._event_matcher.match(
                classified=classified,
                league=league,
                target_date=target_date,
                group_id=self._group_id,
                stream_id=stream_id,
                generation=self._generation,
                user_tz=self._user_tz,
            )
            if outcome.is_matched:
                return outcome

        # No match in any event card league
        return MatchOutcome.failed(
            reason=outcome.failed_reason if outcome else None,
            stream_name=classified.normalized.original,
            stream_id=stream_id,
            detail="No matching event card found",
        )

    def _match_racing_event(
        self,
        classified: ClassifiedStream,
        stream_id: int,
        target_date: date,
    ) -> MatchOutcome:
        """Match a racing stream (F1, NASCAR, IndyCar, MotoGP, ...)."""
        # Find the racing leagues in our search leagues
        racing_leagues = [
            lg for lg in self._search_leagues if self._league_event_types.get(lg) == "event"
        ]

        if not racing_leagues:
            return MatchOutcome.filtered(
                FilteredReason.LEAGUE_NOT_INCLUDED,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
                detail="No racing leagues configured",
            )

        # Try each racing league
        outcome = None
        for league in racing_leagues:
            outcome = self._racing_matcher.match(
                classified=classified,
                league=league,
                target_date=target_date,
                group_id=self._group_id,
                stream_id=stream_id,
                generation=self._generation,
                user_tz=self._user_tz,
            )
            if outcome.is_matched:
                return outcome

        # No match in any racing league
        return MatchOutcome.failed(
            reason=outcome.failed_reason if outcome else None,
            stream_name=classified.normalized.original,
            stream_id=stream_id,
            detail="No matching racing event found",
        )

    def _outcome_to_result(
        self,
        outcome: MatchOutcome,
        stream_id: int,
        stream_name: str,
        classified: ClassifiedStream,
    ) -> MatchedStreamResult:
        """Convert MatchOutcome to MatchedStreamResult."""
        # Determine inclusion
        included = False
        exclusion_reason = None

        if outcome.is_matched and outcome.event:
            # Check if league is in include list
            if outcome.detected_league and outcome.detected_league in self._include_leagues:
                # Check if event is final
                if not self._include_final_events and is_event_final(outcome.event):
                    exclusion_reason = "event_final"
                else:
                    included = True
            else:
                exclusion_reason = f"league_not_included:{outcome.detected_league}"
        elif outcome.is_filtered:
            reason = outcome.filtered_reason.value if outcome.filtered_reason else "filtered"
            exclusion_reason = reason
        elif outcome.is_failed:
            reason = outcome.failed_reason.value if outcome.failed_reason else "failed"
            exclusion_reason = reason

        # Convert list hint to comma-separated string for storage
        league_hint = classified.league_hint
        detected_league_str = (
            ", ".join(league_hint) if isinstance(league_hint, list) else league_hint
        )

        return MatchedStreamResult(
            stream_name=stream_name,
            stream_id=stream_id,
            matched=outcome.is_matched,
            event=outcome.event,
            league=outcome.detected_league,
            included=included,
            exclusion_reason=exclusion_reason,
            match_method=outcome.match_method,
            confidence=outcome.confidence,
            from_cache=outcome.match_method == MatchMethod.CACHE if outcome.match_method else False,
            origin_match_method=outcome.origin_match_method,  # For cache hits
            category=classified.category,
            parsed_team1=classified.team1,
            parsed_team2=classified.team2,
            detected_league=detected_league_str,
            card_segment=classified.card_segment,  # UFC segment from stream name
            # Preserve detailed reason enums from MatchOutcome
            failed_reason=outcome.failed_reason,
            filtered_reason=outcome.filtered_reason,
            excluded_reason=outcome.excluded_reason,
            detail=outcome.detail,
            feed_hint=classified.feed_hint,
            epg_program_start=outcome.epg_program_start,
            epg_program_end=outcome.epg_program_end,
        )

    def _get_dominant_event_type(self) -> str | None:
        """Get the dominant event type from the group's configured leagues.

        Uses `_include_leagues` (the group's subscribed leagues) rather than
        `_search_leagues` (all known leagues, used for broad fuzzy matching).
        Otherwise the dominant type across ~300 leagues is always
        "team_vs_team", masking event-type leagues like racing/event_card.
        """
        if not self._league_event_types:
            return None

        # Count event types
        type_counts: dict[str, int] = {}
        for league in self._include_leagues:
            event_type = self._league_event_types.get(league, "team_vs_team")
            type_counts[event_type] = type_counts.get(event_type, 0) + 1

        # Return the most common type
        if type_counts:
            return max(type_counts, key=type_counts.get)
        return None

    def _load_league_event_types(self) -> None:
        """Load event types for all search leagues."""
        with self._db_factory() as conn:
            for league in self._search_leagues:
                league_info = get_league(conn, league)
                if league_info:
                    self._league_event_types[league] = league_info.get("event_type", "team_vs_team")

    def purge_stale(self) -> int:
        """Purge stale cache entries.

        Call at end of EPG run.

        Returns:
            Number of entries purged
        """
        return self._cache.purge_stale(self._generation)

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "generation": self._generation,
            "size": self._cache.get_size(),
            **self._cache.get_stats(),
        }
