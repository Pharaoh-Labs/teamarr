"""Custom-league API endpoints (epic teamarrv2-eqz).

Hosts the custom-league feature: the premium-gated capability check (eqz.1),
the TSDB-only CRUD write path (eqz.2), and the live test-fetch validator
(eqz.3). Read access to the full league catalogue lives separately under
``/cache/leagues``.

All write/validate routes are hard-gated behind a TheSportsDB premium key and
reject any non-TSDB provider; edits and deletes only ever touch user-added
(``is_custom=1``) rows, so built-in leagues can never be mutated via the API.
"""

import logging
from typing import NoReturn

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from teamarr.database import get_db
from teamarr.services.custom_leagues import (
    CustomLeagueGateError,
    CustomLeagueNotFoundError,
    CustomLeagueProtectedError,
    CustomLeagueValidationError,
    create_custom_league_and_refresh,
    custom_leagues_enabled,
    delete_custom_league,
    list_custom_leagues_with_state,
    run_custom_league_test_fetch,
    supported_custom_league_sports,
    update_custom_league,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leagues")


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CustomLeagueCreate(BaseModel):
    """Body for creating a custom league. ``provider`` defaults to (and must be)
    ``tsdb``; the service rejects anything else."""

    league_code: str = Field(..., description="Canonical code, e.g. 'swe.1'")
    provider: str = Field("tsdb", description="Must be 'tsdb'")
    provider_league_id: str = Field(..., description="TSDB idLeague, e.g. '4460'")
    provider_league_name: str = Field(..., description="Exact TSDB strLeague")
    display_name: str = Field(..., description="Human-readable league name")
    sport: str = Field(..., description="Functional sport code")
    event_type: str | None = Field(None, description="team_vs_team | event_card")
    tsdb_tier: str | None = Field(None, description="'free' | 'premium'")
    allow_empty: bool = Field(
        False,
        description="Override the zero-events guardrail for an off-season league",
    )


class CustomLeagueUpdate(BaseModel):
    """Body for editing a custom league. ``league_code`` comes from the path and
    is immutable; the provider is fixed at ``tsdb``."""

    provider_league_id: str
    provider_league_name: str
    display_name: str
    sport: str
    event_type: str | None = None
    tsdb_tier: str | None = None


class CustomLeagueTestFetch(BaseModel):
    """Body for the live pre-save validation (eqz.3)."""

    provider_league_id: str = Field(..., description="TSDB idLeague to validate")
    sport: str = Field(..., description="Sport the user selected, cross-checked")
    provider_league_name: str | None = Field(
        None, description="Optional strLeague; cross-checked and reported as name_matches"
    )


# ---------------------------------------------------------------------------
# Exception → HTTP mapping
# ---------------------------------------------------------------------------


def _raise_http(exc: Exception) -> NoReturn:
    """Translate a custom-league service exception into an HTTPException."""
    if isinstance(exc, CustomLeagueGateError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, CustomLeagueProtectedError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, CustomLeagueNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, CustomLeagueValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/custom/capability")
def get_custom_league_capability() -> dict:
    """Report whether the custom-league feature is unlocked, and its sport list.

    The feature is hard-gated behind a TheSportsDB premium key. The frontend
    uses ``enabled`` to lock/hide the UI and ``supported_sports`` to populate
    the sport dropdown (only matcher-backed sports — never free text).

    Returns:
        ``{enabled: bool, supported_sports: [{sport_code, display_name}]}``
    """
    with get_db() as conn:
        enabled = custom_leagues_enabled(conn)
        sports = supported_custom_league_sports(conn)

    return {"enabled": enabled, "supported_sports": sports}


@router.get("/custom")
def get_custom_leagues() -> dict:
    """List all user-added (``is_custom=1``) leagues for the management UI.

    Each row carries a ``subscribed`` flag — ``False`` means the league exists
    but the global subscription won't match its events (the #240 footgun), so the
    UI can warn. New leagues auto-subscribe; this only trips if a user later
    unsubscribes one.

    Returns:
        ``{custom_leagues: [{league_code, provider, provider_league_id,
        provider_league_name, display_name, sport, event_type, tsdb_tier,
        enabled, subscribed}]}``
    """
    with get_db() as conn:
        return {"custom_leagues": list_custom_leagues_with_state(conn)}


@router.post("/custom/test-fetch")
def post_custom_league_test_fetch(body: CustomLeagueTestFetch) -> dict:
    """Live-validate a prospective custom league against TheSportsDB (eqz.3).

    Confirms the idLeague resolves, cross-checks the sport, and returns upcoming
    fixtures so the user can confirm before saving — the guard against the
    silent-empty-guide failure mode.
    """
    try:
        with get_db() as conn:
            return run_custom_league_test_fetch(
                conn,
                provider_league_id=body.provider_league_id,
                chosen_sport=body.sport,
                provider_league_name=body.provider_league_name,
            )
    except Exception as exc:  # noqa: BLE001 — mapped to HTTP below, else re-raised
        _raise_http(exc)


@router.post("", status_code=201)
def post_custom_league(body: CustomLeagueCreate) -> dict:
    """Create a custom league (TSDB-only, premium-gated, is_custom=1).

    On success the response includes a ``team_refresh`` summary — the scoped
    team-cache refresh (eqz.4) fired right after create so teams populate
    without waiting for the next full refresh.
    """
    try:
        return create_custom_league_and_refresh(
            league_code=body.league_code,
            provider=body.provider,
            provider_league_id=body.provider_league_id,
            provider_league_name=body.provider_league_name,
            display_name=body.display_name,
            sport=body.sport,
            event_type=body.event_type,
            tsdb_tier=body.tsdb_tier,
            allow_empty=body.allow_empty,
        )
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)


@router.put("/{league_code}")
def put_custom_league(league_code: str, body: CustomLeagueUpdate) -> dict:
    """Edit a custom league. Built-in leagues are rejected with 403."""
    try:
        with get_db() as conn:
            return update_custom_league(
                conn,
                league_code,
                provider_league_id=body.provider_league_id,
                provider_league_name=body.provider_league_name,
                display_name=body.display_name,
                sport=body.sport,
                event_type=body.event_type,
                tsdb_tier=body.tsdb_tier,
            )
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)


@router.delete("/{league_code}", status_code=204)
def delete_custom_league_route(league_code: str) -> None:
    """Delete a custom league. Built-in leagues are rejected with 403."""
    try:
        with get_db() as conn:
            delete_custom_league(conn, league_code)
    except Exception as exc:  # noqa: BLE001
        _raise_http(exc)
