"""Abstract interfaces for Teamarr v2.

Defines the contracts that providers must implement.
"""

from abc import ABC, abstractmethod
from datetime import date

from teamarr.core.types import Event, Team


class SportsProvider(ABC):
    """Abstract base class for sports data providers.

    Providers fetch data from external APIs (ESPN, TheSportsDB, etc.)
    and normalize it into our dataclass format.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'espn', 'thesportsdb')."""
        ...

    @abstractmethod
    def supports_league(self, league: str) -> bool:
        """Check if this provider supports the given league."""
        ...

    @abstractmethod
    def get_events(self, league: str, date: date) -> list[Event]:
        """Get all events for a league on a given date.

        Args:
            league: League identifier (e.g., 'nfl', 'nba')
            date: Date to fetch events for

        Returns:
            List of events, empty list if none found or on error
        """
        ...

    @abstractmethod
    def get_team_schedule(
        self,
        team_id: str,
        league: str,
        days_ahead: int = 14,
    ) -> list[Event]:
        """Get upcoming schedule for a specific team.

        Args:
            team_id: Provider's team ID
            league: League identifier
            days_ahead: Number of days to look ahead

        Returns:
            List of upcoming events, empty list if none found or on error
        """
        ...

    @abstractmethod
    def get_team(self, team_id: str, league: str) -> Team | None:
        """Get team details.

        Args:
            team_id: Provider's team ID
            league: League identifier

        Returns:
            Team if found, None otherwise
        """
        ...

    @abstractmethod
    def get_event(self, event_id: str, league: str) -> Event | None:
        """Get a specific event by ID.

        Args:
            event_id: Provider's event ID
            league: League identifier

        Returns:
            Event if found, None otherwise
        """
        ...
