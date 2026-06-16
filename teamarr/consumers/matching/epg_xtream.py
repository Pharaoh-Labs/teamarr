"""Xtream-Codes provider EPG support (epic teamarrv2-crs).

When a stream's M3U account is an Xtream-Codes panel (Dispatcharr account_type
"XC"), the provider exposes its OWN guide at a standard endpoint:

    {server_url}/xmltv.php?username=<user>&password=<pass>

Crucially, the channel ids in that XMLTV are the SAME namespace as the M3U's
``tvg_id`` (live-verified: Infinity's xmltv uses ``ESPN.us`` / ``USANetwork.us``
/ ``FoxSports1.us`` — exactly the stream tvg_ids). So a stream that fails to
resolve against Dispatcharr's curated guide (direct/channel/name) can still be
matched against the provider's own guide by an EXACT tvg_id == channel-id hit —
no fuzzing, no ambiguity.

This module only handles detection + URL construction; fetching/parsing the
(large) XMLTV and indexing it lives in the fetch layer. The provider guide is
authoritative for coverage but its per-channel sports overrides are patchier
than a dedicated guide, so it sits BELOW direct/channel/name in the resolution
cascade and above fuzzy.
"""

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from teamarr.dispatcharr.types import DispatcharrProgram

logger = logging.getLogger(__name__)

# Dispatcharr M3U account_type for an Xtream-Codes panel.
_XTREAM_ACCOUNT_TYPE = "XC"

# epg_source label stamped on programs parsed from a provider's own xmltv, so
# they're distinguishable in logs and never collide with DP's "_Teamarr" guard.
XTREAM_EPG_SOURCE = "_xtream"

# XMLTV timestamp: "YYYYMMDDHHMMSS[ +ZZZZ]" (offset optional; assume UTC if absent).
_XMLTV_TIME = re.compile(r"^\s*(\d{14})(?:\s+([+-]\d{4}))?")


def is_xtream_account(account: dict) -> bool:
    """True if the M3U account is an Xtream-Codes panel with usable credentials.

    Requires the Xtream account type plus a server URL, username, and password —
    all three are needed to build the xmltv.php endpoint. A standard ("STD")
    account or one missing credentials returns False.
    """
    if not account or account.get("account_type") != _XTREAM_ACCOUNT_TYPE:
        return False
    return bool(account.get("server_url") and account.get("username") and account.get("password"))


def xmltv_url(account: dict) -> str | None:
    """Build the Xtream xmltv.php EPG URL for an account, or None if not Xtream.

    Mirrors the standard Xtream convention (the M3U ``get.php`` endpoint with
    ``get.php`` swapped for ``xmltv.php``): ``{scheme}://{host}/xmltv.php?
    username=<user>&password=<pass>``. The server URL's path/query/fragment are
    discarded — only scheme + netloc are kept — so a ``server_url`` that already
    points at ``get.php`` or carries a trailing slash still yields a clean URL.
    Credentials are percent-encoded.
    """
    if not is_xtream_account(account):
        return None

    parts = urlsplit(account["server_url"].strip())
    # server_url may be bare ("https://db4.org") or carry a path; keep host only.
    scheme = parts.scheme or "http"
    netloc = parts.netloc or parts.path  # bare "host:port" lands in path when scheme present
    user = quote(str(account["username"]), safe="")
    pwd = quote(str(account["password"]), safe="")
    return urlunsplit((scheme, netloc, "/xmltv.php", f"username={user}&password={pwd}", ""))


def _parse_xmltv_time(value: str | None) -> datetime | None:
    """Parse an XMLTV timestamp ("20260603233000 -0400") to an aware UTC dt."""
    if not value:
        return None
    m = _XMLTV_TIME.match(value)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if m.group(2):
        off = m.group(2)
        sign = 1 if off[0] == "+" else -1
        offset = timedelta(hours=int(off[1:3]), minutes=int(off[3:5]))
        dt = dt.replace(tzinfo=timezone(sign * offset))
    else:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_xmltv_programs(
    fileobj,
    wanted_tvg_ids: set[str],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, list[DispatcharrProgram]]:
    """Stream-parse an XMLTV document into DispatcharrProgram lists per tvg_id.

    Only ``<programme>`` elements whose ``channel`` is in ``wanted_tvg_ids`` AND
    that overlap [window_start, window_end] are kept, so a 100 MB / 300k-entry
    guide is reduced to just the streams and window we care about. Uses
    ``iterparse`` and clears parsed elements so peak memory stays flat.

    The result is keyed by the XMLTV ``channel`` id — which for an Xtream
    provider equals the M3U ``tvg_id`` — and holds the SAME DispatcharrProgram
    dataclass the Dispatcharr path produces, so the index/matcher are agnostic
    to the source. Program ids are synthetic (negative, sequential): these
    programs never came from DP's API.
    """
    if not wanted_tvg_ids:
        return {}

    by_tvg: dict[str, list[DispatcharrProgram]] = {}
    synthetic_id = 0
    # iterparse with a captured root so we can drop processed children and keep
    # memory bounded across the whole document.
    context = ET.iterparse(fileobj, events=("start", "end"))
    _, root = next(context)
    for event, elem in context:
        if event != "end" or elem.tag != "programme":
            continue
        channel = elem.get("channel")
        if channel in wanted_tvg_ids:
            start = _parse_xmltv_time(elem.get("start"))
            stop = _parse_xmltv_time(elem.get("stop"))
            # Overlap test (half-open); skip entries we can't window.
            if start and stop and start < window_end and stop > window_start:
                synthetic_id -= 1
                cats = tuple(c.text for c in elem.findall("category") if c.text)
                title_el = elem.find("title")
                sub_el = elem.find("sub-title")
                desc_el = elem.find("desc")
                by_tvg.setdefault(channel, []).append(
                    DispatcharrProgram(
                        id=synthetic_id,
                        tvg_id=channel,
                        title=(title_el.text or "") if title_el is not None else "",
                        start_time=start.isoformat().replace("+00:00", "Z"),
                        end_time=stop.isoformat().replace("+00:00", "Z"),
                        sub_title=sub_el.text if sub_el is not None else None,
                        description=desc_el.text if desc_el is not None else None,
                        epg_source=XTREAM_EPG_SOURCE,
                        categories=cats,
                    )
                )
        root.clear()  # drop accumulated siblings — keeps memory flat

    for programs in by_tvg.values():
        programs.sort(key=lambda p: p.start_time or "")
    return by_tvg


def _cache_dir() -> Path:
    """Directory for cached provider XMLTV files (mirrors log-dir detection)."""
    if env := os.getenv("TEAMARR_CACHE_DIR"):
        d = Path(env)
    elif Path("/app/data").exists():
        d = Path("/app/data/epg_cache")
    else:
        d = Path(__file__).resolve().parents[3] / "data" / "epg_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_xtream_programs(
    url: str,
    cache_key: str,
    wanted_tvg_ids: set[str],
    window_start: datetime,
    window_end: datetime,
    *,
    ttl_seconds: int = 6 * 3600,
    timeout: float = 60.0,
) -> dict[str, list[DispatcharrProgram]]:
    """Fetch (cached) a provider's xmltv.php and parse it for wanted streams.

    The raw XMLTV is streamed to a per-account cache file and re-downloaded only
    once the file is older than ``ttl_seconds`` (provider guides change slowly;
    the file is large). Parsing is done fresh each call from the cached file,
    filtered to ``wanted_tvg_ids`` + window. Any network/parse failure logs and
    returns ``{}`` so EPG matching degrades to "no Xtream programs" rather than
    breaking generation.
    """
    if not url or not wanted_tvg_ids:
        return {}

    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", cache_key)
    cache_file = _cache_dir() / f"xtream_{safe}.xml"

    fresh = cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < ttl_seconds
    if not fresh:
        try:
            tmp = cache_file.with_suffix(".xml.tmp")
            with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=1 << 16):
                        fh.write(chunk)
            tmp.replace(cache_file)
            logger.info(
                "[XTREAM-EPG] fetched %s -> %s (%d bytes)",
                url.split("?")[0], cache_file.name, cache_file.stat().st_size,
            )
        except (httpx.HTTPError, OSError) as e:
            logger.warning("[XTREAM-EPG] fetch failed for %s: %s", url.split("?")[0], e)
            if not cache_file.exists():
                return {}
            # fall through and use the stale cache if we have one

    try:
        with open(cache_file, "rb") as fh:
            result = parse_xmltv_programs(fh, wanted_tvg_ids, window_start, window_end)
        logger.info(
            "[XTREAM-EPG] parsed %d/%d wanted tvg_ids, %d programs in window",
            len(result), len(wanted_tvg_ids), sum(len(v) for v in result.values()),
        )
        return result
    except (ET.ParseError, OSError) as e:
        logger.warning("[XTREAM-EPG] parse failed for %s: %s", cache_file.name, e)
        return {}
