"""``{exception_keyword}`` resolves in event pregame/postgame filler (#1136).

The main programme path injects the keyword through ``TemplateContext.extra_vars``;
the event filler built its own context without it, so a keyword channel's filler
titles, subtitles, descriptions and art URLs rendered the variable empty while the
channel name and the live programme carried it.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.event_group_processor import EventGroupProcessor
from teamarr.consumers.filler.event_filler import (
    EventFillerConfig,
    EventFillerGenerator,
    EventFillerOptions,
    EventFillerResult,
)
from teamarr.core import Event, EventStatus, Team
from teamarr.core.filler_types import FillerTemplate

START = datetime(2026, 10, 25, 17, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_league_mapping_service():
    """Full template resolution reads the league mapping singleton."""
    svc = MagicMock()
    svc.get_league_alias.side_effect = lambda code: code.upper()
    svc.get_league_display_name.side_effect = lambda code: code.upper()
    svc.get_league_id.side_effect = lambda code: code
    svc.get_league_logo.return_value = ""
    svc.get_gracenote_category.side_effect = lambda code: code.upper()
    svc.get_sport_display_name.side_effect = lambda code: code.title()
    with patch("teamarr.services.league_mappings._league_mapping_service", svc):
        yield svc


def _event() -> Event:
    def team(id_, name, abbrev):
        return Team(
            id=id_,
            provider="espn",
            name=name,
            short_name=name.split()[-1],
            abbreviation=abbrev,
            league="nfl",
            sport="football",
        )

    return Event(
        id="401772510",
        provider="espn",
        name="New England Patriots at Chicago Bears",
        short_name="NE @ CHI",
        start_time=START,
        league="nfl",
        sport="football",
        status=EventStatus(state="pre"),
        home_team=team("3", "Chicago Bears", "CHI"),
        away_team=team("17", "New England Patriots", "NE"),
    )


def _config() -> EventFillerConfig:
    return EventFillerConfig(
        pregame_template=FillerTemplate(
            title="Coming up: {exception_keyword} {away_team} at {home_team}",
            subtitle="{exception_keyword}",
            description="Pregame for the {exception_keyword} channel",
            art_url="https://art.example/{away_abbrev}-{home_abbrev}?badge={exception_keyword}",
        ),
        postgame_template=FillerTemplate(
            title="Final: {exception_keyword} {away_team} at {home_team}",
            description="",
        ),
    )


def _generate(exception_keyword: str | None) -> EventFillerResult:
    service = MagicMock()
    service.get_team_stats.return_value = None
    generator = EventFillerGenerator(service)
    options = EventFillerOptions(
        epg_start=START - timedelta(hours=2),
        epg_end=START + timedelta(hours=8),
        sport_durations={"football": 3.5},
    )
    return generator.generate_with_counts(
        event=_event(),
        channel_id="teamarr-401772510-4k",
        config=_config(),
        options=options,
        exception_keyword=exception_keyword,
    )


def test_keyword_resolves_in_every_filler_field():
    result = _generate("[4K]")
    pregame = [p for p in result.programmes if p.title.startswith("Coming up")]
    postgame = [p for p in result.programmes if p.title.startswith("Final")]
    assert pregame and postgame

    first = pregame[0]
    assert first.title == "Coming up: [4K] New England Patriots at Chicago Bears"
    assert first.subtitle == "[4K]"
    assert first.description == "Pregame for the [4K] channel"
    assert first.icon is not None
    assert "badge=%5B4K%5D" in first.icon or "badge=[4K]" in first.icon
    assert postgame[0].title == "Final: [4K] New England Patriots at Chicago Bears"


def test_no_keyword_renders_empty_not_literal():
    result = _generate(None)
    pregame = next(p for p in result.programmes if p.title.startswith("Coming up"))
    assert "{exception_keyword}" not in pregame.title
    assert pregame.title == "Coming up: New England Patriots at Chicago Bears"


def test_xmltv_filler_passes_the_display_value():
    """The processor hands the filler the same display value the programme gets:
    the keyword, else the untagged label, else empty."""
    with patch("teamarr.consumers.event_group_processor.processor.create_default_service"):
        processor = EventGroupProcessor(db_factory=MagicMock())
    processor._run_now = datetime(2026, 10, 25, 15, 0, tzinfo=ZoneInfo("America/New_York"))

    seen: list[tuple[str, str | None]] = []

    def fake_generate_with_counts(**kwargs):
        seen.append((kwargs["channel_id"], kwargs["exception_keyword"]))
        return EventFillerResult(programmes=[], pregame_count=0, postgame_count=0)

    def stream(keyword):
        return {
            "event": _event(),
            "feed_team": None,
            "_exception_keyword": keyword,
            "segment": None,
            "segment_start": None,
            "segment_end": None,
        }

    module = "teamarr.consumers.event_group_processor.xmltv"
    with (
        patch(f"{module}.EventFillerGenerator") as generator,
        patch(f"{module}.get_user_timezone", return_value=ZoneInfo("America/New_York")),
    ):
        generator.return_value.generate_with_counts = fake_generate_with_counts
        processor._generate_filler_for_streams(
            matched_streams=[stream("4K"), stream(None)],
            filler_config=EventFillerConfig(),
            sport_durations={"football": 3.5},
            untagged_keyword_label="Main",
        )

    assert [k for _, k in seen] == ["4K", "Main"]
    # The tvg-id keeps the raw keyword; the untagged channel's id carries no label.
    assert seen[0][0] != seen[1][0]
    assert "main" not in seen[1][0].lower()
