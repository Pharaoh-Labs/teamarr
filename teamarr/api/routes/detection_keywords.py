"""Detection Keywords API routes.

CRUD operations for user-defined detection patterns that extend
the built-in patterns in DetectionKeywordService.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from teamarr.database.connection import get_db
from teamarr.database.detection_keywords import (
    bulk_import_keywords,
    export_keywords,
)
from teamarr.database.detection_keywords import (
    create_keyword as db_create,
)
from teamarr.database.detection_keywords import (
    delete_keyword as db_delete,
)
from teamarr.database.detection_keywords import (
    get_keyword as db_get,
)
from teamarr.database.detection_keywords import (
    list_keywords as db_list,
)
from teamarr.database.detection_keywords import (
    update_keyword as db_update,
)
from teamarr.services.detection_keywords import DetectionKeywordService

router = APIRouter(prefix="/api/v1/detection-keywords", tags=["Detection Keywords"])

# Valid categories for detection keywords
CategoryType = Literal[
    "event_type_keywords",  # Keywords that detect event type (target_value = EVENT_CARD, etc.)
    "league_hints",
    "sport_hints",
    "placeholders",
    "card_segments",
    "exclusions",
    "separators",
]


# =============================================================================
# Pydantic Models
# =============================================================================


class DetectionKeywordCreate(BaseModel):
    """Request to create a detection keyword."""

    category: CategoryType
    keyword: str = Field(..., min_length=1, max_length=200)
    is_regex: bool = False
    target_value: str | None = None
    enabled: bool = True
    priority: int = 0
    description: str | None = None


class DetectionKeywordUpdate(BaseModel):
    """Request to update a detection keyword."""

    keyword: str | None = Field(None, min_length=1, max_length=200)
    is_regex: bool | None = None
    target_value: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    description: str | None = None
    clear_target_value: bool = False
    clear_description: bool = False


class DetectionKeywordResponse(BaseModel):
    """Response for a detection keyword."""

    id: int
    category: str
    keyword: str
    is_regex: bool
    target_value: str | None
    enabled: bool
    priority: int
    description: str | None
    created_at: str
    updated_at: str


class DetectionKeywordListResponse(BaseModel):
    """Response for listing detection keywords."""

    total: int
    keywords: list[DetectionKeywordResponse]


class BulkImportRequest(BaseModel):
    """Request to bulk import detection keywords."""

    keywords: list[DetectionKeywordCreate]
    replace_category: bool = False  # If true, deletes existing in category first


class BulkImportResponse(BaseModel):
    """Response for bulk import."""

    created: int
    updated: int
    failed: int
    errors: list[str]


# =============================================================================
# Helper Functions
# =============================================================================


def _row_to_response(row: dict) -> DetectionKeywordResponse:
    """Convert database row to response model."""
    return DetectionKeywordResponse(
        id=row["id"],
        category=row["category"],
        keyword=row["keyword"],
        is_regex=bool(row["is_regex"]),
        target_value=row["target_value"],
        enabled=bool(row["enabled"]),
        priority=row["priority"] or 0,
        description=row["description"],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _invalidate_detection_cache():
    """Invalidate the detection keyword service cache after mutations."""

    DetectionKeywordService.invalidate_cache()


# =============================================================================
# API Routes
# =============================================================================


@router.get("", response_model=DetectionKeywordListResponse)
def list_keywords(
    category: CategoryType | None = None,
    enabled_only: bool = False,
):
    """List all detection keywords, optionally filtered by category."""

    with get_db() as conn:
        rows = db_list(conn, category=category, enabled_only=enabled_only)
        return DetectionKeywordListResponse(
            total=len(rows),
            keywords=[_row_to_response(r) for r in rows],
        )


@router.get("/categories")
def list_categories():
    """List available keyword categories with descriptions."""
    return {
        "categories": [
            {
                "id": "event_type_keywords",
                "name": "Event Type Detection",
                "description": "Keywords that detect event type (routed to type-specific pipeline)",
                "has_target": True,
                "target_description": "Event type: EVENT_CARD, TEAM_VS_TEAM, FIELD_EVENT",
            },
            {
                "id": "league_hints",
                "name": "League Hints",
                "description": "Patterns that map to league code(s)",
                "has_target": True,
                "target_description": "League code or JSON array of codes",
            },
            {
                "id": "sport_hints",
                "name": "Sport Hints",
                "description": "Patterns that map to sport name",
                "has_target": True,
                "target_description": "Sport name (e.g., 'Hockey', 'Soccer')",
            },
            {
                "id": "placeholders",
                "name": "Placeholders",
                "description": "Patterns for placeholder/filler streams to skip",
                "has_target": False,
            },
            {
                "id": "card_segments",
                "name": "Card Segments",
                "description": "Patterns for UFC card segments",
                "has_target": True,
                "target_description": "Segment name: early_prelims, prelims, main_card, combined",
            },
            {
                "id": "exclusions",
                "name": "Combat Exclusions",
                "description": "Skip non-event combat sports content (weigh-ins, etc.)",
                "has_target": False,
            },
            {
                "id": "separators",
                "name": "Separators",
                "description": (
                    "Matchup delimiters used to split a stream into two teams "
                    "(built-ins: vs, @, at, x, contra). Add locale-specific ones "
                    "like ' - ' for 'España - Inglaterra'. Pad with spaces and use "
                    "sparingly — a bare hyphen can over-split normal titles."
                ),
                "has_target": False,
            },
        ]
    }


@router.get("/{category}", response_model=DetectionKeywordListResponse)
def list_by_category(
    category: CategoryType,
    enabled_only: bool = False,
):
    """List detection keywords for a specific category."""

    with get_db() as conn:
        rows = db_list(conn, category=category, enabled_only=enabled_only)
        return DetectionKeywordListResponse(
            total=len(rows),
            keywords=[_row_to_response(r) for r in rows],
        )


@router.post("", response_model=DetectionKeywordResponse, status_code=201)
def create_keyword(
    request: DetectionKeywordCreate,
):
    """Create a new detection keyword."""

    try:
        with get_db() as conn:
            row = db_create(
                conn,
                category=request.category,
                keyword=request.keyword,
                is_regex=request.is_regex,
                target_value=request.target_value,
                enabled=request.enabled,
                priority=request.priority,
                description=request.description,
            )
        _invalidate_detection_cache()
        return _row_to_response(row)
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"Keyword '{request.keyword}' already exists in "
                f"category '{request.category}'",
            ) from None
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/id/{keyword_id}", response_model=DetectionKeywordResponse)
def get_keyword(
    keyword_id: int,
):
    """Get a specific detection keyword by ID."""

    with get_db() as conn:
        row = db_get(conn, keyword_id)
        if not row:
            raise HTTPException(status_code=404, detail="Keyword not found")
        return _row_to_response(row)


@router.put("/id/{keyword_id}", response_model=DetectionKeywordResponse)
def update_keyword(
    keyword_id: int,
    request: DetectionKeywordUpdate,
):
    """Update a detection keyword."""

    with get_db() as conn:
        row = db_update(
            conn,
            keyword_id,
            keyword=request.keyword,
            is_regex=request.is_regex,
            target_value=request.target_value,
            clear_target_value=request.clear_target_value,
            enabled=request.enabled,
            priority=request.priority,
            description=request.description,
            clear_description=request.clear_description,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Keyword not found")
    _invalidate_detection_cache()
    return _row_to_response(row)


@router.delete("/id/{keyword_id}", status_code=204)
def delete_keyword(
    keyword_id: int,
):
    """Delete a detection keyword."""

    with get_db() as conn:
        result = db_delete(conn, keyword_id)
        if not result:
            raise HTTPException(status_code=404, detail="Keyword not found")
    _invalidate_detection_cache()


@router.post("/import", response_model=BulkImportResponse)
def bulk_import(
    request: BulkImportRequest,
):
    """Bulk import detection keywords."""

    keyword_dicts = [
        {
            "category": kw.category,
            "keyword": kw.keyword,
            "is_regex": kw.is_regex,
            "target_value": kw.target_value,
            "enabled": kw.enabled,
            "priority": kw.priority,
            "description": kw.description,
        }
        for kw in request.keywords
    ]

    with get_db() as conn:
        created, updated, failed, errors = bulk_import_keywords(
            conn, keyword_dicts, replace_category=request.replace_category
        )
    _invalidate_detection_cache()

    return BulkImportResponse(
        created=created,
        updated=updated,
        failed=failed,
        errors=errors,
    )


@router.get("/export")
def bulk_export(
    category: CategoryType | None = None,
):
    """Export detection keywords as JSON."""

    with get_db() as conn:
        keywords = export_keywords(conn, category=category)
        return {
            "exported_at": datetime.now().isoformat(),
            "count": len(keywords),
            "keywords": keywords,
        }
