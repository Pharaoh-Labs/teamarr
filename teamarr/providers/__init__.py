"""Provider layer - sports data providers.

This is the SINGLE place where providers are configured and registered.
All other code discovers providers via ProviderRegistry.

Adding a new provider:
1. Create provider module (providers/newprovider/)
2. Register it here using ProviderRegistry.register()
3. Add league config to database (leagues table)

The rest of the system automatically discovers and uses registered providers.

Dependency Injection:
ProviderRegistry.initialize() must be called during app startup
to inject the LeagueMappingSource into providers.
"""

from collections.abc import Callable

from teamarr.database import get_db
from teamarr.database.team_cache import get_team_name_by_id
from teamarr.providers.espn import ESPNClient, ESPNProvider
from teamarr.providers.hockeytech import HockeyTechClient, HockeyTechProvider
from teamarr.providers.mlbstats import MLBStatsClient, MLBStatsProvider
from teamarr.providers.nascar import NASCARProvider
from teamarr.providers.registry import ProviderConfig, ProviderRegistry
from teamarr.providers.squiggle import SquiggleClient, SquiggleProvider
from teamarr.providers.supabase import SupabaseLeagueClient, SupabaseProvider
from teamarr.providers.tsdb import RateLimitStats, TSDBClient, TSDBProvider

# =============================================================================
# PROVIDER FACTORY FUNCTIONS
# =============================================================================
# Factories inject dependencies from the registry at instantiation time.


def _create_espn_provider() -> ESPNProvider:
    """Factory for ESPN provider with injected dependencies."""
    return ESPNProvider(
        league_mapping_source=ProviderRegistry.get_league_mapping_source(),
    )


def _get_tsdb_api_key() -> str | None:
    """Fetch TSDB API key from database settings.

    This is the boundary where database access happens before
    passing to the provider layer (which should not access database).
    """
    try:

        with get_db() as conn:
            cursor = conn.execute("SELECT tsdb_api_key FROM settings WHERE id = 1")
            row = cursor.fetchone()
            if row and row["tsdb_api_key"]:
                return row["tsdb_api_key"]
    except Exception:
        # Database not available or column doesn't exist yet - expected during startup
        # No logging here to avoid noise during initialization
        pass
    return None


def _create_tsdb_team_name_resolver() -> Callable[[str, str], str | None]:
    """Create a team name resolver callback for TSDB provider.

    This callback accesses the database, keeping DB access at the factory
    boundary rather than inside the provider layer.
    """

    def resolver(team_id: str, league: str) -> str | None:
        with get_db() as conn:
            return get_team_name_by_id(conn, team_id, league, provider="tsdb")

    return resolver


def _create_tsdb_provider() -> TSDBProvider:
    """Factory for TSDB provider with injected dependencies."""
    return TSDBProvider(
        league_mapping_source=ProviderRegistry.get_league_mapping_source(),
        api_key=_get_tsdb_api_key(),
        team_name_resolver=_create_tsdb_team_name_resolver(),
    )


def _create_hockeytech_provider() -> HockeyTechProvider:
    """Factory for HockeyTech provider with injected dependencies."""
    return HockeyTechProvider(
        league_mapping_source=ProviderRegistry.get_league_mapping_source(),
    )


def _create_supabase_provider() -> SupabaseProvider:
    """Factory for Supabase provider with injected dependencies."""
    return SupabaseProvider(
        league_mapping_source=ProviderRegistry.get_league_mapping_source(),
    )


def _create_mlbstats_provider() -> MLBStatsProvider:
    """Factory for MLB Stats provider with injected dependencies."""
    return MLBStatsProvider(
        league_mapping_source=ProviderRegistry.get_league_mapping_source(),
    )


def _create_squiggle_provider() -> SquiggleProvider:
    """Factory for Squiggle provider with injected dependencies."""
    return SquiggleProvider(
        league_mapping_source=ProviderRegistry.get_league_mapping_source(),
    )


def _create_nascar_provider() -> NASCARProvider:
    """Factory for NASCAR provider with injected dependencies."""
    return NASCARProvider(
        league_mapping_source=ProviderRegistry.get_league_mapping_source(),
    )


# =============================================================================
# PROVIDER REGISTRATION
# =============================================================================
# This is the ONLY place providers need to be added.
# Priority: Lower = higher priority (tried first for matching leagues)

ProviderRegistry.register(
    name="espn",
    provider_class=ESPNProvider,
    factory=_create_espn_provider,
    priority=0,  # Primary provider
    enabled=True,
)

ProviderRegistry.register(
    name="hockeytech",
    provider_class=HockeyTechProvider,
    factory=_create_hockeytech_provider,
    priority=50,  # CHL leagues (OHL, WHL, QMJHL) + AHL, PWHL, USHL
    enabled=True,
)

ProviderRegistry.register(
    name="supabase",
    provider_class=SupabaseProvider,
    factory=_create_supabase_provider,
    priority=55,  # Supabase-backed leagues (CBL, etc.)
    enabled=True,
)

ProviderRegistry.register(
    name="mlbstats",
    provider_class=MLBStatsProvider,
    factory=_create_mlbstats_provider,
    priority=40,  # MiLB / Triple-A provider
    enabled=True,
)

ProviderRegistry.register(
    name="squiggle",
    provider_class=SquiggleProvider,
    factory=_create_squiggle_provider,
    priority=30,  # AFL primary provider — free, no key required
    enabled=True,
)

ProviderRegistry.register(
    name="nascar",
    provider_class=NASCARProvider,
    factory=_create_nascar_provider,
    priority=35,  # NASCAR Cup/ORAP/Trucks — authoritative session schedules
    enabled=True,
)

ProviderRegistry.register(
    name="tsdb",
    provider_class=TSDBProvider,
    factory=_create_tsdb_provider,
    priority=100,  # Fallback provider for boxing, etc.
    enabled=True,
)

# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Registry
    "ProviderConfig",
    "ProviderRegistry",
    # ESPN
    "ESPNClient",
    "ESPNProvider",
    # HockeyTech
    "HockeyTechClient",
    "HockeyTechProvider",
    # MLB Stats
    "MLBStatsClient",
    "MLBStatsProvider",
    # Supabase
    "SupabaseLeagueClient",
    "SupabaseProvider",
    # Squiggle (AFL)
    "SquiggleClient",
    "SquiggleProvider",
    # NASCAR
    "NASCARProvider",
    # TheSportsDB
    "RateLimitStats",
    "TSDBClient",
    "TSDBProvider",
]
