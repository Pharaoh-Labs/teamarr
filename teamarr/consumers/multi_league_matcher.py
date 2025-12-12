"""Multi-league stream matcher.

Uses Events → Streams approach:
1. Fetch all events from configured leagues
2. Generate search patterns from event data (team names, abbreviations)
3. For each stream, find events whose patterns appear in the stream name

This is more robust than parsing stream names because:
- We know exact team names/abbreviations from the provider
- Don't rely on parser correctly extracting from messy stream names
- Uses fuzzy matching for better tolerance of name variations
"""

from dataclasses import dataclass
from datetime import date

from teamarr.core import Event
from teamarr.services import SportsDataService
from teamarr.utilities.fuzzy_match import FuzzyMatcher, get_matcher


@dataclass
class StreamMatchResult:
    """Result of matching a single stream."""

    stream_name: str

    # Match outcome
    matched: bool
    event: Event | None = None
    league: str | None = None

    # Inclusion decision
    included: bool = False
    exclusion_reason: str | None = None

    # Exception handling
    exception_keyword: str | None = None

    @property
    def is_exception(self) -> bool:
        return self.exception_keyword is not None


@dataclass
class BatchMatchResult:
    """Result of matching a batch of streams."""

    results: list[StreamMatchResult]
    target_date: date
    leagues_searched: list[str]
    include_leagues: list[str]
    events_found: int

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def matched_count(self) -> int:
        return sum(1 for r in self.results if r.matched)

    @property
    def included_count(self) -> int:
        return sum(1 for r in self.results if r.included)

    @property
    def excluded_count(self) -> int:
        return sum(1 for r in self.results if r.matched and not r.included)

    @property
    def unmatched_count(self) -> int:
        return sum(1 for r in self.results if not r.matched and not r.is_exception)

    @property
    def exception_count(self) -> int:
        return sum(1 for r in self.results if r.is_exception)

    @property
    def match_rate(self) -> float:
        non_exception = self.total - self.exception_count
        if non_exception == 0:
            return 0.0
        return self.matched_count / non_exception


@dataclass
class EventPatterns:
    """Search patterns generated from an event."""

    event: Event
    league: str
    # Patterns to find BOTH of (for team_vs_team)
    home_patterns: list[str]
    away_patterns: list[str]
    # Patterns to find ANY of (for event name)
    event_patterns: list[str]


class MultiLeagueMatcher:
    """Matches streams to events using Events → Streams approach."""

    def __init__(
        self,
        service: SportsDataService,
        search_leagues: list[str],
        include_leagues: list[str] | None = None,
        exception_keywords: list[str] | None = None,
        fuzzy_matcher: FuzzyMatcher | None = None,
    ):
        self._service = service
        self._search_leagues = search_leagues
        self._include_leagues = set(include_leagues) if include_leagues else None
        self._exception_keywords = [kw.lower() for kw in (exception_keywords or [])]
        self._fuzzy = fuzzy_matcher or get_matcher()

        # Built during match_all
        self._event_patterns: list[EventPatterns] = []
        self._patterns_date: date | None = None

    def match_all(
        self, stream_names: list[str], target_date: date
    ) -> BatchMatchResult:
        """Match all streams against events from configured leagues."""
        # Build event patterns for target date
        self._build_event_patterns(target_date)

        # Match each stream
        results = [self._match_stream(name) for name in stream_names]

        return BatchMatchResult(
            results=results,
            target_date=target_date,
            leagues_searched=self._search_leagues,
            include_leagues=(
                list(self._include_leagues) if self._include_leagues else self._search_leagues
            ),
            events_found=len(self._event_patterns),
        )

    def _build_event_patterns(self, target_date: date) -> None:
        """Build search patterns from all events."""
        if self._patterns_date == target_date:
            return

        self._event_patterns = []

        for league in self._search_leagues:
            events = self._service.get_events(league, target_date)
            for event in events:
                patterns = self._generate_patterns(event, league)
                self._event_patterns.append(patterns)

        self._patterns_date = target_date

    def _generate_patterns(self, event: Event, league: str) -> EventPatterns:
        """Generate search patterns from an event using fuzzy matcher."""
        # Use fuzzy matcher to generate patterns (includes mascot stripping)
        home_patterns = self._fuzzy.generate_team_patterns(event.home_team)
        away_patterns = self._fuzzy.generate_team_patterns(event.away_team)

        # Event name patterns
        event_patterns = self._unique_patterns([
            event.name,
            event.short_name,
        ])

        return EventPatterns(
            event=event,
            league=league,
            home_patterns=home_patterns,
            away_patterns=away_patterns,
            event_patterns=event_patterns,
        )

    def _unique_patterns(self, values: list[str]) -> list[str]:
        """Normalize and dedupe patterns."""
        seen = set()
        result = []
        for v in values:
            if v:
                lower = v.lower()
                if lower not in seen and len(lower) >= 2:
                    seen.add(lower)
                    result.append(lower)
        return result

    def _match_stream(self, stream_name: str) -> StreamMatchResult:
        """Match a stream against all event patterns."""
        stream_lower = stream_name.lower()

        # Check for exception keyword
        for keyword in self._exception_keywords:
            if keyword in stream_lower:
                return StreamMatchResult(
                    stream_name=stream_name,
                    matched=False,
                    exception_keyword=keyword,
                    exclusion_reason="exception",
                )

        # Find matching event
        event, league = self._find_matching_event(stream_lower)

        if not event:
            return StreamMatchResult(
                stream_name=stream_name,
                matched=False,
                exclusion_reason="unmatched",
            )

        # Check whitelist
        included = self._is_league_included(league)

        return StreamMatchResult(
            stream_name=stream_name,
            matched=True,
            event=event,
            league=league,
            included=included,
            exclusion_reason=None if included else "league_not_in_whitelist",
        )

    def _find_matching_event(
        self, stream_lower: str
    ) -> tuple[Event | None, str | None]:
        """Find event that matches the stream name using fuzzy matching."""
        # First pass: try to find both teams using fuzzy matching
        for ep in self._event_patterns:
            home_match = self._fuzzy.matches_any(ep.home_patterns, stream_lower)
            away_match = self._fuzzy.matches_any(ep.away_patterns, stream_lower)

            if home_match.matched and away_match.matched:
                return ep.event, ep.league

        # Fallback: try event name matching
        for ep in self._event_patterns:
            event_match = self._fuzzy.matches_any(ep.event_patterns, stream_lower)
            if event_match.matched:
                return ep.event, ep.league

        return None, None

    def _is_league_included(self, league: str) -> bool:
        """Check if league is in the include whitelist."""
        if self._include_leagues is None:
            return True
        return league in self._include_leagues
