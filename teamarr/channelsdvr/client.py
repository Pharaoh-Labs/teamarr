"""Channels DVR Server client for triggering M3U + XMLTV refresh.

Channels DVR exposes an unauthenticated REST API on port 8089
(see https://getchannels.com/docs/server-api/introduction/). The API
requires requests to originate from the same local network — Teamarr
deployments live next to the DVR, so no auth handling is needed here.

CDVR splits "channels" and "guide" into two providers, each with its
own refresh verb:

* ``POST /providers/m3u/sources/<source_name>/refresh`` — refreshes the
  M3U channel list. Returns ``200 OK`` with body ``true`` as soon as the
  request is accepted; the actual refresh runs in the background.
* ``PUT /dvr/lineups/<lineup_id>`` — refreshes the XMLTV lineup that
  CDVR creates alongside an M3U source with EPG. Without this call the
  channel list is fresh but the guide data is stale, which is the
  whole reason Teamarr triggers the hook.

Both endpoints accept immediately and run the work in the background —
the 200 means "request accepted", not "refresh finished". Because CDVR's
guide lineup is tied to the M3U source, the steps must actually be
sequenced or the guide can index against a stale channel list:

    M3U refresh accepted (200)
      → wait for "[M3U] Refreshed lineup for <source>"   (channels current)
      → guide PUT accepted (200)
      → wait for "[DVR] Fetched guide data for <lineup>"  (guide pulled)
      → wait for "[DVR] Indexed N airings into <lineup>"  (guide live)

Each wait polls CDVR's own server log (``GET /log``) for *evidence* that
the prior step finished — it does not sleep a fixed amount. We capture a
log watermark before each request and only accept a matching line newer
than it, so we confirm *our* refresh completed rather than matching a
stale line. The timeouts are give-up ceilings (so generation can't hang
when CDVR errors), not delays.
"""

import logging
import re
import time
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class ChannelsDVRClient:
    """Client for Channels DVR Server API."""

    SERVER_LABEL: str = "CHANNELSDVR"

    # /log re-read cadence while waiting for an evidence line. We break the
    # moment the evidence appears, so this only bounds detection lag (≤2s).
    LOG_POLL_INTERVAL: float = 2.0
    # Give-up ceilings (NOT fixed waits) — how long to keep polling for each
    # evidence line before logging "couldn't confirm" and proceeding anyway.
    M3U_COMPLETION_TIMEOUT: float = 60.0  # "[M3U] Refreshed lineup for <source>"
    GUIDE_FETCH_TIMEOUT: float = 30.0  # "[DVR] Fetched guide data for <lineup>"
    GUIDE_INDEX_TIMEOUT: float = 30.0  # "[DVR] Indexed N airings into <lineup>"

    def __init__(
        self,
        base_url: str,
        source_name: str = "",
        lineup_id: str = "",
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        # CDVR names the XMLTV lineup of a custom M3U source "XMLTV-<source_name>"
        # (e.g. source "dispatcharr" → lineup "XMLTV-dispatcharr"). When no lineup
        # is explicitly configured, derive it from the source so the guide refresh
        # still fires — otherwise the channels refresh but the EPG silently doesn't.
        self.lineup_id = lineup_id or (f"XMLTV-{source_name}" if source_name else "")
        # True when lineup_id was derived rather than explicitly configured.
        self.lineup_derived = bool(not lineup_id and self.lineup_id)
        self.timeout = timeout

    def _source_path(self) -> str:
        return f"/providers/m3u/sources/{quote(self.source_name, safe='')}"

    # --- CDVR /log evidence polling ------------------------------------
    # CDVR's refresh endpoints are fire-and-forget, but the server logs a
    # line when each background step actually finishes. We poll GET /log for
    # those lines to sequence the steps (channels current -> guide pulled ->
    # guide indexed) on real evidence rather than a fixed delay.

    @staticmethod
    def _log_timestamp(line: str) -> str:
        """Extract the leading 'YYYY/MM/DD HH:MM:SS.ffffff' stamp from a log line.

        CDVR log lines are '<ts> [TAG] message'; the fixed-width stamp sorts
        lexically in chronological order, so string comparison == time order.
        Returns '' for lines that don't start with a stamp.
        """
        ts = line.split(" [", 1)[0]
        return ts if len(ts) >= 19 and ts[:4].isdigit() else ""

    def _fetch_log(self) -> str | None:
        """Return CDVR's server log text, or None if /log is unreachable."""
        try:
            resp = httpx.get(f"{self.base_url}/log", timeout=self.timeout)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError:
            return None

    def _latest_log_marker(self, pattern: re.Pattern) -> str | None:
        """Lexically-greatest timestamp of log lines matching ``pattern``.

        Returns None when /log is unreachable (caller can't verify), or '' when
        reachable but no matching line exists yet. Used as a pre-request
        watermark so a later match newer than it is known to be *ours*.
        """
        text = self._fetch_log()
        if text is None:
            return None
        marker = ""
        for line in text.splitlines():
            if pattern.search(line):
                ts = self._log_timestamp(line)
                if ts > marker:
                    marker = ts
        return marker

    def _poll_log_for(
        self,
        pattern: re.Pattern,
        since_marker: str,
        timeout: float,
    ) -> str | None:
        """Poll /log until a line matching ``pattern`` newer than ``since_marker`` appears.

        Returns the matching line as soon as it shows up (no fixed wait), or
        None if ``timeout`` seconds elapse first / the log stays unreachable.
        """
        deadline = time.monotonic() + timeout
        while True:
            text = self._fetch_log()
            if text is not None:
                match = None
                for line in text.splitlines():
                    if pattern.search(line) and self._log_timestamp(line) > since_marker:
                        match = line
                if match:
                    return match
            if time.monotonic() >= deadline:
                return None
            time.sleep(self.LOG_POLL_INTERVAL)

    def list_m3u_sources(self) -> dict:
        """Fetch the list of M3U sources configured on the server.

        Channels DVR has no list endpoint at /providers/m3u/sources; instead
        every tuner and provider surfaces under /devices, and M3U sources are
        the entries with Provider == "m3u". The FriendlyName field is the
        source name used in /providers/m3u/sources/<name>/refresh.

        Returns:
            dict with success, sources (list of source names), error
        """
        try:
            resp = httpx.get(
                f"{self.base_url}/devices",
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.ConnectError:
            return {
                "success": False,
                "sources": [],
                "error": f"Cannot connect to {self.base_url}",
            }
        except httpx.HTTPError as e:
            return {"success": False, "sources": [], "error": str(e)}

        try:
            data = resp.json()
        except ValueError:
            return {
                "success": False,
                "sources": [],
                "error": "Devices endpoint did not return JSON",
            }

        sources: list[str] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                provider = item.get("Provider") or item.get("provider") or ""
                if str(provider).lower() != "m3u":
                    continue
                name = (
                    item.get("FriendlyName")
                    or item.get("friendlyName")
                    or item.get("Name")
                    or item.get("name")
                )
                if name:
                    sources.append(str(name))

        return {"success": True, "sources": sources}

    def test_connection(self) -> dict:
        """Verify connectivity, version, and that the source exists.

        Returns:
            dict with success, server_version, source_name, error
        """
        try:
            resp = httpx.get(
                f"{self.base_url}/status",
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.ConnectError:
            return {
                "success": False,
                "error": f"Cannot connect to {self.base_url}",
            }
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}

        server_version: str | None = None
        try:
            data = resp.json()
            server_version = data.get("version") if isinstance(data, dict) else None
        except ValueError:
            # /status returned non-JSON — still treat as reachable
            pass

        if not self.source_name:
            return {
                "success": True,
                "server_version": server_version,
                "source_name": None,
            }

        try:
            src_resp = httpx.get(
                f"{self.base_url}{self._source_path()}",
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            return {
                "success": False,
                "server_version": server_version,
                "error": f"Failed to verify source: {e}",
            }

        if src_resp.status_code == 404:
            return {
                "success": False,
                "server_version": server_version,
                "error": f"Source '{self.source_name}' not found on Channels DVR",
            }
        if src_resp.status_code >= 400:
            return {
                "success": False,
                "server_version": server_version,
                "error": f"Source check returned HTTP {src_resp.status_code}",
            }

        return {
            "success": True,
            "server_version": server_version,
            "source_name": self.source_name,
        }

    def trigger_m3u_refresh(
        self, timeout: int = 60, wait_for_completion: bool = False
    ) -> dict:
        """Trigger an M3U source refresh on the Channels DVR server.

        The POST returns immediately — CDVR runs the refresh in the
        background. With ``wait_for_completion`` the method then polls
        ``GET /log`` for the "[M3U] Refreshed lineup for <source>" line that
        marks the channel-list refresh as actually done, so a caller can
        sequence a guide refresh only once the channels are current. This is
        evidence-based (breaks the moment the line appears); the timeout is a
        give-up ceiling, not a fixed wait.

        Returns:
            dict with success, message, duration, and — when
            ``wait_for_completion`` — ``completed`` (True/False/None) and
            ``completion_detail``.
        """
        if not self.source_name:
            return {
                "success": False,
                "message": "No source name configured",
                "duration": 0,
            }

        # Watermark the log BEFORE the POST so a later "Refreshed lineup" line
        # newer than this is known to be from our refresh, not a prior one.
        completion_pattern = re.compile(
            rf"\[M3U\] Refreshed lineup for {re.escape(self.source_name)}\b"
        )
        since_marker = (
            self._latest_log_marker(completion_pattern) if wait_for_completion else None
        )

        start = time.monotonic()
        try:
            resp = httpx.post(
                f"{self.base_url}{self._source_path()}/refresh",
                timeout=timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            duration = time.monotonic() - start
            if e.response.status_code == 404:
                msg = f"Source '{self.source_name}' not found"
            else:
                msg = f"Refresh failed: HTTP {e.response.status_code}"
            return {"success": False, "message": msg, "duration": duration}
        except httpx.HTTPError as e:
            return {
                "success": False,
                "message": f"Refresh failed: {e}",
                "duration": time.monotonic() - start,
            }

        duration = time.monotonic() - start
        logger.info(
            "[%s] Triggered refresh for source '%s' in %.2fs",
            self.SERVER_LABEL,
            self.source_name,
            duration,
        )
        result = {
            "success": True,
            "message": f"Refresh triggered for source '{self.source_name}'",
            "duration": duration,
        }

        if wait_for_completion:
            self._await_m3u_completion(completion_pattern, since_marker, result)

        return result

    def _await_m3u_completion(
        self, pattern: re.Pattern, since_marker: str | None, result: dict
    ) -> None:
        """Poll /log for M3U-refresh completion and annotate ``result`` in place."""
        if since_marker is None:
            result["completed"] = None
            result["completion_detail"] = "CDVR /log unavailable — cannot confirm completion"
            logger.warning(
                "[%s] Cannot confirm M3U refresh completion for '%s' "
                "(/log unreachable); proceeding without sequencing",
                self.SERVER_LABEL,
                self.source_name,
            )
            return

        line = self._poll_log_for(pattern, since_marker, self.M3U_COMPLETION_TIMEOUT)
        if line:
            result["completed"] = True
            logger.info(
                "[%s] M3U refresh for '%s' confirmed complete",
                self.SERVER_LABEL,
                self.source_name,
            )
        else:
            result["completed"] = False
            result["completion_detail"] = (
                f"channel-list refresh not confirmed in CDVR log within "
                f"{self.M3U_COMPLETION_TIMEOUT:.0f}s"
            )
            logger.warning(
                "[%s] M3U refresh for '%s' not confirmed within %.0fs — the guide "
                "may index against a stale channel list",
                self.SERVER_LABEL,
                self.source_name,
                self.M3U_COMPLETION_TIMEOUT,
            )

    def list_lineups(self) -> dict:
        """Fetch the list of XMLTV lineups configured on the server.

        ``GET /dvr/lineups`` returns every guide lineup CDVR knows about —
        Gracenote, XMLTV-from-M3U, and any user-imported XMLTV files. The
        ``ID`` field is what the refresh endpoint expects in the URL path.
        We surface ID + Name so the UI can show a user-friendly label
        while still POSTing the canonical ID.

        Returns:
            dict with success, lineups (list of {id, name}), error
        """
        try:
            resp = httpx.get(
                f"{self.base_url}/dvr/lineups",
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.ConnectError:
            return {
                "success": False,
                "lineups": [],
                "error": f"Cannot connect to {self.base_url}",
            }
        except httpx.HTTPError as e:
            return {"success": False, "lineups": [], "error": str(e)}

        try:
            data = resp.json()
        except ValueError:
            return {
                "success": False,
                "lineups": [],
                "error": "Lineups endpoint did not return JSON",
            }

        lineups: list[dict] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                lineup_id = (
                    item.get("ID")
                    or item.get("Id")
                    or item.get("id")
                    or item.get("Name")
                    or item.get("name")
                )
                if not lineup_id:
                    continue
                name = (
                    item.get("Name")
                    or item.get("name")
                    or str(lineup_id)
                )
                lineups.append({"id": str(lineup_id), "name": str(name)})
        elif isinstance(data, dict):
            # CDVR returns {source_id: lineup_id} — values are the lineup IDs
            # we PUT to /dvr/lineups/<lineup_id> to refresh the guide.
            for _source_id, lineup_id in data.items():
                if not lineup_id:
                    continue
                lineups.append({"id": str(lineup_id), "name": str(lineup_id)})
        else:
            logger.warning(
                "[%s] Unexpected /dvr/lineups response type: %s",
                self.SERVER_LABEL,
                type(data).__name__,
            )

        return {"success": True, "lineups": lineups}

    def trigger_epg_refresh(self, timeout: int = 60, verify: bool = False) -> dict:
        """Trigger an XMLTV lineup refresh on the Channels DVR server.

        Without this call CDVR refreshes the M3U channel list but leaves
        the guide data stale — which is the whole reason this integration
        exists. Endpoint: ``PUT /dvr/lineups/<lineup_id>``. The PUT returns
        ``200`` immediately even when CDVR re-indexes nothing.

        With ``verify`` the method then polls ``GET /log`` for the
        "[DVR] Fetched guide data for <lineup>" line (proof the guide was
        pulled — its absence means the refresh silently did nothing) and the
        following "[DVR] Indexed N airings into <lineup>" line (proof the
        guide is live), turning "request accepted" into "guide re-indexed".

        Returns:
            dict with success, message, duration, and — when ``verify`` —
            ``verified`` (True/False/None) plus ``verification`` (status +
            airings/detail). ``verification.status`` is one of: ``indexed``
            (fetched + indexed), ``fetched`` (pulled but no re-index — content
            unchanged or still indexing), ``no_fetch`` (real failure), or
            ``unverifiable`` (/log unreachable).
        """
        if not self.lineup_id:
            return {
                "success": False,
                "message": "No XMLTV lineup configured",
                "duration": 0,
            }

        # Watermark BEFORE the PUT so the fetch/index lines we match are ours.
        fetched_pattern = re.compile(
            rf"\[DVR\] Fetched guide data for {re.escape(self.lineup_id)}\b"
        )
        indexed_pattern = re.compile(
            rf"\[DVR\] Indexed (\d+) airings into {re.escape(self.lineup_id)}\b"
        )
        since_marker = (
            self._latest_log_marker(re.compile(rf"{re.escape(self.lineup_id)}\b"))
            if verify
            else None
        )

        start = time.monotonic()
        url = f"{self.base_url}/dvr/lineups/{quote(self.lineup_id, safe='')}"
        try:
            resp = httpx.put(url, timeout=timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            duration = time.monotonic() - start
            if e.response.status_code == 404:
                msg = f"Lineup '{self.lineup_id}' not found"
            else:
                msg = f"EPG refresh failed: HTTP {e.response.status_code}"
            return {"success": False, "message": msg, "duration": duration}
        except httpx.HTTPError as e:
            return {
                "success": False,
                "message": f"EPG refresh failed: {e}",
                "duration": time.monotonic() - start,
            }

        duration = time.monotonic() - start
        logger.info(
            "[%s] Triggered EPG refresh for lineup '%s' in %.2fs",
            self.SERVER_LABEL,
            self.lineup_id,
            duration,
        )
        result = {
            "success": True,
            "message": f"EPG refresh triggered for lineup '{self.lineup_id}'",
            "duration": duration,
        }

        if verify:
            self._verify_guide_reindexed(
                fetched_pattern, indexed_pattern, since_marker, result
            )

        return result

    def _verify_guide_reindexed(
        self,
        fetched_pattern: re.Pattern,
        indexed_pattern: re.Pattern,
        since_marker: str | None,
        result: dict,
    ) -> None:
        """Poll /log for guide fetch+index evidence and annotate ``result`` in place."""
        if since_marker is None:
            result["verified"] = None
            result["verification"] = {
                "status": "unverifiable",
                "detail": "CDVR /log unreachable — cannot confirm guide re-index",
            }
            logger.warning(
                "[%s] Cannot verify guide re-index for '%s' (/log unreachable)",
                self.SERVER_LABEL,
                self.lineup_id,
            )
            return

        # Step 1: the guide must actually be fetched. No fetch line = the PUT
        # was accepted but did nothing = the stale-guide failure we must surface.
        fetched = self._poll_log_for(
            fetched_pattern, since_marker, self.GUIDE_FETCH_TIMEOUT
        )
        if not fetched:
            result["verified"] = False
            result["verification"] = {
                "status": "no_fetch",
                "detail": (
                    "CDVR accepted the refresh but never fetched the guide — "
                    "guide is likely stale"
                ),
            }
            logger.warning(
                "[%s] EPG refresh accepted but CDVR never fetched guide '%s' "
                "within %.0fs — guide may be stale",
                self.SERVER_LABEL,
                self.lineup_id,
                self.GUIDE_FETCH_TIMEOUT,
            )
            return

        # Step 2: the fetch should be followed by an index. Its absence is
        # benign (unchanged content is deduped, or indexing is still running).
        indexed = self._poll_log_for(
            indexed_pattern, since_marker, self.GUIDE_INDEX_TIMEOUT
        )
        if indexed:
            match = indexed_pattern.search(indexed)
            airings = int(match.group(1)) if match else None
            result["verified"] = True
            result["verification"] = {"status": "indexed", "airings": airings}
            logger.info(
                "[%s] Guide '%s' re-indexed (%s airings)",
                self.SERVER_LABEL,
                self.lineup_id,
                airings,
            )
        else:
            result["verified"] = True
            result["verification"] = {
                "status": "fetched",
                "detail": (
                    "guide fetched; no re-index observed "
                    "(content unchanged or still indexing)"
                ),
            }
            logger.info(
                "[%s] Guide '%s' fetched; no re-index within %.0fs "
                "(content unchanged or indexing pending)",
                self.SERVER_LABEL,
                self.lineup_id,
                self.GUIDE_INDEX_TIMEOUT,
            )
