"""Teams API endpoints."""

import json
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from teamarr.api.models import (
    TeamChannelStatusResponse,
    TeamCreate,
    TeamResponse,
    TeamUpdate,
)
from teamarr.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


def generate_channel_id(team_name: str, primary_league: str) -> str:
    """Generate channel ID from team name and league."""
    from teamarr.database.leagues import get_league_id

    name = "".join(
        word.capitalize()
        for word in "".join(c if c.isalnum() or c.isspace() else "" for c in team_name).split()
    )

    with get_db() as conn:
        league_id = get_league_id(conn, primary_league)

    return f"{name}.{league_id}"


def _can_consolidate_leagues(conn, league1: str, league2: str) -> bool:
    """Check if two leagues can be consolidated (same team plays in both).

    ONLY soccer teams play in multiple competitions (EPL + Champions League),
    so only soccer leagues can consolidate.

    All other sports (NFL, NCAAF, NHL, NBA, etc.) have separate teams per league
    and ESPN reuses team IDs across leagues, so they must NOT be consolidated.

    Returns:
        True if leagues can share a team, False if they must be separate.
    """
    from teamarr.database.leagues import get_league_sport

    if league1 == league2:
        return True

    # Only soccer leagues can consolidate across competitions
    sport1 = get_league_sport(conn, league1)
    sport2 = get_league_sport(conn, league2)

    if sport1 == "soccer" and sport2 == "soccer":
        return True

    # All other sports: do not consolidate
    return False


class BulkImportTeam(BaseModel):
    """Team data from cache for bulk import."""

    team_name: str
    team_abbrev: str | None = None
    provider: str
    provider_team_id: str
    league: str  # League this team was found in
    sport: str
    logo_url: str | None = None


class BulkImportRequest(BaseModel):
    """Bulk import request body."""

    teams: list[BulkImportTeam]


class BulkImportResponse(BaseModel):
    """Bulk import result."""

    imported: int
    updated: int  # Teams that had new leagues added
    skipped: int


@router.get("/teams", response_model=list[TeamResponse])
def list_teams(active_only: bool = False):
    """List all teams."""
    from teamarr.database.teams import list_teams as db_list_teams

    with get_db() as conn:
        return db_list_teams(conn, active_only=active_only)


@router.post("/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(team: TeamCreate):
    """Create a new team."""
    from teamarr.database.teams import create_team as db_create_team

    # Ensure primary_league is in leagues list
    leagues = list(set(team.leagues + [team.primary_league]))
    leagues_json = json.dumps(sorted(leagues))

    with get_db() as conn:
        try:
            return db_create_team(
                conn,
                provider=team.provider,
                provider_team_id=team.provider_team_id,
                primary_league=team.primary_league,
                leagues_json=leagues_json,
                sport=team.sport,
                team_name=team.team_name,
                team_abbrev=team.team_abbrev,
                team_logo_url=team.team_logo_url,
                team_color=team.team_color,
                channel_id=team.channel_id,
                channel_logo_url=team.channel_logo_url,
                template_id=team.template_id,
                active=team.active,
            )
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Team with this channel_id or provider/team_id/sport already exists",
                ) from None
            raise


@router.get("/teams/{team_id}", response_model=TeamResponse)
def get_team(team_id: int):
    """Get a team by ID."""
    from teamarr.database.teams import get_team as db_get_team

    with get_db() as conn:
        team = db_get_team(conn, team_id)
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
        return team


@router.get("/teams/{team_id}/channel-status", response_model=TeamChannelStatusResponse)
def get_team_channel_status(team_id: int):
    """Get Dispatcharr mapping and next live window for a static team channel."""
    from teamarr.database.teams import get_team as db_get_team
    from teamarr.database.teams import get_team_xmltv
    from teamarr.dispatcharr import ChannelManager, get_dispatcharr_client
    from teamarr.services.team_channel_status import build_team_channel_status

    with get_db() as conn:
        team = db_get_team(conn, team_id)
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

        xmltv_row = get_team_xmltv(conn, team_id)

    dispatcharr_channel = None
    dispatcharr_error = None
    try:
        client = get_dispatcharr_client(get_db)
        if client:
            manager = ChannelManager(client)
            dispatcharr_channel = manager.find_by_tvg_id(team["channel_id"])
        else:
            dispatcharr_error = "Dispatcharr connection not available"
    except Exception as exc:
        dispatcharr_error = str(exc)
        logger.warning(
            "[TEAMS] Failed to resolve Dispatcharr channel for team %s: %s",
            team_id,
            exc,
        )

    return build_team_channel_status(
        team=team,
        dispatcharr_channel=dispatcharr_channel,
        xmltv_content=xmltv_row["xmltv_content"] if xmltv_row else None,
        xmltv_updated_at=xmltv_row["updated_at"] if xmltv_row else None,
        dispatcharr_error=dispatcharr_error,
    )


@router.put("/teams/{team_id}", response_model=TeamResponse)
@router.patch("/teams/{team_id}", response_model=TeamResponse)
def update_team(team_id: int, team: TeamUpdate):
    """Update a team (full or partial)."""
    from teamarr.database.teams import update_team as db_update_team

    updates = {k: v for k, v in team.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    # Convert leagues list to JSON if present
    if "leagues" in updates:
        updates["leagues"] = json.dumps(updates["leagues"])

    with get_db() as conn:
        result = db_update_team(conn, team_id, updates)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
        return result


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: int):
    """Delete a team and its associated XMLTV content."""
    from teamarr.database.teams import delete_team as db_delete_team

    with get_db() as conn:
        if not db_delete_team(conn, team_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")


@router.post("/teams/bulk-import", response_model=BulkImportResponse)
def bulk_import_teams(request: BulkImportRequest):
    """Bulk import teams from cache.

    Delegates to service layer for business logic (soccer consolidation,
    deduplication, indexing). See teamarr/services/team_import.py.
    """
    from teamarr.services.team_import import ImportTeam
    from teamarr.services.team_import import bulk_import_teams as do_import

    import_teams = [
        ImportTeam(
            team_name=t.team_name,
            team_abbrev=t.team_abbrev,
            provider=t.provider,
            provider_team_id=t.provider_team_id,
            league=t.league,
            sport=t.sport,
            logo_url=t.logo_url,
        )
        for t in request.teams
    ]

    with get_db() as conn:
        result = do_import(conn, import_teams)

    return BulkImportResponse(
        imported=result.imported, updated=result.updated, skipped=result.skipped
    )


class BulkChannelIdRequest(BaseModel):
    """Bulk channel ID update request."""

    team_ids: list[int]
    format_template: str


class BulkChannelIdResponse(BaseModel):
    """Bulk channel ID update response."""

    updated: int
    errors: list[str]


@router.post("/teams/bulk-channel-id", response_model=BulkChannelIdResponse)
def bulk_update_channel_ids(request: BulkChannelIdRequest):
    """Bulk update channel IDs based on a format template.

    Supported format variables:
    - {team_name_pascal}: Team name in PascalCase (e.g., "MichiganWolverines")
    - {team_abbrev}: Team abbreviation lowercase (e.g., "mich")
    - {team_name}: Team name lowercase with dashes (e.g., "michigan-wolverines")
    - {provider_team_id}: Provider's team ID
    - {league_id}: League code lowercase (e.g., "ncaam")
    - {league}: League display name (e.g., "NCAAM")
    - {sport}: Sport name lowercase (e.g., "basketball")
    """
    from teamarr.database.teams import bulk_update_channel_ids as db_bulk_update

    if not request.team_ids:
        return BulkChannelIdResponse(updated=0, errors=["No teams selected"])

    if not request.format_template:
        return BulkChannelIdResponse(updated=0, errors=["No format template provided"])

    with get_db() as conn:
        updated_count, errors = db_bulk_update(conn, request.team_ids, request.format_template)

    return BulkChannelIdResponse(updated=updated_count, errors=errors[:5])
