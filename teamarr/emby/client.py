"""Emby server client for Live TV guide refresh.

Lightweight HTTP client using httpx to authenticate with Emby
and trigger a Live TV guide refresh after EPG generation.

Jellyfin (which forked from Emby) is API-compatible. JellyfinClient
subclasses this and only overrides the URL path prefix — Emby uses
``/emby/...`` while Jellyfin omits the prefix.
"""

import logging
import time
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

# Auth header required for all Emby API calls
_EMBY_AUTH_HEADER = (
    'MediaBrowser Client="Teamarr", Device="Server",'
    ' DeviceId="teamarr", Version="1.0"'
)


class EmbyClient:
    """Client for Emby server API interactions."""

    # Path prefix in front of every Emby API URL. Subclasses (e.g.
    # JellyfinClient) can set this to "" to target servers that don't
    # mount the API under /emby/.
    PATH_PREFIX: str = "/emby"

    # Display name used in log messages — overridable by subclasses.
    SERVER_LABEL: str = "EMBY"

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        timeout: int = 30,
        api_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.api_key = api_key
        self._access_token: str | None = api_key  # Pre-set if API key provided
        self._user_id: str | None = None

    def _url(self, path: str) -> str:
        """Build a full URL for an API path (e.g. '/ScheduledTasks')."""
        return f"{self.base_url}{self.PATH_PREFIX}{path}"

    def _auth_headers(self) -> dict[str, str]:
        """Build headers for unauthenticated requests."""
        return {
            "X-Emby-Authorization": _EMBY_AUTH_HEADER,
            "Content-Type": "application/json",
        }

    def _token_headers(self) -> dict[str, str]:
        """Build headers for authenticated requests."""
        if not self._access_token:
            raise RuntimeError("Not authenticated — call authenticate() first")
        return {"X-Emby-Token": self._access_token}

    def authenticate(self) -> bool:
        """Authenticate with Emby server.

        When an API key is configured, skips username/password auth and
        uses the key directly as the access token.

        Returns:
            True if authentication succeeded
        """
        # API key auth: already pre-set in __init__, just validate it works
        if self.api_key:
            self._access_token = self.api_key
            try:
                resp = httpx.get(
                    self._url("/ScheduledTasks"),
                    headers=self._token_headers(),
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                logger.debug("[%s] Authenticated via API key", self.SERVER_LABEL)
                return True
            except httpx.HTTPError as e:
                logger.warning(
                    "[%s] API key authentication failed: %s", self.SERVER_LABEL, e
                )
                self._access_token = None
                return False

        # Username/password auth
        url = self._url("/Users/AuthenticateByName")
        payload = {"Username": self.username, "Pw": self.password}

        try:
            resp = httpx.post(
                url,
                json=payload,
                headers=self._auth_headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data.get("AccessToken")
            user = data.get("User", {})
            self._user_id = user.get("Id")
            if self._access_token:
                logger.debug(
                    "[%s] Authenticated as %s", self.SERVER_LABEL, self.username
                )
                return True
            logger.warning("[%s] Auth response missing AccessToken", self.SERVER_LABEL)
            return False
        except httpx.HTTPError as e:
            logger.warning("[%s] Authentication failed: %s", self.SERVER_LABEL, e)
            self._access_token = None
            self._user_id = None
            return False

    def test_connection(self) -> dict:
        """Test connection to the media server.

        Returns:
            dict with success, server_name, server_version, error
        """
        # First try to get server info (public endpoint)
        try:
            resp = httpx.get(
                self._url("/System/Info/Public"),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            info = resp.json()
        except httpx.ConnectError:
            return {
                "success": False,
                "error": f"Cannot connect to {self.base_url}",
            }
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}

        server_name = info.get("ServerName", "Unknown")
        server_version = info.get("Version", "Unknown")

        # Now test authentication
        if not self.authenticate():
            error_msg = (
                "Authentication failed — check API key"
                if self.api_key
                else "Authentication failed — check username/password"
            )
            return {
                "success": False,
                "server_name": server_name,
                "server_version": server_version,
                "error": error_msg,
            }

        return {
            "success": True,
            "server_name": server_name,
            "server_version": server_version,
        }

    def trigger_guide_refresh(
        self,
        timeout: int = 300,
        poll_interval: int = 5,
        on_progress: Callable[[float], None] | None = None,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> dict:
        """Trigger the Live TV guide refresh and wait for completion.

        Args:
            timeout: Maximum seconds to wait for refresh
            poll_interval: Seconds between status polls
            on_progress: Callback with progress percentage (0-100)
            cancellation_check: Returns True if operation should be cancelled

        Returns:
            dict with success, message, duration
        """
        if not self._access_token and not self.authenticate():
            return {
                "success": False,
                "message": "Authentication failed",
                "duration": 0,
            }

        headers = self._token_headers()
        start_time = time.monotonic()

        # Find the RefreshGuide task
        try:
            resp = httpx.get(
                self._url("/ScheduledTasks"),
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            tasks = resp.json()
        except httpx.HTTPError as e:
            return {
                "success": False,
                "message": f"Failed to list scheduled tasks: {e}",
                "duration": 0,
            }

        guide_task = None
        for task in tasks:
            if task.get("Key") == "RefreshGuide":
                guide_task = task
                break

        if not guide_task:
            return {
                "success": False,
                "message": (
                    f"RefreshGuide task not found on {self.SERVER_LABEL.title()} server"
                ),
                "duration": 0,
            }

        task_id = guide_task["Id"]

        # Trigger the task
        try:
            resp = httpx.post(
                self._url(f"/ScheduledTasks/Running/{task_id}"),
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            logger.info(
                "[%s] Triggered guide refresh (task %s)", self.SERVER_LABEL, task_id
            )
        except httpx.HTTPError as e:
            return {
                "success": False,
                "message": f"Failed to trigger guide refresh: {e}",
                "duration": 0,
            }

        # Poll until complete or timeout
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                return {
                    "success": False,
                    "message": f"Guide refresh timed out after {timeout}s",
                    "duration": elapsed,
                }

            if cancellation_check and cancellation_check():
                return {
                    "success": False,
                    "message": "Guide refresh cancelled",
                    "duration": elapsed,
                }

            time.sleep(poll_interval)

            try:
                resp = httpx.get(
                    self._url(f"/ScheduledTasks/{task_id}"),
                    headers=headers,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                task_info = resp.json()
            except httpx.HTTPError as e:
                logger.warning("[%s] Poll failed: %s", self.SERVER_LABEL, e)
                continue

            state = task_info.get("State", "")
            progress = task_info.get("CurrentProgressPercentage")

            if progress is not None and on_progress:
                on_progress(float(progress))

            if state == "Idle":
                duration = time.monotonic() - start_time
                last_result = task_info.get("LastExecutionResult", {})
                status = last_result.get("Status", "Unknown")
                if status == "Completed":
                    return {
                        "success": True,
                        "message": "Guide refresh completed",
                        "duration": duration,
                    }
                elif status == "Failed":
                    error_msg = last_result.get(
                        "ErrorMessage", "Unknown error"
                    )
                    return {
                        "success": False,
                        "message": f"Guide refresh failed: {error_msg}",
                        "duration": duration,
                    }
                else:
                    return {
                        "success": True,
                        "message": f"Guide refresh finished (status: {status})",
                        "duration": duration,
                    }
