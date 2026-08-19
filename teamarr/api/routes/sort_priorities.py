"""Sort priorities CRUD endpoints.

Manages the channel_sort_priorities table for global channel sorting.
Used when channel_sorting_scope is 'global' to determine channel order
across all AUTO event groups by sport and league.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from teamarr.database import get_db
from teamarr.database.sort_priorities import (
    delete_sort_priority,
    get_sort_priorities_with_channel_counts,
    get_sort_priority,
    upsert_sort_priority,
)

router = APIRouter(prefix="/sort-priorities", tags=["Sort Priorities"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class SortPriorityModel(BaseModel):
    """A sport/league sort priority entry."""

    id: int
    sport: str
    league_code: str | None = None
    sort_priority: int
    display_name: str | None = None
    channel_count: int | None = None


class SortPriorityCreate(BaseModel):
    """Create/update a sort priority entry."""

    sport: str
    league_code: str | None = None
    sort_priority: int


class SortPriorityReorder(BaseModel):
    """Bulk reorder request."""

    ordered_list: list[dict]  # [{"sport": "football", "league_code": None, "priority": 0}, ...]


class AutoPopulateResponse(BaseModel):
    """Response from auto-populate."""

    added: int
    message: str


class PriorityTeamModel(BaseModel):
    """A team whose channels float to the top of the global channel list."""

    id: int
    provider: str
    provider_team_id: str
    team_name: str
    league: str | None = None
    sport: str


class PriorityTeamCreate(BaseModel):
    """Add a priority team (a TeamPicker ``TeamFilterEntry``).

    Name + sport are resolved server-side from ``team_cache``.
    """

    provider: str
    team_id: str
    league: str | None = None


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("", response_model=list[SortPriorityModel])
def get_all_sort_priorities():
    """Get all sort priority entries ordered by priority.

    Returns all configured sport/league priorities, including those
    that may not have active AUTO groups.
    """

    with get_db() as conn:
        priorities = get_sort_priorities_with_channel_counts(conn)

    return [
        SortPriorityModel(
            id=p["id"],
            sport=p["sport"],
            league_code=p["league_code"],
            sort_priority=p["sort_priority"],
            display_name=p["display_name"],
            channel_count=p["channel_count"],
        )
        for p in priorities
    ]


@router.get("/active", response_model=list[SortPriorityModel])
def get_active_sort_priorities():
    """Get sort priorities only for sports/leagues with active AUTO groups.

    This filters to only include entries that are relevant to current
    channel numbering - sports/leagues that have enabled AUTO groups.
    """
    from teamarr.database.sort_priorities import get_active_sort_priorities

    with get_db() as conn:
        priorities = get_active_sort_priorities(conn)

    return [
        SortPriorityModel(
            id=p.id,
            sport=p.sport,
            league_code=p.league_code,
            sort_priority=p.sort_priority,
        )
        for p in priorities
    ]


@router.post("", response_model=SortPriorityModel)
def create_sort_priority(data: SortPriorityCreate):
    """Create or update a sort priority entry.

    If an entry for the sport/league_code combination already exists,
    it will be updated with the new priority.
    """

    with get_db() as conn:
        success = upsert_sort_priority(
            conn,
            sport=data.sport,
            league_code=data.league_code,
            priority=data.sort_priority,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create/update sort priority",
            )

        # Fetch the created/updated entry
        entry = get_sort_priority(conn, data.sport, data.league_code)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Entry created but could not be retrieved",
        )

    return SortPriorityModel(
        id=entry.id,
        sport=entry.sport,
        league_code=entry.league_code,
        sort_priority=entry.sort_priority,
    )


# =============================================================================
# PRIORITY TEAMS — a team-level tier that floats above sport/league ordering.
# Defined BEFORE the `/{sport}` routes below so `/teams/{id}` isn't shadowed by
# `DELETE /{sport}/{league_code}` (Starlette matches in definition order).
# =============================================================================


@router.get("/teams", response_model=list[PriorityTeamModel])
def get_priority_teams():
    """List teams whose channels float to the top of the global channel list."""
    from teamarr.database.priority_teams import get_priority_teams

    with get_db() as conn:
        teams = get_priority_teams(conn)

    return [PriorityTeamModel(**t) for t in teams]


@router.post("/teams", response_model=PriorityTeamModel)
def add_priority_team(data: PriorityTeamCreate):
    """Add a priority team. Name + sport are resolved from ``team_cache``."""
    from teamarr.database.priority_teams import add_priority_team

    with get_db() as conn:
        team = add_priority_team(
            conn,
            provider=data.provider,
            provider_team_id=data.team_id,
            league=data.league,
        )

    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found in cache — refresh the team directory and try again",
        )

    return PriorityTeamModel(**team)


@router.delete("/teams/{team_pk}")
def delete_priority_team(team_pk: int):
    """Remove a priority team by id."""
    from teamarr.database.priority_teams import delete_priority_team

    with get_db() as conn:
        removed = delete_priority_team(conn, team_pk)

    return {"success": removed, "id": team_pk}


@router.delete("/{sport}")
def delete_sort_priority_sport(sport: str):
    """Delete a sport-level sort priority entry."""

    with get_db() as conn:
        delete_sort_priority(conn, sport=sport, league_code=None)

    return {"success": True, "sport": sport, "league_code": None}


@router.delete("/{sport}/{league_code}")
def delete_sort_priority_league(sport: str, league_code: str):
    """Delete a league-level sort priority entry."""

    with get_db() as conn:
        delete_sort_priority(conn, sport=sport, league_code=league_code)

    return {"success": True, "sport": sport, "league_code": league_code}


@router.put("/reorder")
def reorder_sort_priorities(data: SortPriorityReorder):
    """Bulk reorder sort priorities based on UI drag-drop.

    The ordered_list should contain dicts with 'sport', 'league_code' (optional),
    and 'priority' fields. All specified entries will be updated.

    Example:
    ```json
    {
        "ordered_list": [
            {"sport": "football", "league_code": null, "priority": 0},
            {"sport": "football", "league_code": "nfl", "priority": 1},
            {"sport": "basketball", "league_code": null, "priority": 100}
        ]
    }
    ```
    """
    from teamarr.database.sort_priorities import reorder_sort_priorities

    if not data.ordered_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ordered_list cannot be empty",
        )

    with get_db() as conn:
        success = reorder_sort_priorities(conn, data.ordered_list)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reorder priorities",
            )

    return {"success": True, "updated": len(data.ordered_list)}


@router.post("/auto-populate", response_model=AutoPopulateResponse)
def auto_populate_sort_priorities():
    """Populate sort priorities from active AUTO groups.

    Scans all enabled AUTO event groups and creates sort priority entries
    for any sport/league combinations that don't already have entries.
    New entries are added alphabetically at the end.

    This is useful when setting up global sorting for the first time or
    after adding new leagues to AUTO groups.
    """
    from teamarr.database.sort_priorities import auto_populate_sort_priorities

    with get_db() as conn:
        added = auto_populate_sort_priorities(conn)

    if added == 0:
        message = "No new entries needed - all active leagues already have priorities"
    else:
        message = f"Added {added} new sport/league entries"

    return AutoPopulateResponse(added=added, message=message)
