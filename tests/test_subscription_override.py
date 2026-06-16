"""Tests for per-group subscription override resolution.

Verifies the priority chain:
1. Group with subscription override → uses group's leagues
2. Group without override (NULL) → uses global subscription
3. Group with empty override ([]) → processes no leagues
4. Soccer mode override at group level
5. Caching: groups with overrides get separate cache keys
"""

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest


@dataclass
class FakeGroup:
    """Minimal EventEPGGroup stand-in for testing."""

    id: int = 1
    subscription_leagues: list[str] | None = None
    subscription_soccer_mode: str | None = None
    subscription_soccer_followed_teams: list[dict] | None = None


@dataclass
class FakeSubscription:
    """Minimal SportsSubscription stand-in."""

    leagues: list[str] = field(default_factory=lambda: ["nhl", "nba"])
    soccer_mode: str | None = None
    soccer_followed_teams: list[dict] | None = None


@pytest.fixture
def processor():
    """Create a minimal EventGroupProcessor with mocked dependencies."""
    from teamarr.consumers.event_group_processor import EventGroupProcessor

    with patch("teamarr.consumers.event_group_processor.create_default_service"):
        proc = EventGroupProcessor(db_factory=MagicMock())
    return proc


@pytest.fixture
def mock_conn():
    return MagicMock()


@pytest.fixture
def mock_subscription():
    return FakeSubscription()


class TestGroupOverridePriority:
    """Group subscription_leagues != None → use group, else global."""

    def test_group_override_uses_group_leagues(self, processor, mock_conn, mock_subscription):
        group = FakeGroup(
            id=1,
            subscription_leagues=["mlb", "mls"],
        )
        with patch(
            "teamarr.database.subscription.get_subscription",
            return_value=mock_subscription,
        ):
            result = processor._resolve_subscription_leagues(mock_conn, group)

        assert sorted(result) == ["mlb", "mls"]

    def test_null_override_falls_back_to_global(self, processor, mock_conn, mock_subscription):
        group = FakeGroup(id=2, subscription_leagues=None)
        with patch(
            "teamarr.database.subscription.get_subscription",
            return_value=mock_subscription,
        ):
            result = processor._resolve_subscription_leagues(mock_conn, group)

        assert sorted(result) == ["nba", "nhl"]

    def test_no_group_falls_back_to_global(self, processor, mock_conn, mock_subscription):
        with patch(
            "teamarr.database.subscription.get_subscription",
            return_value=mock_subscription,
        ):
            result = processor._resolve_subscription_leagues(mock_conn, None)

        assert sorted(result) == ["nba", "nhl"]

    def test_empty_override_returns_empty(self, processor, mock_conn, mock_subscription):
        group = FakeGroup(id=3, subscription_leagues=[])
        with patch(
            "teamarr.database.subscription.get_subscription",
            return_value=mock_subscription,
        ):
            result = processor._resolve_subscription_leagues(mock_conn, group)

        assert result == []


class TestSoccerModeOverride:
    """Soccer mode at group level overrides global soccer_mode."""

    def test_group_soccer_all_overrides_global(self, processor, mock_conn):
        group = FakeGroup(
            id=1,
            subscription_leagues=["nhl"],
            subscription_soccer_mode="all",
        )
        fake_soccer = ["eng.1", "esp.1"]
        with (
            patch(
                "teamarr.database.subscription.get_subscription",
                return_value=FakeSubscription(),
            ),
            patch(
                "teamarr.consumers.event_group_processor.get_enabled_soccer_leagues",
                return_value=fake_soccer,
            ),
        ):
            result = processor._resolve_subscription_leagues(mock_conn, group)

        # Non-soccer from override + all enabled soccer
        assert "nhl" in result
        assert "eng.1" in result
        assert "esp.1" in result

    def test_group_manual_mode_keeps_leagues_as_is(self, processor, mock_conn):
        group = FakeGroup(
            id=1,
            subscription_leagues=["nhl", "eng.1"],
            subscription_soccer_mode="manual",
        )
        with patch(
            "teamarr.database.subscription.get_subscription",
            return_value=FakeSubscription(),
        ):
            result = processor._resolve_subscription_leagues(mock_conn, group)

        assert sorted(result) == ["eng.1", "nhl"]

    def test_global_soccer_mode_not_used_when_group_overrides(self, processor, mock_conn):
        """Global has soccer_mode='all' but group overrides with manual."""
        global_sub = FakeSubscription(
            leagues=["nhl", "eng.1"],
            soccer_mode="all",
        )
        group = FakeGroup(
            id=1,
            subscription_leagues=["nba"],
            subscription_soccer_mode=None,  # No soccer mode
        )
        with patch(
            "teamarr.database.subscription.get_subscription",
            return_value=global_sub,
        ):
            result = processor._resolve_subscription_leagues(mock_conn, group)

        # Group override: just nba, no soccer expansion
        assert result == ["nba"]


class TestCaching:
    """_get_subscription_leagues caches per group."""

    def test_global_cache_shared_for_null_overrides(self, processor, mock_conn, mock_subscription):
        group_a = FakeGroup(id=1, subscription_leagues=None)
        group_b = FakeGroup(id=2, subscription_leagues=None)

        with patch(
            "teamarr.database.subscription.get_subscription",
            return_value=mock_subscription,
        ) as mock_get:
            result_a = processor._get_subscription_leagues(mock_conn, group_a)
            result_b = processor._get_subscription_leagues(mock_conn, group_b)

        # Same global result, subscription fetched only once
        assert result_a == result_b
        assert mock_get.call_count == 1

    def test_override_groups_get_separate_cache(self, processor, mock_conn, mock_subscription):
        group_a = FakeGroup(id=1, subscription_leagues=["nhl"])
        group_b = FakeGroup(id=2, subscription_leagues=["nba"])

        with patch(
            "teamarr.database.subscription.get_subscription",
            return_value=mock_subscription,
        ):
            result_a = processor._get_subscription_leagues(mock_conn, group_a)
            result_b = processor._get_subscription_leagues(mock_conn, group_b)

        assert result_a == ["nhl"]
        assert result_b == ["nba"]

    def test_override_and_global_groups_coexist(self, processor, mock_conn, mock_subscription):
        group_override = FakeGroup(id=1, subscription_leagues=["mlb"])
        group_global = FakeGroup(id=2, subscription_leagues=None)

        with patch(
            "teamarr.database.subscription.get_subscription",
            return_value=mock_subscription,
        ):
            result_override = processor._get_subscription_leagues(mock_conn, group_override)
            result_global = processor._get_subscription_leagues(mock_conn, group_global)

        assert result_override == ["mlb"]
        assert sorted(result_global) == ["nba", "nhl"]
