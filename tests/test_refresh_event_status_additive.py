"""refresh_event_status overlays mutable fields without clobbering static ones (#201).

Background: ESPN's summary endpoint returns degraded team data — most notably,
shortDisplayName is null. The original implementation replaced the entire Event
with the freshly-parsed one, so home_team.short_name went from "Rays" to None
the moment a refresh happened. This made {home_team_short} resolve empty in
templates while the auto-feed-label (which captured the team object before
enrichment) kept the populated short_name. Diagnosed from millercentral's
fresh-wipe log on 2026-05-06.

Fix: refresh_event_status now overlays only mutable fields (status, scores,
broadcasts, odds, fight_result_*) onto the original event. Teams, start_time,
league, sport, and other identity/static fields are preserved verbatim.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from teamarr.core.types import Event, EventStatus, Team
from teamarr.services.sports_data import SportsDataService
from teamarr.utilities.cache import make_cache_key


def _make_event(status_state: str = "scheduled", **overrides) -> Event:
    home = Team(
        id="12",
        provider="espn",
        name="Tampa Bay Rays",
        short_name="Rays",
        abbreviation="TB",
        league="mlb",
        sport="Baseball",
    )
    away = Team(
        id="14",
        provider="espn",
        name="Toronto Blue Jays",
        short_name="Blue Jays",
        abbreviation="TOR",
        league="mlb",
        sport="Baseball",
    )
    defaults = dict(
        id="401",
        provider="espn",
        name="Toronto Blue Jays at Tampa Bay Rays",
        short_name="TOR @ TB",
        league="mlb",
        sport="Baseball",
        start_time=datetime(2026, 5, 6, 17, 10, tzinfo=UTC),
        home_team=home,
        away_team=away,
        status=EventStatus(state=status_state),
        home_score=None,
        away_score=None,
        broadcasts=["FOX"],
        season_type="regular",
    )
    defaults.update(overrides)
    return Event(**defaults)


class TestRefreshIsAdditive:
    """Verify refresh_event_status preserves data the summary endpoint loses."""

    def test_team_short_name_survives_refresh_when_summary_returns_none(self):
        # Original: scoreboard-quality teams with populated short_name.
        original = _make_event(status_state="scheduled")

        # Fresh from summary: same teams but degraded — short_name=None.
        # This is exactly what ESPN's summary endpoint produces.
        degraded_home = Team(
            id="12",
            provider="espn",
            name="Tampa Bay Rays",
            short_name=None,
            abbreviation="TB",
            league="mlb",
            sport="Baseball",
        )
        degraded_away = Team(
            id="14",
            provider="espn",
            name="Toronto Blue Jays",
            short_name=None,
            abbreviation="TOR",
            league="mlb",
            sport="Baseball",
        )
        fresh = _make_event(
            status_state="final",
            home_team=degraded_home,
            away_team=degraded_away,
            home_score=4,
            away_score=2,
        )

        service = SportsDataService(providers=[])
        with (
            patch.object(service, "get_event", return_value=fresh),
            patch.object(service._cache, "delete"),
        ):
            result = service.refresh_event_status(original)

        # Status was the point of the refresh — should reflect fresh.
        assert result.status.state == "final"
        # Scores changed with status — should reflect fresh.
        assert result.home_score == 4
        assert result.away_score == 2
        # Teams must NOT have been clobbered by the degraded summary data.
        assert result.home_team.short_name == "Rays"
        assert result.away_team.short_name == "Blue Jays"
        assert result.home_team.name == "Tampa Bay Rays"

    def test_returns_original_when_refresh_fails(self):
        original = _make_event(status_state="scheduled")
        service = SportsDataService(providers=[])
        with (
            patch.object(service, "get_event", return_value=None),
            patch.object(service._cache, "delete"),
        ):
            result = service.refresh_event_status(original)
        assert result is original

    def test_handles_none_event(self):
        service = SportsDataService(providers=[])
        assert service.refresh_event_status(None) is None  # type: ignore[arg-type]

    def test_broadcasts_overlay_when_fresh_has_them(self):
        original = _make_event(broadcasts=["FOX"])
        fresh = _make_event(broadcasts=["FOX", "ESPN"], status_state="in_progress")
        service = SportsDataService(providers=[])
        with (
            patch.object(service, "get_event", return_value=fresh),
            patch.object(service._cache, "delete"),
        ):
            result = service.refresh_event_status(original)
        assert result.broadcasts == ["FOX", "ESPN"]

    def test_broadcasts_preserved_when_fresh_is_empty(self):
        original = _make_event(broadcasts=["FOX"])
        fresh = _make_event(broadcasts=[], status_state="final")
        service = SportsDataService(providers=[])
        with (
            patch.object(service, "get_event", return_value=fresh),
            patch.object(service._cache, "delete"),
        ):
            result = service.refresh_event_status(original)
        # Empty broadcasts from summary shouldn't wipe the original list.
        assert result.broadcasts == ["FOX"]

    def test_static_fields_never_replaced(self):
        original = _make_event()
        # Adversarial fresh: pretend summary returned wrong league/sport/start_time.
        fresh = _make_event(
            status_state="final",
            league="WRONG",
            sport="WRONG_SPORT",
            start_time=datetime(2030, 1, 1, tzinfo=UTC),
            season_type=None,
        )
        service = SportsDataService(providers=[])
        with (
            patch.object(service, "get_event", return_value=fresh),
            patch.object(service._cache, "delete"),
        ):
            result = service.refresh_event_status(original)
        assert result.league == "mlb"
        assert result.sport == "Baseball"
        assert result.start_time == datetime(2026, 5, 6, 17, 10, tzinfo=UTC)
        assert result.season_type == "regular"


class TestRefreshCacheInvalidation:
    """First refresh invalidates the event cache for a fresh fetch; repeats
    within the coalesce window reuse it instead of re-hitting the provider."""

    def test_first_refresh_invalidates_then_coalesces(self):
        original = _make_event()
        service = SportsDataService(providers=[])
        # The service cache is a process-wide singleton, so a prior test may have
        # left a coalesce marker for this event — start from a clean state.
        service._cache.delete(make_cache_key("event_refresh", original.league, original.id))

        mock_delete = MagicMock()
        with (
            patch.object(service, "get_event", return_value=original),
            patch.object(service._cache, "delete", mock_delete),
        ):
            # First refresh: cache invalidated so the provider is hit fresh.
            service.refresh_event_status(original)
            assert mock_delete.call_count == 1
            # Key shape: ("event", "mlb", "401")
            call_args = mock_delete.call_args[0][0]
            assert "401" in str(call_args)
            assert "mlb" in str(call_args)

            # Second refresh within the window: coalesced — no re-invalidation,
            # so a popular event matched to many channels fetches once per run.
            service.refresh_event_status(original)
            assert mock_delete.call_count == 1
