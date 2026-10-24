"""Context builder for template resolution.

Assembles TemplateContext from Event/Team data using SportsDataService.
This is the bridge between the data layer and the template engine.
"""

import logging
from dataclasses import replace
from datetime import datetime

from teamarr.core import Event, TeamStats
from teamarr.services.sports_data import SportsDataService
from teamarr.templates.context import (
    GameContext,
    Odds,
    TeamChannelContext,
    TemplateContext,
)
from teamarr.utilities.sports import get_sport_from_league

logger = logging.getLogger(__name__)


def segment_start_time(event: Event, segment: str | None) -> datetime | None:
    """The start of the session or card segment a segment channel covers.

    A race weekend (or a cricket Test) is one Event whose `sessions[]` each
    get their own channel; an MMA card is one Event whose `segment_times`
    carry ESPN's per-segment starts. `event.start_time` is the weekend's or
    card's FIRST start, so a context built for one segment must read that
    segment's own start, or `{game_time}` / `{game_day_short}` in a session
    channel's name print Practice 1's time on every channel while the guide
    (which swaps the start in before resolving) shows each session's own
    (#1148). A code that repeats on the weekend (three `race` runnings)
    shares one channel, which starts at the earliest running (same rule as
    the lifecycle timing). None when `segment` names nothing on the event.
    """
    if not segment:
        return None
    sessions = [s for s in event.sessions or [] if s.code == segment and s.start_time]
    if sessions:
        return min(s.start_time for s in sessions)
    return (event.segment_times or {}).get(segment)


class ContextBuilder:
    """Builds TemplateContext from events and team configuration.

    Usage:
        builder = ContextBuilder(sports_service)
        context = builder.build_for_event(
            event=event,
            team_id="8",
            league="nfl",
        )
        # Use context with TemplateResolver
    """

    def __init__(self, sports_service: SportsDataService):
        self._service = sports_service
        # Cache for team stats to avoid redundant API calls
        self._stats_cache: dict[tuple[str, str], TeamStats | None] = {}

    def build_for_event(
        self,
        event: Event,
        team_id: str,
        league: str,
        team_stats: TeamStats | None = None,
        next_event: Event | None = None,
        last_event: Event | None = None,
        card_segment: str | None = None,
    ) -> TemplateContext:
        """Build complete template context for an event.

        Args:
            event: The current game/event
            team_id: ID of the team this context is for
            league: League identifier
            team_stats: Pre-fetched team stats (optional, will fetch if None)
            next_event: Next scheduled game (optional)
            last_event: Last completed game (optional)
            card_segment: UFC card segment code (early_prelims, prelims, main_card)

        Returns:
            Complete TemplateContext ready for template resolution
        """
        # Get team info from event
        is_home = event.home_team.id == team_id
        team = event.home_team if is_home else event.away_team

        # Build team config - use event.sport (provider is authoritative)
        team_config = TeamChannelContext(
            team_id=team_id,
            league=league,
            sport=event.sport,
            team_name=team.name,
            team_abbrev=team.abbreviation,
            team_short_name=team.short_name,
        )

        # Fetch team stats if not provided
        if team_stats is None:
            team_stats = self._get_team_stats(team_id, league)

        # Build game context for current event
        game_context = self._build_game_context(
            event=event,
            team_id=team_id,
            league=league,
            card_segment=card_segment,
        )

        # Build contexts for next/last games if provided
        next_game = None
        if next_event:
            next_game = self._build_game_context(
                event=next_event,
                team_id=team_id,
                league=league,
            )

        last_game = None
        if last_event:
            last_game = self._build_game_context(
                event=last_event,
                team_id=team_id,
                league=league,
            )

        return TemplateContext(
            game_context=game_context,
            team_config=team_config,
            team_stats=team_stats,
            team=team,
            next_game=next_game,
            last_game=last_game,
        )

    def build_minimal(
        self,
        team_id: str,
        league: str,
        team_name: str,
        team_abbrev: str | None = None,
        team_short_name: str | None = None,
    ) -> TemplateContext:
        """Build minimal context without game info.

        Useful for non-game content or when event data isn't available.
        """
        team_config = TeamChannelContext(
            team_id=team_id,
            league=league,
            sport=self._get_sport(league),
            team_name=team_name,
            team_abbrev=team_abbrev,
            team_short_name=team_short_name,
        )

        team_stats = self._get_team_stats(team_id, league)

        return TemplateContext(
            game_context=None,
            team_config=team_config,
            team_stats=team_stats,
        )

    def _build_game_context(
        self,
        event: Event,
        team_id: str,
        league: str,
        card_segment: str | None = None,
    ) -> GameContext:
        """Build GameContext for a single event."""
        # Days-ahead structured preview (tvnk.15): the service gates this to
        # future events within its lookahead, serves a per-event cache, and
        # enforces a fetch budget — a no-op for past/imminent/enriched events.
        event = self._service.enrich_event_preview(event)

        # A segment channel's context is anchored to its own segment's start
        # (#1148) — see segment_start_time. Every reader of this context
        # (channel name, logo URL, conditions, the sync rename, the guide)
        # then agrees on what "the game time" is for that channel.
        segment_start = segment_start_time(event, card_segment)
        if segment_start is not None and segment_start != event.start_time:
            event = replace(event, start_time=segment_start)

        is_home = event.home_team.id == team_id
        team = event.home_team if is_home else event.away_team
        opponent = event.away_team if is_home else event.home_team

        # Fetch opponent stats
        opponent_stats = self._get_team_stats(opponent.id, league)

        # Convert odds data to Odds dataclass
        odds = self._build_odds(event.odds_data, is_home) if event.odds_data else None

        return GameContext(
            event=event,
            is_home=is_home,
            team=team,
            opponent=opponent,
            opponent_stats=opponent_stats,
            odds=odds,
            card_segment=card_segment,
        )

    def _build_odds(self, odds_data: dict, is_home: bool) -> Odds:
        """Convert raw odds dict to Odds dataclass.

        Adjusts moneylines based on whether our team is home or away.
        """
        # Determine our moneyline vs opponent's based on home/away
        if is_home:
            team_ml = odds_data.get("home_moneyline") or 0
            opp_ml = odds_data.get("away_moneyline") or 0
        else:
            team_ml = odds_data.get("away_moneyline") or 0
            opp_ml = odds_data.get("home_moneyline") or 0

        return Odds(
            provider=odds_data.get("provider", ""),
            spread=abs(odds_data.get("spread", 0.0)),  # Absolute value
            over_under=odds_data.get("over_under", 0.0),
            details=odds_data.get("details", ""),
            team_moneyline=team_ml,
            opponent_moneyline=opp_ml,
        )

    def _get_team_stats(self, team_id: str, league: str) -> TeamStats | None:
        """Get team stats with caching."""
        cache_key = (team_id, league)
        if cache_key not in self._stats_cache:
            try:
                self._stats_cache[cache_key] = self._service.get_team_stats(team_id, league)
            except Exception as e:
                logger.warning("[CONTEXT] Failed to fetch stats for team %s: %s", team_id, e)
                self._stats_cache[cache_key] = None
        return self._stats_cache[cache_key]

    def _get_sport(self, league: str) -> str:
        """Derive sport from league identifier (fallback).

        Prefer using event.sport or team.sport when available.
        This is only used when no Event is available (e.g., build_minimal).
        """
        return get_sport_from_league(league)

    def clear_cache(self) -> None:
        """Clear the stats cache."""
        self._stats_cache.clear()


def build_context_for_event(
    event: Event,
    team_id: str,
    league: str,
    sports_service: SportsDataService,
) -> TemplateContext:
    """Convenience function to build context for a single event.

    For batch processing, use ContextBuilder directly to benefit from caching.
    """
    builder = ContextBuilder(sports_service)
    return builder.build_for_event(event, team_id, league)


def find_adjacent_games(
    events: list[Event],
    current_event: Event,
) -> tuple[Event | None, Event | None]:
    """Find next and last games relative to current event.

    Useful for populating .next and .last suffix contexts.

    Args:
        events: List of events (sorted by start_time)
        current_event: The current event

    Returns:
        Tuple of (next_event, last_event)
    """
    if not events:
        return None, None

    # Sort by start time
    sorted_events = sorted(events, key=lambda e: e.start_time)

    next_event = None
    last_event = None
    current_time = current_event.start_time

    for event in sorted_events:
        if event.id == current_event.id:
            continue

        if event.start_time > current_time and next_event is None:
            next_event = event
        elif event.start_time < current_time:
            last_event = event  # Keep updating until we pass current

    return next_event, last_event


def find_next_and_last_from_schedule(
    events: list[Event],
    reference_time=None,
) -> tuple[Event | None, Event | None]:
    """Find next scheduled and last completed games from a schedule.

    Useful for filler content when there's no "current" event.

    Args:
        events: List of events (team's schedule)
        reference_time: Reference datetime (defaults to now)

    Returns:
        Tuple of (next_event, last_event)
    """
    from datetime import UTC, datetime

    if not events:
        return None, None

    if reference_time is None:
        reference_time = datetime.now(UTC)

    # Sort by start time
    sorted_events = sorted(events, key=lambda e: e.start_time)

    next_event = None
    last_event = None

    for event in sorted_events:
        if event.start_time > reference_time:
            if next_event is None:
                next_event = event
        else:
            last_event = event  # Keep updating - last one before reference

    return next_event, last_event
