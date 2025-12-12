"""Event-based EPG generation.

Fetches events from data providers and generates EPG programmes.
Each event gets its own channel.

Note: This queries DATA providers (ESPN, TheSportsDB) by league.
Event groups (M3U provider stream collections) are a separate concept
handled elsewhere.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from teamarr.core import Event, Programme
from teamarr.services import SportsDataService


@dataclass
class EventChannelInfo:
    """Generated channel info for an event."""

    channel_id: str
    name: str
    icon: str | None = None


@dataclass
class EventEPGOptions:
    """Options for event-based EPG generation."""

    pregame_minutes: int = 30
    default_duration_hours: float = 3.0


class EventEPGGenerator:
    """Generates EPG programmes for events from data providers."""

    def __init__(self, service: SportsDataService):
        self._service = service

    def generate_for_leagues(
        self,
        leagues: list[str],
        target_date: date,
        channel_prefix: str,
        options: EventEPGOptions | None = None,
    ) -> tuple[list[Programme], list[EventChannelInfo]]:
        """Generate EPG for all events in specified leagues.

        Args:
            leagues: League codes to fetch events from
            target_date: Date to fetch events for
            channel_prefix: Prefix for generated channel IDs
            options: Generation options

        Returns:
            Tuple of (programmes, channels)
        """
        options = options or EventEPGOptions()

        all_events: list[Event] = []
        for league in leagues:
            events = self._service.get_events(league, target_date)
            all_events.extend(events)

        programmes = []
        channels = []

        for event in all_events:
            channel_id = f"{channel_prefix}-{event.id}"
            channel_info = EventChannelInfo(
                channel_id=channel_id,
                name=f"{event.away_team.abbreviation} @ {event.home_team.abbreviation}",
                icon=event.home_team.logo_url,
            )
            channels.append(channel_info)

            programme = self._event_to_programme(event, channel_id, options)
            programmes.append(programme)

        return programmes, channels

    def generate_for_event(
        self,
        event_id: str,
        league: str,
        channel_id: str,
        options: EventEPGOptions | None = None,
    ) -> Programme | None:
        """Generate EPG for a specific event."""
        options = options or EventEPGOptions()

        event = self._service.get_event(event_id, league)
        if not event:
            return None

        return self._event_to_programme(event, channel_id, options)

    def _event_to_programme(
        self,
        event: Event,
        channel_id: str,
        options: EventEPGOptions,
    ) -> Programme:
        """Convert an Event to a Programme."""
        start = event.start_time - timedelta(minutes=options.pregame_minutes)
        stop = event.start_time + timedelta(hours=options.default_duration_hours)

        return Programme(
            channel_id=channel_id,
            title=f"{event.away_team.name} @ {event.home_team.name}",
            start=start,
            stop=stop,
            description=self._format_description(event),
            category="Sports",
            icon=event.home_team.logo_url,
        )

    def _format_description(self, event: Event) -> str:
        """Format programme description."""
        parts = [event.name]
        if event.venue:
            parts.append(f"Venue: {event.venue.name}")
        if event.broadcasts:
            parts.append(f"Watch on: {', '.join(event.broadcasts)}")
        return " | ".join(parts)
