"""Runtime log-level control (#585).

Adjusts the console handler's minimum level in-process, no restart —
*arr-style temporary debugging. Runtime-only: a restart returns to the
``LOG_LEVEL`` env default, and the rotating file log always captures DEBUG
regardless of this setting.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from teamarr.utilities.logging import (
    RUNTIME_LOG_LEVELS,
    default_log_level,
    get_console_log_level,
    set_console_log_level,
)

router = APIRouter()

logger = logging.getLogger(__name__)


class LogLevelUpdate(BaseModel):
    level: str


def _state() -> dict:
    return {
        "level": get_console_log_level(),
        "default": default_log_level(),
        "levels": list(RUNTIME_LOG_LEVELS),
    }


@router.get("/logging/level")
def get_log_level() -> dict:
    """Current console log level, the startup default, and valid choices."""
    return _state()


@router.put("/logging/level")
def update_log_level(payload: LogLevelUpdate) -> dict:
    """Set the console log level at runtime; reverts to default on restart."""
    try:
        applied = set_console_log_level(payload.level)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid level {payload.level!r}; valid: {', '.join(RUNTIME_LOG_LEVELS)}",
        ) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    # WARNING so the change itself survives the new filter when raising the level
    logger.warning("[LOGGING] Console log level set to %s (runtime-only)", applied)
    return _state()
