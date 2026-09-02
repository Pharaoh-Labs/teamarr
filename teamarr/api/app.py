"""FastAPI application factory."""

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from teamarr.api.routes import (
    aliases,
    backup,
    cache,
    channels,
    detection_keywords,
    dispatcharr,
    epg,
    groups,
    health,
    keywords,
    leagues,
    logs,
    numbering_exceptions,
    presets,
    settings,
    sort_priorities,
    stats,
    subscription,
    support,
    teams,
    templates,
    variables,
)
from teamarr.api.startup_state import StartupPhase, get_startup_state
from teamarr.config import BASE_VERSION, set_display_settings, set_matchup_orders, set_timezone
from teamarr.database import get_db, init_db
from teamarr.database.settings import get_display_settings, get_epg_settings, get_scheduler_settings
from teamarr.database.stats import cleanup_stuck_runs
from teamarr.database.subscription import get_league_configs
from teamarr.dispatcharr import close_dispatcharr, get_factory
from teamarr.providers import ProviderRegistry
from teamarr.services import (
    create_cache_service,
    create_scheduler_service,
    init_league_mapping_service,
)
from teamarr.utilities.logging import setup_logging

logger = logging.getLogger(__name__)


def _cleanup_orphaned_xmltv(conn) -> None:
    """Clean up XMLTV content for disabled or deleted teams/groups.

    Called on startup to ensure no stale XMLTV data persists.
    """
    try:
        # Delete XMLTV for inactive teams
        cursor = conn.execute("""
            DELETE FROM team_epg_xmltv
            WHERE team_id IN (SELECT id FROM teams WHERE active = 0)
        """)
        if cursor.rowcount > 0:
            logger.info("[STARTUP] Cleaned up XMLTV for %d disabled teams", cursor.rowcount)

        # Delete XMLTV for disabled groups
        cursor = conn.execute("""
            DELETE FROM event_epg_xmltv
            WHERE group_id IN (SELECT id FROM event_epg_groups WHERE enabled = 0)
        """)
        if cursor.rowcount > 0:
            logger.info("[STARTUP] Cleaned up XMLTV for %d disabled groups", cursor.rowcount)

        # Delete orphaned XMLTV (team/group no longer exists)
        cursor = conn.execute("""
            DELETE FROM team_epg_xmltv
            WHERE team_id NOT IN (SELECT id FROM teams)
        """)
        if cursor.rowcount > 0:
            logger.info("[STARTUP] Cleaned up %d orphaned team XMLTV entries", cursor.rowcount)

        cursor = conn.execute("""
            DELETE FROM event_epg_xmltv
            WHERE group_id NOT IN (SELECT id FROM event_epg_groups)
        """)
        if cursor.rowcount > 0:
            logger.info("[STARTUP] Cleaned up %d orphaned group XMLTV entries", cursor.rowcount)
    except Exception as e:
        # Log actual error for diagnosis, but don't crash startup
        logger.warning("[STARTUP] XMLTV cleanup failed: %s", e)


def _run_ufc_segment_migration(db_factory, migration_name: str = "ufc_segment_fix_v1"):
    """One-time migration to fix UFC segment handling.

    Clears UFC event cache and managed channels so they're recreated
    with proper segment_times and segment-aware event_ids.

    Uses a migrations table to track completion (runs only once per migration_name).
    """
    try:
        with db_factory() as conn:
            # Create migrations table if it doesn't exist
            conn.execute("""
                CREATE TABLE IF NOT EXISTS migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Check if migration already ran
            cursor = conn.execute("SELECT 1 FROM migrations WHERE name = ?", (migration_name,))
            if cursor.fetchone():
                return  # Already migrated

            # Clear UFC event cache entries
            cursor = conn.execute("DELETE FROM service_cache WHERE cache_key LIKE 'events:ufc:%'")
            events_cleared = cursor.rowcount

            # Delete UFC managed channels (will be recreated with segment IDs)
            cursor = conn.execute("DELETE FROM managed_channels WHERE league = 'ufc'")
            channels_cleared = cursor.rowcount

            # Clear UFC fingerprint cache
            cursor = conn.execute("DELETE FROM stream_match_cache WHERE league = 'ufc'")
            fingerprints_cleared = cursor.rowcount

            # Mark migration as done
            conn.execute("INSERT INTO migrations (name) VALUES (?)", (migration_name,))
            conn.commit()

            if events_cleared or channels_cleared or fingerprints_cleared:
                logger.info(
                    "[MIGRATION] %s: cleared %d events, %d channels, %d fingerprints",
                    migration_name,
                    events_cleared,
                    channels_cleared,
                    fingerprints_cleared,
                )
    except Exception as e:
        logger.warning("[MIGRATION] %s failed: %s", migration_name, e)


def _warn_if_tsdb_leagues_keyless(db_factory) -> None:
    """One-time startup notice (#676): TSDB is premium-key only.

    Without a key the provider isn't constructed, so subscribed TSDB
    leagues silently produce no events — say so once, loudly, at startup.
    Never blocks startup.
    """
    import json as _json

    try:
        if ProviderRegistry.get("tsdb") is not None:
            return  # key configured — nothing to warn about
        with db_factory() as conn:
            row = conn.execute(
                "SELECT leagues FROM sports_subscription WHERE id = 1"
            ).fetchone()
            subscribed = set(_json.loads(row["leagues"] or "[]")) if row else set()
            if not subscribed:
                return
            tsdb_leagues = sorted(
                r["league_code"]
                for r in conn.execute(
                    "SELECT league_code FROM leagues WHERE provider = 'tsdb' AND enabled = 1"
                )
                if r["league_code"] in subscribed
            )
        if tsdb_leagues:
            logger.warning(
                "[STARTUP] %d subscribed league(s) use TheSportsDB, which now "
                "requires a premium API key — they will produce no events until "
                "a key is added in Settings > General: %s",
                len(tsdb_leagues),
                ", ".join(tsdb_leagues),
            )
    except Exception:  # noqa: BLE001 — advisory only, never block startup
        logger.debug("[STARTUP] TSDB keyless-subscription check failed", exc_info=True)


def _run_startup_tasks():
    """Run startup tasks in background thread."""

    startup_state = get_startup_state()

    try:
        # Initialize services and providers with dependencies
        startup_state.set_phase(StartupPhase.INITIALIZING)
        league_mapping_service = init_league_mapping_service(get_db)
        ProviderRegistry.initialize(league_mapping_service)
        from teamarr.providers import reload_provider_request_policy

        reload_provider_request_policy()
        logger.info("[STARTUP] League mapping service and providers initialized")
        _warn_if_tsdb_leagues_keyless(get_db)

        # One-time migrations: Clear UFC caches for segment fixes
        # v1: Initial segment_times and segment-aware event_ids
        # v2: Cross-group consolidation and event_date fixes
        # v3: Switch from app API to scoreboard (correct times)
        _run_ufc_segment_migration(get_db, "ufc_segment_fix_v1")
        _run_ufc_segment_migration(get_db, "ufc_segment_fix_v2")
        _run_ufc_segment_migration(get_db, "ufc_segment_fix_v3")

        # Refresh team/league cache (this takes time)
        skip_cache = os.getenv("SKIP_CACHE_REFRESH", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if skip_cache:
            logger.info("[STARTUP] Cache refresh skipped (SKIP_CACHE_REFRESH set)")
        else:
            startup_state.set_phase(StartupPhase.REFRESHING_CACHE)
            cache_service = create_cache_service(get_db)
            logger.info("[STARTUP] Refreshing team/league cache on startup...")
            cache_service.refresh()
            logger.info("[STARTUP] Team/league cache refreshed")

        # Reload league mapping service to pick up new league names from cache
        league_mapping_service.reload()

        # Load display settings from database into config cache
        startup_state.set_phase(StartupPhase.LOADING_SETTINGS)

        with get_db() as conn:
            # Load timezone
            epg_settings = get_epg_settings(conn)
            set_timezone(epg_settings.epg_timezone)

            # Load display settings
            display = get_display_settings(conn)
            set_display_settings(
                time_format=display.time_format,
                show_timezone=display.show_timezone,
                channel_id_format=display.channel_id_format,
                xmltv_generator_name=display.xmltv_generator_name,
                xmltv_generator_url=display.xmltv_generator_url,
            )
            # Matchup order (#692): global + per-league overrides
            set_matchup_orders(
                display.matchup_order,
                {c.league_code: c.matchup_order for c in get_league_configs(conn)},
            )
        logger.info("[STARTUP] Display settings loaded into config cache")

        # Initialize Dispatcharr factory (lazy connection)
        startup_state.set_phase(StartupPhase.CONNECTING_DISPATCHARR)
        try:
            factory = get_factory(get_db)
            if factory.is_configured:
                logger.info(
                    "[STARTUP] Dispatcharr configured, connection will be established on first use"
                )
            else:
                logger.info("[STARTUP] Dispatcharr not configured")
        except Exception as e:
            logger.warning("[STARTUP] Failed to initialize Dispatcharr factory: %s", e)

        # Start background scheduler if enabled
        startup_state.set_phase(StartupPhase.STARTING_SCHEDULER)

        with get_db() as conn:
            scheduler_settings = get_scheduler_settings(conn)
            epg_settings = get_epg_settings(conn)

        from teamarr.config.runtime import dry_run, scheduler_enabled

        if dry_run():
            logger.warning(
                "[STARTUP] DRY_RUN=true — outbound writes (Dispatcharr channels/streams, "
                "media-server refreshes) will be logged, not executed"
            )

        if scheduler_settings.enabled and not scheduler_enabled():
            logger.warning(
                "[STARTUP] SCHEDULER=off — background scheduler NOT started; "
                "timed generation, backups and channel resets are disabled "
                "(manual generation still works)"
            )
        elif scheduler_settings.enabled:
            try:
                # Get Dispatcharr connection for scheduler (may be None)
                # Must use get_connection() to get the full DispatcharrConnection
                # with .m3u, .channels, .epg managers (not just the raw client)
                connection = None
                try:
                    factory = get_factory()
                    connection = factory.get_connection()
                except Exception as e:
                    logger.debug(
                        "[STARTUP] Dispatcharr connection unavailable for scheduler: %s", e
                    )

                scheduler_service = create_scheduler_service(get_db, connection)
                cron_expr = epg_settings.cron_expression or "0 * * * *"
                started = scheduler_service.start(cron_expression=cron_expr)
                if started:
                    logger.info("[STARTUP] Background scheduler started (cron: %s)", cron_expr)
                # Store scheduler service reference for shutdown
                _app_state["scheduler_service"] = scheduler_service
            except Exception as e:
                logger.warning("[STARTUP] Failed to start scheduler: %s", e)
        else:
            logger.info("[STARTUP] Background scheduler disabled")

        startup_state.set_phase(StartupPhase.READY)
        logger.info("[STARTUP] Teamarr ready")

    except Exception as e:
        logger.exception("[STARTUP] Failed: %s", e)
        startup_state.set_error(str(e))


# Store app-level state for cleanup
_app_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - runs on startup and shutdown."""

    # Startup - minimal blocking, then background tasks
    setup_logging()
    logger.info("[STARTUP] Starting Teamarr...")

    # Initialize database (fast)
    init_db()

    # Cleanup any stuck processing runs from previous crashes

    with get_db() as conn:
        cleanup_stuck_runs(conn)

        # Clean up orphaned XMLTV content (disabled teams/groups, deleted entries)
        _cleanup_orphaned_xmltv(conn)

    # Start background startup tasks (cache refresh, etc.)
    startup_thread = threading.Thread(target=_run_startup_tasks, daemon=True)
    startup_thread.start()

    yield

    # Shutdown
    logger.info("[SHUTDOWN] Shutting down Teamarr...")

    # Stop scheduler
    scheduler_service = _app_state.get("scheduler_service")
    if scheduler_service:
        scheduler_service.stop()

    # Close Dispatcharr connection
    close_dispatcharr()

    logger.info("[SHUTDOWN] Teamarr stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Teamarr API",
        description="Sports EPG generation service",
        version=BASE_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Add gzip compression for large responses
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Include API routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(teams.router, prefix="/api/v1", tags=["Teams"])
    app.include_router(templates.router, prefix="/api/v1", tags=["Templates"])
    app.include_router(presets.router, prefix="/api/v1/presets", tags=["Condition Presets"])
    app.include_router(groups.router, prefix="/api/v1/groups", tags=["Event Groups"])
    app.include_router(aliases.router, prefix="/api/v1", tags=["Team Aliases"])
    app.include_router(epg.router, prefix="/api/v1", tags=["EPG"])
    app.include_router(keywords.router, prefix="/api/v1/keywords", tags=["Exception Keywords"])
    app.include_router(cache.router, prefix="/api/v1", tags=["Cache"])
    app.include_router(leagues.router, prefix="/api/v1", tags=["Custom Leagues"])
    app.include_router(logs.router, prefix="/api/v1", tags=["Logging"])
    app.include_router(channels.router, prefix="/api/v1/channels", tags=["Channels"])
    app.include_router(settings.router, prefix="/api/v1", tags=["Settings"])
    app.include_router(sort_priorities.router, prefix="/api/v1", tags=["Sort Priorities"])
    app.include_router(
        numbering_exceptions.router, prefix="/api/v1", tags=["Numbering Exceptions"]
    )
    app.include_router(stats.router, prefix="/api/v1/stats", tags=["Stats"])
    app.include_router(variables.router, prefix="/api/v1", tags=["Variables"])
    app.include_router(dispatcharr.router, prefix="/api/v1", tags=["Dispatcharr"])
    app.include_router(backup.router, prefix="/api/v1", tags=["Backup"])
    app.include_router(subscription.router, prefix="/api/v1", tags=["Subscription"])
    app.include_router(support.router, prefix="/api/v1", tags=["Support"])
    app.include_router(detection_keywords.router, tags=["Detection Keywords"])

    # Serve React UI static files
    frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        # Serve static assets (JS, CSS, etc.)
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        # Serve index.html for all non-API routes (SPA routing)
        @app.get("/{path:path}", include_in_schema=False)
        async def serve_spa(path: str):
            # IMPORTANT: Never serve SPA for API routes - let them 404 naturally
            # This prevents the catch-all from hijacking API requests
            if path.startswith("api/"):
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Not found")

            # Serve static files if they exist (favicon, etc.)
            file_path = frontend_dist / path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)

            # Fall back to index.html for SPA routing
            return FileResponse(frontend_dist / "index.html")

        logger.info("[STARTUP] Serving React UI from %s", frontend_dist)
    else:
        logger.warning("[STARTUP] Frontend dist not found at %s - UI not available", frontend_dist)

    return app


app = create_app()
