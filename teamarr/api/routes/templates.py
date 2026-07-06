"""Templates API endpoints."""

import json
import logging

from fastapi import APIRouter, HTTPException, status

from teamarr.api.models import (
    TemplateCreate,
    TemplateFullResponse,
    TemplateResponse,
    TemplateUpdate,
    TemplateValidateRequest,
    TemplateValidateResponse,
)
from teamarr.database import get_db
from teamarr.database.templates import (
    create_template as db_create,
)
from teamarr.database.templates import (
    delete_template as db_delete,
)
from teamarr.database.templates import (
    get_template as db_get,
)
from teamarr.database.templates import (
    get_template_raw,
    list_templates_with_counts,
)
from teamarr.database.templates import (
    update_template as db_update,
)
from teamarr.templates.validation import (
    validate_conditional_descriptions,
    validate_fields,
    warnings_as_dicts,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Flat string fields that accept template variables. Used to log advisory
# validation warnings on write so programmatic saves (API/import) surface the
# same issues the editor shows. Nested conditional/fallback templates are
# validated separately (see teamarrv2-3zjp.3).
_VALIDATED_TEXT_FIELDS = (
    "title_format",
    "subtitle_template",
    "description_template",
    "program_art_url",
    "event_channel_name",
    "event_channel_logo_url",
)


def _log_validation_warnings(template_type: str | None, data: dict) -> None:
    """Validate template text + conditional-description fields, log warnings (non-blocking)."""

    is_event = (template_type or "team") == "event"
    fields = {k: data.get(k) for k in _VALIDATED_TEXT_FIELDS if data.get(k)}
    results = validate_fields(fields, is_event) if fields else {}
    cond = data.get("conditional_descriptions")
    if cond:
        results.update(validate_conditional_descriptions(cond, is_event))
    for field, warnings in results.items():
        for w in warnings:
            logger.warning("[template-validation] %s: %s", field, w.message)

# JSON fields that need serialization from Pydantic models to strings
_JSON_FIELDS = {
    "xmltv_flags",
    "xmltv_video",
    "xmltv_categories",
    "pregame_periods",
    "pregame_fallback",
    "postgame_periods",
    "postgame_fallback",
    "postgame_conditional",
    "idle_content",
    "idle_conditional",
    "idle_offseason",
    "conditional_descriptions",
}


def _pydantic_to_plain(key: str, value):
    """Convert Pydantic model field to plain Python type for database layer.

    The database layer handles its own JSON serialization for known fields.
    This only converts Pydantic sub-models to dicts/lists.
    """
    if key in _JSON_FIELDS and value is not None:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        elif isinstance(value, list):
            return [v.model_dump() if hasattr(v, "model_dump") else v for v in value]
    return value


def _parse_json_fields(row: dict) -> dict:
    """Parse JSON string fields into Python objects for API response."""
    result = dict(row)
    for field in _JSON_FIELDS:
        if field in result and result[field]:
            try:
                result[field] = json.loads(result[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


@router.get("/templates", response_model=list[TemplateResponse])
def list_templates():
    """List all templates with usage counts."""

    with get_db() as conn:
        return list_templates_with_counts(conn)


@router.post("/templates/validate", response_model=TemplateValidateResponse)
def validate_template(req: TemplateValidateRequest):
    """Validate template field strings for unknown/misused variables (advisory).

    Returns per-field warnings without saving. Mirrors the editor's inline checks
    so API/import callers can catch the same issues. Never rejects — the resolver
    keeps unknown variables literal by design.
    """

    is_event = req.template_type == "event"
    results = validate_fields(req.fields, is_event)
    results.update(
        validate_conditional_descriptions(req.conditional_descriptions or [], is_event)
    )
    return {"valid": not results, "warnings": warnings_as_dicts(results)}


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(template: TemplateCreate):
    """Create a new template."""

    # Convert Pydantic models to plain types for database layer
    data = template.model_dump()
    name = data.pop("name")
    template_type = data.pop("template_type", "team")

    # Convert Pydantic sub-models to plain dicts
    kwargs = {}
    for k, v in data.items():
        if v is not None:
            kwargs[k] = _pydantic_to_plain(k, getattr(template, k, v))

    _log_validation_warnings(template_type, data)

    with get_db() as conn:
        try:
            template_id = db_create(conn, name=name, template_type=template_type, **kwargs)

            return get_template_raw(conn, template_id)
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Template with this name already exists",
                ) from None
            raise


@router.get("/templates/{template_id}", response_model=TemplateFullResponse)
def get_template(template_id: int):
    """Get a template by ID with all JSON fields parsed."""
    from dataclasses import asdict


    with get_db() as conn:
        template = db_get(conn, template_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )
        # Template dataclass already has parsed JSON fields
        return asdict(template)


@router.put("/templates/{template_id}", response_model=TemplateResponse)
def update_template(template_id: int, template: TemplateUpdate):
    """Update a template."""

    updates = {k: v for k, v in template.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    # Convert Pydantic sub-models to plain types for database layer
    kwargs = {k: _pydantic_to_plain(k, getattr(template, k, v)) for k, v in updates.items()}

    with get_db() as conn:
        if not db_update(conn, template_id, **kwargs):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )
        logger.info("[UPDATED] Template id=%d fields=%s", template_id, list(updates.keys()))

        row = get_template_raw(conn, template_id)
        _log_validation_warnings((row or {}).get("template_type"), updates)
        return row


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int):
    """Delete a template."""

    with get_db() as conn:
        if not db_delete(conn, template_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
