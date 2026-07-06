"""Tests for the team filter master toggle (settings.team_filter_enabled).

Bead `teamarrv2-zer`: when the global toggle is off, _get_effective_team_filter
must return no-filter regardless of group-level or global team selections.
That single chokepoint controls both the per-event filter (_filter_by_teams)
and the post-filter channel cleanup (_cleanup_team_filtered_channels), so
flipping the toggle truly disables team filtering end-to-end.
"""

from unittest.mock import MagicMock, patch

import pytest

from teamarr.database.settings import TeamFilterSettings
from tests.fakes import FakeGroup


@pytest.fixture
def processor():
    from teamarr.consumers.event_group_processor import EventGroupProcessor

    with patch("teamarr.consumers.event_group_processor.processor.create_default_service"):
        return EventGroupProcessor(db_factory=MagicMock())


@pytest.fixture
def mock_conn():
    return MagicMock()


def _patch_settings(settings: TeamFilterSettings):
    return patch(
        "teamarr.database.settings.get_team_filter_settings",
        return_value=settings,
    )


class TestMasterToggleOff:
    """When settings.enabled=False, all filtering is bypassed."""

    def test_toggle_off_overrides_group_include_filter(self, processor, mock_conn):
        group = FakeGroup(
            include_teams=[{"provider": "espn", "team_id": "1", "league": "nhl"}],
            team_filter_mode="include",
        )
        with _patch_settings(TeamFilterSettings(enabled=False)):
            result = processor._get_effective_team_filter(group, mock_conn)
        assert result == (None, None, "include", False)

    def test_toggle_off_overrides_group_exclude_filter(self, processor, mock_conn):
        group = FakeGroup(
            exclude_teams=[{"provider": "espn", "team_id": "2", "league": "nba"}],
            team_filter_mode="exclude",
        )
        with _patch_settings(TeamFilterSettings(enabled=False)):
            result = processor._get_effective_team_filter(group, mock_conn)
        assert result == (None, None, "include", False)

    def test_toggle_off_overrides_global_default_filter(self, processor, mock_conn):
        group = FakeGroup()
        global_settings = TeamFilterSettings(
            enabled=False,
            include_teams=[{"provider": "espn", "team_id": "9", "league": "nhl"}],
            mode="include",
        )
        with _patch_settings(global_settings):
            result = processor._get_effective_team_filter(group, mock_conn)
        assert result == (None, None, "include", False)

    def test_toggle_off_drops_playoff_bypass(self, processor, mock_conn):
        # Even if global bypass is on, master-off means no filtering happens,
        # so bypass is irrelevant. Return False to keep callsite logic simple.
        group = FakeGroup(
            include_teams=[{"provider": "espn", "team_id": "1", "league": "nhl"}],
            bypass_filter_for_playoffs=True,
        )
        global_settings = TeamFilterSettings(enabled=False, bypass_filter_for_playoffs=True)
        with _patch_settings(global_settings):
            _, _, _, bypass = processor._get_effective_team_filter(group, mock_conn)
        assert bypass is False


class TestMasterToggleOn:
    """When settings.enabled=True, the original priority chain is preserved."""

    def test_toggle_on_uses_group_filter(self, processor, mock_conn):
        teams = [{"provider": "espn", "team_id": "1", "league": "nhl"}]
        group = FakeGroup(include_teams=teams, team_filter_mode="include")
        with _patch_settings(TeamFilterSettings(enabled=True)):
            result = processor._get_effective_team_filter(group, mock_conn)
        assert result == (teams, None, "include", False)

    def test_toggle_on_falls_back_to_global_when_group_empty(self, processor, mock_conn):
        global_teams = [{"provider": "espn", "team_id": "9", "league": "nhl"}]
        global_settings = TeamFilterSettings(
            enabled=True,
            include_teams=global_teams,
            mode="include",
        )
        with _patch_settings(global_settings):
            result = processor._get_effective_team_filter(FakeGroup(), mock_conn)
        assert result == (global_teams, None, "include", False)

    def test_toggle_on_no_filters_returns_passthrough(self, processor, mock_conn):
        with _patch_settings(TeamFilterSettings(enabled=True)):
            result = processor._get_effective_team_filter(FakeGroup(), mock_conn)
        assert result == (None, None, "include", False)

    def test_toggle_on_preserves_playoff_bypass(self, processor, mock_conn):
        group = FakeGroup(
            include_teams=[{"provider": "espn", "team_id": "1", "league": "nhl"}],
            bypass_filter_for_playoffs=True,
        )
        with _patch_settings(TeamFilterSettings(enabled=True)):
            _, _, _, bypass = processor._get_effective_team_filter(group, mock_conn)
        assert bypass is True


class TestDefaultEnabledTrue:
    """TeamFilterSettings.enabled defaults to True (backward compat)."""

    def test_default_constructor_enables_filtering(self):
        assert TeamFilterSettings().enabled is True
