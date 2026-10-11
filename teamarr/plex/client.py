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


_ENABLED_TRUE = {"1", "true", "yes", "on"}
_ENABLED_FALSE = {"0", "false", "no", "off", "none", ""}


def parse_enabled(raw: Any) -> bool:
    """Interpret Plex's ``enabled`` field, defaulting to True when unsure.

    Observed as the string ``"1"``, but the shape is not guaranteed — a JSON
    ``true`` read as ``str(True) == "True"`` used to fall through to False,
    which silently dropped the channel from the preserved set and so disabled
    it. Anything unrecognised now counts as enabled: the cost of wrongly
    preserving a channel is a stale guide entry, the cost of wrongly dropping
    one is disabling somebody else's channel.
    """
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in _ENABLED_FALSE:
        return False
    if text in _ENABLED_TRUE:
        return True
    return True


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
    previously_pushed: set[str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Fetch-merge-write core: compute the full PUT payload for one device.

    The result is a union — everything the device already has enabled, plus
    Teamarr's current channels — so a channel Teamarr does not manage can
    never be disabled, whatever its number. Ownership is NOT inferred from a
    channel-number range: that treated every channel above
    ``channel_range_start`` as Teamarr's and disabled other tools' channels
    (and Teamarr's own team channels) on a default install.

    ``previously_pushed`` is the set this scope pushed on its last successful
    run. Its only job is removal: a channel we pushed before and no longer
    have is dropped. Plex normally unchecks a channel itself once it leaves
    the tuner's lineup (confirmed live 2026-10-07), so this is a backstop for
    the window before Plex notices — it can only ever remove channels Teamarr
    provably added, never a foreign one.

    Everything is keyed on ``device_identifier`` (the stable Dispatcharr
    physical channel number), never ``channel_key`` (Plex's mutable,
    currently-matched EPG guide channel — see module docstring).

    Returns ``(enabled_channel_keys, channel_mapping)`` ready for
    ``PlexClient.update_channelmap``. ``channel_mapping`` MUST cover every
    enabled channel (preserved foreign ones too), not just Teamarr's own —
    live testing (2026-09-12) showed a channel present in ``channelsEnabled``
    but absent from the mapping params gets disabled anyway, so this is not
    the delta the API reference's "mapping of changes" wording suggests.
    Plex Web itself sends the complete set on every Save (HAR, 2026-10-03).
    """
    stale = (previously_pushed or set()) - teamarr_channel_keys

    keep = [
        m for m in current if m.enabled and m.device_identifier not in stale
    ]

    mapping: dict[str, str] = {
        m.device_identifier: m.lineup_identifier or m.device_identifier for m in keep
    }
    for key in teamarr_channel_keys:
        mapping[key] = key

    enabled = sorted(mapping, key=_channel_sort_key)
    return enabled, mapping


def device_read_problem(device: "PlexDevice", expect_channels: bool) -> str | None:
    """Reason the device read looks untrustworthy, or None when it is usable.

    The channelmap PUT replaces the device's whole state, so a malformed read
    must never be turned into a write. ``expect_channels`` is True when this
    scope has pushed before and therefore knows the device had channels.
    """
    mapping = device.channel_mapping
    if any(not m.device_identifier or m.device_identifier == "None" for m in mapping):
        return "device read contained a channel with no deviceIdentifier"
    if expect_channels and not mapping:
        return "device returned no ChannelMapping but was previously populated"
    return None


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
                        enabled=parse_enabled(m.get("enabled")),
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
        params: list[tuple[str, Any]] = [
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
