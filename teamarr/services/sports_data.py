"""Sports data service layer.

Routes requests to appropriate providers with caching.
Consumers call this service - never providers directly.

Uses PersistentTTLCache for all caching:
- Fast in-memory operations (no SQLite during generation)
- Background flush to SQLite every 2 minutes
- Persists across restarts
- Call flush_cache() after EPG generation for immediate persistence
"""

import logging
import threading
from dataclasses import replace
from datetime import date

from teamarr.core import Event, SportsProvider, Team, TeamStats
from teamarr.database.provider_cache import (
    dict_to_event,
    dict_to_stats,
    dict_to_team,
    event_to_dict,
    stats_to_dict,
    team_to_dict,
)
from teamarr.database.team_cache import get_team_identity
from teamarr.providers import ProviderRegistry
from teamarr.utilities.cache import (
    CACHE_TTL_SCHEDULE,
    CACHE_TTL_SINGLE_EVENT,
    CACHE_TTL_TEAM_INFO,
    CACHE_TTL_TEAM_STATS,
    PersistentTTLCache,
    get_events_cache_ttl,
    make_cache_key,
)
from teamarr.utilities.event_status import is_event_final

logger = logging.getLogger(__name__)


def _backfill_team_from_cache(team: Team | None, league: str) -> Team | None:
    """Patch a Team's short_name/abbreviation/name from team_cache when missing.

    Some provider endpoints return degraded team data (e.g. ESPN's summary
    endpoint omits `shortDisplayName`). team_cache is seeded from each
    provider's `/teams` endpoint where these fields are reliably populated,
    so it's the canonical source — fall back to it whenever a field is empty.
    """
    if team is None or not team.id:
        return team
    if team.short_name and team.abbreviation and team.name:
        return team

    from teamarr.database import get_db

    try:
        with get_db() as conn:
            cached = get_team_identity(conn, team.provider, team.id, league)
    except Exception as e:
        logger.debug("[TEAM_BACKFILL] lookup failed for %s/%s: %s", team.provider, team.id, e)
        return team

    if not cached:
        return team

    return replace(
        team,
        short_name=team.short_name or cached.get("short_name") or "",
        abbreviation=team.abbreviation or cached.get("abbreviation") or "",
        name=team.name or cached.get("name") or "",
        logo_url=team.logo_url or cached.get("logo_url"),
    )


def _enrich_event_teams(event: Event | None) -> Event | None:
    """Backfill home_team and away_team from team_cache where fields are empty."""
    if event is None:
        return event
    home = _backfill_team_from_cache(event.home_team, event.league)
    away = _backfill_team_from_cache(event.away_team, event.league)
    if home is event.home_team and away is event.away_team:
        return event
    return replace(event, home_team=home, away_team=away)


def _team_dict_is_stale(team_dict: dict | None) -> bool:
    """A team dict is stale if it has a populated name but no short_name.

    Every modern provider populates short_name (falling back to the full name
    when no shorter form exists). A row with name set but short_name empty
    was written before the field flowed end-to-end and should be re-fetched.
    """
    if not isinstance(team_dict, dict):
        return False
    return bool(team_dict.get("name")) and not team_dict.get("short_name")


def _event_dict_is_stale(event_dict: dict) -> bool:
    """Detect cached events written before short_name flowed end-to-end."""
    return _team_dict_is_stale(event_dict.get("home_team")) or _team_dict_is_stale(
        event_dict.get("away_team")
    )


# Singleton cache instance - shared across all SportsDataService instances
# This ensures one in-memory cache with background persistence
_shared_cache: PersistentTTLCache | None = None
_cache_lock = threading.Lock()


def _get_shared_cache() -> PersistentTTLCache:
    """Get or create the shared cache singleton."""
    global _shared_cache
    if _shared_cache is None:
        with _cache_lock:
            if _shared_cache is None:
                _shared_cache = PersistentTTLCache()
                logger.info("[CACHE] Initialized shared service cache")
    return _shared_cache


def flush_shared_cache() -> int:
    """Flush the shared cache to SQLite.

    Call after EPG generation for immediate persistence.
    Returns number of entries written.
    """
    if _shared_cache is not None:
        return _shared_cache.flush()
    return 0


def _ensure_registry_initialized() -> None:
    """Ensure ProviderRegistry is initialized with dependencies.

    Called automatically by create_default_service() to ensure providers
    have access to league mappings from the database.
    """
    if ProviderRegistry.is_initialized():
        return

    from teamarr.database import get_db
    from teamarr.services.league_mappings import init_league_mapping_service

    league_mapping_service = init_league_mapping_service(get_db)
    ProviderRegistry.initialize(league_mapping_service)
    logger.info("[STARTUP] Auto-initialized ProviderRegistry with league mappings")


def create_default_service() -> "SportsDataService":
    """Create SportsDataService with providers from registry.

    Providers are registered in teamarr/providers/__init__.py.
    Priority is determined by registration order and priority values.

    Automatically initializes ProviderRegistry if not already done
    (e.g., when called from CLI or scheduler outside FastAPI context).
    """
    # Ensure registry is initialized with database league mappings
    _ensure_registry_initialized()

    # Get all enabled providers from the registry, sorted by priority
    providers = ProviderRegistry.get_all()
    return SportsDataService(providers=providers)


class SportsDataService:
    """Service layer for sports data access.

    Provides a unified interface to sports data regardless of provider.
    Handles provider selection, fallback, and caching.

    Cache TTLs (optimized for hourly EPG regeneration):
    - Scoreboard (league events): 8 hours - daily schedule rarely changes
    - Team schedules: 8 hours - games rarely added/removed
    - Single event: 30 minutes - fresh scores/odds for current games
    - Team stats: 4 hours - record/standings change infrequently
    - Team info: 24 hours - static team data
    """

    def __init__(self, providers: list[SportsProvider] | None = None):
        self._providers: list[SportsProvider] = providers or []
        self._cache = _get_shared_cache()

    def add_provider(self, provider: SportsProvider) -> None:
        """Register a provider."""
        self._providers.append(provider)

    def get_events(self, league: str, target_date: date, cache_only: bool = False) -> list[Event]:
        """Get all events for a league on a given date.

        Args:
            league: League code
            target_date: Date to get events for
            cache_only: If True, only return cached events (no API calls).
                       Use for older dates where we don't want to fetch.

        Returns:
            List of events (may be empty if cache_only and not cached)
        """
        cache_key = make_cache_key("events", league, target_date.isoformat())

        # Check cache (deserialize from dict)
        cached = self._cache.get(cache_key)
        if cached is not None:
            if isinstance(cached, list) and any(
                _event_dict_is_stale(e) for e in cached if isinstance(e, dict)
            ):
                logger.debug(
                    "[CACHE_STALE] %s — team data missing short_name, re-fetching",
                    cache_key,
                )
                self._cache.delete(cache_key)
            else:
                logger.debug("[CACHE_HIT] %s", cache_key)
                try:
                    return [_enrich_event_teams(dict_to_event(e)) for e in cached]
                except (KeyError, TypeError) as e:
                    logger.warning("[CACHE_ERROR] Deserialization failed: %s", e)

        # If cache_only, don't fetch from API
        if cache_only:
            return []

        # Iterate through providers
        for provider in self._providers:
            if provider.supports_league(league):
                events = provider.get_events(league, target_date)
                # Check if all events are final (for past dates, enables 30-day cache)
                # Empty list counts as "all final" (no games = nothing to update)
                all_final = len(events) == 0 or all(is_event_final(e) for e in events)
                ttl = get_events_cache_ttl(target_date, all_events_final=all_final)
                # Cache ALL results including empty lists to avoid repeated API calls
                # for leagues with no events on a given day
                self._cache.set(cache_key, [event_to_dict(e) for e in events], ttl)
                return [_enrich_event_teams(e) for e in events]
        return []

    def get_team_schedule(
        self,
        team_id: str,
        league: str,
        days_ahead: int = 14,
    ) -> list[Event]:
        """Get schedule for a team (past and future games)."""
        cache_key = make_cache_key("schedule", league, team_id)

        # Check cache (deserialize from dict)
        cached = self._cache.get(cache_key)
        if cached is not None:
            if isinstance(cached, list) and any(
                _event_dict_is_stale(e) for e in cached if isinstance(e, dict)
            ):
                logger.debug(
                    "[CACHE_STALE] %s — team data missing short_name, re-fetching",
                    cache_key,
                )
                self._cache.delete(cache_key)
            else:
                logger.debug("[CACHE_HIT] %s", cache_key)
                try:
                    return [_enrich_event_teams(dict_to_event(e)) for e in cached]
                except (KeyError, TypeError) as e:
                    logger.warning("[CACHE_ERROR] Deserialization failed: %s", e)

        # Fetch from provider
        for provider in self._providers:
            if provider.supports_league(league):
                events = provider.get_team_schedule(team_id, league, days_ahead)
                if events:
                    # Serialize to dict before caching
                    serialized = [event_to_dict(e) for e in events]
                    self._cache.set(cache_key, serialized, CACHE_TTL_SCHEDULE)
                    return [_enrich_event_teams(e) for e in events]
        return []

    def get_team(self, team_id: str, league: str) -> Team | None:
        """Get team details."""
        cache_key = make_cache_key("team", league, team_id)

        # Check cache (deserialize from dict)
        cached = self._cache.get(cache_key)
        if cached is not None:
            if _team_dict_is_stale(cached):
                logger.debug(
                    "[CACHE_STALE] %s — team data missing short_name, re-fetching",
                    cache_key,
                )
                self._cache.delete(cache_key)
            else:
                logger.debug("[CACHE_HIT] %s", cache_key)
                try:
                    return dict_to_team(cached)
                except (KeyError, TypeError) as e:
                    logger.warning("[CACHE_ERROR] Deserialization failed: %s", e)

        # Fetch from provider
        for provider in self._providers:
            if provider.supports_league(league):
                team = provider.get_team(team_id, league)
                if team:
                    # Serialize to dict before caching
                    self._cache.set(cache_key, team_to_dict(team), CACHE_TTL_TEAM_INFO)
                    return team
        return None

    def get_event(self, event_id: str, league: str) -> Event | None:
        """Get a specific event by ID.

        Uses shorter TTL (30min) since this is called for fresh scores/odds.
        """
        # Guard against empty event_id which would cause malformed API requests
        if not event_id:
            logger.warning(
                "[SPORTS_DATA] get_event called with empty event_id for league %s", league
            )
            return None

        cache_key = make_cache_key("event", league, event_id)

        # Check cache (deserialize from dict)
        cached = self._cache.get(cache_key)
        if cached is not None:
            if isinstance(cached, dict) and _event_dict_is_stale(cached):
                logger.debug(
                    "[CACHE_STALE] %s — team data missing short_name, re-fetching",
                    cache_key,
                )
                self._cache.delete(cache_key)
            else:
                logger.debug("[CACHE_HIT] %s", cache_key)
                try:
                    return _enrich_event_teams(dict_to_event(cached))
                except (KeyError, TypeError) as e:
                    logger.warning("[CACHE_ERROR] Deserialization failed: %s", e)

        for provider in self._providers:
            if provider.supports_league(league):
                event = provider.get_event(event_id, league)
                if event:
                    # Serialize to dict before caching
                    self._cache.set(cache_key, event_to_dict(event), CACHE_TTL_SINGLE_EVENT)
                    return _enrich_event_teams(event)
        return None

    # Fields refreshed onto the original event by refresh_event_status. Anything
    # not listed here is preserved from the original — teams, start_time, league,
    # sport, season_type, etc. don't change between fetches and the summary
    # endpoint may return degraded versions of them (e.g. ESPN omits
    # shortDisplayName), so overwriting would be destructive, not additive.
    _REFRESH_FIELDS = (
        "status",
        "home_score",
        "away_score",
        "broadcasts",
        "odds_data",
        "fight_result_method",
        "finish_round",
        "finish_time",
    )

    def refresh_event_status(self, event: Event) -> Event:
        """Overlay fresh status (and other game-state fields) onto event.

        The summary endpoint can return a strict subset of what scoreboard
        returned — most notably ESPN's summary omits shortDisplayName, so
        replacing the event wholesale wipes team short_names. This function
        instead fetches fresh data and overlays only the fields that
        legitimately change during a game (status, scores, broadcasts,
        odds, fight result), preserving everything else from the original.

        Args:
            event: Event with potentially stale status from schedule/scoreboard cache

        Returns:
            Event with refreshed game-state fields, original team/identity data
        """
        if not event:
            return event

        # Invalidate cache to force fresh fetch from provider
        cache_key = make_cache_key("event", event.league, event.id)
        self._cache.delete(cache_key)

        fresh_event = self.get_event(event.id, event.league)
        if not fresh_event:
            logger.debug(
                "[SPORTS_DATA] Could not refresh event %s, using cached status", event.id
            )
            return event

        logger.debug(
            "[REFRESH] event=%s status: %s → %s",
            event.id,
            event.status.state if event.status else "N/A",
            fresh_event.status.state if fresh_event.status else "N/A",
        )

        # Build the overlay: take each refresh field from the fresh event when
        # it has a meaningful value, otherwise fall back to the original. This
        # is what makes the merge additive — an empty/None value in the fresh
        # response never clobbers data we already had.
        overlay: dict = {}
        for field_name in self._REFRESH_FIELDS:
            fresh_val = getattr(fresh_event, field_name, None)
            orig_val = getattr(event, field_name, None)
            if field_name == "status":
                # Status is the whole point of the refresh — always take fresh
                # when present, even if state is unchanged (other status fields
                # like clock/period may have updated).
                overlay[field_name] = fresh_val if fresh_val is not None else orig_val
            else:
                overlay[field_name] = fresh_val if fresh_val else orig_val
        return replace(event, **overlay)

    def get_team_stats(self, team_id: str, league: str) -> TeamStats | None:
        """Get detailed team statistics."""
        cache_key = make_cache_key("stats", league, team_id)

        # Check cache (deserialize from dict)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("[CACHE_HIT] %s", cache_key)
            try:
                return dict_to_stats(cached)
            except (KeyError, TypeError) as e:
                logger.warning("[CACHE_ERROR] Deserialization failed: %s", e)

        # Fetch from provider
        for provider in self._providers:
            if provider.supports_league(league):
                stats = provider.get_team_stats(team_id, league)
                if stats:
                    # Serialize to dict before caching
                    self._cache.set(cache_key, stats_to_dict(stats), CACHE_TTL_TEAM_STATS)
                    return stats
        return None

    # Cache management

    def get_provider_name(self, league: str) -> str | None:
        """Get the provider name that handles a league.

        Returns provider name (e.g., 'espn', 'tsdb') or None if no provider.
        """
        for provider in self._providers:
            if provider.supports_league(league):
                return provider.name
        return None

    def cache_stats(self) -> dict:
        """Get cache statistics."""
        return self._cache.stats()

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    def flush_cache(self) -> int:
        """Flush dirty cache entries to SQLite.

        Call after EPG generation for immediate persistence.
        Returns number of entries written.
        """
        return self._cache.flush()

    def invalidate_team(self, team_id: str, league: str) -> None:
        """Invalidate all cached data for a team."""
        self._cache.delete(make_cache_key("team", league, team_id))
        self._cache.delete(make_cache_key("stats", league, team_id))
        self._cache.delete(make_cache_key("schedule", league, team_id))

    def provider_stats(self) -> dict:
        """Get statistics from all providers for UI feedback.

        Returns a dict with provider-specific stats including:
        - Rate limit status (TSDB)
        - Cache statistics (if provider has internal cache)

        Example response:
        {
            "espn": {"name": "espn", "has_rate_limit": False},
            "tsdb": {
                "name": "tsdb",
                "has_rate_limit": True,
                "rate_limit": {
                    "total_requests": 10,
                    "is_rate_limited": True,
                    "total_wait_seconds": 45.2,
                    ...
                },
                "cache": {"total_entries": 5, ...}
            }
        }
        """
        stats = {}
        for provider in self._providers:
            provider_stats: dict = {"name": provider.name, "has_rate_limit": False}

            # Check for TSDB-specific stats
            if hasattr(provider, "_client"):
                client = provider._client
                if hasattr(client, "rate_limit_stats"):
                    provider_stats["has_rate_limit"] = True
                    provider_stats["rate_limit"] = client.rate_limit_stats().to_dict()
                if hasattr(client, "cache_stats"):
                    provider_stats["cache"] = client.cache_stats()

            stats[provider.name] = provider_stats

        return stats

    def reset_provider_stats(self) -> None:
        """Reset provider statistics (call at start of EPG generation).

        Resets rate limit counters so each generation has clean stats.
        """
        for provider in self._providers:
            if hasattr(provider, "_client"):
                client = provider._client
                if hasattr(client, "reset_rate_limit_stats"):
                    client.reset_rate_limit_stats()

    def prewarm_tsdb_leagues(self, leagues: list[str], days_ahead: int = 14) -> None:
        """Pre-warm TSDB events cache for multiple leagues.

        Fetches events for each league/day upfront, populating the cache.
        This ensures all subsequent get_team_schedule calls are cache hits.

        NOTE: Team name lookup uses seeded database cache (not API), so we
        only need to pre-warm events, not teams. This saves 2 API calls per league.

        Args:
            leagues: List of canonical league codes to pre-warm
            days_ahead: Number of days to pre-warm (default 14, matches get_team_schedule)
        """
        from datetime import timedelta

        if not leagues:
            return

        # Find TSDB provider
        tsdb_provider = None
        for provider in self._providers:
            if provider.name == "tsdb":
                tsdb_provider = provider
                break

        if not tsdb_provider:
            logger.debug("[PREWARM] No TSDB provider registered, skipping pre-warm")
            return

        unique_leagues = list(set(leagues))
        today = date.today()

        # Cap to TSDB's max days (same as provider)
        days_ahead = min(days_ahead, 14)

        total_calls = len(unique_leagues) * days_ahead  # N days per league
        logger.info(
            "[PREWARM] TSDB: %d leagues × %d days = ~%d API calls",
            len(unique_leagues),
            days_ahead,
            total_calls,
        )

        for league in unique_leagues:
            if not tsdb_provider.supports_league(league):
                continue

            # Pre-warm events cache for each day
            # Team names come from seeded database cache (no API needed)
            for i in range(days_ahead):
                target_date = today + timedelta(days=i)
                # Use get_events which goes through provider → client cache
                tsdb_provider.get_events(league, target_date)

            logger.debug("[PREWARM] TSDB league %s: %d days", league, days_ahead)
