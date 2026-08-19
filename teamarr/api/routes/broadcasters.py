"""API routes for user-defined broadcaster and RSN mappings."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from teamarr.core.rsn_catalog import MLB_RSN_CATALOG
from teamarr.database import get_db
from teamarr.database.broadcaster_mappings import (
    BroadcasterMapping,
    create_broadcaster_mapping,
    delete_broadcaster_mapping,
    get_broadcaster_mapping,
    list_broadcaster_mappings,
    update_broadcaster_mapping,
)

router = APIRouter(prefix="/broadcasters", tags=["Broadcasters"])


# =============================================================================
# Pydantic Models
# =============================================================================


class BroadcasterMappingCreate(BaseModel):
    """Create a new user-defined broadcaster mapping."""

    name: str = Field(..., description="User-friendly name (e.g. 'MASN Orioles')")
    pattern: str = Field(..., description="Regex pattern or match string (e.g. '(?i)\\bMASN\\b')")
    pattern_type: str = Field("regex", description="Match type: regex, exact, tvg_id, channel_id")
    team_id: str = Field(..., description="Team abbreviation or provider team ID (e.g. 'BAL', '110')")
    team_name: str | None = Field(None, description="Optional team display name")
    league: str = Field("mlb", description="League code (e.g. 'mlb')")
    is_active: bool = Field(True, description="Whether mapping is active")


class BroadcasterMappingUpdate(BaseModel):
    """Update an existing broadcaster mapping."""

    name: str | None = None
    pattern: str | None = None
    pattern_type: str | None = None
    team_id: str | None = None
    team_name: str | None = None
    league: str | None = None
    is_active: bool | None = None


class BroadcasterMappingResponse(BaseModel):
    """Response model for a broadcaster mapping."""

    id: int
    name: str
    pattern: str
    pattern_type: str
    team_id: str
    team_name: str | None = None
    league: str
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_db(cls, mapping: BroadcasterMapping) -> "BroadcasterMappingResponse":
        return cls(
            id=mapping.id,
            name=mapping.name,
            pattern=mapping.pattern,
            pattern_type=mapping.pattern_type,
            team_id=mapping.team_id,
            team_name=mapping.team_name,
            league=mapping.league,
            is_active=mapping.is_active,
            created_at=str(mapping.created_at) if mapping.created_at else None,
            updated_at=str(mapping.updated_at) if mapping.updated_at else None,
        )


class RSNCatalogEntryResponse(BaseModel):
    """Response model for built-in catalog entries."""

    network_name: str
    league: str
    team_abbreviation: str
    patterns: list[str]
    is_ambiguous: bool
    team_synonyms: list[str]


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/", response_model=list[BroadcasterMappingResponse])
def list_mappings(
    league: str | None = Query(None, description="Filter by league"),
    active_only: bool = Query(False, description="Filter to active mappings only"),
):
    """List all user-defined broadcaster mappings."""
    with get_db() as conn:
        mappings = list_broadcaster_mappings(conn, league=league, active_only=active_only)
    return [BroadcasterMappingResponse.from_db(m) for m in mappings]


@router.get("/catalog", response_model=list[RSNCatalogEntryResponse])
def get_rsn_catalog(
    league: str = Query("mlb", description="Filter catalog by league"),
):
    """List pre-seeded built-in RSN catalog entries."""
    entries = [
        RSNCatalogEntryResponse(
            network_name=e.network_name,
            league=e.league,
            team_abbreviation=e.team_abbreviation,
            patterns=list(e.patterns),
            is_ambiguous=e.is_ambiguous,
            team_synonyms=list(e.team_synonyms),
        )
        for e in MLB_RSN_CATALOG
        if e.league.lower() == league.lower()
    ]
    return entries


@router.post("/", response_model=BroadcasterMappingResponse, status_code=201)
def create_mapping(req: BroadcasterMappingCreate):
    """Create a new user-defined broadcaster mapping."""
    with get_db() as conn:
        mapping = create_broadcaster_mapping(
            conn=conn,
            name=req.name,
            pattern=req.pattern,
            pattern_type=req.pattern_type,
            team_id=req.team_id,
            team_name=req.team_name,
            league=req.league,
            is_active=req.is_active,
        )
    return BroadcasterMappingResponse.from_db(mapping)


@router.get("/{mapping_id}", response_model=BroadcasterMappingResponse)
def get_mapping(mapping_id: int):
    """Get a single broadcaster mapping by ID."""
    with get_db() as conn:
        mapping = get_broadcaster_mapping(conn, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Broadcaster mapping not found")
    return BroadcasterMappingResponse.from_db(mapping)


@router.put("/{mapping_id}", response_model=BroadcasterMappingResponse)
def update_mapping(mapping_id: int, req: BroadcasterMappingUpdate):
    """Update an existing broadcaster mapping."""
    with get_db() as conn:
        mapping = update_broadcaster_mapping(
            conn=conn,
            mapping_id=mapping_id,
            name=req.name,
            pattern=req.pattern,
            pattern_type=req.pattern_type,
            team_id=req.team_id,
            team_name=req.team_name,
            league=req.league,
            is_active=req.is_active,
        )
    if not mapping:
        raise HTTPException(status_code=404, detail="Broadcaster mapping not found")
    return BroadcasterMappingResponse.from_db(mapping)


@router.delete("/{mapping_id}", status_code=204)
def delete_mapping(mapping_id: int):
    """Delete a broadcaster mapping by ID."""
    with get_db() as conn:
        success = delete_broadcaster_mapping(conn, mapping_id)
    if not success:
        raise HTTPException(status_code=404, detail="Broadcaster mapping not found")
    return None
