"""Plex Media Server client for Live TV channel-map refresh.

Plex's Live TV & DVR feature (pointed at Dispatcharr's HDHomeRun emulation)
does not notice new/removed channels on its own. The fix is one call after
each Teamarr generation:

* ``PUT /media/grabbers/devices/<device_key>/channelmap`` — the enable/EPG-bind
  call. This is what Plex's own UI sends when you open a tuner's Channel
  Matching screen and hit Save — even with no changes — and doing so
  triggers a full guide refresh on Plex's side as an observed side effect
  (2026-09-12 live testing). It's a **full-state-replace**, and that applies
  to BOTH ``channelsEnabled`` and the per-channel ``channelMappingByKey``/
  ``channelMapping`` params: a channel present in ``channelsEnabled`` but
  missing its own mapping entry gets disabled anyway — omitting "unchanged"
  channels from the mapping to avoid resending them is NOT safe, despite
  looking like a harmless delta. An integration that PUTs only its own
  channels' mapping would therefore silently disable every other channel
  on that device (other tools, manually-added channels, etc.) — see
  ``compute_channelmap_update``, which resubmits every enabled channel
  outside Teamarr's own channel-number range with its own current,
  unchanged binding.

  A separate ``POST /livetv/dvrs/<dvr_id>/reloadGuide`` endpoint exists and
  was used here previously on the assumption it refreshes programme data —
  live testing showed it does not reliably do that (a channel reassigned
  to a different event kept showing stale guide data through several
  ``reloadGuide`` calls). It's not used by this client.

This endpoint requires ``X-Plex-Token`` (sent as a header here) — no other
auth scheme. ``GET /livetv/dvrs`` is the read side: it returns every DVR and
its attached HDHomeRun devices, each carrying its current ``ChannelMapping``
(channelKey/enabled/lineupIdentifier/deviceIdentifier) — the fetch half of
the fetch-merge-write cycle.

Verified against a live server (2026-09): ``deviceIdentifier`` is the
stable Dispatcharr/HDHomeRun physical channel number and never changes.
``channelKey`` is whatever EPG entry is *currently matched* in Plex's
Channel Matching UI — it starts out equal to ``deviceIdentifier`` but
diverges the moment that match is changed (manually, or by Plex's own
auto-matching). Everything here keys on ``deviceIdentifier``; ``channelKey``
is kept only for display/debugging and must never drive an ownership or
identity decision.
"""

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

logger = logging.getLogger(__name__)


@dataclass
class PlexChannelMapping:
    """One tuner-channel entry on a Plex DVR device.

    ``device_identifier`` is the stable Dispatcharr/HDHomeRun physical
    channel number — the identity everything is keyed on. ``channel_key``
    is Plex's currently-matched EPG guide channel (mutable, display-only —
    never use it for ownership/identity, see module docstring).
    ``lineup_identifier`` is the EPG binding to preserve for a foreign
    channel that isn't Teamarr's own.
    """

    device_identifier: str
    enabled: bool
    lineup_identifier: str | None = None
    channel_key: str | None = None


@dataclass
class PlexDevice:
    """One HDHomeRun (emulated) device attached to a Plex DVR."""

    key: str
    device_id: str | None = None
    uri: str | None = None
    channel_mapping: list[PlexChannelMapping] = field(default_factory=list)

    @property
    def profile_hint(self) -> str | None:
        """Last path segment of ``uri`` (e.g. the Dispatcharr profile name).

        None for root-scoped devices (``.../hdhr`` with no suffix, or no
        URI at all) — those pull every channel from every profile and need
        manual confirmation rather than an automatic match.
        """
        if not self.uri:
            return None
        path = urlsplit(self.uri).path.rstrip("/")
        segment = path.rsplit("/", 1)[-1] if path else ""
        return segment if segment and segment.lower() != "hdhr" else None


@dataclass
class PlexDvr:
    """One DVR configured in Plex Live TV."""

    key: str
    lineup_title: str | None = None
    lineup: str | None = None
    devices: list[PlexDevice] = field(default_factory=list)


def _as_list(value: Any) -> list:
    """Normalize a Plex JSON container that may collapse to a bare object.

    Plex-style APIs are known to return a single-child container as one
    object instead of a 1-element array (e.g. one DVR, one device, one
    channel mapping) — unverified here against a live server, but cheap
    to guard against regardless.
    """
    if isinstance(value, dict):
        return [value]
    return list(value) if value else []


def _channel_sort_key(channel_key: str) -> tuple[int, object]:
    try:
        return (0, int(float(channel_key)))
    except (TypeError, ValueError):
        return (1, channel_key)


_LINEUP_PREFIX = "lineup://tv.plex.providers.epg.xmltv/"


def guide_path_from_lineup(lineup: str | None) -> str | None:
    """Path + query of the XMLTV guide URL embedded in a DVR ``lineup`` string.

    Plex stores it as ``lineup://tv.plex.providers.epg.xmltv/<urlencoded url>#<title>``.
    Only the path/query is returned: the host is Plex's view of Dispatcharr, which
    need not be reachable under the same name from Teamarr.
    """
    if not lineup or not lineup.startswith(_LINEUP_PREFIX):
        return None
    url = unquote(lineup[len(_LINEUP_PREFIX) :].split("#", 1)[0])
    parts = urlsplit(url)
    if not parts.path:
        return None
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def is_complete_xmltv(content: bytes) -> bool:
    """True when ``content`` is a whole, well-formed XMLTV document.

    Plex was observed (2026-09-20) crashing outright when it fetched the guide
    while Dispatcharr was still rewriting it — libxml reported "Extra content at
    the end of the document" on a file cut off mid-<programme>, then the server
    died with SIGFPE.
    """
    try:
        return ET.fromstring(content).tag == "tv"
    except ET.ParseError:
        return False


def compute_channelmap_update(
    current: list[PlexChannelMapping],
    teamarr_channel_keys: set[str],
    teamarr_range: tuple[int, int | None] | None,
) -> tuple[list[str], dict[str, str]]:
    """Fetch-merge-write core: compute the full PUT payload for one device.

    ``current`` is the device's existing ``ChannelMapping`` (from
    ``PlexClient.list_dvrs``). Every currently-enabled channel OUTSIDE
    ``teamarr_range`` is preserved untouched in ``channelsEnabled`` — this
    is what protects other tools' or manually-added channels sharing the
    same device, especially on a root-scoped device pulling multiple
    profiles. ``teamarr_range`` is ``(start, end)`` with ``end=None``
    meaning unbounded; pass ``None`` only when Teamarr manages no range at
    all (nothing is preserved-vs-owned in that case — every enabled
    channel is treated as foreign).

    Everything is keyed on ``device_identifier`` (the stable Dispatcharr
    physical channel number), never ``channel_key`` (Plex's mutable,
    currently-matched EPG guide channel — see module docstring).

    Returns ``(enabled_channel_keys, channel_mapping)`` ready for
    ``PlexClient.update_channelmap``. ``channel_mapping`` MUST cover every
    enabled channel on the device (preserved foreign ones too), not just
    Teamarr's own — live testing (2026-09-12) showed a channel present in
    ``channelsEnabled`` but absent from ``channelMappingByKey``/
    ``channelMapping`` gets disabled anyway, i.e. this is not the delta it
    looks like; a preserved channel's own current ``lineup_identifier`` is
    resubmitted unchanged, never overwritten.
    """

    def _owned_by_teamarr(device_identifier: str) -> bool:
        if teamarr_range is None:
            return False
        start, end = teamarr_range
        try:
            number = int(float(device_identifier))
        except (TypeError, ValueError):
            return False
        if end is None:
            return number >= start
        return start <= number <= end

    preserved = [
        m for m in current if m.enabled and not _owned_by_teamarr(m.device_identifier)
    ]

    mapping: dict[str, str] = {
        m.device_identifier: m.lineup_identifier or m.device_identifier for m in preserved
    }
    for key in teamarr_channel_keys:
        mapping[key] = key

    enabled = sorted(mapping, key=_channel_sort_key)
    return enabled, mapping


class PlexClient:
    """Client for the Plex Media Server Live TV / DVR API."""

    SERVER_LABEL: str = "PLEX"

    def __init__(self, base_url: str, token: str = "", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"X-Plex-Token": self.token, "Accept": "application/json"}

    def list_dvrs(self) -> dict:
        """GET /livetv/dvrs — every configured DVR with its devices/channel maps."""
        try:
            resp = httpx.get(
                f"{self.base_url}/livetv/dvrs",
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            message = "Invalid Plex token" if status == 401 else f"HTTP {status}"
            return {"success": False, "error": message}
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}

        container = (data or {}).get("MediaContainer") or {}
        dvrs: list[PlexDvr] = []
        for dvr in _as_list(container.get("Dvr")):
            devices: list[PlexDevice] = []
            for dev in _as_list(dvr.get("Device")):
                mapping = [
                    PlexChannelMapping(
                        device_identifier=str(m.get("deviceIdentifier")),
                        enabled=str(m.get("enabled")) == "1",
                        lineup_identifier=m.get("lineupIdentifier"),
                        channel_key=(
                            str(m.get("channelKey")) if m.get("channelKey") is not None else None
                        ),
                    )
                    for m in _as_list(dev.get("ChannelMapping"))
                ]
                devices.append(
                    PlexDevice(
                        key=str(dev.get("key")),
                        device_id=dev.get("deviceId"),
                        uri=dev.get("uri"),
                        channel_mapping=mapping,
                    )
                )
            dvrs.append(
                PlexDvr(
                    key=str(dvr.get("key")),
                    lineup_title=dvr.get("lineupTitle"),
                    lineup=dvr.get("lineup"),
                    devices=devices,
                )
            )
        return {"success": True, "dvrs": dvrs}

    def test_connection(self) -> dict:
        """Verify the URL/token combination works."""
        result = self.list_dvrs()
        if not result["success"]:
            return result
        return {"success": True, "dvr_count": len(result["dvrs"])}

    def update_channelmap(
        self,
        device_key: str,
        enabled_channel_keys: list[str],
        channel_mapping: dict[str, str],
    ) -> dict:
        """PUT /media/grabbers/devices/<device_key>/channelmap — enable + EPG-bind.

        Full-state-replace, and NOT just on ``enabled_channel_keys``:
        ``channel_mapping`` must ALSO cover every enabled channel (see
        ``compute_channelmap_update``) — a channel present in
        ``channelsEnabled`` but missing its own mapping entry gets disabled
        anyway (confirmed on a live server, 2026-09-12). There is no safe
        delta here; every enabled channel's binding must be resubmitted
        every time, even unchanged.
        """
        params: list[tuple[str, str]] = [
            ("channelsEnabled", ",".join(enabled_channel_keys)),
        ]
        for key, value in channel_mapping.items():
            params.append((f"channelMappingByKey[{key}]", value))
            params.append((f"channelMapping[{key}]", value))

        try:
            resp = httpx.put(
                f"{self.base_url}/media/grabbers/devices/{device_key}/channelmap",
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}"}
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}
        return {"success": True, "channel_count": len(enabled_channel_keys)}
