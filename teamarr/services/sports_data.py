"""Sports data service layer.

Routes requests to appropriate providers.
Consumers call this service - never providers directly.
"""

import logging
from datetime import date

from teamarr.core import Event, SportsProvider, Team

logger = logging.getLogger(__name__)


class SportsDataService:
    """Service layer for sports data access.

    Provides a unified interface to sports data regardless of provider.
    Handles provider selection, fallback, and future caching.
    """

    def __init__(self, providers: list[SportsProvider] | None = None):
        self._providers: list[SportsProvider] = providers or []

    def add_provider(self, provider: SportsProvider) -> None:
        """Register a provider."""
        self._providers.append(provider)

    def get_events(self, league: str, target_date: date) -> list[Event]:
        """Get all events for a league on a given date."""
        for provider in self._providers:
            if provider.supports_league(league):
                events = provider.get_events(league, target_date)
                if events:
                    return events
        return []

    def get_team_schedule(
        self,
        team_id: str,
        league: str,
        days_ahead: int = 14,
    ) -> list[Event]:
        """Get upcoming schedule for a team."""
        for provider in self._providers:
            if provider.supports_league(league):
                events = provider.get_team_schedule(team_id, league, days_ahead)
                if events:
                    return events
        return []

    def get_team(self, team_id: str, league: str) -> Team | None:
        """Get team details."""
        for provider in self._providers:
            if provider.supports_league(league):
                team = provider.get_team(team_id, league)
                if team:
                    return team
        return None

    def get_event(self, event_id: str, league: str) -> Event | None:
        """Get a specific event by ID."""
        for provider in self._providers:
            if provider.supports_league(league):
                event = provider.get_event(event_id, league)
                if event:
                    return event
        return None
