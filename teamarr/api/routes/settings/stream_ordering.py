"""Stream ordering settings endpoints."""

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from teamarr.database import get_db
from teamarr.database.settings.types import NO_VALUE_RULE_TYPES, VALID_RULE_TYPES
from teamarr.database.stream_ordering_scopes import ScopeAssignmentConflict

from .models import (
    StreamOrderingScopeModel,
    StreamOrderingScopeUpdate,
    StreamOrderingSettingsModel,
    StreamOrderingSettingsUpdate,
    to_model,
)

router = APIRouter()


class ApplyStreamOrderingResponse(BaseModel):
    """Counts from a reorder-only pass (#576)."""

    channels_reordered: int = 0
    streams_reordered: int = 0
    windows_synced: int = 0
    order_drift_synced: int = 0
    stats_refreshed: int = 0


@router.post("/settings/stream-ordering/apply", response_model=ApplyStreamOrderingResponse)
def apply_stream_ordering():
    """Re-sort every managed channel's streams now, without a generation run (#576).

    Pulls current stream stats from Dispatcharr, re-applies the ordering rules
    and pushes only the channels whose order changed. Nothing else runs — no
    matching, provider calls, EPG rebuild or media-server refresh. Like a
    manual generation, it bypasses the live-event #1 pin. Returns 409 while a
    generation is in progress.
    """
    from teamarr.consumers.generation import run_stream_ordering_only
    from teamarr.database.settings import get_dispatcharr_settings
    from teamarr.dispatcharr import get_dispatcharr_connection

    with get_db() as conn:
        dispatcharr_settings = get_dispatcharr_settings(conn)
    client = None
    if dispatcharr_settings.enabled and dispatcharr_settings.url:
        client = get_dispatcharr_connection(get_db)

    result = run_stream_ordering_only(get_db, client, manual=True)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation already in progress",
        )
    fields = ApplyStreamOrderingResponse.model_fields
    return ApplyStreamOrderingResponse(**{k: int(v) for k, v in result.items() if k in fields})


def _validated_rules(rules) -> list[dict]:
    """Validate and normalize rule payloads shared by global and scoped settings."""
    for rule in rules:
        if rule.type not in VALID_RULE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid rule type '{rule.type}'. Valid: {VALID_RULE_TYPES}",
            )
        if rule.type not in NO_VALUE_RULE_TYPES and (not rule.value or not rule.value.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rule value cannot be empty",
            )
        if rule.type == "stream_type":
            base = rule.value.split("|")[0].strip()
            if base not in {"event", "team"}:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="stream_type value must be 'event' or 'team'",
                )
    return [
        {
            "type": rule.type,
            "value": rule.value.strip(),
            "priority": rule.priority,
            "mode": rule.mode,
            "points": rule.points,
        }
        for rule in rules
    ]


def _scope_model(scope) -> StreamOrderingScopeModel:
    return StreamOrderingScopeModel(**scope.__dict__)


def _validate_scope_update(update: StreamOrderingScopeUpdate) -> list[dict]:
    if not update.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Ruleset name cannot be empty"
        )
    if not update.sports and not update.leagues:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one sport or league for a scoped ruleset",
        )
    return _validated_rules(update.rules)


@router.get("/settings/stream-ordering", response_model=StreamOrderingSettingsModel)
def get_stream_ordering_settings():
    """Get stream ordering rules.

    Returns the list of rules used to prioritize streams within channels.
    Rules are evaluated in priority order (lowest number first).
    First matching rule determines the stream's position.
    """
    from teamarr.database.settings import get_stream_ordering_settings

    with get_db() as conn:
        settings = get_stream_ordering_settings(conn)

    return to_model(StreamOrderingSettingsModel, settings)


@router.put("/settings/stream-ordering", response_model=StreamOrderingSettingsModel)
def update_stream_ordering_settings(update: StreamOrderingSettingsUpdate):
    """Update stream ordering rules (full replacement).

    Replaces all existing rules with the provided list.
    Rules are validated for:
    - Valid type (m3u, group, regex)
    - Non-empty value
    - Priority between 1-99

    Changes take effect on the next EPG generation.
    """
    from teamarr.database.settings import (
        get_stream_ordering_settings,
        update_stream_ordering_rules,
    )

    rules_data = _validated_rules(update.rules)

    with get_db() as conn:
        update_stream_ordering_rules(conn, rules_data)

    # Return updated settings
    with get_db() as conn:
        settings = get_stream_ordering_settings(conn)

    return to_model(StreamOrderingSettingsModel, settings)


@router.get("/settings/stream-ordering/scopes", response_model=list[StreamOrderingScopeModel])
def get_stream_ordering_scopes():
    """List persisted scoped stream-ordering rulesets."""
    from teamarr.database.stream_ordering_scopes import get_stream_ordering_scopes

    with get_db() as conn:
        return [_scope_model(scope) for scope in get_stream_ordering_scopes(conn)]


@router.post(
    "/settings/stream-ordering/scopes",
    response_model=StreamOrderingScopeModel,
    status_code=status.HTTP_201_CREATED,
)
def create_stream_ordering_scope(update: StreamOrderingScopeUpdate):
    """Create a scoped stream-ordering ruleset."""
    from teamarr.database.stream_ordering_scopes import create_stream_ordering_scope

    rules = _validate_scope_update(update)
    try:
        with get_db() as conn:
            scope = create_stream_ordering_scope(
                conn,
                name=update.name,
                sports=update.sports,
                leagues=update.leagues,
                rules=rules,
                use_global_scoring=update.use_global_scoring,
                use_global_priority=update.use_global_priority,
            )
    except ScopeAssignmentConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _scope_model(scope)


@router.get(
    "/settings/stream-ordering/scopes/{ruleset_id}", response_model=StreamOrderingScopeModel
)
def get_stream_ordering_scope(ruleset_id: int):
    """Get one scoped stream-ordering ruleset."""
    from teamarr.database.stream_ordering_scopes import get_stream_ordering_scope

    with get_db() as conn:
        scope = get_stream_ordering_scope(conn, ruleset_id)
    if scope is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ruleset not found")
    return _scope_model(scope)


@router.put(
    "/settings/stream-ordering/scopes/{ruleset_id}", response_model=StreamOrderingScopeModel
)
def update_stream_ordering_scope(ruleset_id: int, update: StreamOrderingScopeUpdate):
    """Fully replace a scoped stream-ordering ruleset."""
    from teamarr.database.stream_ordering_scopes import update_stream_ordering_scope

    rules = _validate_scope_update(update)
    try:
        with get_db() as conn:
            scope = update_stream_ordering_scope(
                conn,
                ruleset_id,
                name=update.name,
                sports=update.sports,
                leagues=update.leagues,
                rules=rules,
                use_global_scoring=update.use_global_scoring,
                use_global_priority=update.use_global_priority,
            )
    except ScopeAssignmentConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if scope is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ruleset not found")
    return _scope_model(scope)


@router.delete(
    "/settings/stream-ordering/scopes/{ruleset_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_stream_ordering_scope(ruleset_id: int):
    """Delete a scoped stream-ordering ruleset."""
    from teamarr.database.stream_ordering_scopes import delete_stream_ordering_scope

    with get_db() as conn:
        deleted = delete_stream_ordering_scope(conn, ruleset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ruleset not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
