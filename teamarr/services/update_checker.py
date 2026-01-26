"""Update checker service for version notifications.

Checks for updates from GitHub Releases (stable) or GHCR (dev builds).
Supports optional notifications, caching, and rate limiting.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx

logger = logging.getLogger(__name__)


@dataclass
class UpdateInfo:
    """Information about available updates."""

    current_version: str
    latest_version: str | None
    update_available: bool
    checked_at: datetime
    build_type: Literal["stable", "dev"]
    download_url: str | None = None
    release_notes_url: str | None = None


class UpdateChecker:
    """Base class for update checking."""

    def __init__(
        self,
        current_version: str,
        cache_duration_hours: int = 6,
        timeout_seconds: int = 10,
    ):
        """Initialize update checker.

        Args:
            current_version: Current application version
            cache_duration_hours: How long to cache results (default: 6 hours)
            timeout_seconds: HTTP request timeout (default: 10 seconds)
        """
        self.current_version = current_version
        self.cache_duration_hours = cache_duration_hours
        self.timeout_seconds = timeout_seconds
        self._cached_result: UpdateInfo | None = None
        self._last_check_time: float = 0

    def _is_cache_valid(self) -> bool:
        """Check if cached result is still valid."""
        if not self._cached_result:
            return False
        cache_age = time.time() - self._last_check_time
        cache_max_age = self.cache_duration_hours * 3600
        return cache_age < cache_max_age

    def check_for_updates(self, force: bool = False) -> UpdateInfo | None:
        """Check for updates with caching.

        Args:
            force: Skip cache and force a fresh check

        Returns:
            UpdateInfo if check succeeded, None if check failed
        """
        if not force and self._is_cache_valid():
            logger.debug("[UPDATE_CHECKER] Using cached result")
            return self._cached_result

        try:
            result = self._fetch_update_info()
            self._cached_result = result
            self._last_check_time = time.time()
            return result
        except Exception as e:
            logger.warning("[UPDATE_CHECKER] Failed to check for updates: %s", e)
            # Return cached result if available, even if expired
            return self._cached_result

    def _fetch_update_info(self) -> UpdateInfo:
        """Fetch update information (implemented by subclasses)."""
        raise NotImplementedError


class StableUpdateChecker(UpdateChecker):
    """Check for stable release updates via GitHub Releases API."""

    def __init__(
        self,
        current_version: str,
        owner: str = "Pharaoh-Labs",
        repo: str = "teamarr",
        **kwargs,
    ):
        """Initialize stable update checker.

        Args:
            current_version: Current application version
            owner: GitHub repository owner (default: "Pharaoh-Labs")
            repo: GitHub repository name (default: "teamarr")
            **kwargs: Additional arguments passed to UpdateChecker
        """
        super().__init__(current_version, **kwargs)
        self.owner = owner
        self.repo = repo

    def _fetch_update_info(self) -> UpdateInfo:
        """Fetch latest stable release from GitHub."""
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest"

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        latest_version = data["tag_name"].lstrip("v")
        current_clean = self.current_version.split("-")[0].lstrip("v")

        # Simple version comparison (assumes semver)
        update_available = self._compare_versions(current_clean, latest_version)

        return UpdateInfo(
            current_version=self.current_version,
            latest_version=latest_version,
            update_available=update_available,
            checked_at=datetime.now(UTC),
            build_type="stable",
            download_url=data.get("html_url"),
            release_notes_url=data.get("html_url"),
        )

    @staticmethod
    def _compare_versions(current: str, latest: str) -> bool:
        """Compare semantic versions.

        Args:
            current: Current version (e.g., "2.0.11")
            latest: Latest version (e.g., "2.0.12")

        Returns:
            True if latest > current
        """
        try:
            current_parts = [int(x) for x in current.split(".")]
            latest_parts = [int(x) for x in latest.split(".")]

            # Pad to same length
            max_len = max(len(current_parts), len(latest_parts))
            current_parts.extend([0] * (max_len - len(current_parts)))
            latest_parts.extend([0] * (max_len - len(latest_parts)))

            return latest_parts > current_parts
        except (ValueError, AttributeError):
            logger.warning("[UPDATE_CHECKER] Invalid version format: %s or %s", current, latest)
            return False


class DevUpdateChecker(UpdateChecker):
    """Check for dev build updates via GitHub Container Registry."""

    def __init__(
        self,
        current_version: str,
        owner: str = "pharaoh-labs",
        image: str = "teamarr",
        dev_tag: str = "dev",
        **kwargs,
    ):
        """Initialize dev update checker.

        Args:
            current_version: Current application version with commit SHA
            owner: GitHub repository owner
            image: Container image name
            dev_tag: Docker tag to check (default: "dev")
            **kwargs: Additional arguments passed to UpdateChecker
        """
        super().__init__(current_version, **kwargs)
        self.owner = owner
        self.image = image
        self.dev_tag = dev_tag

    def _extract_sha_from_version(self, version: str) -> str | None:
        """Extract commit SHA from version string.

        Args:
            version: Version string (e.g., "2.0.11-dev+abc123")

        Returns:
            Commit SHA if found, None otherwise
        """
        if "+" in version:
            return version.split("+")[-1]
        return None

    def _fetch_update_info(self) -> UpdateInfo:
        """Fetch latest dev build from GHCR.

        LIMITATION: This implementation cannot reliably detect if updates are available
        for dev builds. It fetches the manifest digest but always returns
        update_available=false because:
        1. We don't persist the previous digest to compare against
        2. Build timestamps aren't directly comparable without image metadata
        3. Digest comparison would require storing state

        A full implementation would need to:
        - Store the last seen digest in database
        - Compare current manifest digest with stored digest
        - Or parse image labels/metadata for build timestamps

        For now, this provides visibility into the latest dev build but doesn't
        actively notify of updates. Users can manually check the digest changes.
        """
        # For dev builds, we check the manifest of the configured tag
        # A more sophisticated approach would compare digests
        url = f"https://ghcr.io/v2/{self.owner}/{self.image}/manifests/{self.dev_tag}"

        headers = {
            "Accept": "application/vnd.docker.distribution.manifest.v2+json",
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()

            # Get the digest from the Docker-Content-Digest header
            latest_digest = response.headers.get("Docker-Content-Digest", "")

        # Conservative: don't claim updates unless we can reliably detect them
        update_available = False

        return UpdateInfo(
            current_version=self.current_version,
            latest_version=f"{self.dev_tag} ({latest_digest[:12] if latest_digest else 'unknown'})",
            update_available=update_available,
            checked_at=datetime.now(UTC),
            build_type="dev",
            download_url=f"https://ghcr.io/{self.owner}/{self.image}:{self.dev_tag}",
        )


def create_update_checker(
    version: str,
    owner: str = "Pharaoh-Labs",
    repo: str = "teamarr",
    ghcr_owner: str | None = None,
    ghcr_image: str | None = None,
    dev_tag: str = "dev",
    cache_duration_hours: int = 6,
) -> UpdateChecker:
    """Factory function to create appropriate update checker.

    Args:
        version: Current application version
        owner: GitHub repository owner for stable releases (default: "Pharaoh-Labs")
        repo: GitHub repository name (default: "teamarr")
        ghcr_owner: GHCR repository owner for dev builds (defaults to "pharaoh-labs")
        ghcr_image: GHCR image name for dev builds (defaults to repo)
        dev_tag: Docker tag to check for dev builds (default: "dev")
        cache_duration_hours: How long to cache results

    Returns:
        StableUpdateChecker for stable releases, DevUpdateChecker for dev builds
    """
    # Use lowercase for GHCR if not specified (Docker registry is case-sensitive lowercase)
    if ghcr_owner is None:
        ghcr_owner = "pharaoh-labs"
    if ghcr_image is None:
        ghcr_image = repo

    # Detect build type from version string
    # Stable: X.Y.Z (e.g., "2.0.11")
    # Dev: X.Y.Z-branch+sha (e.g., "2.0.11-dev+abc123", "2.0.11-feature/xyz+def456")
    # The presence of both "-" and "+" indicates a dev build with branch and commit info
    is_dev = "-" in version and "+" in version

    if is_dev:
        return DevUpdateChecker(
            current_version=version,
            owner=ghcr_owner,
            image=ghcr_image,
            dev_tag=dev_tag,
            cache_duration_hours=cache_duration_hours,
        )
    else:
        return StableUpdateChecker(
            current_version=version,
            owner=owner,
            repo=repo,
            cache_duration_hours=cache_duration_hours,
        )
