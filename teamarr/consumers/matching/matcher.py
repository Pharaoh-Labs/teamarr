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
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.config import get_user_timezone
from teamarr.consumers.matching.classifier import (
    ClassifiedStream,
    CustomRegexConfig,
    StreamCategory,
    classify_stream,
    detect_racing_series_leagues,
    has_racing_text_evidence,
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
from teamarr.consumers.matching.tennis_matcher import TennisMatcher
from teamarr.consumers.racing_segments import nearest_session
from teamarr.consumers.stream_match_cache import (
    StreamMatchCache,
    get_generation_counter,
    increment_generation_counter,
)
from teamarr.core import Event
from teamarr.database.leagues import get_leagues_bulk
from teamarr.services import SportsDataService
from teamarr.utilities.event_status import is_event_final
from teamarr.utilities.fuzzy_match import normalize_text

logger = logging.getLogger(__name__)

# Concurrency for the event prefetch. Shares ESPN_MAX_WORKERS with the team
# scan and cache refresh so a user throttling DNS (PiHole, AdGuard) turns both
# down with one knob.
PREFETCH_MAX_WORKERS = int(os.environ.get("ESPN_MAX_WORKERS", 24))


@dataclass
class _PrefetchSlot:
    """One (league, date) cell of the prefetch window.

    Planning, fetching and assembly are three separate passes over these, so a
    slot carries both the decision made about it and the events that answered
    it. ``reused`` marks a slot already served from ``shared_events`` — it must
    not be written back, since it came from there.

    ``failed`` marks a slot whose fetch raised. Its empty ``events`` is an
    absence of knowledge, not an answer, so it must not be written back either:
    ``shared_events`` treats an empty-but-freshly-fetched entry as authoritative
    (``shared_events or not was_cache_only or ...``), so publishing one would
    silently blank that league/date for every later group in the run instead of
    letting them retry.
    """

    league: str
    fetch_date: date
    shared_key: str
    cache_only: bool
    is_tsdb: bool
    events: list[Event] = field(default_factory=list)
    reused: bool = False
    failed: bool = False


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
    # TEAM_ONLY (#489): which event side the branded team is ("home"/"away").
    # The lifecycle persists that side's team id per-stream for ordering rules.
    matched_side: str | None = None

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
        custom_regex_fighters: str | None = None,
        custom_regex_fighters_enabled: bool = False,
        custom_regex_event_name: str | None = None,
        custom_regex_event_name_enabled: bool = False,
        days_ahead: int | None = None,
        shared_events: dict[str, tuple[list[Event], bool]] | None = None,
        stream_timezone: str | None = None,
        feed_home_terms: list[str] | None = None,
        feed_away_terms: list[str] | None = None,
        name_match_enabled: bool = True,
        team_streams_enabled: bool = False,
        tennis_majors_only: bool = False,
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
            custom_regex_fighters: Custom regex for extracting fighter names (Combat/Event Card)
            custom_regex_fighters_enabled: Whether custom regex for fighters is enabled
            custom_regex_event_name: Custom regex for extracting the event/card name
            custom_regex_event_name_enabled: Whether custom regex for event name is enabled
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
            or (custom_regex_fighters_enabled and custom_regex_fighters)
            or (custom_regex_event_name_enabled and custom_regex_event_name)
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
                fighters_pattern=custom_regex_fighters,
                fighters_enabled=custom_regex_fighters_enabled,
                event_name_pattern=custom_regex_event_name,
                event_name_enabled=custom_regex_event_name_enabled,
            )
            if has_custom_regex
            else None
        )

        # Feed separation terms
        self._feed_home_terms = feed_home_terms
        self._feed_away_terms = feed_away_terms
        self._name_match_enabled = name_match_enabled
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
        self._tennis_matcher = TennisMatcher(
            service, self._cache, majors_only=tennis_majors_only
        )
        # EPG tennis programmes that could not be resolved to a matchup, per
        # tvg_id (mf7.9) — surfaced on the linear stream's result in
        # _reconcile_epg when nothing else matched.
        self._epg_tennis_unknown: dict[str, list[str]] = {}
        # Per-tvg_id summary of an EPG pass that attempted programmes but
        # matched none (#683) — surfaced as NO_EPG_PROGRAM_MATCH + detail on
        # the linear stream's failure row instead of the bare catch-all.
        # Keyed (not popped): mirrors of one linear channel share the tvg_id
        # and every one of them should carry the same diagnosis.
        self._epg_no_match: dict[str, str] = {}

        # League event types + sports cache
        self._league_event_types: dict[str, str] = {}
        self._league_sports: dict[str, str] = {}

        # Shared events cache (cross-matcher in a single generation run)
        # Keys are "league:date" strings, values are (events, was_cache_only) tuples
        self._shared_events = shared_events

        # Prefetched events (populated in match_all for multi-league matching)
        self._prefetched_events: dict[str, list[Event]] | None = None

        # EPG program index (epic teamarrv2-183). When present (group opted in
        # via 183.6), the matcher augments name matching with EPG-title matching
        # for streams carrying a tvg_id. None = no EPG matching (default).
        self._epg_index = epg_index

        # Per-run memo of EPG-title match plans keyed by tvg_id. Many streams
        # share one guide channel (726 streams / 89 tvg_ids on a typical
        # channel-source group), and the classify+route work depends only on
        # the tvg_id's program timeline — not the stream — so compute it once
        # and materialize per-stream results from the shared plan.
        self._epg_plan_by_tvg: dict[str, list[tuple[MatchOutcome, ClassifiedStream]]] = {}

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

        # Learn the source's date format from the whole batch (#474): the
        # custom date regex describes where the date lives; the batch shows
        # how it's formatted (one 16/07 proves the source is day-first).
        if self._custom_regex is not None:
            self._custom_regex.learn_date_format(
                s.get("name", "") for s in streams
            )

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
        # One DB connection for the whole batch's cache traffic (2-3 cache
        # round-trips per stream otherwise each open a fresh connection).
        with self._cache.session():
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
        # Rebuilt, never mutated in place. TeamMatcher memoizes its flattened
        # candidate lists against this dict's *identity* (_prefetched_candidates),
        # so mutating it after the fact would leave those memos serving stale
        # candidates for the rest of the batch. Replace the dict; don't edit it.
        self._prefetched_events = {}
        total_events = 0
        shared_hits = 0

        total_leagues = len(self._search_leagues)

        # Pass 1 (sequential): decide, for every league x date in the window,
        # whether the answer is already in shared_events or still has to be
        # fetched. Every shared_key is distinct, so no slot in this plan depends
        # on another's result — which is what makes pass 2 safe to parallelize.
        plan: list[list[_PrefetchSlot]] = []
        for league in self._search_leagues:
            is_tsdb = self._service.get_provider_name(league) == "tsdb"
            is_group_league = league in self._include_leagues
            slots: list[_PrefetchSlot] = []

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

                slot = _PrefetchSlot(
                    league=league,
                    fetch_date=fetch_date,
                    shared_key=shared_key,
                    cache_only=cache_only,
                    is_tsdb=is_tsdb,
                )

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
                        slot.events = shared_events
                        slot.reused = True
                        shared_hits += 1
                slots.append(slot)
            plan.append(slots)

        # Pass 2: fill the slots that still need a service call. Network-bound
        # fetches (cache_only=False) go out concurrently — the window is
        # ~11 dates deep per league, and serializing every one of them was the
        # single longest stretch of dead wall-clock time in a run. Cache-only
        # slots stay inline: they never touch the network, so a thread would
        # only add GIL hand-off to pure deserialization work.
        #
        # TSDB is excluded from the pool on purpose. Its client serializes on a
        # rate limiter that sleeps while holding its lock, so concurrent callers
        # would queue up inside that sleep rather than overlap — all the cost of
        # threads, none of the overlap.
        pending = [s for row in plan for s in row if not s.reused]
        concurrent_slots = [s for s in pending if not s.cache_only and not s.is_tsdb]
        inline_slots = [s for s in pending if s.cache_only or s.is_tsdb]

        service_calls = len(pending)

        def _record(slot: _PrefetchSlot, exc: Exception) -> None:
            """One slot's failure must neither kill the batch nor be cached."""
            logger.warning(
                "[PREFETCH] %s %s failed: %s", slot.league, slot.fetch_date, exc
            )
            slot.events = []
            slot.failed = True

        if concurrent_slots:
            workers = min(PREFETCH_MAX_WORKERS, len(concurrent_slots))
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="prefetch"
            ) as executor:
                futures = {
                    executor.submit(
                        self._service.get_events,
                        slot.league,
                        slot.fetch_date,
                        cache_only=slot.cache_only,
                    ): slot
                    for slot in concurrent_slots
                }
                for future in as_completed(futures):
                    slot = futures[future]
                    try:
                        slot.events = future.result()
                    except Exception as e:  # noqa: BLE001 - see _record
                        _record(slot, e)

        # Isolated per slot exactly like the concurrent path above. TSDB runs
        # here and is the flakiest fetch we make (rate-limited), so
        # letting it propagate would let one league take down the whole
        # prefetch for every other league.
        for slot in inline_slots:
            try:
                slot.events = self._service.get_events(
                    slot.league, slot.fetch_date, cache_only=slot.cache_only
                )
            except Exception as e:  # noqa: BLE001 - see _record
                _record(slot, e)

        # Pass 3 (sequential): assemble in league order and publish to
        # shared_events, exactly as the serial version did.
        for league_idx, (league, slots) in enumerate(
            zip(self._search_leagues, plan, strict=True)
        ):
            league_events: list[Event] = []
            for slot in slots:
                league_events.extend(slot.events)
                # Reused slots came FROM shared_events; failed slots know
                # nothing (see _PrefetchSlot). Neither is ours to publish.
                if self._shared_events is not None and not slot.reused and not slot.failed:
                    self._shared_events[slot.shared_key] = (slot.events, slot.cache_only)

            if league_events:
                self._prefetched_events[league] = league_events
                total_events += len(league_events)

            # Report progress periodically (every 20 leagues or at end)
            if status_callback and (league_idx % 20 == 0 or league_idx == total_leagues - 1):
                status_callback(
                    f"Prefetching events: {league_idx + 1}/{total_leagues} leagues "
                    f"({total_events} events, {shared_hits} reused)"
                )

        failed_slots = [s for s in pending if s.failed]
        if failed_slots:
            # One line to grep for during a dev soak: a burst here (429s from a
            # provider under the prefetch's concurrency) is the signal to turn
            # PREFETCH_MAX_WORKERS down.
            logger.warning(
                "[PREFETCH] %d/%d fetches failed and were NOT cached; "
                "affected leagues: %s",
                len(failed_slots),
                service_calls,
                ", ".join(sorted({s.league for s in failed_slots})),
            )

        logger.debug(
            f"Prefetched {total_events} events from {len(self._prefetched_events)} leagues "
            f"(window: -{MATCH_WINDOW_DAYS} to +{self._days_ahead} days, "
            f"shared_hits={shared_hits}, service_calls={service_calls}, "
            f"concurrent={len(concurrent_slots)}, failed={len(failed_slots)})"
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
        event_league_sport = self._get_event_league_sport()

        classified = classify_stream(
            stream_name, league_event_type, self._custom_regex,
            self._feed_home_terms, self._feed_away_terms,
            event_league_sport=event_league_sport,
        )

        # Step 2: Handle placeholders (streams that couldn't be classified)
        # Note: Placeholder pattern detection and unsupported sports filtering
        # is now handled by StreamFilter before streams reach the matcher.
        # This handles streams that passed filtering but still can't be classified
        # (e.g., no separator found, no custom regex match).
        if classified.category == StreamCategory.PLACEHOLDER:
            # A racing stream with a timestamp but no separator ("US (Peacock
            # 031) | IMSA CTMP Grand Prix (2026-07-12 14:00:00)") classifies
            # PLACEHOLDER — a date/time was extracted, so _classify_team_only
            # refuses it and nothing else fits. Give the racing fallback a
            # chance before writing it off as unclassifiable (same gate as
            # the TEAM_ONLY path below).
            if self._name_match_enabled:
                fallback = self._try_racing_fallback(stream_name, stream_id, target_date)
                if fallback is not None:
                    outcome, racing_classified = fallback
                    return [self._outcome_to_result(
                        outcome=outcome,
                        stream_id=stream_id,
                        stream_name=stream_name,
                        classified=racing_classified,
                    )]
            return [MatchedStreamResult(
                stream_name=stream_name,
                stream_id=stream_id,
                matched=False,
                included=False,
                category=StreamCategory.PLACEHOLDER,
                exclusion_reason="unclassifiable",
            )]

        # Step 3: Gate TEAM_ONLY when disabled, then route by category.
        if classified.category == StreamCategory.TEAM_ONLY and not self._team_streams_enabled:
            # A racing stream without a separator ("F1 | Monaco Grand Prix")
            # classifies TEAM_ONLY in a mixed group — give the racing
            # fallback a chance before dropping it. Racing-by-name is a
            # Stream Name matching type, so it stays gated on name_match.
            if self._name_match_enabled:
                fallback = self._try_racing_fallback(stream_name, stream_id, target_date)
                if fallback is not None:
                    outcome, racing_classified = fallback
                    return [self._outcome_to_result(
                        outcome=outcome,
                        stream_id=stream_id,
                        stream_name=stream_name,
                        classified=racing_classified,
                    )]
            return [MatchedStreamResult(
                stream_name=stream_name,
                stream_id=stream_id,
                matched=False,
                included=False,
                category=StreamCategory.PLACEHOLDER,
                exclusion_reason="team_streams_disabled",
            )]

        # Gate the name-identifies-event categories when Stream Name matching is
        # disabled for this source. TEAM_ONLY is gated above by Team matching; the
        # EPG path (program titles) is gated separately by epg_match_enabled.
        # Classification still runs so the other declared types can use it.
        if not self._name_match_enabled and classified.category in (
            StreamCategory.TEAM_VS_TEAM,
            StreamCategory.EVENT_CARD,
            StreamCategory.RACING_EVENT,
            StreamCategory.TENNIS_MATCH,
            StreamCategory.ALL_STAR,
        ):
            return [MatchedStreamResult(
                stream_name=stream_name,
                stream_id=stream_id,
                matched=False,
                included=False,
                category=StreamCategory.PLACEHOLDER,
                exclusion_reason="name_match_disabled",
            )]

        outcomes = self._route_to_outcomes(classified, stream_id, target_date)

        # Racing fallback for mixed groups (see _try_racing_fallback): the
        # primary route found nothing and the stream may be a racing stream
        # whose classification was masked by a team_vs_team-dominant group.
        # Gated on name_match: TEAM_ONLY routing runs even when Stream Name
        # matching is off, and racing-by-name must not sneak in through it.
        if (
            self._name_match_enabled
            and classified.category != StreamCategory.RACING_EVENT
            and not any(o.is_matched for o in outcomes)
        ):
            fallback = self._try_racing_fallback(stream_name, stream_id, target_date)
            if fallback is not None:
                outcome, racing_classified = fallback
                return [self._outcome_to_result(
                    outcome=outcome,
                    stream_id=stream_id,
                    stream_name=stream_name,
                    classified=racing_classified,
                )]

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
            return [self._match_racing_event(
                classified, stream_id, target_date, anchor_dt=anchor_dt
            )]
        if classified.category == StreamCategory.TENNIS_MATCH:
            return self._match_tennis_event(classified, stream_id, target_date)
        if classified.category == StreamCategory.TEAM_ONLY:
            return self._match_team_only(classified, stream_id, target_date, anchor_dt=anchor_dt)
        if classified.category == StreamCategory.ALL_STAR:
            return self._match_all_star(classified, stream_id, target_date, anchor_dt=anchor_dt)
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

        The heavy classify+route work over the guide channel's program timeline
        depends only on the tvg_id, so it is computed once per tvg_id per run
        (_compute_epg_plan) and shared by every stream carrying that tvg_id —
        mirrors of one linear channel would otherwise re-match the identical
        program list once per stream. Per-stream results are materialized from
        the shared plan. Only MATCHED outcomes are returned — non-games
        self-reject in the pipeline.
        """
        plan = self._epg_plan_by_tvg.get(tvg_id)
        if plan is None:
            plan = self._compute_epg_plan(tvg_id, target_date, stream_id, stream_name)
            self._epg_plan_by_tvg[tvg_id] = plan
        return [
            self._outcome_to_result(
                outcome=outcome,
                stream_id=stream_id,
                stream_name=stream_name,
                classified=classified,
            )
            for outcome, classified in plan
        ]

    def _compute_epg_plan(
        self,
        tvg_id: str,
        target_date: date,
        stream_id: int,
        stream_name: str,
    ) -> "list[tuple[MatchOutcome, ClassifiedStream]]":
        """Match a guide channel's program timeline to events, once per tvg_id.

        Walks every program on the tvg_id (from the injected EPGProgramIndex),
        feeds each program's title+sub_title through the SAME classify_stream ->
        TeamMatcher pipeline used for stream names, and keeps the best outcome
        per matched event (a linear channel legitimately matches MANY
        events/day). Each outcome carries the program's broadcast window for
        the lifecycle layer.

        stream_id/stream_name are the first carrier of this tvg_id — used only
        for the sub-matchers' cache keys and log context.
        """
        # Keyed by matched event id so that when several programs match the SAME
        # event (e.g. a pre-game block + the game itself both pass the anchor
        # gate), we keep only the one whose start is nearest the event — the live
        # broadcast — giving a deterministic, correctly-anchored window (bead
        # t5e). Different events on the same channel keep distinct keys. Racing
        # events key by (event id, session) instead — see the bucketing below.
        best_by_event: dict[object, tuple[float, MatchOutcome, ClassifiedStream]] = {}
        league_event_type = self._get_dominant_event_type()

        # Full sorted timeline for this tvg_id. A linear channel legitimately
        # matches many programs/day; each matched program's broadcast slot drives
        # its own attach/detach window in the lifecycle layer.
        programs = self._epg_index.programs_for(tvg_id) if self._epg_index is not None else []
        attempted = 0
        skipped_non_event = 0
        attempted_titles: list[str] = []
        for program in programs:
            if not should_attempt(program):
                skipped_non_event += 1
                continue
            attempted += 1

            epg_input = build_match_input(program)
            attempted_titles.append(epg_input)
            # NOTE: event_league_sport is deliberately NOT passed here. One
            # guide programme ("Wimbledon, Day 7") covers MANY concurrent
            # matches, so routing programme titles through the tennis
            # pipeline mass-matched arbitrary linear channels (2026-07-05:
            # match volume 166 -> 1,099 on the channel-source group, 252
            # bindings to one WTA tournament). Tennis programmes are only
            # those that classify TENNIS_MATCH on their own evidence (atp/wta
            # league hint or a "Tennis" sport hint) and they take the
            # dedicated programme path below (mf7.9, #642), which requires a
            # tournament AND a player pair or court before binding anything.
            classified = classify_stream(
                epg_input, league_event_type, self._custom_regex,
                self._feed_home_terms, self._feed_away_terms,
            )
            if classified.category == StreamCategory.PLACEHOLDER:
                continue
            if classified.category == StreamCategory.TENNIS_MATCH:
                for outcome in self._match_tennis_program(
                    program, classified, epg_input, stream_id, tvg_id
                ):
                    outcome.match_method = MatchMethod.EPG
                    outcome.epg_program_start = program.start_dt
                    outcome.epg_program_end = program.end_dt
                    ev_id = outcome.event.id if outcome.event else None
                    prev = best_by_event.get(ev_id)
                    skew_s = (
                        abs((outcome.event.start_time - program.start_dt).total_seconds())
                        if outcome.event is not None and program.start_dt is not None
                        else 0.0
                    )
                    if prev is None or skew_s < prev[0]:
                        best_by_event[ev_id] = (skew_s, outcome, classified)
                continue

            # Same text-evidence gate as the racing fallback, applied to the
            # PRIMARY classification too: in a racing-dominant group
            # _get_dominant_event_type() returns "event" directly, so this
            # classify_stream call already defaults arbitrary EPG titles
            # (documentaries, movies) to RACING_EVENT with no series name in
            # the text — the fallback's gate never even runs for these groups
            # since primary_outcomes already "succeeds". Without this check,
            # any program on any linear channel resolved into a racing-only
            # group can bind to "the one race happening this weekend" by date
            # coverage alone.
            if classified.category == StreamCategory.RACING_EVENT and not (
                has_racing_text_evidence(epg_input)
            ):
                logger.debug(
                    "[EPG_MATCH] racing programme skipped, no series name in text: %s",
                    epg_input[:60],
                )
                continue

            # TEAM_ONLY gate: skip team routing when disabled, but fall
            # through with no outcomes so the later fallbacks still get their
            # chance — racing (self-gated on event-type leagues + series-name
            # text evidence; "F1 | Monaco Grand Prix" classifies TEAM_ONLY in
            # a mixed group) and the description fallback (#540; a league-only
            # programme title like "Scottish Premiership Football" also
            # classifies TEAM_ONLY, but with the full matchup in the
            # description it is morally TEAM_VS_TEAM, so the team-streams
            # toggle must not gate it).
            if classified.category == StreamCategory.TEAM_ONLY and not self._team_streams_enabled:
                primary_outcomes: list[MatchOutcome] = []
            else:
                # Anchor matching to the program's own broadcast instant (bead t5e).
                # EPG titles carry no date/time, so a program would otherwise match
                # purely by team names — and a series game whose title repeats across
                # nights, or a post-game encore/replay, would bind to the wrong
                # occurrence and anchor its attach/detach window to the wrong slot.
                # The matcher gates candidate events to those airing within
                # ANCHOR_MATCH_TOLERANCE of this instant (live broadcast only).
                primary_outcomes = list(self._route_to_outcomes(
                    classified, stream_id, target_date, anchor_dt=program.start_dt
                ))

            # Pair each matched outcome with its effective classification so the
            # racing fallback (which re-classifies) can pass the right object to
            # _outcome_to_result without losing the RACING_EVENT category.
            matched_pairs: list[tuple[MatchOutcome, ClassifiedStream]] = [
                (o, classified) for o in primary_outcomes if o.is_matched
            ]

            # Racing fallback for mixed groups (see _try_racing_fallback).
            if not matched_pairs and classified.category != StreamCategory.RACING_EVENT:
                fallback = self._try_racing_fallback(
                    epg_input, stream_id, target_date, anchor_dt=program.start_dt
                )
                if fallback is not None:
                    matched_pairs.append(fallback)

            # Description fallback (#540): Sky-style guides title sports
            # programmes by competition ("Scottish Premiership Football") and
            # carry the matchup only in the description ("Celtic v Dundee FC
            # Following final day triumph..."). When the title yielded a
            # league hint but no team pair, look for exactly one league event
            # airing inside the programme window whose BOTH team names appear
            # in the description.
            if not matched_pairs:
                desc_outcome = self._try_description_match(program, classified, stream_id)
                if desc_outcome is not None:
                    matched_pairs.append((desc_outcome, classified))

            for outcome, eff_classified in matched_pairs:
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
                    epg_input[:48],
                    program.start_dt.isoformat() if program.start_dt else "?",
                    ev_id or "?",
                    (getattr(ev, "short_name", None) or getattr(ev, "name", None) or "?")[:32],
                    ev_start.isoformat() if ev_start is not None else "?",
                    round(skew_s / 60),
                )
                # Keep the nearest-to-event program per event (live over pre-game).
                # Racing weekends are the exception: the guide carries one
                # programme per SESSION (FP1, Qualifying, Race, ...) and every
                # one of them matches the same event — keyed by event id alone
                # they'd collapse to a single entry/window and the weekend's
                # other session channels would never see this stream. Bucket
                # racing programmes by (event, nearest session) instead, with
                # skew measured against that session so "live over pre-game"
                # still holds within each bucket.
                key: object = ev_id
                if (
                    ev is not None
                    and getattr(ev, "sessions", None)
                    and program.start_dt is not None
                ):
                    s_code, s_dist = nearest_session(
                        ev, program.start_dt, self._sport_durations
                    )
                    if s_code is not None:
                        key = (ev_id, s_code)
                        skew_s = s_dist
                prev = best_by_event.get(key)
                if prev is None or skew_s < prev[0]:
                    best_by_event[key] = (skew_s, outcome, eff_classified)

        plan = [(o, c) for _, o, c in best_by_event.values()]
        if programs and not plan:
            # Nothing on this guide channel bound to an event — record what
            # the pass actually saw so the failure row is diagnosable (#683).
            sample = " | ".join(t[:60] for t in attempted_titles[:3])
            self._epg_no_match[tvg_id] = (
                f"EPG: {len(programs)} programme(s) in window, {attempted} attempted, "
                f"{skipped_non_event} non-event"
                + (f"; e.g. {sample}" if sample else "")
            )
        if programs:
            tennis_unknown = len(self._epg_tennis_unknown.get(tvg_id, ()))
            logger.info(
                "[EPG_MATCH] tvg=%s (via stream '%s'): %d program(s), %d attempted, "
                "%d non-event skipped, %d event(s) matched%s",
                tvg_id,
                stream_name[:32],
                len(programs),
                attempted,
                skipped_non_event,
                len(plan),
                f", {tennis_unknown} tennis matchup(s) not known" if tennis_unknown else "",
            )
        return plan

    def _match_tennis_program(
        self,
        program,
        classified: ClassifiedStream,
        epg_input: str,
        stream_id: int,
        tvg_id: str,
    ) -> list[MatchOutcome]:
        """Tennis EPG programme → matched outcomes (mf7.9, #642).

        Feeds title + sub_title + description to TennisMatcher.match_program;
        a TENNIS_MATCHUP_UNKNOWN failure is recorded per tvg_id so the linear
        stream's result can carry it when nothing else matches.
        """
        tennis_leagues = [
            lg
            for lg in self._search_leagues
            if self._league_event_types.get(lg) == "event"
            and self._league_sports.get(lg) == "tennis"
        ]
        if not tennis_leagues or program.start_dt is None or program.end_dt is None:
            return []
        description = (program.description or "").strip()
        program_text = f"{epg_input} | {description}" if description else epg_input
        outcomes = self._tennis_matcher.match_program(
            classified=classified,
            program_text=program_text,
            leagues=tennis_leagues,
            program_start=program.start_dt,
            program_end=program.end_dt,
            stream_id=stream_id,
            user_tz=self._user_tz,
            duration_hours=self._sport_durations.get("tennis", 3.0),
        )
        matched = [o for o in outcomes if o.is_matched]
        if not matched:
            detail = next((o.detail for o in outcomes if o.detail), "") or "matchup not known"
            self._epg_tennis_unknown.setdefault(tvg_id, []).append(f"{epg_input[:48]}: {detail}")
            logger.debug("[EPG_MATCH] tennis matchup not known: %s — %s", epg_input[:60], detail)
        return matched

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
        name_matched = any(r.matched for r in name_results)
        if not epg_matched and not name_matched:
            # The stream will persist as a failure — say what the EPG pass
            # actually saw (#683) instead of the bare catch-all. Only rows
            # without a real failure/filter verdict are upgraded: a name-path
            # NO_EVENT_FOUND with near-miss detail is more specific and wins.
            # .get, not .pop: mirrors sharing the tvg_id all get the reason.
            unknown = self._epg_tennis_unknown.get(tvg_id)
            no_match = self._epg_no_match.get(tvg_id)
            for r in name_results:
                if r.failed_reason is not None or r.filtered_reason is not None:
                    continue
                if unknown:
                    # Tennis programmes with no resolvable matchup (mf7.9):
                    # the guide DID carry tennis, it just didn't say which
                    # match. A real FailedReason now — the old exclusion_reason
                    # overwrite persisted as bare "unmatched" (#683).
                    r.failed_reason = FailedReason.TENNIS_MATCHUP_UNKNOWN
                    r.detail = "; ".join(unknown[:3])
                elif no_match:
                    r.failed_reason = FailedReason.NO_EPG_PROGRAM_MATCH
                    r.detail = no_match
        if self._epg_index is not None and self._epg_index.is_linear(tvg_id):
            return epg_matched if epg_matched else name_results
        if not name_matched and epg_matched:
            return epg_matched
        return name_results

    def _try_description_match(
        self,
        program,
        classified: ClassifiedStream,
        stream_id: int,
    ) -> MatchOutcome | None:
        """EPG description fallback (#540).

        Sky-style guides title sports programmes by competition ("Scottish
        Premiership Football") with no sub_title; the matchup lives only in
        the description prose. Prose can't go through classify_stream (no
        reliable terminator after "Celtic v Dundee FC Following final day
        triumph..."), so instead of parsing it we verify against known
        events: the classification must carry a league hint, and exactly ONE
        event in the hinted league(s) may both air inside the programme's
        broadcast window AND have BOTH team names present in the description.
        Zero or multiple candidates -> no match (conservative by design:
        never bind on partial or ambiguous evidence).
        """
        description = program.description or ""
        if not description.strip():
            return None
        # The title/sub_title path already extracted a team pair — it had
        # its shot; this fallback is only for league-only programme titles.
        if classified.team1 and classified.team2:
            return None
        hint = classified.league_hint
        hint_leagues = [hint] if isinstance(hint, str) else list(hint or [])
        leagues = [
            lg
            for lg in hint_leagues
            if lg in self._include_leagues and self._league_sports.get(lg) != "tennis"
        ]
        if not leagues:
            # No league hint — scope by the title's sport hint instead
            # ("Scottish Premiership Football" carries a built-in Soccer/
            # Football hint but the league name is often only a user-defined
            # keyword). A hint of SOME kind is required: it anchors "this is
            # a sports programme about this competition" before we go
            # verifying prose against events.
            sport_hint = classified.sport_hint
            if not sport_hint:
                return None
            sports = {
                s.lower()
                for s in ([sport_hint] if isinstance(sport_hint, str) else sport_hint)
            }
            leagues = [
                lg
                for lg in self._include_leagues
                if self._league_sports.get(lg, "").lower() in sports
                and self._league_sports.get(lg) != "tennis"
            ]
        if not leagues:
            return None
        start_dt, end_dt = program.start_dt, program.end_dt
        if start_dt is None or end_dt is None:
            return None

        desc_norm = normalize_text(description)

        def _in_desc(team) -> bool:
            for form in (team.name, team.short_name):
                form_norm = normalize_text(form or "")
                if len(form_norm) >= 3 and re.search(
                    rf"\b{re.escape(form_norm)}\b", desc_norm
                ):
                    return True
            return False

        candidates: list[tuple[str, Event]] = []
        for league in leagues:
            events = None
            if self._prefetched_events is not None:
                events = self._prefetched_events.get(league)
            if events is None:
                # Single-league groups skip the prefetch — fetch the
                # programme-window dates directly (cache-backed).
                events = []
                dates = {
                    start_dt.astimezone(self._user_tz).date(),
                    end_dt.astimezone(self._user_tz).date(),
                }
                for d in dates:
                    events.extend(self._service.get_events(league, d))
            for event in events:
                ev_start = event.start_time
                if ev_start is None or not (start_dt <= ev_start <= end_dt):
                    continue
                if _in_desc(event.home_team) and _in_desc(event.away_team):
                    candidates.append((league, event))

        if len(candidates) != 1:
            if len(candidates) > 1:
                logger.debug(
                    "[EPG_MATCH] description fallback ambiguous (%d candidates) "
                    "for prog '%s'",
                    len(candidates),
                    (program.title or "")[:48],
                )
            return None

        league, event = candidates[0]
        logger.info(
            "[EPG_MATCH] description fallback: prog '%s' -> event=%s '%s' (%s)",
            (program.title or "")[:48],
            event.id,
            (event.short_name or event.name or "?")[:40],
            league,
        )
        return MatchOutcome.matched(
            MatchMethod.EPG,
            event,
            detected_league=league,
            confidence=0.9,
            stream_name=classified.normalized.original,
            stream_id=stream_id,
        )

    def _non_tennis_leagues(self, leagues: list[str]) -> list[str]:
        """Drop tennis leagues from a generic team-matching candidate pool.

        Tennis events are player-vs-player, so through the TEAM_ONLY /
        TEAM_VS_TEAM paths arbitrary text sharing a surname can fuzzy-bind to
        them ("Good Day Chicago" -> "Kayla Day vs Diane Parry", #541) —
        bypassing both the tennis-EPG skip (mf7.9) and the tennis_majors_only
        filter, which only the tennis pipeline enforces. Tennis events must
        stay reachable solely via TENNIS_MATCH -> TennisMatcher.
        """
        return [lg for lg in leagues if self._league_sports.get(lg) != "tennis"]

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

        search_leagues = self._non_tennis_leagues(self._search_leagues)
        if not search_leagues:
            return MatchOutcome.filtered(
                FilteredReason.LEAGUE_NOT_INCLUDED,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
                detail="No non-tennis leagues configured for team matching",
            )

        # Determine if single-league or multi-league matching
        if len(search_leagues) == 1:
            league = search_leagues[0]
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
                enabled_leagues=search_leagues,
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
            enabled_leagues=self._non_tennis_leagues(list(self._include_leagues)),
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

    def _match_all_star(
        self,
        classified: ClassifiedStream,
        stream_id: int,
        target_date: date,
        anchor_dt: "datetime | None" = None,
    ) -> list[MatchOutcome]:
        """Match a league All-Star stream to that league's All-Star event."""
        stream_tz = self._stream_tz
        if classified.normalized.extracted_tz:
            try:
                stream_tz = ZoneInfo(classified.normalized.extracted_tz)
            except (KeyError, ValueError):
                pass

        return self._team_matcher.match_all_star(
            classified=classified,
            enabled_leagues=self._non_tennis_leagues(list(self._include_leagues)),
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
        anchor_dt: "datetime | None" = None,
    ) -> MatchOutcome:
        """Match a racing stream (F1, NASCAR, IndyCar, MotoGP, ...).

        anchor_dt (EPG path only): the program's broadcast instant — candidate
        events are gated to those with a session actually airing near it.
        """
        # Find the racing leagues in our search leagues. The "event" type is
        # shared with tennis/golf, so exclude leagues whose sport is known to
        # be something else (unknown sport = legacy racing behavior).
        racing_leagues = [
            lg
            for lg in self._search_leagues
            if self._league_event_types.get(lg) == "event"
            and self._league_sports.get(lg, "racing") == "racing"
        ]

        if not racing_leagues:
            return MatchOutcome.filtered(
                FilteredReason.LEAGUE_NOT_INCLUDED,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
                detail="No racing leagues configured",
            )

        # Series scoping: when the stream text explicitly names a series
        # (MotoGP, NASCAR, ...), only that series' league(s) are eligible.
        # Without this, a stream for an unconfigured series carries racing
        # text evidence, reaches the racing matcher, and date-binds to
        # whatever configured series races that weekend ("MotoGP - Grand
        # Prix of Germany" direct-matched IMSA's Chevrolet Grand Prix via
        # the shared "Grand Prix" tokens). Generic racing text (a bare
        # "Monaco Grand Prix") names no series and stays unscoped.
        named_leagues = detect_racing_series_leagues(classified.normalized.original)
        if named_leagues:
            scoped = [lg for lg in racing_leagues if lg in named_leagues]
            if not scoped:
                return MatchOutcome.failed(
                    reason=FailedReason.NO_RACING_MATCH,
                    stream_name=classified.normalized.original,
                    stream_id=stream_id,
                    detail=(
                        "Stream names a racing series with no configured league "
                        f"({', '.join(named_leagues)})"
                    ),
                )
            racing_leagues = scoped

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
                anchor_dt=anchor_dt,
                sport_durations=self._sport_durations,
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

    def _try_racing_fallback(
        self,
        text: str,
        stream_id: int,
        target_date: date,
        anchor_dt: "datetime | None" = None,
    ) -> "tuple[MatchOutcome, ClassifiedStream] | None":
        """Racing fallback for mixed groups (#349): re-classify as racing and retry.

        In a group where team-sport leagues dominate, the dominant
        league_event_type is "team_vs_team", so a racing stream like
        "Formula 1 | Monaco Grand Prix" (TEAM_ONLY) or "NASCAR Cup Series |
        at San Diego" (TEAM_VS_TEAM) never classifies RACING_EVENT on the
        primary pass. When the primary route found nothing and the group
        includes event-type leagues, re-classify with
        league_event_type="event" to see if it reads as a racing stream.

        Requires TEXT evidence of racing (a series name in the input), not
        just the RACING_EVENT category. With league_event_type="event",
        racing is the classifier's default bucket for anything unrecognized —
        fine inside a curated racing group, but EPG programmes are arbitrary
        TV (documentaries, movies), and the racing matcher's date-coverage
        strategy then binds them to whatever race covers the date
        ("Brimstone" fuzzy-matched Silverstone at 62).

        Shared by the stream-name path (_match_single) and the EPG-title
        path (_match_via_epg). Returns the matched outcome paired with its
        racing classification, or None if the fallback doesn't apply/match.
        """
        if not any(
            self._league_event_types.get(lg) == "event"
            for lg in self._include_leagues
        ):
            return None
        if not has_racing_text_evidence(text):
            return None

        racing_classified = classify_stream(
            text, "event", self._custom_regex,
            self._feed_home_terms, self._feed_away_terms,
        )
        if racing_classified.category != StreamCategory.RACING_EVENT:
            return None

        outcome = self._match_racing_event(
            racing_classified, stream_id, target_date, anchor_dt=anchor_dt
        )
        if not outcome.is_matched:
            return None
        return outcome, racing_classified

    def _match_tennis_event(
        self,
        classified: ClassifiedStream,
        stream_id: int,
        target_date: date,
    ) -> list[MatchOutcome]:
        """Match a tennis stream (ATP, WTA).

        Player-pair streams ("Zheng vs Norrie") match ONE event; court/round
        day-feeds ("Day #6 No 1 Court") fan out to every match on that
        court/round for the day (one outcome per match, each carrying its own
        time-share window — mirrors the TEAM_ONLY/EPG fan-out shape).
        """
        tennis_leagues = [
            lg
            for lg in self._search_leagues
            if self._league_event_types.get(lg) == "event"
            and self._league_sports.get(lg) == "tennis"
        ]

        if not tennis_leagues:
            return [MatchOutcome.filtered(
                FilteredReason.LEAGUE_NOT_INCLUDED,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
                detail="No tennis leagues configured",
            )]

        # Court/round feeds: no player pair — fan out across ALL tennis
        # leagues at once (a court hosts both tours' draws).
        if not (classified.team1 and classified.team2):
            return self._tennis_matcher.match_feed(
                classified=classified,
                leagues=tennis_leagues,
                target_date=target_date,
                stream_id=stream_id,
                user_tz=self._user_tz,
                duration_hours=self._sport_durations.get("tennis", 3.0),
            )

        outcome = None
        for league in tennis_leagues:
            outcome = self._tennis_matcher.match(
                classified=classified,
                league=league,
                target_date=target_date,
                group_id=self._group_id,
                stream_id=stream_id,
                generation=self._generation,
                user_tz=self._user_tz,
            )
            if outcome.is_matched:
                return [outcome]

        return [MatchOutcome.failed(
            reason=outcome.failed_reason if outcome else None,
            stream_name=classified.normalized.original,
            stream_id=stream_id,
            detail=outcome.detail if outcome else "No matching tennis match found",
        )]

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
            matched_side=outcome.matched_side,
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
            return max(type_counts, key=lambda k: type_counts[k])
        return None

    def _load_league_event_types(self) -> None:
        """Load event types and sports for all search leagues (one bulk query)."""
        with self._db_factory() as conn:
            leagues_info = get_leagues_bulk(conn, list(self._search_leagues))
        for league in self._search_leagues:
            league_info = leagues_info.get(league.lower())
            if league_info:
                self._league_event_types[league] = league_info.get("event_type", "team_vs_team")
                sport = league_info.get("sport")
                if sport:
                    self._league_sports[league] = sport

    def _get_event_league_sport(self) -> str | None:
        """Dominant sport among the group's event-type leagues.

        The "event" league type is shared by all tournament sports (racing,
        tennis, golf); the classifier needs the sport to route between the
        RACING_EVENT and TENNIS_MATCH paths. Uses `_include_leagues` for the
        same reason as _get_dominant_event_type.
        """
        sport_counts: dict[str, int] = {}
        for league in self._include_leagues:
            if self._league_event_types.get(league) != "event":
                continue
            sport = self._league_sports.get(league)
            if sport:
                sport_counts[sport] = sport_counts.get(sport, 0) + 1

        if sport_counts:
            return max(sport_counts, key=lambda k: sport_counts[k])
        return None

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
