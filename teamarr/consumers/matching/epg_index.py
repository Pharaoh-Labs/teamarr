"""Per-run EPG program index for stream-to-event matching (epic teamarrv2-183).

Builds an in-memory index of Dispatcharr EPG programs keyed by ``tvg_id`` so
the matcher can ask "what was airing on this stream's guide channel during this
event's window?" without per-stream API calls.

Scope discipline (hard requirement): the index is built ONLY from the distinct
``tvg_id`` values carried by candidate streams in imported event groups — never
the whole Dispatcharr instance. The program-search endpoint accepts a single
``tvg_id`` per call, so the fetch loops over that small distinct set (one call
per linear channel, not per stream).

This module is a pure data layer: it fetches, indexes, and answers time-window
overlap queries. It contains NO matching logic — interpreting program titles
and categories is the matcher's job (teamarrv2-183.4).
"""

import logging
from datetime import UTC, datetime

from teamarr.dispatcharr.managers.epg import EPGManager
from teamarr.dispatcharr.types import DispatcharrProgram

logger = logging.getLogger(__name__)


def _iso_z(dt: datetime) -> str:
    """Format a datetime as the UTC ISO8601-Z string the endpoint expects."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class EPGProgramIndex:
    """In-memory ``tvg_id -> [programs]`` index scoped to candidate streams.

    Construct via :meth:`build` once per generation run, then call
    :meth:`lookup` to get the programs overlapping a given event window.

    Programs from Teamarr's own generated EPG source ("_Teamarr") are excluded
    by default so we never match streams against our own output. Programs
    without parseable start/end times are kept in the index but never returned
    by :meth:`lookup` (they cannot be windowed).
    """

    def __init__(self, programs_by_tvg: dict[str, list[DispatcharrProgram]]):
        # Each tvg_id's list is pre-sorted by start time for cheap scans.
        self._by_tvg = programs_by_tvg

    # ------------------------------------------------------------------ build
    @classmethod
    def build(
        cls,
        epg_manager: EPGManager,
        tvg_id_resolution: "dict[str, str]",
        window_start: datetime,
        window_end: datetime,
        exclude_teamarr: bool = True,
        page_size: int = 500,
    ) -> "EPGProgramIndex":
        """Fetch and index programs per candidate stream over a time window.

        A raw M3U stream's ``tvg_id`` (e.g. "FoxSports1.us") usually lives in a
        different namespace from EPG program ``tvg_id`` values (the EPG source's
        channel id, e.g. "82547"), so ``search_programs(tvg_id=<stream tvg>)``
        returns nothing. The caller resolves each stream tvg_id to the EPG-source
        tvg_id (see :mod:`epg_resolver`); we fetch by that resolved id but key
        the index by the STREAM tvg_id so the matcher can look programs up by the
        value carried on each stream dict.

        Args:
            epg_manager: Connected EPGManager (feature-detection handled inside).
            tvg_id_resolution: Map of stream ``tvg_id`` -> EPG-source ``tvg_id``.
            window_start: Start of the window to index (inclusive-ish).
            window_end: End of the window to index.
            exclude_teamarr: Drop programs from our own "_Teamarr" EPG source.
            page_size: Page size passed to the search endpoint.

        Returns:
            An EPGProgramIndex. Empty if the endpoint is unsupported, no
            resolved tvg_ids were given, or nothing matched.
        """
        if not tvg_id_resolution:
            logger.debug("[EPG-INDEX] No resolved tvg_ids; index empty")
            return cls({})

        if not epg_manager.supports_program_search():
            logger.info(
                "[EPG-INDEX] Program search unsupported on this Dispatcharr build; "
                "EPG matching unavailable"
            )
            return cls({})

        start_iso = _iso_z(window_start)
        end_iso = _iso_z(window_end)

        by_tvg: dict[str, list[DispatcharrProgram]] = {}
        total = 0
        for stream_tvg, program_tvg in tvg_id_resolution.items():
            if not stream_tvg or not program_tvg:
                continue
            # One call per resolved EPG-source tvg_id (the endpoint does not
            # support multi-value tvg_id). Key the result by the stream tvg_id.
            programs = epg_manager.search_programs(
                tvg_id=program_tvg,
                start_before=end_iso,
                end_after=start_iso,
                page_size=page_size,
            )
            if exclude_teamarr:
                programs = [p for p in programs if not p.is_teamarr]
            if not programs:
                continue
            programs.sort(key=lambda p: p.start_time or "")
            by_tvg[stream_tvg] = programs
            total += len(programs)

        logger.info(
            "[EPG-INDEX] Indexed %d programs across %d/%d tvg_ids (window %s..%s)",
            total,
            len(by_tvg),
            len(tvg_id_resolution),
            start_iso,
            end_iso,
        )
        return cls(by_tvg)

    # ----------------------------------------------------------------- lookup
    def lookup(
        self,
        tvg_id: str,
        event_start: datetime,
        event_end: datetime,
    ) -> list[DispatcharrProgram]:
        """Return programs on ``tvg_id`` overlapping [event_start, event_end].

        Overlap uses the half-open convention: a program overlaps when it
        starts before the event ends AND ends after the event starts. Programs
        with unparseable times are skipped. Results keep index (start-time) order.
        """
        programs = self._by_tvg.get(tvg_id)
        if not programs:
            return []

        hits: list[DispatcharrProgram] = []
        for p in programs:
            p_start, p_end = p.start_dt, p.end_dt
            if p_start is None or p_end is None:
                continue
            if p_start < event_end and p_end > event_start:
                hits.append(p)
        return hits

    # -------------------------------------------------------------- merge
    def merge(self, programs_by_tvg: dict[str, list[DispatcharrProgram]]) -> int:
        """Add programs for tvg_ids not already present, returning count added.

        Folds in a secondary program source (an Xtream provider's own xmltv,
        epic crs) AFTER the primary Dispatcharr-guide index is built. tvg_ids
        already in the index are left untouched — the curated guide wins — so
        this only fills gaps (streams DP produced no programs for, whether
        unresolved or resolved to an empty mirror channel). Each added list is
        sorted by start time to preserve build()'s invariant.
        """
        added = 0
        for tvg, programs in programs_by_tvg.items():
            if not tvg or not programs or tvg in self._by_tvg:
                continue
            self._by_tvg[tvg] = sorted(programs, key=lambda p: p.start_time or "")
            added += len(self._by_tvg[tvg])
        return added

    # ------------------------------------------------------------- accessors
    def programs_for(self, tvg_id: str) -> list[DispatcharrProgram]:
        """All indexed programs on a tvg_id (start-time order). Empty if none.

        Used by the matcher to walk every program on a stream's guide channel
        and match each to an event (stream → programs → events). Distinct from
        :meth:`lookup`, which is the reverse (event window → programs) for the
        lifecycle layer.
        """
        return self._by_tvg.get(tvg_id, [])

    def is_linear(self, tvg_id: str) -> bool:
        """True if the tvg_id carries more than one program in the window.

        Program multiplicity is our LINEAR-vs-DEDICATED signal: a linear channel
        (ESPN, NBA1) airs many programs/day; a dedicated single-event stream has
        one. Drives reconciliation — linear streams get EPG time-windowing,
        dedicated streams keep full-life name-match semantics.
        """
        return len(self._by_tvg.get(tvg_id, [])) > 1

    def tvg_ids(self) -> list[str]:
        """tvg_ids that have at least one indexed program."""
        return list(self._by_tvg.keys())

    def program_count(self) -> int:
        """Total programs held in the index."""
        return sum(len(v) for v in self._by_tvg.values())

    def __bool__(self) -> bool:
        return bool(self._by_tvg)
