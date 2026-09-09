"""Team and league cache API endpoints.

Provides endpoints for cache management:
- GET /cache/status - Get cache statistics
- POST /cache/refresh - Trigger cache refresh
- GET /cache/refresh/status - Get refresh progress
- GET /cache/leagues - List cached leagues
- GET /cache/teams/search - Search teams by name
"""

from fastapi import APIRouter, HTTPException, Query

from teamarr.api.cache_refresh import start_cache_refresh
from teamarr.api.cache_refresh_status import (
    get_refresh_status,
)
from teamarr.database import get_db
from teamarr.database.team_cache import (
    get_league_teams as db_get_league_teams,
)
from teamarr.database.team_cache import (
    get_team_picker_leagues as db_get_picker_leagues,
)
from teamarr.database.team_cache import (
    list_sports as db_list_sports,
)
from teamarr.database.team_cache import (
    search_teams as db_search,
)
from teamarr.services import create_cache_service

router = APIRouter(prefix="/cache")


@router.get("/status")
def get_cache_status() -> dict:
    """Get cache statistics and status.

    Returns:
        Cache status including last refresh time, counts, and staleness
    """
    cache_service = create_cache_service(get_db)
    stats = cache_service.get_stats()

    return {
        "last_refresh": stats.last_refresh.isoformat() if stats.last_refresh else None,
        "leagues_count": stats.leagues_count,
        "teams_count": stats.teams_count,
        "refresh_duration_seconds": stats.refresh_duration_seconds,
        "is_stale": stats.is_stale,
        "is_empty": stats.is_empty,
        "refresh_in_progress": stats.refresh_in_progress,
        "last_error": stats.last_error,
    }


@router.get("/refresh/status")
def get_refresh_progress() -> dict:
    """Get current cache refresh progress.

    Returns:
        Current refresh status including percent, message, phase
    """
    return get_refresh_status()


@router.post("/refresh")
def trigger_refresh():
    """Start a cache refresh and return immediately with its shared status."""
    if not start_cache_refresh(get_db):
        raise HTTPException(status_code=409, detail="Cache refresh already in progress")
    return get_refresh_status()


@router.get("/sports")
def list_sports() -> dict:
    """Get all sport codes and their display names.

    Returns:
        Dict mapping sport codes to display names
    """

    with get_db() as conn:
        sports = db_list_sports(conn)

    return {"sports": sports}


@router.get("/leagues")
def list_leagues(
    sport: str | None = Query(None, description="Filter by sport (e.g., 'soccer')"),
    provider: str | None = Query(None, description="Filter by provider"),
    import_only: bool = Query(False, description="Only import-enabled leagues"),
) -> dict:
    """List all available leagues.

    By default, returns all leagues (configured + discovered).
    Use import_only=True for Team Importer to get only explicitly configured
    leagues with import_enabled=1.

    Args:
        sport: Optional sport filter
        provider: Optional provider filter
        import_only: If True, only return import-enabled configured leagues

    Returns:
        List of leagues
    """
    cache_service = create_cache_service(get_db)
    leagues = cache_service.get_leagues(
        sport=sport, provider=provider, import_enabled_only=import_only
    )

    return {
        "count": len(leagues),
        "leagues": [
            {
                "slug": league.slug,
                "provider": league.provider,
                "name": league.name,
                "sport": league.sport,
                "team_count": league.team_count,
                "logo_url": league.logo_url,
                "logo_url_dark": league.logo_url_dark,
                "import_enabled": league.import_enabled,
                "league_alias": league.league_alias,
            }
            for league in leagues
        ],
    }


@router.get("/teams/search")
def search_teams(
    q: str = Query(..., min_length=2, description="Search query (team name)"),
    league: str | None = Query(None, description="Filter by league slug"),
    sport: str | None = Query(None, description="Filter by sport"),
) -> dict:
    """Search for teams in the cache."""

    with get_db() as conn:
        teams = db_search(conn, query=q, league=league, sport=sport)

    return {
        "query": q,
        "count": len(teams),
        "teams": teams,
    }


@router.get("/leagues/{league_slug}/teams")
def get_league_teams(league_slug: str) -> list[dict]:
    """Get all teams for a specific league.

    Args:
        league_slug: League identifier (e.g., 'nfl', 'eng.1')

    Returns:
        List of teams in the league
    """

    with get_db() as conn:
        return db_get_league_teams(conn, league_slug)


@router.get("/leagues/{league_slug}/conferences")
def get_league_conferences(league_slug: str) -> list[dict]:
    """Cached conference groups for a league, with member team ids (#91).

    Serves the Team Importer's conference filter. Empty list for leagues
    without conference data (only NCAA football/basketball have it) — the
    UI hides the filter.
    """
    from teamarr.database.provider_groups import get_league_groups

    with get_db() as conn:
        return get_league_groups(conn, league_slug)


@router.get("/team-picker-leagues")
def get_team_picker_leagues() -> dict:
    """Get all leagues from team_cache for the TeamPicker component.

    Returns unique leagues from team_cache with their sports.
    Leagues that exist in the configured leagues table sort first.
    This endpoint is the source of truth for TeamPicker to avoid
    "unknown sport" issues.

    Returns:
        List of leagues with sport and is_configured flag, plus sport display names
    """

    with get_db() as conn:
        leagues = db_get_picker_leagues(conn)

    return {
        "count": len(leagues),
        "leagues": leagues,
    }
