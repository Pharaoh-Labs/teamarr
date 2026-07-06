"""Regression tests for issue #267 — single-profile assignment at channel create.

When only one channel profile exists in Dispatcharr and the user checks it in
Dispatcharr Output, the frontend collapses "all profiles selected" to null.
The create path used to push that None through
DynamicResolver.resolve_channel_profiles, which collapsed it to []
(NO profiles), so channels were created without any profile assignment.

None must survive to _create_channel, which maps it to the [0] all-profiles
sentinel — and the same value must be persisted to the local DB so the
profile drift sync doesn't immediately flag the new channel.
"""

from unittest.mock import MagicMock, patch

from teamarr.dispatcharr.types import OperationResult
from tests.fakes import FakeEvent


def _make_service(channel_manager=None):
    from teamarr.consumers.lifecycle.service import ChannelLifecycleService

    sports_service = MagicMock()
    sports_service.get_sport_display_name.return_value = "Baseball"

    return ChannelLifecycleService(
        db_factory=MagicMock(),
        sports_service=sports_service,
        channel_manager=channel_manager,
        logo_manager=MagicMock(),
        epg_manager=MagicMock(),
    )


class TestResolveProfilesForEvent:
    """None (not configured) must bypass the dynamic resolver entirely."""

    def test_none_is_preserved_and_resolver_not_called(self):
        service = _make_service()
        service._dynamic_resolver = MagicMock()

        result = service._resolve_profiles_for_event(None, "baseball", "milb")

        assert result is None
        service._dynamic_resolver.resolve_channel_profiles.assert_not_called()

    def test_lists_are_delegated_to_resolver(self):
        service = _make_service()
        service._dynamic_resolver = MagicMock()
        service._dynamic_resolver.resolve_channel_profiles.return_value = [2]

        result = service._resolve_profiles_for_event([2], "baseball", "milb")

        assert result == [2]
        service._dynamic_resolver.resolve_channel_profiles.assert_called_once_with(
            profile_ids=[2],
            event_sport="baseball",
            event_league="milb",
        )

    def test_empty_list_stays_empty(self):
        """[] means explicitly no profiles — not the all-profiles fallback."""
        service = _make_service()
        service._dynamic_resolver = MagicMock()
        service._dynamic_resolver.resolve_channel_profiles.return_value = []

        assert service._resolve_profiles_for_event([], "baseball", "milb") == []


class TestCreateChannelProfileSentinel:
    """_create_channel maps None → [0] for Dispatcharr AND the local DB."""

    def _run_create(self, channel_profile_ids):
        cm = MagicMock()
        cm.create_channel.return_value = OperationResult(
            success=True, channel={"id": 100, "uuid": "uuid-100"}
        )
        service = _make_service(channel_manager=cm)

        with (
            patch.object(service, "_generate_channel_name", return_value="Test Channel"),
            patch.object(service, "_get_next_channel_number", return_value="5001"),
            patch.object(service, "_resolve_logo_url", return_value=None),
            patch.object(
                service._timing_manager, "calculate_delete_time", return_value=None
            ),
            patch("teamarr.database.channels.create_managed_channel", return_value=1)
            as mock_create_db,
            patch("teamarr.database.channels.add_stream_to_channel"),
        ):
            result = service._create_channel(
                conn=MagicMock(),
                event=FakeEvent(),
                stream={"id": 456, "name": "Test Stream"},
                group_config={"id": 1},
                template=None,
                matched_keyword=None,
                channel_group_id=10,
                channel_profile_ids=channel_profile_ids,
            )

        assert result.success
        api_profiles = cm.create_channel.call_args.kwargs["channel_profile_ids"]
        db_profiles = mock_create_db.call_args.kwargs["channel_profile_ids"]
        return api_profiles, db_profiles

    def test_none_becomes_all_profiles_sentinel(self):
        """Issue #267: unconfigured (None) must create with [0], not []."""
        api_profiles, db_profiles = self._run_create(None)
        assert api_profiles == [0]
        assert db_profiles == [0]

    def test_empty_list_means_no_profiles(self):
        api_profiles, db_profiles = self._run_create([])
        assert api_profiles == []
        assert db_profiles == []

    def test_specific_profiles_pass_through(self):
        api_profiles, db_profiles = self._run_create([2, 3])
        assert api_profiles == [2, 3]
        assert db_profiles == [2, 3]
