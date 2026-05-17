"""Fetch and parse external XMLTV EPG feeds.

Handles plain XML and gzip-compressed XMLTV sources.
"""

import gzip
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from io import BytesIO
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_USER_AGENT = "Teamarr/2.0 (EPG Source Fetcher)"


def fetch_xmltv(url: str, timeout: int = 60) -> str:
    """Fetch XMLTV content from URL, auto-detecting gzip compression."""
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        content_encoding = resp.headers.get("Content-Encoding", "")

        if content_encoding == "gzip" or url.rstrip("/").endswith(".gz"):
            try:
                raw = gzip.decompress(raw)
            except gzip.BadGzipFile:
                pass
        elif raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)

        return raw.decode("utf-8", errors="replace")


def parse_xmltv_channels(xml_content: str) -> list[dict]:
    """Parse <channel> elements from XMLTV content."""
    channels = []
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.error("[XMLTV_PARSER] Failed to parse XML: %s", e)
        return channels

    for elem in root.findall("channel"):
        xmltv_id = elem.get("id", "")
        if not xmltv_id:
            continue

        display_name = ""
        dn_elem = elem.find("display-name")
        if dn_elem is not None and dn_elem.text:
            display_name = dn_elem.text.strip()

        icon_url = None
        icon_elem = elem.find("icon")
        if icon_elem is not None:
            icon_url = icon_elem.get("src")

        channels.append({
            "xmltv_id": xmltv_id,
            "display_name": display_name or xmltv_id,
            "icon_url": icon_url,
        })

    return channels


def _parse_xmltv_datetime(dt_str: str) -> datetime | None:
    """Parse XMLTV datetime format: YYYYMMDDHHmmss +HHMM."""
    if not dt_str:
        return None
    dt_str = dt_str.strip()

    for fmt in (
        "%Y%m%d%H%M%S %z",
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M %z",
        "%Y%m%d%H%M",
        "%Y%m%d",
    ):
        try:
            dt = datetime.strptime(dt_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def parse_xmltv_programmes(
    xml_content: str,
    channel_ids: set[str] | None = None,
) -> list[dict]:
    """Parse <programme> elements from XMLTV content."""
    programmes = []
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.error("[XMLTV_PARSER] Failed to parse XML: %s", e)
        return programmes

    for elem in root.findall("programme"):
        channel = elem.get("channel", "")
        if channel_ids is not None and channel not in channel_ids:
            continue

        start_str = elem.get("start", "")
        stop_str = elem.get("stop", "")
        start = _parse_xmltv_datetime(start_str)
        stop = _parse_xmltv_datetime(stop_str)
        if not start or not stop:
            continue

        title_elem = elem.find("title")
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
        if not title:
            continue

        desc_elem = elem.find("desc")
        description = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else None

        sub_elem = elem.find("sub-title")
        subtitle = sub_elem.text.strip() if sub_elem is not None and sub_elem.text else None

        categories = []
        for cat_elem in elem.findall("category"):
            if cat_elem.text:
                categories.append(cat_elem.text.strip())

        programmes.append({
            "channel_xmltv_id": channel,
            "title": title,
            "start": start.isoformat(),
            "stop": stop.isoformat(),
            "description": description,
            "subtitle": subtitle,
            "categories": categories or None,
        })

    return programmes


def fetch_and_parse_source(
    url: str, timeout: int = 60
) -> tuple[list[dict], list[dict]]:
    """Fetch and parse an XMLTV source in one call.

    Returns (channels, programmes).
    """
    xml_content = fetch_xmltv(url, timeout=timeout)
    channels = parse_xmltv_channels(xml_content)
    programmes = parse_xmltv_programmes(xml_content)
    return channels, programmes
