"""FastAPI application factory."""

from fastapi import FastAPI

from teamarr.api.routes import epg, health, teams, templates


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Teamarr API",
        description="Sports EPG generation service",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Include routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(teams.router, prefix="/api/v1", tags=["Teams"])
    app.include_router(templates.router, prefix="/api/v1", tags=["Templates"])
    app.include_router(epg.router, prefix="/api/v1", tags=["EPG"])

    return app


app = create_app()
