"""Tests for TSDB provider hot-reload when API key changes (s9n.1).

Verifies that ProviderRegistry.reinitialize_provider() causes the TSDB
provider to be recreated with the updated API key from the database,
without requiring a restart.
"""

from unittest.mock import MagicMock

from teamarr.providers.registry import ProviderConfig, ProviderRegistry


class TestReinitializeProvider:
    def test_reinitialize_resets_cached_instance(self):
        """reinitialize_provider should clear the cached instance."""
        mock_provider = MagicMock()
        factory = MagicMock(return_value=mock_provider)

        config = ProviderConfig(
            name="test_provider",
            provider_class=type(mock_provider),
            factory=factory,
            enabled=True,
            priority=100,
        )
        # Simulate a cached instance
        config._instance = MagicMock()
        old_instance = config._instance

        ProviderRegistry._providers["test_provider"] = config

        try:
            result = ProviderRegistry.reinitialize_provider("test_provider")
            assert result is True
            assert config._instance is None

            # Next get() call should recreate via factory
            new_instance = config.get_instance()
            assert new_instance is mock_provider
            assert new_instance is not old_instance
            factory.assert_called_once()
        finally:
            ProviderRegistry._providers.pop("test_provider", None)

    def test_reinitialize_unknown_provider(self):
        """reinitialize_provider with unknown name returns False."""
        result = ProviderRegistry.reinitialize_provider("nonexistent_provider")
        assert result is False

    def test_reinitialize_picks_up_new_api_key(self):
        """After reinitialize, TSDB factory re-reads key from DB."""
        call_count = 0
        keys = ["old_key", "new_premium_key"]

        def mock_factory():
            nonlocal call_count
            key = keys[min(call_count, len(keys) - 1)]
            call_count += 1
            provider = MagicMock()
            provider.is_premium = key != "123"
            provider._api_key = key
            return provider

        config = ProviderConfig(
            name="test_tsdb",
            provider_class=MagicMock,
            factory=mock_factory,
            enabled=True,
            priority=100,
        )
        ProviderRegistry._providers["test_tsdb"] = config

        try:
            # First access creates with old key
            instance1 = config.get_instance()
            assert instance1._api_key == "old_key"

            # Reinitialize
            ProviderRegistry.reinitialize_provider("test_tsdb")

            # Second access creates with new key
            instance2 = config.get_instance()
            assert instance2._api_key == "new_premium_key"
            assert instance2 is not instance1
            assert call_count == 2
        finally:
            ProviderRegistry._providers.pop("test_tsdb", None)


class TestDisplaySettingsReloadIntegration:
    """Verify the endpoint code calls reinitialize when tsdb_api_key is set."""

    def test_endpoint_source_contains_reinitialize_call(self):
        """The display settings endpoint should call reinitialize_provider for tsdb."""
        import inspect

        from teamarr.api.routes.settings.display import update_display_settings_endpoint

        source = inspect.getsource(update_display_settings_endpoint)
        assert 'reinitialize_provider("tsdb")' in source
        assert "unmask_or_skip(update.tsdb_api_key) is not None" in source
