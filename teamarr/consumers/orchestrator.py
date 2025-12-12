"""EPG Orchestrator - coordinates EPG generation.

Supports two modes:
- Team-based: One channel per team, shows team's schedule
- Event-based: One channel per event, shows all events in leagues
"""

from dataclasses import dataclass
from datetime import date, datetime

from teamarr.consumers.event_epg import EventEPGGenerator, EventEPGOptions
from teamarr.consumers.team_epg import TeamConfig, TeamEPGGenerator, TeamEPGOptions
from teamarr.core import Programme
from teamarr.services import SportsDataService
from teamarr.utilities.xmltv import programmes_to_xmltv


@dataclass
class GenerationResult:
    """Result of an EPG generation run."""

    programmes: list[Programme]
    xmltv: str
    teams_processed: int
    events_processed: int
    started_at: datetime
    completed_at: datetime


class Orchestrator:
    """Coordinates EPG generation workflow."""

    def __init__(self, service: SportsDataService):
        self._service = service
        self._team_generator = TeamEPGGenerator(service)
        self._event_generator = EventEPGGenerator(service)

    def generate_for_teams(
        self,
        team_configs: list[TeamConfig],
        options: TeamEPGOptions | None = None,
    ) -> GenerationResult:
        """Generate EPG for teams (team-based mode)."""
        started_at = datetime.now()
        options = options or TeamEPGOptions()

        all_programmes: list[Programme] = []

        for config in team_configs:
            programmes = self._team_generator.generate(config, options)
            all_programmes.extend(programmes)

        channels = [
            {
                "id": config.channel_id,
                "name": config.team_name,
                "icon": config.logo_url,
            }
            for config in team_configs
        ]

        xmltv = programmes_to_xmltv(all_programmes, channels)

        return GenerationResult(
            programmes=all_programmes,
            xmltv=xmltv,
            teams_processed=len(team_configs),
            events_processed=0,
            started_at=started_at,
            completed_at=datetime.now(),
        )

    def generate_for_events(
        self,
        leagues: list[str],
        target_date: date,
        channel_prefix: str = "event",
        options: EventEPGOptions | None = None,
    ) -> GenerationResult:
        """Generate EPG for events (event-based mode).

        Fetches all events from specified leagues and generates
        a channel/programme for each.
        """
        started_at = datetime.now()
        options = options or EventEPGOptions()

        programmes, channels = self._event_generator.generate_for_leagues(
            leagues, target_date, channel_prefix, options
        )

        channel_dicts = [
            {"id": ch.channel_id, "name": ch.name, "icon": ch.icon}
            for ch in channels
        ]

        xmltv = programmes_to_xmltv(programmes, channel_dicts)

        return GenerationResult(
            programmes=programmes,
            xmltv=xmltv,
            teams_processed=0,
            events_processed=len(programmes),
            started_at=started_at,
            completed_at=datetime.now(),
        )

    # Backward compat alias
    generate = generate_for_teams
