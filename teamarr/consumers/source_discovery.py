"""Source discovery — find M3U groups that carry subscribed games (#997).

Sources are added by hand, and providers add, rename and drop groups all year,
so a hand-kept list drifts. A scan reads every M3U group that is not already a
source, puts a sample of its streams through the same filter and matcher a
generation run uses, and records what matched. Nothing else is written: no
match cache, no failed-match rows, no channels.

Three things were measured on a real install (786 groups with streams) and
shape this module:

* **Every group is scanned; the name is never a gate.** League words in the
  group name found 63 of 99 hand-made sources. The misses were network and
  multi-league groups, and so were the best new finds.
* **Only a two-sided game match is evidence.** Streams matched on one team
  name alone were, in a 60-group control, all noise — news and regional
  channels matching a national team on a country word.
* **One scan proves little.** On a Monday 61 of 93 real sources matched
  nothing. Evidence is kept per scan and judged over a window.

The group name is a second, weaker layer: it lowers the bar for content, and a
name hit with no games yet is still worth showing — never worth importing.
"""

import logging
import re
import threading
import time
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from sqlite3 import Connection
from typing import Any

from teamarr.consumers.matching import StreamCategory
from teamarr.consumers.stream_match_cache import NullStreamMatchCache
from teamarr.database.groups import (
    EventEPGGroup,
    create_group,
    delete_group,
    get_all_groups,
    get_group_by_name,
    set_group_managed,
    set_managed_source_enabled,
)
from teamarr.database.source_candidates import (
    CandidateEvidence,
    ScanEvidence,
    dismissed_group_ids,
    get_candidates,
    record_scan,
    set_candidate_status,
)
from teamarr.services.group_pattern import resolve_group_name_pattern
from teamarr.utilities.tz import now_utc, parse_db_timestamp, to_db_utc

logger = logging.getLogger(__name__)

# Streams put to the matcher per group. A group either carries games or it
# does not; a spread of this many tells which without matching all of it.
STREAM_SAMPLE_SIZE = 50
# Streams read per group before stale ones are dropped and the sample is taken.
STREAM_READ_LIMIT = 300

# Evidence is judged over this many days of scans.
EVIDENCE_WINDOW_DAYS = 7
# Game matches one scan must have seen for content alone to qualify a group.
GAME_MATCHES_REQUIRED = 3
# ... and when the group's name also names a subscribed league.
GAME_MATCHES_REQUIRED_WITH_NAME = 1

# A managed source that has matched nothing for this long is disabled ...
MANAGED_IDLE_DAYS = 14
# ... or this long when its group's name still names a subscribed league.
MANAGED_IDLE_DAYS_WITH_NAME = 21
# A disabled managed source whose group has been gone this long is removed.
MANAGED_GONE_DAYS = 14

# Why a candidate is suggested, strongest first.
TIER_GAMES = "games"
TIER_NAME_ONLY = "name_only"


def _name_key(text: str) -> str:
    """Lower-case ASCII words, for whole-word comparison of names."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9+]+", " ", folded).strip()


def league_name_surfaces(conn: Connection, leagues: list[str]) -> dict[str, set[str]]:
    """The names a group could call each league by, as ``{name: {league codes}}``.

    Display name and alias from the leagues table, or the provider's name for
    a league that is only discovered — data that already exists, never a list
    kept here.
    """
    surfaces: dict[str, set[str]] = {}
    wanted = {code.lower() for code in leagues}
    rows = conn.execute("SELECT league_code, display_name, league_alias FROM leagues").fetchall()
    seen: set[str] = set()
    for row in rows:
        code = (row["league_code"] or "").lower()
        if code not in wanted:
            continue
        seen.add(code)
        for name in (row["display_name"], row["league_alias"]):
            key = _name_key(name or "")
            if len(key) >= 2:
                surfaces.setdefault(key, set()).add(code)
    for row in conn.execute("SELECT league_slug, league_name FROM league_cache").fetchall():
        code = (row["league_slug"] or "").lower()
        if code in wanted and code not in seen:
            key = _name_key(row["league_name"] or "")
            if len(key) >= 2:
                surfaces.setdefault(key, set()).add(code)
    return surfaces


def leagues_named_by(group_name: str, surfaces: dict[str, set[str]]) -> list[str]:
    """Subscribed leagues a group name mentions, as whole words."""
    padded = f" {_name_key(group_name)} "
    found: set[str] = set()
    for surface, codes in surfaces.items():
        if f" {surface} " in padded:
            found |= codes
    return sorted(found)


def sample_streams(streams: list[dict], size: int = STREAM_SAMPLE_SIZE) -> list[dict]:
    """An even spread of ``size`` streams, in id order.

    Providers list a group in blocks (one network's feeds, then the next), so
    the first N would sample one block.
    """
    ordered = sorted(streams, key=lambda s: s["id"])
    if len(ordered) <= size:
        return ordered
    step = len(ordered) / size
    return [ordered[int(i * step)] for i in range(size)]


def suggestion_tier(candidate: CandidateEvidence) -> str | None:
    """Why this candidate is worth suggesting, or None when it is not.

    Team-only matches never count: they do not appear here at all.
    """
    required = (
        GAME_MATCHES_REQUIRED_WITH_NAME if candidate.name_leagues else GAME_MATCHES_REQUIRED
    )
    if candidate.best_game_matches >= required:
        return TIER_GAMES
    if candidate.name_leagues:
        return TIER_NAME_ONLY
    return None


@dataclass
class ScanSummary:
    """What one scan did."""

    groups_total: int = 0
    groups_scanned: int = 0
    skipped_sources: int = 0
    skipped_empty: int = 0
    skipped_dismissed: int = 0
    groups_with_games: int = 0
    sources_disabled: int = 0
    sources_reenabled: int = 0
    sources_removed: int = 0
    streams_matched_against: int = 0
    errors: int = 0
    duration_seconds: float = 0.0


class SourceDiscovery:
    """Runs a discovery scan and stores its evidence."""

    def __init__(self, db_factory: Any, dispatcharr: Any, processor: Any):
        """
        Args:
            db_factory: Database connection factory
            dispatcharr: Dispatcharr connection (its ``m3u`` manager is used)
            processor: An EventGroupProcessor — the scan borrows its stream
                filter and its matcher wiring so it can never drift from what
                a generation run would do with the same streams
        """
        self._db_factory = db_factory
        self._m3u = dispatcharr.m3u
        self._processor = processor

    def _source_group_ids(self, conn: Connection, live_groups: list) -> set[int]:
        """M3U group ids some source already reads, by id or by name pattern."""
        taken: set[int] = set()
        for source in get_all_groups(conn, include_disabled=True):
            # A managed source that was retired is scanned again: games in its
            # group are what bring it back.
            if source.managed and not source.enabled:
                continue
            if source.m3u_group_id:
                taken.add(source.m3u_group_id)
            if source.m3u_group_name_pattern_enabled and source.m3u_group_name_pattern:
                matched = resolve_group_name_pattern(live_groups, source.m3u_group_name_pattern)
                taken |= {g.id for g in matched}
        return taken

    def _scan_group(self, group: Any, leagues: list[str], today: date) -> ScanEvidence:
        raw = self._m3u.list_streams(group_id=group.id, limit=STREAM_READ_LIMIT)
        evidence = ScanEvidence(
            m3u_group_id=group.id,
            m3u_group_name=group.name,
            # The group listing does not say which accounts carry it; its streams do.
            m3u_account_ids=sorted({s.m3u_account_id for s in raw if s.m3u_account_id}),
            stream_count=_stream_count(group) or len(raw),
        )
        streams = [
            {"id": s.id, "name": s.name, "tvg_id": s.tvg_id, "is_stale": s.is_stale}
            for s in raw
            if not s.is_stale
        ]
        # A throwaway, unsaved source: every matching type the name path has,
        # no EPG (that needs a guide lookup per stream, and a group that only
        # matches through its guide is found by the channel-source path).
        probe = EventEPGGroup(
            id=0,
            name=group.name,
            name_match_enabled=True,
            team_streams_enabled=True,
            epg_match_enabled=False,
        )
        kept, _ = self._processor._filter_streams(sample_streams(streams), probe)
        evidence.streams_read = len(kept)
        if not kept:
            return evidence
        result = self._processor._match_streams(
            kept,
            probe,
            today,
            resolved_leagues=leagues,
            cache=NullStreamMatchCache(self._db_factory),
        )
        games: dict[int, str] = {}
        team_only: set[int] = set()
        for r in result.results:
            if not r.matched:
                continue
            if r.category == StreamCategory.TEAM_ONLY:
                team_only.add(r.stream_id)
            else:
                games.setdefault(r.stream_id, r.league or "")
        evidence.game_matches = len(games)
        evidence.team_only_matches = len(team_only - set(games))
        evidence.leagues = dict(Counter(lg for lg in games.values() if lg))
        return evidence

    def scan(
        self,
        now: datetime | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> ScanSummary:
        """Scan every M3U group that is not a source and store the evidence."""
        now = now or now_utc()
        started = now_utc()
        summary = ScanSummary()
        live_groups = self._m3u.list_groups()
        summary.groups_total = len(live_groups)

        with self._db_factory() as conn:
            taken = self._source_group_ids(conn, live_groups)
            dismissed = dismissed_group_ids(conn)
            leagues = self._processor._get_subscription_leagues(conn, None)
            surfaces = league_name_surfaces(conn, leagues)

        todo = []
        for group in live_groups:
            if group.id in taken:
                summary.skipped_sources += 1
            elif group.id in dismissed:
                summary.skipped_dismissed += 1
            elif _stream_count(group) == 0:
                summary.skipped_empty += 1
            else:
                todo.append(group)

        found: list[ScanEvidence] = []
        if leagues:
            for index, group in enumerate(todo):
                if progress:
                    progress(index, len(todo), group.name)
                try:
                    evidence = self._scan_group(group, leagues, now.date())
                except Exception:
                    # One unreadable group must not cost the rest of the scan.
                    logger.exception("[DISCOVERY] Failed to scan group %r", group.name)
                    summary.errors += 1
                    continue
                evidence.name_leagues = leagues_named_by(group.name, surfaces)
                summary.groups_scanned += 1
                summary.streams_matched_against += evidence.streams_read
                if evidence.game_matches:
                    summary.groups_with_games += 1
                found.append(evidence)

        with self._db_factory() as conn:
            record_scan(conn, found, now)
            maintain_managed_sources(
                conn, now, {g.id for g in live_groups}, {e.m3u_group_id: e for e in found}, summary
            )

        summary.duration_seconds = round((now_utc() - started).total_seconds(), 1)
        logger.info(
            "[DISCOVERY] Scanned %d of %d M3U groups in %.1fs (%d already sources, %d empty, "
            "%d dismissed, %d errors): %d carry subscribed games",
            summary.groups_scanned,
            summary.groups_total,
            summary.duration_seconds,
            summary.skipped_sources,
            summary.skipped_empty,
            summary.skipped_dismissed,
            summary.errors,
            summary.groups_with_games,
        )
        return summary


def accept_candidate(conn: Connection, candidate: CandidateEvidence) -> int:
    """Turn a candidate into a managed source and return the new source's id.

    The source follows the global subscription and matches by stream name —
    the kind of evidence that qualified it.
    """
    name = candidate.m3u_group_name
    suffix = 2
    while get_group_by_name(conn, name) is not None:
        name = f"{candidate.m3u_group_name} ({suffix})"
        suffix += 1
    source_id = create_group(
        conn,
        name=name,
        leagues=[],
        m3u_group_id=candidate.m3u_group_id,
        m3u_group_name=candidate.m3u_group_name,
        m3u_account_id=candidate.m3u_account_ids[0] if candidate.m3u_account_ids else None,
        name_match_enabled=True,
    )
    set_group_managed(conn, source_id, True)
    set_candidate_status(conn, candidate.id, "accepted", source_group_id=source_id)
    logger.info("[DISCOVERY] Accepted %r as managed source id=%d", name, source_id)
    return source_id


def _age_days(stamp: str | None, now: datetime) -> float | None:
    parsed = parse_db_timestamp(stamp) if stamp else None
    return (now - parsed).total_seconds() / 86400 if parsed else None


def maintain_managed_sources(
    conn: Connection,
    now: datetime,
    live_group_ids: set[int],
    evidence: dict[int, ScanEvidence],
    summary: ScanSummary,
) -> None:
    """Retire managed sources that went quiet and bring back ones with games again.

    Only sources discovery created are touched, and only while still marked
    managed: a hand edit clears the mark, and a hand-made source never has it.

    * enabled, matched nothing for the idle window -> disabled (settings kept)
    * disabled, its group shows games in this scan -> enabled again
    * disabled, its group gone for the gone window -> removed
    """
    named = {
        c.m3u_group_id: bool(c.name_leagues)
        for c in get_candidates(conn, now, EVIDENCE_WINDOW_DAYS, status="accepted")
    }
    created = {
        row["id"]: row["created_at"]
        for row in conn.execute("SELECT id, created_at FROM event_epg_groups WHERE managed = 1")
    }
    seen = {
        row["id"]: row["source_last_seen"]
        for row in conn.execute(
            "SELECT id, source_last_seen FROM event_epg_groups WHERE managed = 1"
        )
    }
    for source in get_all_groups(conn, include_disabled=True):
        # A managed source always has the group it was accepted from.
        if not source.managed or source.m3u_group_id is None:
            continue
        group_live = source.m3u_group_id in live_group_ids
        if source.enabled:
            idle = _age_days(source.last_matched_at or created.get(source.id), now)
            limit = (
                MANAGED_IDLE_DAYS_WITH_NAME
                if named.get(source.m3u_group_id)
                else MANAGED_IDLE_DAYS
            )
            if idle is not None and idle >= limit:
                set_managed_source_enabled(conn, source.id, False)
                summary.sources_disabled += 1
                logger.info(
                    "[DISCOVERY] Disabled managed source %r: no match in %d days",
                    source.name, int(idle),
                )
            continue
        found = evidence.get(source.m3u_group_id)
        if group_live:
            # Generation runs stop looking at a disabled source, so the scan
            # keeps its "last seen" current; "gone" is counted from here.
            conn.execute(
                "UPDATE event_epg_groups SET source_last_seen = ? WHERE id = ?",
                (to_db_utc(now), source.id),
            )
        if group_live and found and found.game_matches:
            set_managed_source_enabled(conn, source.id, True)
            summary.sources_reenabled += 1
            logger.info("[DISCOVERY] Re-enabled managed source %r: games again", source.name)
        elif not group_live:
            gone = _age_days(seen.get(source.id) or created.get(source.id), now)
            if gone is not None and gone >= MANAGED_GONE_DAYS:
                delete_group(conn, source.id)
                summary.sources_removed += 1
                logger.info(
                    "[DISCOVERY] Removed managed source %r: group gone %d days",
                    source.name, int(gone),
                )
    conn.commit()


def _stream_count(group: Any) -> int | None:
    """Streams a group holds across the accounts that carry it.

    None when the listing does not say — an older Dispatcharr lists bare
    account ids — so the caller reads the group rather than assume it is empty.
    """
    accounts = getattr(group, "m3u_accounts", None) or []
    if any(not isinstance(a, dict) for a in accounts):
        return None
    return sum((a.get("stream_count") or 0) for a in accounts)


# --- running a scan -----------------------------------------------------------

# How long a scan waits for a generation run to finish before giving up. Both
# are CPU-bound matching; side by side each slows the other.
GENERATION_WAIT_SECONDS = 20 * 60

_scan_lock = threading.Lock()
_state: dict[str, Any] = {"running": False, "progress": None, "last": None}


def discovery_status() -> dict[str, Any]:
    """Whether a scan is running, how far it is, and what the last one did."""
    return dict(_state)


def run_discovery_scan(db_factory: Any) -> dict[str, Any]:
    """Run one scan now. One at a time; never alongside a generation run.

    Returns the scan summary, or ``{"skipped": True, "reason": ...}``.
    """
    from teamarr.consumers import generation_status
    from teamarr.consumers.event_group_processor import EventGroupProcessor
    from teamarr.dispatcharr.factory import get_dispatcharr_connection

    if not _scan_lock.acquire(blocking=False):
        return {"skipped": True, "reason": "A discovery scan is already running"}
    try:
        _state.update(running=True, progress=None)
        dispatcharr = get_dispatcharr_connection(db_factory)
        if not dispatcharr:
            return {"skipped": True, "reason": "Dispatcharr not configured or unavailable"}

        deadline = time.monotonic() + GENERATION_WAIT_SECONDS
        while generation_status.is_in_progress():
            if time.monotonic() > deadline:
                return {"skipped": True, "reason": "A generation run was still in progress"}
            time.sleep(5)

        def progress(done: int, total: int, name: str) -> None:
            _state["progress"] = {"done": done, "total": total, "group": name}

        processor = EventGroupProcessor(db_factory=db_factory, dispatcharr_client=None)
        summary = SourceDiscovery(db_factory, dispatcharr, processor).scan(progress=progress)
        result = asdict(summary)
        _state["last"] = {"finished_at": now_utc().isoformat(), **result}
        return result
    except Exception as e:
        logger.exception("[DISCOVERY] Scan failed")
        _state["last"] = {"finished_at": now_utc().isoformat(), "error": str(e)}
        return {"error": str(e)}
    finally:
        _state.update(running=False, progress=None)
        _scan_lock.release()
