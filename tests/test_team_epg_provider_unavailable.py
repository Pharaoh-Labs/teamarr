"""Team EPG schedule-provider availability classification tests."""

from unittest.mock import Mock

from teamarr.consumers.team_epg import TeamEPGGenerator, TeamEPGOptions
from teamarr.core import TemplateConfig
from teamarr.core.filler_types import FillerConfig, FillerTemplate, OffseasonFillerTemplate


def _options() -> TeamEPGOptions:
    return TeamEPGOptions(
        template=TemplateConfig(
            title_format="{team_name}",
            subtitle_format="",
            description_format="",
        ),
        filler_config=FillerConfig(
            idle_template=FillerTemplate(title="Idle", description="Offseason"),
            idle_offseason=OffseasonFillerTemplate(enabled=True, description="Offseason"),
            idle_provider_unavailable=OffseasonFillerTemplate(
                enabled=True, description="Provider unavailable"
            ),
        ),
        output_days_ahead=1,
    )


def _service(schedule):
    service = Mock()
    if isinstance(schedule, list) and not any(isinstance(item, Exception) for item in schedule):
        service.get_team_schedule.return_value = schedule
    else:
        service.get_team_schedule.side_effect = schedule
    service.get_team_stats.return_value = None
    service.refresh_event_status.side_effect = lambda event: event
    return service


def _provider_unavailable(service, *, additional_leagues=None):
    generator = TeamEPGGenerator(service)
    generator._generate_fillers = Mock(return_value=[])
    generator.generate(
        team_id="1",
        league="nba",
        channel_id="teamarr-team-1",
        team_name="Test Team",
        options=_options(),
        additional_leagues=additional_leagues,
    )
    return generator._generate_fillers.call_args.kwargs["provider_unavailable"]


def test_all_schedule_failures_use_provider_unavailable_override():
    assert _provider_unavailable(_service(RuntimeError("provider down"))) is True


def test_successful_empty_schedule_uses_offseason_override():
    assert _provider_unavailable(_service([])) is False


def test_partial_schedule_failure_remains_offseason():
    assert _provider_unavailable(
        _service([RuntimeError("provider down"), []]), additional_leagues=["cup"]
    ) is False
