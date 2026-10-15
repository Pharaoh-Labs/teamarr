"""{league_code} on cricket events: the ESPN series slug wins (bead s7ny).

ESPN has no standing cricket leagues — every tour is its own numbered series
("8050", "1554555") — and game-thumbs keys cricket art under that slug, so the
format code ("cricket-t20i") matches nothing there. When the panel supplied a
series slug the variable emits it, digits untouched; every other league — and
any render without an event, like team channels and samples — resolves exactly
as before.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from teamarr.consumers.matching.team_matcher import TeamMatcher
from teamarr.consumers.stream_match_cache import event_to_cache_data
from teamarr.core.types import Event, EventStatus, Team
from teamarr.database.provider_cache import dict_to_event, event_to_dict
from teamarr.services import league_mappings as lm
from teamarr.services.sports_data import _event_dict_is_stale
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.resolver import TemplateResolver
from teamarr.templates.variables.identity import extract_league_code


@pytest.fixture
def league_service(db_factory):
    """A real mapping service — a full resolve() runs every extractor."""
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


def _cricket_event(series_slug: str = "8050") -> Event:
    return Event(
        id="1546541",
        provider="espn",
        name="Sikkim v Meghalaya",
        short_name="SIKM v MEGHA",
        start_time=datetime(2026, 10, 11, 2, 45, tzinfo=UTC),
        home_team=Team(
            id="2085",
            provider="espn",
            name="Sikkim",
            short_name="Sikkim",
            abbreviation="SIKM",
            league="cricket-test",
            sport="cricket",
        ),
        away_team=Team(
            id="2086",
            provider="espn",
            name="Meghalaya",
            short_name="Meghalaya",
            abbreviation="MEGHA",
            league="cricket-test",
            sport="cricket",
        ),
        status=EventStatus(state="live", detail="Stumps"),
        league="cricket-test",
        sport="cricket",
        series_slug=series_slug,
    )


def _ctx(event: Event | None, league: str = "cricket-test") -> TemplateContext:
    game_ctx = GameContext(event=event)
    team_config = TeamChannelContext(team_id="1", league=league, sport="cricket", team_name="X")
    return TemplateContext(game_context=game_ctx, team_config=team_config, team_stats=None)


def test_the_series_slug_wins_and_digits_pass_through():
    ctx = _ctx(_cricket_event("8050"))
    assert extract_league_code(ctx, ctx.game_context) == "8050"

    ctx = _ctx(_cricket_event("1554555"))
    assert extract_league_code(ctx, ctx.game_context) == "1554555"


def test_without_a_slug_the_format_code_stands():
    ctx = _ctx(_cricket_event(""))
    assert extract_league_code(ctx, ctx.game_context) == "cricket-test"


def test_a_render_without_an_event_still_resolves_the_format_code():
    ctx = _ctx(None)
    assert extract_league_code(ctx, ctx.game_context) == "cricket-test"


def test_an_art_path_renders_the_numeric_slug(league_service):
    resolver = TemplateResolver()
    art = resolver.resolve_art(
        "{league_code}/{away_team|pascal}/{home_team|pascal}/cover.png"
        "?style=1&logo=true&fallback=true",
        _ctx(_cricket_event("8050")),
    )
    assert art == "8050/Meghalaya/Sikkim/cover.png?style=1&logo=true&fallback=true"


@pytest.mark.parametrize(
    "league,slug",
    [
        ("cricket-t20i", "8836"),
        ("cricket-odi", "24289"),
        ("cricket-test", "1554555"),
        ("mlc", "21266"),
        ("ipl", "8048"),
        ("bbl", "8044"),
        ("sa20", "21275"),
    ],
)
@pytest.mark.parametrize("cache_path", ["service", "match", "service_then_match"])
def test_art_url_keeps_numeric_series_through_caches(league_service, league, slug, cache_path):
    # The series number here is illustrative: it must pass through untouched,
    # not be inferred from either team or the international format league.
    event = _cricket_event(slug)
    event.league = league
    event.home_team = replace(event.home_team, name="India", short_name="India", league=league)
    event.away_team = replace(
        event.away_team, name="West Indies", short_name="West Indies", league=league
    )
    if cache_path in {"service", "service_then_match"}:
        payload = json.loads(json.dumps(event_to_dict(event)))
        assert not _event_dict_is_stale(payload)
        event = dict_to_event(payload)
    if cache_path in {"match", "service_then_match"}:
        payload = json.loads(
            json.dumps(event_to_cache_data(event), default=lambda d: d.isoformat())
        )
        matcher = TeamMatcher.__new__(TeamMatcher)
        event = matcher._reconstruct_event(payload)
        assert event is not None

    art = TemplateResolver().resolve_art(
        "{league_code}/{away_team|pascal}/{home_team|pascal}/thumb.png"
        "?style=1&logo=true&fallback=true&badge={broadcast_national_network}%20{exception_keyword}",
        _ctx(event, league),
    )
    assert art == f"{slug}/WestIndies/India/thumb.png?style=1&logo=true&fallback=true&badge=%20"
    assert event.league == league  # Artwork must not change matching/subscription identity.


def test_legacy_cricket_cache_refreshes_but_explicit_empty_slug_is_supported():
    payload = event_to_dict(_cricket_event())
    payload.pop("series_slug")
    matcher = TeamMatcher.__new__(TeamMatcher)
    assert _event_dict_is_stale(payload)
    # Direct reconstruction stays backward compatible, including user pins.
    assert matcher._reconstruct_event(payload).series_slug == ""
    assert dict_to_event(payload).series_slug == ""  # Backward-compatible decoder.

    payload["series_slug"] = ""
    assert not _event_dict_is_stale(payload)  # Provider genuinely had no series metadata.
    assert matcher._reconstruct_event(payload) is not None


@pytest.mark.parametrize("pinned", [False, True])
def test_legacy_match_cache_refresh_preserves_manual_pin(pinned):
    payload = event_to_cache_data(_cricket_event())
    payload.pop("series_slug")
    matcher = TeamMatcher.__new__(TeamMatcher)
    matcher._cache = MagicMock()
    matcher._cache.get.return_value = SimpleNamespace(
        cached_data=payload, user_corrected=pinned, event_id=payload["id"], league="cricket-test"
    )
    ctx = SimpleNamespace(
        anchor_dt=None,
        group_id=1,
        stream_id=2,
        stream_name="India v West Indies",
        generation=1,
        team1="India",
        team2="West Indies",
    )
    result = matcher._check_cache(ctx)
    if pinned:
        assert result is not None and result.event.id == payload["id"]
    else:
        assert result is None
    matcher._cache.delete.assert_not_called()


def test_non_cricket_legacy_cache_remains_valid():
    event = _cricket_event("")
    event.league = "nfl"
    event.sport = "football"
    payload = event_to_dict(event)
    payload.pop("series_slug")
    assert not _event_dict_is_stale(payload)
    restored = TeamMatcher.__new__(TeamMatcher)._reconstruct_event(payload)
    assert restored is not None
    ctx = _ctx(restored, "nfl")
    assert extract_league_code(ctx, ctx.game_context) == "nfl"
