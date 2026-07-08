"""Stream ordering settings endpoints."""

from fastapi import APIRouter, HTTPException, status

from teamarr.database import get_db
from teamarr.database.settings.types import NO_VALUE_RULE_TYPES, VALID_RULE_TYPES

from .models import (
    StreamOrderingSettingsModel,
    StreamOrderingSettingsUpdate,
    to_model,
)

router = APIRouter()


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

    # Validate rule types
    for rule in update.rules:
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

    # Convert to dict format for database function
    rules_data = [
        {
            "type": rule.type,
            "value": rule.value.strip(),
            "priority": rule.priority,
        }
        for rule in update.rules
    ]

    with get_db() as conn:
        update_stream_ordering_rules(conn, rules_data)

    # Return updated settings
    with get_db() as conn:
        settings = get_stream_ordering_settings(conn)

    return to_model(StreamOrderingSettingsModel, settings)
