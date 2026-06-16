"""EPG source management for Dispatcharr.

Handles EPG source operations including refresh and status polling.
"""

import logging
import time
from collections.abc import Callable
from urllib.parse import urlencode

from teamarr.dispatcharr.client import DispatcharrClient
from teamarr.dispatcharr.types import (
    DispatcharrEPGSource,
    DispatcharrProgram,
    RefreshResult,
)

logger = logging.getLogger(__name__)


class EPGManager:
    """EPG source management for Dispatcharr.

    Handles listing, refreshing, and status checking of EPG sources.

    Usage:
        manager = EPGManager(client)
        sources = manager.list_sources()
        result = manager.wait_for_refresh(epg_id=21, timeout=60)
    """

    # Endpoint for program-data search (newer Dispatcharr builds only).
    _PROGRAMS_SEARCH_PATH = "/api/epg/programs/search/"

    def __init__(self, client: DispatcharrClient):
        """Initialize EPG manager.

        Args:
            client: Authenticated DispatcharrClient instance
        """
        self._client = client
        # Cached feature-detection result for the program-search endpoint.
        # None = not probed yet, True/False = endpoint present/absent.
        self._programs_search_supported: bool | None = None

    def list_sources(self, include_dummy: bool = True) -> list[DispatcharrEPGSource]:
        """List all EPG sources.

        Args:
            include_dummy: Whether to include dummy sources (default: True)

        Returns:
            List of DispatcharrEPGSource objects
        """
        response = self._client.get("/api/epg/sources/")
        if response is None or response.status_code != 200:
            return []

        sources = [DispatcharrEPGSource.from_api(s) for s in response.json()]

        if not include_dummy:
            sources = [s for s in sources if s.source_type != "dummy"]

        return sources

    def get_source(self, epg_id: int) -> DispatcharrEPGSource | None:
        """Get a specific EPG source by ID.

        Args:
            epg_id: EPG source ID

        Returns:
            DispatcharrEPGSource or None if not found
        """
        response = self._client.get(f"/api/epg/sources/{epg_id}/")
        if response and response.status_code == 200:
            return DispatcharrEPGSource.from_api(response.json())
        return None

    def find_by_name(
        self,
        name: str,
        exact: bool = False,
    ) -> DispatcharrEPGSource | None:
        """Find EPG source by name.

        Args:
            name: Name to search for
            exact: If True, require exact match; otherwise partial match

        Returns:
            First matching EPG source or None
        """
        sources = self.list_sources()

        for source in sources:
            if exact:
                if source.name == name:
                    return source
            else:
                if name.lower() in source.name.lower():
                    return source

        return None

    def refresh(self, epg_id: int) -> RefreshResult:
        """Trigger refresh for a single EPG source.

        Args:
            epg_id: EPG source ID to refresh

        Returns:
            RefreshResult with success status and message
        """
        response = self._client.post("/api/epg/import/", {"id": epg_id})

        if response is None:
            return RefreshResult(
                success=False,
                message="Request failed - could not connect",
            )

        if response.status_code == 202:
            return RefreshResult(success=True, message="EPG refresh initiated")
        elif response.status_code == 400:
            return RefreshResult(success=False, message="Cannot refresh dummy EPG source")
        elif response.status_code == 401:
            return RefreshResult(success=False, message="Authentication failed")
        elif response.status_code == 404:
            return RefreshResult(success=False, message="EPG source not found")
        else:
            try:
                msg = response.json().get("message", f"HTTP {response.status_code}")
            except Exception:
                msg = f"HTTP {response.status_code}"
            return RefreshResult(success=False, message=msg)

    def wait_for_refresh(
        self,
        epg_id: int,
        timeout: int = 300,
        poll_interval: int = 2,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> RefreshResult:
        """Trigger EPG refresh and wait for completion.

        Dispatcharr's EPG import is async (returns 202). This method triggers
        the refresh and polls until completion by monitoring status and updated_at.

        EPG status values: idle, fetching, parsing, error, success, disabled

        Args:
            epg_id: EPG source ID to refresh
            timeout: Maximum seconds to wait (default: 60)
            poll_interval: Seconds between status checks (default: 2)

        Returns:
            RefreshResult with success status, duration, and final source state
        """
        # Get current state before refresh
        before = self.get_source(epg_id)
        if not before:
            return RefreshResult(success=False, message=f"EPG source {epg_id} not found")

        before_updated = before.updated_at

        # Trigger refresh
        trigger_result = self.refresh(epg_id)
        if not trigger_result.success:
            return trigger_result

        # Poll until status changes to success/error or updated_at changes
        start_time = time.time()
        last_logged_status: str | None = None
        last_status: str | None = None
        last_message: str | None = None

        while time.time() - start_time < timeout:
            time.sleep(poll_interval)

            # Check for cancellation before making a potentially slow API call
            if cancellation_check and cancellation_check():
                duration = time.time() - start_time
                return RefreshResult(
                    success=False,
                    message="Cancelled",
                    duration=duration,
                )

            current = self.get_source(epg_id)

            # Check if elapsed time exceeded timeout after the API call
            # (get_source can take up to 150s with retries, overshooting the timeout)
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                break

            if not current:
                logger.debug("[EPG] Refresh poll: could not get source %d", epg_id)
                continue

            current_status = current.status
            current_updated = current.updated_at
            current_message = current.last_message
            last_status = current_status
            last_message = current_message

            # Log status changes
            if current_status != last_logged_status:
                elapsed = time.time() - start_time
                logger.debug(
                    "[EPG] Refresh poll: status=%s message='%s' elapsed=%.1fs",
                    current_status,
                    current_message,
                    elapsed,
                )
                last_logged_status = current_status

            # Check if refresh completed (status is success and updated_at changed)
            if current_status == "success" and current_updated != before_updated:
                duration = time.time() - start_time
                return RefreshResult(
                    success=True,
                    message=current.last_message or "EPG refresh completed",
                    duration=duration,
                    source={"id": current.id, "status": current.status},
                )
            # Quick exit: no channels mapped - Dispatcharr returns success instantly
            # but updated_at doesn't change, so we'd wait full timeout otherwise
            elif current_status == "success" and "no channels" in (current_message or "").lower():
                duration = time.time() - start_time
                logger.info("[EPG] Refresh: no channels mapped (%.1fs)", duration)
                return RefreshResult(
                    success=True,
                    message=current_message or "EPG refresh completed (no channels mapped)",
                    duration=duration,
                    source={"id": current.id, "status": current.status},
                )
            elif current_status == "error":
                duration = time.time() - start_time
                return RefreshResult(
                    success=False,
                    message=current.last_message or "EPG refresh failed",
                    duration=duration,
                    source={"id": current.id, "status": current.status},
                )

        # Timeout - but check if status is actually success
        # When no channels are mapped, Dispatcharr completes instantly
        if last_status == "success":
            return RefreshResult(
                success=True,
                message=last_message or "EPG refresh completed (no channels mapped yet)",
                duration=float(timeout),
                last_status=last_status,
                last_message=last_message,
            )

        return RefreshResult(
            success=False,
            message=f"EPG refresh timed out after {timeout} seconds",
            duration=float(timeout),
            last_status=last_status,
            last_message=last_message,
        )

    def refresh_by_name(self, name: str) -> RefreshResult:
        """Refresh EPG source by name (partial match).

        Args:
            name: Name to search for

        Returns:
            RefreshResult with success status
        """
        source = self.find_by_name(name)
        if not source:
            return RefreshResult(
                success=False,
                message=f"No EPG source found matching '{name}'",
            )
        return self.refresh(source.id)

    def supports_program_search(self, force: bool = False) -> bool:
        """Check whether this Dispatcharr build exposes program-data search.

        Probes GET /api/epg/programs/search/ once with page_size=1 and caches
        the result. A 404 means the endpoint is unavailable (older Dispatcharr)
        and callers should degrade gracefully. The result is cached so this is
        cheap to call repeatedly within a generation run.

        Args:
            force: Re-probe even if a cached result exists.

        Returns:
            True if the endpoint responds (HTTP 200), False if absent (404).
            On other/transient errors, returns False without caching so a
            later call can retry.
        """
        if self._programs_search_supported is not None and not force:
            return self._programs_search_supported

        response = self._client.get(f"{self._PROGRAMS_SEARCH_PATH}?page_size=1")
        if response is None:
            # Connection/auth failure — unknown, don't cache a negative.
            logger.debug("[EPG] Program-search probe got no response; treating as unsupported")
            return False

        if response.status_code == 200:
            self._programs_search_supported = True
            logger.debug("[EPG] Program-search endpoint supported")
            return True

        if response.status_code == 404:
            self._programs_search_supported = False
            logger.info(
                "[EPG] Program-search endpoint not available on this Dispatcharr build "
                "(HTTP 404); EPG-based matching disabled"
            )
            return False

        # Other status (401/5xx) — unknown, don't cache so we retry later.
        logger.debug(
            "[EPG] Program-search probe returned HTTP %s; treating as unsupported for now",
            response.status_code,
        )
        return False

    def search_programs(
        self,
        tvg_id: str | None = None,
        start_before: str | None = None,
        end_after: str | None = None,
        title: str | None = None,
        channel_id: int | None = None,
        epg_source: int | str | None = None,
        page_size: int = 500,
        fields: str | None = None,
    ) -> list[DispatcharrProgram]:
        """Search EPG programs via /api/epg/programs/search/.

        Fetches all matching programs across pages (DRF-paginated). Use the
        time-window params to scope a single day: pass start_before=<window end>
        and end_after=<window start> to get programs overlapping that window.

        Feature-gated: if the endpoint is unavailable (older Dispatcharr), this
        returns an empty list and logs once. Check supports_program_search()
        first if you need to distinguish "unsupported" from "no results".

        Args:
            tvg_id: Restrict to a single tvg_id (guide channel).
            start_before: Only programs starting before this ISO8601 time.
            end_after: Only programs ending after this ISO8601 time.
            title: Server-side substring filter on program title.
            channel_id: Restrict to programs on a specific Dispatcharr channel.
            epg_source: Restrict to a specific EPG source (id or name).
            page_size: Page size for pagination (default 500).
            fields: Optional comma-separated field projection (server-supported).

        Returns:
            List of DispatcharrProgram. Empty if unsupported or no matches.
        """
        if not self.supports_program_search():
            return []

        params: dict[str, str | int] = {"page_size": page_size}
        if tvg_id is not None:
            params["tvg_id"] = tvg_id
        if start_before is not None:
            params["start_before"] = start_before
        if end_after is not None:
            params["end_after"] = end_after
        if title is not None:
            params["title"] = title
        if channel_id is not None:
            params["channel_id"] = channel_id
        if epg_source is not None:
            params["epg_source"] = epg_source
        if fields is not None:
            params["fields"] = fields

        endpoint = f"{self._PROGRAMS_SEARCH_PATH}?{urlencode(params)}"
        raw = self._client.paginated_get(endpoint, error_context="epg programs")

        programs: list[DispatcharrProgram] = []
        for item in raw:
            try:
                programs.append(DispatcharrProgram.from_api(item))
            except (KeyError, TypeError) as e:
                logger.debug("[EPG] Skipping malformed program record: %s", e)
        return programs

    def test_connection(self) -> dict:
        """Test connection to Dispatcharr EPG API.

        Returns:
            Dict with success, message, and optionally sources list
        """
        try:
            sources = self.list_sources()
            return {
                "success": True,
                "message": f"Connected successfully. Found {len(sources)} EPG source(s).",
                "sources": [{"id": s.id, "name": s.name} for s in sources],
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error: {e!s}",
            }
