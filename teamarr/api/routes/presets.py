"""Condition presets API endpoints.

Provides REST API for managing condition presets used in template descriptions.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from teamarr.database import get_db
from teamarr.database.condition_presets import (
    create_preset as db_create_preset,
)
from teamarr.database.condition_presets import (
    delete_preset as db_delete_preset,
)
from teamarr.database.condition_presets import (
    get_all_presets,
    get_preset_by_name,
)
from teamarr.database.condition_presets import (
    get_preset as db_get_preset,
)
from teamarr.database.condition_presets import (
    update_preset as db_update_preset,
)

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class ConditionPresetCreate(BaseModel):
    """Create condition preset request."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    conditions: list[dict[str, Any]] = Field(default_factory=list)


class ConditionPresetUpdate(BaseModel):
    """Update condition preset request."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    conditions: list[dict[str, Any]] | None = None
    clear_description: bool = False


class ConditionPresetResponse(BaseModel):
    """Condition preset response."""

    id: int
    name: str
    description: str | None = None
    conditions: list[dict[str, Any]] = []
    created_at: str | None = None


class ConditionPresetListResponse(BaseModel):
    """List of condition presets."""

    presets: list[ConditionPresetResponse]
    total: int


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("", response_model=ConditionPresetListResponse)
def list_presets():
    """List all condition presets."""

    with get_db() as conn:
        presets = get_all_presets(conn)

    responses = []
    for p in presets:
        assert p.id is not None  # persisted rows always have an id
        responses.append(
            ConditionPresetResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                conditions=p.conditions,
                created_at=p.created_at.isoformat() if p.created_at else None,
            )
        )

    return ConditionPresetListResponse(
        presets=responses,
        total=len(presets),
    )


@router.get("/{preset_id}", response_model=ConditionPresetResponse)
def get_preset(preset_id: int):
    """Get a single condition preset by ID."""

    with get_db() as conn:
        preset = db_get_preset(conn, preset_id)

    if not preset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preset {preset_id} not found",
        )

    assert preset.id is not None  # persisted rows always have an id
    return ConditionPresetResponse(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        conditions=preset.conditions,
        created_at=preset.created_at.isoformat() if preset.created_at else None,
    )


@router.post("", response_model=ConditionPresetResponse, status_code=status.HTTP_201_CREATED)
def create_preset(request: ConditionPresetCreate):
    """Create a new condition preset."""

    with get_db() as conn:
        # Check for duplicate name
        existing = get_preset_by_name(conn, request.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Preset with name '{request.name}' already exists",
            )

        preset_id = db_create_preset(
            conn,
            name=request.name,
            description=request.description,
            conditions=request.conditions,
        )
        preset = db_get_preset(conn, preset_id)

    if preset is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Preset could not be retrieved after creation",
        )

    assert preset.id is not None  # persisted rows always have an id
    return ConditionPresetResponse(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        conditions=preset.conditions,
        created_at=preset.created_at.isoformat() if preset.created_at else None,
    )


@router.put("/{preset_id}", response_model=ConditionPresetResponse)
def update_preset(preset_id: int, request: ConditionPresetUpdate):
    """Update a condition preset."""

    with get_db() as conn:
        preset = db_get_preset(conn, preset_id)
        if not preset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preset {preset_id} not found",
            )

        # Check for duplicate name if changing
        if request.name and request.name != preset.name:
            existing = get_preset_by_name(conn, request.name)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Preset with name '{request.name}' already exists",
                )

        db_update_preset(
            conn,
            preset_id,
            name=request.name,
            description=request.description,
            conditions=request.conditions,
            clear_description=request.clear_description,
        )
        preset = db_get_preset(conn, preset_id)

    if preset is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Preset could not be retrieved after update",
        )

    assert preset.id is not None  # persisted rows always have an id
    return ConditionPresetResponse(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        conditions=preset.conditions,
        created_at=preset.created_at.isoformat() if preset.created_at else None,
    )


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(preset_id: int):
    """Delete a condition preset."""

    with get_db() as conn:
        preset = db_get_preset(conn, preset_id)
        if not preset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preset {preset_id} not found",
            )

        db_delete_preset(conn, preset_id)
