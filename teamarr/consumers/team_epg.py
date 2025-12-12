"""Team-based EPG generation.

Takes team configuration, fetches schedule, generates programmes.
"""

from dataclasses import dataclass
from datetime import timedelta

from teamarr.core import Event, Programme
from teamarr.services import SportsDataService


@dataclass
class TeamConfig:
    """Configuration for a team's EPG channel."""

    team_id: str
    league: str
    team_name: str
    channel_id: str
    logo_url: str | None = None


@dataclass
class TeamEPGOptions:
    """Options for team-based EPG generation."""

    days_ahead: int = 14
    pregame_minutes: int = 30
    default_duration_hours: float = 3.0


class TeamEPGGenerator:
    """Generates EPG programmes for a team-based channel."""

    def __init__(self, service: SportsDataService):
        self._service = service

    def generate(
        self,
        config: TeamConfig,
        options: TeamEPGOptions | None = None,
    ) -> list[Programme]:
        """Generate EPG programmes for a team.

        Args:
            config: Team configuration
            options: Generation options

        Returns:
            List of Programme entries for XMLTV
        """
        options = options or TeamEPGOptions()

        events = self._service.get_team_schedule(
            team_id=config.team_id,
            league=config.league,
            days_ahead=options.days_ahead,
        )

        programmes = []
        for event in events:
            programme = self._event_to_programme(event, config, options)
            if programme:
                programmes.append(programme)

        return programmes

    def _event_to_programme(
        self,
        event: Event,
        config: TeamConfig,
        options: TeamEPGOptions,
    ) -> Programme | None:
        """Convert an Event to a Programme."""
        start = event.start_time - timedelta(minutes=options.pregame_minutes)
        stop = event.start_time + timedelta(hours=options.default_duration_hours)

        title = self._format_title(event, config)
        description = self._format_description(event, config)

        return Programme(
            channel_id=config.channel_id,
            title=title,
            start=start,
            stop=stop,
            description=description,
            category="Sports",
            icon=config.logo_url or event.home_team.logo_url,
        )

    def _format_title(self, event: Event, config: TeamConfig) -> str:
        """Format programme title."""
        is_home = event.home_team.id == config.team_id
        if is_home:
            return f"{event.away_team.name} @ {event.home_team.name}"
        else:
            return f"{event.away_team.name} @ {event.home_team.name}"

    def _format_description(self, event: Event, config: TeamConfig) -> str:
        """Format programme description."""
        parts = [event.name]

        if event.venue:
            parts.append(f"Venue: {event.venue.name}")

        if event.broadcasts:
            parts.append(f"Watch on: {', '.join(event.broadcasts)}")

        return " | ".join(parts)
