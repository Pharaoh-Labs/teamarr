"""Cache service facade.

This module provides a clean API for team/league cache operations.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from teamarr.database import get_db


@dataclass
class CacheStats:
    """Cache statistics."""

    last_refresh: datetime | None = None
    leagues_count: int = 0
    teams_count: int = 0
    refresh_duration_seconds: float | None = None
    is_stale: bool = False
    is_empty: bool = True
    refresh_in_progress: bool = False
    last_error: str | None = None


@dataclass
class LeagueInfo:
    """League information from cache."""

    slug: str
    provider: str
    name: str | None
    sport: str
    team_count: int = 0
    logo_url: str | None = None
    logo_url_dark: str | None = None
    import_enabled: bool = False
    league_alias: str | None = None  # Short display alias (e.g., 'EPL', 'UCL')
    tsdb_tier: str | None = None  # 'free', 'premium', or None (non-TSDB)


@dataclass
class TeamInfo:
    """Team information from cache."""

    name: str
    abbrev: str | None = None
    short_name: str | None = None
    provider: str = ""
    team_id: str = ""
    league: str = ""
    sport: str = ""
    logo_url: str | None = None


@dataclass
class RefreshResult:
    """Result of cache refresh."""

    success: bool = True
    leagues_added: int = 0
    teams_added: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class CacheService:
    """Service for team/league cache operations.

    Wraps the consumer layer CacheRefresher and TeamLeagueCache.
    """

    def __init__(self, db_factory: Callable[[], Any] | None = None):
        """Initialize with optional database factory."""
        self._db_factory = db_factory

    def get_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            CacheStats with counts, staleness, and refresh status
        """
        from teamarr.consumers.cache import get_cache

        cache = get_cache()
        stats = cache.get_cache_stats()

        return CacheStats(
            last_refresh=stats.last_refresh,
            leagues_count=stats.leagues_count,
            teams_count=stats.teams_count,
            refresh_duration_seconds=stats.refresh_duration_seconds,
            is_stale=stats.is_stale,
            is_empty=cache.is_cache_empty(),
            refresh_in_progress=stats.refresh_in_progress,
            last_error=stats.last_error,
        )

    def refresh(
        self,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> RefreshResult:
        """Refresh cache from all providers.

        Args:
            progress_callback: Optional callback for progress updates

        Returns:
            RefreshResult with counts and errors
        """
        from teamarr.consumers.cache import CacheRefresher

        refresher = CacheRefresher(self._db_factory) if self._db_factory else CacheRefresher()
        result = refresher.refresh(progress_callback)

        return RefreshResult(
            success=not result.get("errors"),
            leagues_added=result.get("leagues_count", 0),
            teams_added=result.get("teams_count", 0),
            duration_seconds=result.get("duration_seconds", 0.0),
            errors=result.get("errors", []),
        )

    def refresh_if_needed(self, max_age_days: int = 7) -> bool:
        """Refresh cache if stale.

        Args:
            max_age_days: Maximum age in days before refresh

        Returns:
            True if refresh was performed
        """
        from teamarr.consumers.cache import refresh_cache_if_needed

        return refresh_cache_if_needed(max_age_days)

    def get_leagues(
        self,
        sport: str | None = None,
        provider: str | None = None,
        import_enabled_only: bool = False,
        configured_only: bool = False,
    ) -> list[LeagueInfo]:
        """Get all leagues from cache.

        Args:
            sport: Optional sport filter
            provider: Optional provider filter
            import_enabled_only: Only return import-enabled leagues
            configured_only: Only return enabled configured leagues

        Returns:
            List of LeagueInfo
        """
        from teamarr.consumers.cache import get_cache

        cache = get_cache()
        leagues = cache.get_all_leagues(
            sport=sport,
            provider=provider,
            import_enabled_only=import_enabled_only,
            configured_only=configured_only,
        )

        return [
            LeagueInfo(
                slug=lg.league_slug,
                provider=lg.provider,
                name=lg.league_name,
                sport=lg.sport,
                team_count=lg.team_count,
                logo_url=lg.logo_url,
                logo_url_dark=lg.logo_url_dark,
                import_enabled=lg.import_enabled,
                league_alias=lg.league_alias,
                tsdb_tier=lg.tsdb_tier,
            )
            for lg in leagues
        ]

    def search_teams(
        self,
        query: str,
        league: str | None = None,
        sport: str | None = None,
        limit: int = 50,
    ) -> list[TeamInfo]:
        """Search for teams in cache.

        Args:
            query: Search query (partial match on name)
            league: Optional league filter
            sport: Optional sport filter
            limit: Maximum results

        Returns:
            List of matching TeamInfo
        """

        q_lower = query.lower().strip()

        with get_db() as conn:
            cursor = conn.cursor()

            sql = """
                SELECT team_name, team_abbrev, team_short_name, provider,
                       provider_team_id, league, sport, logo_url
                FROM team_cache
                WHERE (LOWER(team_name) LIKE ?
                       OR LOWER(team_abbrev) = ?
                       OR LOWER(team_short_name) LIKE ?)
            """
            params: list = [f"%{q_lower}%", q_lower, f"%{q_lower}%"]

            if league:
                sql += " AND league = ?"
                params.append(league)
            if sport:
                sql += " AND sport = ?"
                params.append(sport)

            sql += f" ORDER BY team_name LIMIT {limit}"
            cursor.execute(sql, params)

            return [
                TeamInfo(
                    name=row["team_name"],
                    abbrev=row["team_abbrev"],
                    short_name=row["team_short_name"],
                    provider=row["provider"],
                    team_id=row["provider_team_id"],
                    league=row["league"],
                    sport=row["sport"],
                    logo_url=row["logo_url"],
                )
                for row in cursor.fetchall()
            ]

    def find_candidate_leagues(
        self,
        team1: str,
        team2: str,
        sport: str | None = None,
    ) -> list[tuple[str, str]]:
        """Find leagues where both teams exist.

        Args:
            team1: First team name
            team2: Second team name
            sport: Optional sport filter

        Returns:
            List of (league, provider) tuples
        """
        from teamarr.consumers.cache import get_cache

        cache = get_cache()
        return cache.find_candidate_leagues(team1, team2, sport)

    def expand_leagues(
        self,
        leagues: list[str],
        provider: str | None = None,
    ) -> list[str]:
        """Expand special league patterns to actual league slugs.

        Handles patterns like:
        - "soccer_all" → all cached soccer leagues
        - "nfl" → ["nfl"] (pass-through)

        Args:
            leagues: List of league patterns
            provider: Optional provider filter

        Returns:
            Expanded list of league slugs
        """
        from teamarr.consumers.cache import expand_leagues

        return expand_leagues(leagues, provider)


def create_cache_service(
    db_factory: Callable[[], Any] | None = None,
) -> CacheService:
    """Factory function to create cache service."""
    return CacheService(db_factory)
