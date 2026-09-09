"""Shared background lifecycle for team and league cache refreshes."""

import logging
import re
import threading
from collections.abc import Callable
from typing import Any

from teamarr.api.cache_refresh_status import (
    complete_refresh,
    fail_refresh,
    start_refresh,
    update_refresh_status,
)
from teamarr.services import create_cache_service
from teamarr.services.league_mappings import get_league_mapping_service

logger = logging.getLogger(__name__)


def start_cache_refresh(db_factory: Callable[[], Any]) -> bool:
    """Start one cache refresh worker, returning false when one already runs."""
    if not start_refresh():
        return False

    def run() -> None:
        try:
            service = create_cache_service(db_factory)

            def report(message: str, percent: int) -> None:
                current = total = None
                if match := re.search(r"(\d+)/(\d+) leagues", message):
                    current, total = (int(value) for value in match.groups())
                update_refresh_status(
                    status="progress",
                    message=message,
                    percent=percent,
                    phase="fetching",
                    current=current,
                    total=total,
                )

            result = service.refresh(progress_callback=report)
            if not result.success:
                fail_refresh("; ".join(result.errors) if result.errors else "Unknown error")
                return

            try:
                get_league_mapping_service().reload()
            except RuntimeError:
                logger.debug("League mapping service unavailable after cache refresh")

            complete_refresh(
                {
                    "success": True,
                    "leagues_count": result.leagues_added,
                    "teams_count": result.teams_added,
                    "duration_seconds": result.duration_seconds,
                }
            )
        except Exception as exc:
            logger.exception("Cache refresh failed")
            fail_refresh(str(exc))

    threading.Thread(target=run, daemon=True, name="cache-refresh").start()
    return True
