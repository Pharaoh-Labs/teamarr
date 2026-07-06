"""Team and league cache API endpoints.

Provides endpoints for cache management:
- GET /cache/status - Get cache statistics
- POST /cache/refresh - Trigger cache refresh (SSE streaming)
- GET /cache/refresh/status - Get refresh progress
- GET /cache/leagues - List cached leagues
- GET /cache/teams/search - Search teams by name
"""

import json
import logging
import queue
import threading

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from teamarr.api.cache_refresh_status import (
    complete_refresh,
    fail_refresh,
    get_refresh_status,
    is_refresh_in_progress,
    start_refresh,
    update_refresh_status,
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
from teamarr.services.league_mappings import get_league_mapping_service

logger = logging.getLogger(__name__)

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
    """Trigger a cache refresh from all providers with SSE progress streaming.

    Streams real-time progress updates via Server-Sent Events.
    Frontend should connect with EventSource to receive updates.

    Returns:
        SSE stream with progress updates
    """
    # Check if already in progress
    if is_refresh_in_progress():
        err = {"status": "error", "message": "Cache refresh already in progress"}
        return StreamingResponse(
            iter([f"data: {json.dumps(err)}\n\n"]),
            media_type="text/event-stream",
        )

    # Mark as started
    if not start_refresh():
        err = {"status": "error", "message": "Failed to start cache refresh"}
        return StreamingResponse(
            iter([f"data: {json.dumps(err)}\n\n"]),
            media_type="text/event-stream",
        )

    # Queue for progress updates
    progress_queue: queue.Queue = queue.Queue()

    def generate():
        """Generator function for SSE stream."""

        def run_refresh():
            """Run cache refresh in background thread."""
            try:
                svc = create_cache_service(get_db)

                # Progress callback that updates status and queues for SSE
                def progress_callback(message: str, percent: int) -> None:
                    update_refresh_status(
                        status="progress",
                        message=message,
                        percent=percent,
                    )
                    progress_queue.put(get_refresh_status())

                result = svc.refresh(progress_callback=progress_callback)

                if result.success:
                    # Reload league mapping service so in-memory caches
                    # pick up newly discovered league names from league_cache
                    try:
                        get_league_mapping_service().reload()
                    except RuntimeError:
                        pass  # Service not initialized (shouldn't happen)

                    complete_refresh(
                        {
                            "success": True,
                            "leagues_count": result.leagues_added,
                            "teams_count": result.teams_added,
                            "duration_seconds": result.duration_seconds,
                        }
                    )
                else:
                    fail_refresh("; ".join(result.errors) if result.errors else "Unknown error")

                progress_queue.put(get_refresh_status())

            except Exception as e:
                logger.exception("Cache refresh failed")
                fail_refresh(str(e))
                progress_queue.put(get_refresh_status())

            finally:
                progress_queue.put({"_done": True})

        # Start refresh thread
        refresh_thread = threading.Thread(target=run_refresh, daemon=True)
        refresh_thread.start()

        # Stream progress updates
        while True:
            try:
                data = progress_queue.get(timeout=0.5)

                if data.get("_done"):
                    break

                yield f"data: {json.dumps(data)}\n\n"

            except queue.Empty:
                # Send heartbeat to keep connection alive
                yield ": heartbeat\n\n"

        # Wait for thread to complete
        refresh_thread.join(timeout=5)

        # Send final status
        yield f"data: {json.dumps(get_refresh_status())}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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
                "tsdb_tier": league.tsdb_tier,
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


