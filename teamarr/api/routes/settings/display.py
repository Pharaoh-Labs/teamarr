"""Duration, display, and reconciliation settings endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from teamarr.config import set_display_settings as set_config_display
from teamarr.database import get_db
from teamarr.database.settings import (
    get_all_settings,
    update_display_settings,
)
from teamarr.database.settings import (
    update_duration_settings as db_update,
)
from teamarr.providers.registry import ProviderRegistry

from .models import (
    DisplaySettingsModel,
    ReconciliationSettingsModel,
    TSDBKeyValidationRequest,
    TSDBKeyValidationResponse,
    to_model,
    unmask_or_skip,
)

router = APIRouter()


# =============================================================================
# DURATION SETTINGS
# =============================================================================


@router.get("/settings/durations")
def get_duration_settings() -> dict[str, float]:
    """Get game duration settings.

    Returns all sports and their default durations in hours.
    Sports are defined in DurationSettings dataclass - adding a new sport
    there automatically exposes it here.
    """

    with get_db() as conn:
        settings = get_all_settings(conn)

    return asdict(settings.durations)


@router.put("/settings/durations")
def update_duration_settings(update: dict[str, float]) -> dict[str, float]:
    """Update game duration settings.

    Accepts a dict of sport names to duration hours.
    Only known sports (defined in DurationSettings) will be updated.
    """

    with get_db() as conn:
        # Pass all values from the update dict as kwargs
        db_update(conn, **update)

    with get_db() as conn:
        settings = get_all_settings(conn)

    return asdict(settings.durations)


# =============================================================================
# RECONCILIATION SETTINGS
# =============================================================================


@router.get("/settings/reconciliation", response_model=ReconciliationSettingsModel)
def get_reconciliation_settings():
    """Get reconciliation settings."""

    with get_db() as conn:
        settings = get_all_settings(conn)

    return to_model(ReconciliationSettingsModel, settings.reconciliation)


@router.put("/settings/reconciliation", response_model=ReconciliationSettingsModel)
def update_reconciliation_settings(update: ReconciliationSettingsModel):
    """Update reconciliation settings."""
    from teamarr.database.settings import (
        get_all_settings,
        update_reconciliation_settings,
    )

    valid_modes = {"consolidate", "separate", "ignore"}
    if update.default_duplicate_event_handling not in valid_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid duplicate handling mode. Valid: {valid_modes}",
        )

    with get_db() as conn:
        update_reconciliation_settings(conn, **update.model_dump())

    with get_db() as conn:
        settings = get_all_settings(conn)

    return to_model(ReconciliationSettingsModel, settings.reconciliation)


# =============================================================================
# DISPLAY SETTINGS
# =============================================================================


@router.get("/settings/display", response_model=DisplaySettingsModel)
def get_display_settings():
    """Get display/formatting settings."""

    with get_db() as conn:
        settings = get_all_settings(conn)

    return to_model(DisplaySettingsModel, settings.display)


@router.put("/settings/display", response_model=DisplaySettingsModel)
def update_display_settings_endpoint(update: DisplaySettingsModel):
    """Update display/formatting settings."""

    valid_time_formats = {"12h", "24h"}
    if update.time_format not in valid_time_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid time_format. Valid: {valid_time_formats}",
        )

    with get_db() as conn:
        update_display_settings(
            conn,
            time_format=update.time_format,
            show_timezone=update.show_timezone,
            channel_id_format=update.channel_id_format,
            xmltv_generator_name=update.xmltv_generator_name,
            xmltv_generator_url=update.xmltv_generator_url,
            tsdb_api_key=unmask_or_skip(update.tsdb_api_key),
        )

    # Update cached display settings so new values are used immediately
    set_config_display(
        time_format=update.time_format,
        show_timezone=update.show_timezone,
        channel_id_format=update.channel_id_format,
        xmltv_generator_name=update.xmltv_generator_name,
        xmltv_generator_url=update.xmltv_generator_url,
    )

    # Reinitialize TSDB provider so it picks up the new API key
    # without requiring a restart. The factory re-reads the key from DB.
    if unmask_or_skip(update.tsdb_api_key) is not None:

        ProviderRegistry.reinitialize_provider("tsdb")

    with get_db() as conn:
        settings = get_all_settings(conn)

    return to_model(DisplaySettingsModel, settings.display)


# =============================================================================
# TSDB API KEY VALIDATION
# =============================================================================

TSDB_FREE_KEY = "123"


@router.post("/settings/tsdb/validate-key", response_model=TSDBKeyValidationResponse)
def validate_tsdb_key(request: TSDBKeyValidationRequest):
    """Validate a TSDB API key before saving.

    Tests the key against a lightweight TSDB endpoint (lookupleague.php).
    Premium keys have >3 digits; free key is "123".
    """
    import httpx

    key = request.api_key.strip()
    if not key:
        return TSDBKeyValidationResponse(
            valid=False, is_premium=False, message="API key cannot be empty"
        )

    # Premium keys are >3 digits; "123" is the free tier key
    is_premium = key != TSDB_FREE_KEY and len(key) > 3

    # Test the key against a lightweight endpoint
    url = f"https://www.thesportsdb.com/api/v1/json/{key}/lookupleague.php?id=4328"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)

        if resp.status_code == 404:
            return TSDBKeyValidationResponse(
                valid=False, is_premium=False, message="Invalid API key"
            )

        if resp.status_code != 200:
            return TSDBKeyValidationResponse(
                valid=False,
                is_premium=False,
                message=f"TSDB returned status {resp.status_code}",
            )

        # Valid keys return JSON with league data
        data = resp.json()
        if not data.get("leagues"):
            return TSDBKeyValidationResponse(
                valid=False, is_premium=False, message="Key accepted but returned no data"
            )

        if is_premium:
            message = "Valid premium key — full event coverage, 100 req/min"
        else:
            message = "Valid free key — 5 events/day per league, 30 req/min"

        return TSDBKeyValidationResponse(
            valid=True, is_premium=is_premium, message=message
        )

    except httpx.TimeoutException:
        return TSDBKeyValidationResponse(
            valid=False, is_premium=False, message="Connection to TSDB timed out"
        )
    except Exception as e:
        return TSDBKeyValidationResponse(
            valid=False, is_premium=False, message=f"Connection error: {e}"
        )
