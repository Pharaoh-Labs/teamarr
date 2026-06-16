"""Resolve candidate streams to EPG-source program tvg_ids (epic teamarrv2-183).

A raw M3U stream's ``tvg_id`` (e.g. "FoxSports1.us") usually lives in a
different namespace from the EPG source's program ``tvg_id`` (e.g. "82547"), so
``/api/epg/programs/search/?tvg_id=<stream tvg_id>`` returns nothing. Programs
must be queried by the EPG-source channel id. This module bridges the two
namespaces WITHOUT requiring the stream to be pre-built into a Dispatcharr
channel, using a precedence cascade:

Precedence is by confidence, most authoritative first:

1. Direct  — the stream ``tvg_id`` already IS an EPGData ``tvg_id`` (the user's
   M3U is namespace-aligned with their EPG source). Same id, zero cost.
2. Channel — the stream is assigned to a Dispatcharr channel whose
   ``epg_data_id`` points at an EPGData row. This is a CURATED mapping (a user
   or Dispatcharr's auto-matcher explicitly linked the channel to its guide),
   so it outranks the name heuristic when both are available.
3. Name    — the stream NAME maps to exactly one EPGData ``name`` after strict
   normalization (drop quality suffixes / parentheticals / punctuation). A
   heuristic fallback for streams NOT on a channel. Skipped when ambiguous (a
   normalized name with >1 distinct tvg_id) so "ESPN" never silently resolves
   to "ESPN2".

The result maps stream ``tvg_id`` -> EPG-source ``tvg_id`` so the index can be
fetched by the resolved key yet keyed by the stream tvg_id the matcher carries.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Quality / format tokens that decorate a channel name but not its identity.
# Deliberately NOT including country words (us/usa) or feed words (backup/alt),
# which CAN change identity ("USA Network" must keep "usa").
_QUALITY_TOKENS = re.compile(
    r"\b(fhd|uhd|hd|sd|4k|hevc|h265|h264|hq|lq)\b",
    re.IGNORECASE,
)

# Country / region grouping prefixes (bead yke). Many providers prefix every
# stream with a country label and a delimiter — "US: ESPN FHD", "UK | Sky
# Sports". Without stripping it, "US: ESPN" normalizes to "us espn" and never
# matches the EPGData catalog's "espn", so name-cascade resolution collapses to
# zero for such providers. We strip ONE leading <code> + (':' or '|') prefix.
#
# The delimiter is the safety anchor: "USA Network" (no delimiter) is left
# intact so its identity "usa" survives, while "US: USA Network" -> "USA
# Network". The allowlist keeps a stray "ESPN: …"-style title from being
# mistaken for a region prefix.
_REGION_PREFIX = re.compile(
    r"^\s*(?:us|usa|uk|ca|au|nz|ie|ire|fr|de|es|it|nl|pt|be|ch|no|se|dk|fi|"
    r"br|mx|ar|in|gr|al|tr|bg|cz|pl|ro|hu|hr|rs|eu|intl|latam|ex-?yu)\s*[:|]\s*",
    re.IGNORECASE,
)


def normalize_channel_name(name: str) -> str:
    """Normalize a channel/EPG name for strict equality matching.

    Lower-cases, strips a leading country/region grouping prefix ("US: ", "UK |"),
    drops parentheticals (e.g. "(US)"), strips quality tokens (HD/FHD/UHD/4K/…),
    reduces punctuation to spaces, and collapses whitespace. "Fox Sports 1 FHD"
    and "FS1 HD" intentionally do NOT collapse to the same string — strict mode
    only unifies trivially-decorated variants.
    """
    n = (name or "").lower()
    n = _REGION_PREFIX.sub("", n, count=1)  # drop leading "us: " / "uk | " grouping label
    n = re.sub(r"\(.*?\)", " ", n)  # drop "(US)", "(1080p)", etc.
    n = re.sub(r"[^a-z0-9]+", " ", n)  # punctuation -> space
    n = _QUALITY_TOKENS.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def resolve_program_tvg_ids(
    streams: list[dict],
    epg_data_list: list[dict],
    stream_channel_map: dict[int, dict],
    active_source_ids: set[int] | None = None,
) -> tuple[dict[str, str], dict[str, int]]:
    """Map each candidate stream's ``tvg_id`` -> an EPG-source ``tvg_id``.

    Precedence (most-trusted first), matching the intended resolution policy:

    1. **channel** — the stream is assigned to a Dispatcharr channel with an
       ``epg_data_id``. This is an explicit user/auto curation ("this stream IS
       this guide channel"), so it is trusted unconditionally — even if the
       linked EPG source is inactive (it simply yields no programs then).
    2. **direct** — the stream ``tvg_id`` already equals an imported-EPG
       ``tvg_id`` (namespace-aligned M3U + EPG). Exact id match.
    3. **name** — the stream NAME maps to exactly one imported-EPG ``tvg_id``
       after strict normalization. Ambiguous names (>1 tvg_id) are skipped so
       "ESPN" never silently becomes "ESPN2".

    Direct + name only consider the ACTIVE imported EPG (``active_source_ids``;
    the caller passes the set of enabled EPG-source ids, excluding our own
    ``_Teamarr``). When ``active_source_ids`` is None, the full catalog is used
    (back-compat / unit tests). Streams left unresolved here are candidates for
    the provider-EPG (Xtream) fallback, which the caller applies afterward.

    Args:
        streams: Candidate stream dicts (need ``id``, ``name``, ``tvg_id``).
        epg_data_list: Dispatcharr EPGData rows (``id``, ``tvg_id``, ``name``,
            ``epg_source``).
        stream_channel_map: ``stream id -> channel dict`` (``epg_data_id``).
        active_source_ids: Enabled EPG-source ids for direct/name matching; None
            uses every row.

    Returns:
        (resolution, stats) where ``resolution`` is ``{stream_tvg_id:
        program_tvg_id}`` and ``stats`` counts hits per strategy plus
        ``unresolved`` and ``ambiguous_name`` for logging/observability.
    """
    # Channel curation is trusted against the FULL catalog (the user linked it).
    epgdata_by_id = {e["id"]: e for e in epg_data_list if e.get("id") is not None}

    # Direct + name match only the ACTIVE imported EPG (honor enabled sources).
    if active_source_ids is not None:
        imported = [e for e in epg_data_list if e.get("epg_source") in active_source_ids]
    else:
        imported = epg_data_list
    epgdata_tvgids = {e["tvg_id"] for e in imported if e.get("tvg_id")}

    # Normalized name -> set of distinct tvg_ids; >1 means ambiguous (skip).
    name_to_tvgids: dict[str, set[str]] = {}
    for e in imported:
        norm = normalize_channel_name(e.get("name") or "")
        tvg = e.get("tvg_id")
        if norm and tvg:
            name_to_tvgids.setdefault(norm, set()).add(tvg)

    resolution: dict[str, str] = {}
    stats = {"channel": 0, "direct": 0, "name": 0, "unresolved": 0, "ambiguous_name": 0}

    for s in streams:
        s_tvg = s.get("tvg_id")
        if not s_tvg or s_tvg in resolution:
            continue

        # 1. Channel (curated mapping — most trusted).
        ch = stream_channel_map.get(s.get("id"))
        if ch:
            eid = ch.get("effective_epg_data_id") or ch.get("epg_data_id")
            ed = epgdata_by_id.get(eid)
            if ed and ed.get("tvg_id"):
                resolution[s_tvg] = ed["tvg_id"]
                stats["channel"] += 1
                continue

        # 2. Direct: the stream tvg_id is itself an active imported-EPG tvg_id.
        if s_tvg in epgdata_tvgids:
            resolution[s_tvg] = s_tvg
            stats["direct"] += 1
            continue

        # 3. Name: strict, unambiguous normalized-name match.
        norm = normalize_channel_name(s.get("name") or "")
        candidates = name_to_tvgids.get(norm)
        if candidates:
            if len(candidates) == 1:
                resolution[s_tvg] = next(iter(candidates))
                stats["name"] += 1
                continue
            stats["ambiguous_name"] += 1

        stats["unresolved"] += 1

    logger.info(
        "[EPG-RESOLVE] resolved %d stream tvg_ids (channel=%d direct=%d name=%d "
        "ambiguous_name=%d unresolved=%d)",
        len(resolution), stats["channel"], stats["direct"], stats["name"],
        stats["ambiguous_name"], stats["unresolved"],
    )
    return resolution, stats
