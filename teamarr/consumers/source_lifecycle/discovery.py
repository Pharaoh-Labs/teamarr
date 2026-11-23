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

The group name is a second, weaker layer: it lowers the bar for content, lets
one-team matches count when they are in the league the name names, and a name
hit with nothing matched yet is still worth showing — never worth importing.

Every stream of a group is read and matched. A first version sampled 50 per
group and under-counted the large ones badly (7 matches where a full read
found 98); a full pass over 119,000 streams is a few minutes once a day.
"""

import logging
import re
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from sqlite3 import Connection
from typing import Any

from teamarr.consumers.matching import StreamCategory
from teamarr.consumers.stream_match_cache import NullStreamMatchCache, get_generation_counter
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
    account_key,
    binding_conflicts,
    dismiss_group,
    dismissed_groups,
    dismissed_rotation_keys,
    forget_removed_source,
    get_candidates,
    is_dismissed_day,
    move_accepted_candidate,
    record_scan,
    rotating_family_sizes,
    rotation_rank,
    set_candidate_status,
    upsert_accepted_candidate,
)
from teamarr.utilities.logging import quiet_debug
from teamarr.utilities.m3u_group_identity import name_key, rotating_group_key
from teamarr.utilities.tz import now_utc, parse_db_timestamp, to_db_utc

from .policy import SourceLifecyclePolicy, load_policy

logger = logging.getLogger(__name__)

# Evidence is judged over this many days of scans.
EVIDENCE_WINDOW_DAYS = 7
# Game matches one scan must have seen for content alone to qualify a group.
GAME_MATCHES_REQUIRED = 3
# ... and when the group's name also names a subscribed league.
GAME_MATCHES_REQUIRED_WITH_NAME = 1
# Streams matched on one team name, in a league the group's name names, for a
# team-stream group to qualify. Without the name they are never evidence.
TEAM_MATCHES_REQUIRED = 3
# A group is a replay group when at least this share of its streams say so.
REPLAY_STREAM_SHARE = 0.5
# Two groups are the same content when their matched events overlap this much.
SAME_CONTENT_OVERLAP = 0.8
# ... and only when both matched at least this many. One shared event says
# little: every F1 group in a race week matches the same single Grand Prix.
SAME_CONTENT_MIN_EVENTS = 3

# A managed source that has matched nothing for this long is disabled ...
MANAGED_IDLE_DAYS = 14  # defaults; the live values are the SourceLifecyclePolicy fields
# ... or this long when its group's name still names a subscribed league.
MANAGED_IDLE_DAYS_WITH_NAME = 21
# A disabled managed source whose group has been gone this long is removed.
MANAGED_GONE_DAYS = 14

# Automatic mode (#997): a group is added on its own only with evidence on this
# many different scan days (a one-off listing never imports) ...
AUTO_EVIDENCE_DAYS = 2
# ... and when at least this share of its matched streams are in leagues the
# user turned automatic mode on for.
AUTO_LEAGUE_SHARE = 0.5

# Why a candidate is suggested, strongest first.
TIER_GAMES = "games"
TIER_TEAMS = "teams"
TIER_NAME_ONLY = "name_only"

_REPLAY_WORD = re.compile(r"\breplays?\b", re.IGNORECASE)


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
            key = name_key(name or "")
            if len(key) >= 2:
                surfaces.setdefault(key, set()).add(code)
    for row in conn.execute("SELECT league_slug, league_name FROM league_cache").fetchall():
        code = (row["league_slug"] or "").lower()
        if code in wanted and code not in seen:
            key = name_key(row["league_name"] or "")
            if len(key) >= 2:
                surfaces.setdefault(key, set()).add(code)
    return surfaces


def leagues_named_by(group_name: str, surfaces: dict[str, set[str]]) -> list[str]:
    """Subscribed leagues a group name mentions, as whole words."""
    padded = f" {rotating_group_key(group_name) or name_key(group_name)} "
    found: set[str] = set()
    for surface, codes in surfaces.items():
        if f" {surface} " in padded:
            found |= codes
    return sorted(found)


def is_replay_group(group_name: str, stream_names: list[str]) -> bool:
    """Whether a group holds replays rather than live events.

    Providers label these themselves: the group is called "Replay | NBA", or
    its streams are "NBA Replay 9", "SPFL Replay Highlights" — a word in the
    name and no fixture. Such a group names a league and never matches an
    event, so the name layer alone would suggest it for ever.
    """
    if _REPLAY_WORD.search(group_name):
        return True
    if not stream_names:
        return False
    saying_so = sum(1 for name in stream_names if _REPLAY_WORD.search(name))
    return saying_so / len(stream_names) >= REPLAY_STREAM_SHARE


def team_stream_leagues(candidate: CandidateEvidence | ScanEvidence) -> dict[str, int]:
    """One-team matches that count: those in a league the group's name names.

    Reads a window's evidence or one scan's: the revive rule (#1079) asks
    the same question of the scan that just ran.
    """
    named = set(candidate.name_leagues)
    return {lg: n for lg, n in candidate.team_leagues.items() if lg in named}


def suggestion_tier(candidate: CandidateEvidence) -> str | None:
    """Why this candidate is worth suggesting, or None when it is not."""
    if candidate.replay:
        return None
    required = GAME_MATCHES_REQUIRED_WITH_NAME if candidate.name_leagues else GAME_MATCHES_REQUIRED
    if candidate.best_game_matches >= required:
        return TIER_GAMES
    if max(team_stream_leagues(candidate).values(), default=0) >= TEAM_MATCHES_REQUIRED:
        return TIER_TEAMS
    if candidate.name_leagues and not _name_only_went_stale(candidate):
        return TIER_NAME_ONLY
    return None


def _name_only_went_stale(candidate: CandidateEvidence) -> bool:
    """A name-only group that had streams on every scan for a full window and
    never matched anything is not waiting for match day — it is dead weight.
    It is suggested again the moment a scan matches something in it."""
    return (
        candidate.scan_days >= EVIDENCE_WINDOW_DAYS
        and candidate.scan_days_with_streams == candidate.scan_days
    )


def fold_same_content(candidates: list[CandidateEvidence]) -> list[list[CandidateEvidence]]:
    """Group candidates that carry the same events: ``[[primary, *alternates], ...]``.

    Providers and resellers list the same feeds under several groups. Each
    stays its own candidate — any of them can be added — but they are shown as
    one suggestion. The primary is the one with the most matched events.
    Candidates with fewer than a handful of matched events are never folded.
    """
    ordered = sorted(candidates, key=lambda c: (-len(c.event_ids), c.m3u_group_name.lower()))
    folded: list[list[CandidateEvidence]] = []
    for cand in ordered:
        home = None
        if len(cand.event_ids) >= SAME_CONTENT_MIN_EVENTS:
            for cluster in folded:
                primary = cluster[0].event_ids
                if len(primary) < SAME_CONTENT_MIN_EVENTS:
                    continue
                overlap = len(cand.event_ids & primary) / len(cand.event_ids | primary)
                if overlap >= SAME_CONTENT_OVERLAP:
                    home = cluster
                    break
        if home is None:
            folded.append([cand])
        else:
            home.append(cand)
    return folded


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
    sources_readded: int = 0
    sources_auto_added: int = 0
    sources_rebound: int = 0
    skipped_replay: int = 0
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

    def _taken_accounts(self, conn: Connection) -> dict[int, set[int | None]]:
        """M3U group id -> the accounts some source already reads there (#1226).

        A source reads one account's streams in its group, so a group two
        accounts carry is taken only for the accounts that have a source.
        ``None`` in the set is a source with no account binding: it reads the
        whole group, which is then taken outright.
        """
        taken: dict[int, set[int | None]] = {}
        for source in get_all_groups(conn, include_disabled=True):
            # A managed source that was retired is scanned again: games in its
            # group are what bring it back.
            if source.managed and not source.enabled:
                continue
            if source.m3u_group_id:
                taken.setdefault(source.m3u_group_id, set()).add(source.m3u_account_id)
        return taken

    @staticmethod
    def _nothing_new(group: Any, accounts: set[int]) -> bool:
        """Whether a group with decided accounts can be skipped without reading it.

        ``accounts`` are the ones a source reads or the user dismissed. The
        newer group listing gives a stream count per carrying account but not
        which account each count belongs to, so the only case decided here is
        the common one: at most one account has streams in the group, and one
        is already decided. A group more accounts carry is read, and its
        streams say whose they are.
        """
        entries = getattr(group, "m3u_accounts", None) or []
        if any(not isinstance(e, dict) for e in entries):
            # Older Dispatcharr lists bare account ids: an exact answer.
            return not ({e for e in entries if isinstance(e, int)} - accounts)
        return sum(1 for e in entries if (e.get("stream_count") or 0) > 0) <= 1

    def _scan_group(
        self,
        group: Any,
        leagues: list[str],
        today: date,
        skip: Callable[[int], bool] = lambda account: False,
    ) -> list[ScanEvidence]:
        """One evidence row per account that carries the group (#1226).

        The group is read once and its streams are split by the account they
        belong to: no extra Dispatcharr call. ``skip`` says which accounts the
        caller does not want (a source already reads them, or the user said
        no); their streams are not matched.
        """
        raw = self._m3u.list_streams(group_id=group.id)
        by_account: dict[int, list[Any]] = {}
        for stream in raw:
            by_account.setdefault(account_key(stream.m3u_account_id), []).append(stream)
        return [
            self._scan_account(group, account, streams, leagues, today)
            for account, streams in sorted(by_account.items())
            if not skip(account)
        ]

    def _scan_account(
        self, group: Any, account: int, raw: list[Any], leagues: list[str], today: date
    ) -> ScanEvidence:
        evidence = ScanEvidence(
            m3u_group_id=group.id,
            m3u_group_name=group.name,
            m3u_account_id=account or None,
            stream_count=len(raw),
        )
        streams = [
            {"id": s.id, "name": s.name, "tvg_id": s.tvg_id, "is_stale": s.is_stale}
            for s in raw
            if not s.is_stale
        ]
        if is_replay_group(group.name, [s["name"] for s in streams]):
            evidence.replay = True
            return evidence
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
        kept, _ = self._processor._filter_streams(streams, probe)
        evidence.streams_read = len(kept)
        if not kept:
            return evidence
        # A two-sided match is evidence only on a stream the created source's
        # run would keep (#1034). The probe runs with team matching on, which
        # skips the global event-pattern filter so one-team streams reach the
        # matcher — and so do streams that carry no event shape at all. A
        # source accepted on games evidence has team matching OFF, so its run
        # drops those same streams before matching: three auto-added F1
        # onboard groups (per-driver streams with no Grand Prix name) matched
        # 16 a day in the scan and nothing in any run, idled out, and were
        # rediscovered. Judge the games tier with the filter the run applies.
        run_probe = EventEPGGroup(
            id=0,
            name=group.name,
            name_match_enabled=True,
            team_streams_enabled=False,
            epg_match_enabled=False,
        )
        run_kept, _ = self._processor._filter_streams(streams, run_probe)
        run_keeps = {s["id"] for s in run_kept}
        result = self._processor._match_streams(
            kept,
            probe,
            today,
            resolved_leagues=leagues,
            cache=NullStreamMatchCache(self._db_factory),
        )
        games: dict[int, str] = {}
        team_only: dict[int, str] = {}
        for r in result.results:
            # The matcher searches every league it knows and marks a hit
            # outside the subscription matched-but-not-included
            # (``league_not_included``); a run drops it, so it is not
            # evidence either (#1088).
            if not r.matched or not r.included:
                continue
            if r.category == StreamCategory.TEAM_ONLY:
                team_only.setdefault(r.stream_id, r.league or "")
            elif r.stream_id not in run_keeps:
                # Matched only because the probe bypassed the run's filter:
                # a source made from this evidence would never see the stream.
                continue
            else:
                games.setdefault(r.stream_id, r.league or "")
                event = getattr(r, "event", None)
                if event is not None:
                    evidence.event_ids.add(f"{event.provider}:{event.id}")
        for stream_id in games:
            team_only.pop(stream_id, None)
        evidence.game_matches = len(games)
        evidence.team_only_matches = len(team_only)
        evidence.leagues = dict(Counter(lg for lg in games.values() if lg))
        evidence.team_leagues = dict(Counter(lg for lg in team_only.values() if lg))
        return evidence

    @staticmethod
    def _yield_to_generation() -> None:
        """Wait out a generation run that started mid-scan.

        A full scan takes minutes; both are CPU-bound matching, and the
        generation run is the one with a schedule to keep.
        """
        from teamarr.consumers import generation_status

        deadline = time.monotonic() + GENERATION_WAIT_SECONDS
        while generation_status.is_in_progress() and time.monotonic() < deadline:
            time.sleep(2)

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
        live_ids = {g.id for g in live_groups}
        summary.groups_total = len(live_groups)

        with self._db_factory() as conn:
            taken = self._taken_accounts(conn)
            dismissed, dismissed_names = dismissed_groups(conn)
            dismissed_rotations = dismissed_rotation_keys(conn)
            missing_managed_keys = _missing_managed_rotation_keys(conn, live_ids)
            missing_managed_rot_names = {k for k, _ in missing_managed_keys}
            known_accounts = {
                row[0] or 0
                for row in conn.execute(
                    "SELECT m3u_account_id FROM source_candidates "
                    "UNION SELECT m3u_account_id FROM event_epg_groups "
                    "WHERE m3u_group_id IS NOT NULL"
                )
            }
            leagues = self._processor._get_subscription_leagues(conn, None)
            surfaces = league_name_surfaces(conn, leagues)

        dismissed_by_group: dict[int, set[int]] = {}
        for group_id, account in dismissed:
            dismissed_by_group.setdefault(group_id, set()).add(account)
        dismissed_by_name: dict[str, set[int]] = {}
        for name, account in dismissed_names:
            dismissed_by_name.setdefault(name, set()).add(account)
        dismissed_by_rot: dict[str, set[int]] = {}
        for key, account in dismissed_rotations:
            dismissed_by_rot.setdefault(key, set()).add(account)

        # A dismissed candidate back under a new group id (a provider rename
        # makes Dispatcharr create a new group): still dismissed.
        renamed: list[tuple[Any, int]] = []

        todo = []
        for group in live_groups:
            name = (group.name or "").strip().lower()
            rot_key = rotating_group_key(group.name or "")
            group_accounts = _group_account_ids(group)
            sourced = taken.get(group.id, set())
            said_no = dismissed_by_group.get(group.id, set())
            said_no_by_name = (
                (dismissed_by_name.get(name, set()) - said_no) if rot_key is None else set()
            )
            decided = {account_key(a) for a in sourced} | said_no | said_no_by_name
            if None in sourced:
                summary.skipped_sources += 1
            elif rot_key is not None and (
                (
                    all(
                        (
                            (rot_key, acc) in dismissed_rotations
                            or (rot_key, 0) in dismissed_rotations
                        )
                        and (rot_key, acc) not in missing_managed_keys
                        and (rot_key, 0) not in missing_managed_keys
                        for acc in group_accounts
                    )
                    and not (set(group_accounts) & {account_key(a) for a in sourced})
                )
                if group_accounts
                else (
                    not sourced
                    and not said_no
                    and rot_key not in missing_managed_rot_names
                    and rot_key in dismissed_by_rot
                    and (
                        0 in dismissed_by_rot[rot_key]
                        or not (known_accounts - dismissed_by_rot[rot_key])
                    )
                    and self._nothing_new(group, decided | dismissed_by_rot[rot_key])
                )
            ):
                summary.skipped_dismissed += 1
            elif decided and self._nothing_new(group, decided):
                if sourced:
                    summary.skipped_sources += 1
                else:
                    summary.skipped_dismissed += 1
                    renamed.extend((group, account) for account in said_no_by_name)
            elif _stream_count(group) == 0:
                summary.skipped_empty += 1
            else:
                todo.append(group)

        def unwanted(group: Any) -> Callable[[int], bool]:
            name = (group.name or "").strip().lower()
            rot_key = rotating_group_key(group.name or "")
            sourced = taken.get(group.id, set())

            def skip(account: int) -> bool:
                if (account or None) in sourced:
                    return True
                if (group.id, account) in dismissed:
                    summary.skipped_dismissed += 1
                    return True
                if rot_key is not None:
                    if (
                        (
                            (rot_key, account) in dismissed_rotations
                            or (rot_key, 0) in dismissed_rotations
                        )
                        and (rot_key, account) not in missing_managed_keys
                        and (rot_key, 0) not in missing_managed_keys
                    ):
                        summary.skipped_dismissed += 1
                        return True
                elif (name, account) in dismissed_names:
                    renamed.append((group, account))
                    summary.skipped_dismissed += 1
                    return True
                return False

            return skip

        found: list[ScanEvidence] = []
        if leagues:
            # The scan is read-only, and that includes the match-cache
            # generation counter (#1081): a matcher built without a generation
            # increments it on every batch, so a scan bumped it once per group
            # and the next run's purge_stale found every cached row stale and
            # dropped it — the run after the scan re-scored every stream.
            self._processor._generation = get_generation_counter(self._db_factory)
            with quiet_debug():
                for index, group in enumerate(todo):
                    if progress:
                        progress(index, len(todo), group.name)
                    self._yield_to_generation()
                    try:
                        rows = self._scan_group(group, leagues, now.date(), unwanted(group))
                    except Exception:
                        # One unreadable group must not cost the rest of the scan.
                        logger.exception("[DISCOVERY] Failed to scan group %r", group.name)
                        summary.errors += 1
                        continue
                    named = leagues_named_by(group.name, surfaces)
                    for evidence in rows:
                        evidence.name_leagues = named
                        summary.groups_scanned += 1
                        if evidence.replay:
                            summary.skipped_replay += 1
                        summary.streams_matched_against += evidence.streams_read
                        if evidence.game_matches:
                            summary.groups_with_games += 1
                        found.append(evidence)

        try:
            account_names = {account.id: account.name for account in self._m3u.list_accounts()}
        except Exception:
            logger.warning("[DISCOVERY] Could not list M3U accounts", exc_info=True)
            account_names = {}

        with self._db_factory() as conn:
            for group, account in renamed:
                dismiss_group(conn, group.id, group.name, account or None)
            rebind_rotating_sources(conn, now, live_ids, found, summary)
            scanned_ids = record_scan(conn, found, now)
            readd_approved_sources(conn, now, summary, scanned_ids, account_names=account_names)
            auto_add_sources(conn, now, summary, scanned_ids, account_names=account_names)
            if live_ids:
                maintain_managed_sources(
                    conn,
                    now,
                    live_ids,
                    {(e.m3u_group_id, account_key(e.m3u_account_id)): e for e in found},
                    summary,
                )

        summary.duration_seconds = round((now_utc() - started).total_seconds(), 1)
        logger.info(
            "[DISCOVERY] Scanned %d of %d M3U groups in %.1fs (%d already sources, %d empty, "
            "%d dismissed, %d errors, %d replay): %d carry subscribed games",
            summary.groups_scanned,
            summary.groups_total,
            summary.duration_seconds,
            summary.skipped_sources,
            summary.skipped_empty,
            summary.skipped_dismissed,
            summary.errors,
            summary.skipped_replay,
            summary.groups_with_games,
        )
        return summary


def accept_candidate(
    conn: Connection,
    candidate: CandidateEvidence,
    auto_added_at: str | None = None,
    *,
    account_names: dict[int, str] | None = None,
) -> int:
    """Turn a candidate into a managed source and return the new source's id.

    ``auto_added_at`` marks a source automatic mode added rather than the user.

    The source follows the global subscription and matches the way its
    evidence did: by stream name when streams matched games, as team streams
    when they matched on one team name in the league the group is named for.
    """
    team_streams = bool(team_stream_leagues(candidate))
    name_match = candidate.best_game_matches > 0 or not team_streams
    name = candidate.m3u_group_name
    suffix = 2
    # A name is unique per account, so two accounts' halves of one group share it.
    while get_group_by_name(conn, name, candidate.m3u_account_id) is not None:
        name = f"{candidate.m3u_group_name} ({suffix})"
        suffix += 1
    source_id = create_group(
        conn,
        name=name,
        leagues=[],
        m3u_group_id=candidate.m3u_group_id,
        m3u_group_name=candidate.m3u_group_name,
        m3u_account_id=candidate.m3u_account_id,
        m3u_account_name=(account_names or {}).get(candidate.m3u_account_id or 0),
        name_match_enabled=name_match,
        team_streams_enabled=team_streams,
    )
    set_group_managed(conn, source_id, True, auto_added_at=auto_added_at)
    set_candidate_status(conn, candidate.id, "accepted", source_group_id=source_id)
    logger.info(
        "[DISCOVERY] %s %r as managed source id=%d",
        "Added automatically" if auto_added_at else "Accepted",
        name,
        source_id,
    )
    return source_id


def adopt_source(conn: Connection, source: EventEPGGroup) -> None:
    """Hand a source the user made to Automation: the Automate switch (#1079).

    The source becomes managed, so the Retire and Remove rules apply to it
    exactly as to a discovered one. It also gets the accepted candidate row a
    discovered source has: the scan skips groups that belong to an enabled
    source but reads a retired one's group again, and without this row it
    would list a sleeping source's group under Suggested, where accepting it
    would create a duplicate. The name's league words are recorded so the
    named idle grace applies.
    """
    if source.m3u_group_id is not None:
        league_codes = [row[0] for row in conn.execute("SELECT league_code FROM leagues") if row[0]]
        named = leagues_named_by(
            source.m3u_group_name or source.name, league_name_surfaces(conn, league_codes)
        )
        upsert_accepted_candidate(
            conn,
            m3u_group_id=source.m3u_group_id,
            m3u_group_name=source.m3u_group_name or source.name,
            m3u_account_id=source.m3u_account_id,
            name_leagues=named,
            source_group_id=source.id,
        )
    set_group_managed(conn, source.id, True)
    logger.info("[DISCOVERY] Automate on for source %r (id=%d)", source.name, source.id)


def release_source(conn: Connection, source: EventEPGGroup) -> None:
    """Take a source back from Automation: the Automate switch off (#1079).

    The candidate row stays accepted and linked, so the scan still treats the
    group as taken; deleting the source dismisses it as before.
    """
    set_group_managed(conn, source.id, False)
    logger.info("[DISCOVERY] Automate off for source %r (id=%d)", source.name, source.id)


def auto_leagues(conn: Connection) -> set[str]:
    """Leagues automatic mode is on for: toggled leagues plus every league of a
    toggled sport, including leagues discovered after the toggle was set."""
    from teamarr.database.subscription import get_subscription

    sub = get_subscription(conn)
    leagues = {code.lower() for code in sub.auto_source_leagues}
    sports = {sport.lower() for sport in sub.auto_source_sports}
    if sports:
        for table, code_col, sport_col in (
            ("leagues", "league_code", "sport"),
            ("league_cache", "league_slug", "sport"),
        ):
            for row in conn.execute(f"SELECT {code_col}, {sport_col} FROM {table}"):
                if (row[1] or "").lower() in sports and row[0]:
                    leagues.add(row[0].lower())
    return leagues


def auto_add_decision(
    candidate: CandidateEvidence, toggled: set[str], max_streams: int
) -> str | None:
    """Why automatic mode leaves a candidate alone, or None when it adds it.

    The reasons are the rules, so the review list can show them.
    """
    tier = suggestion_tier(candidate)
    if tier not in (TIER_GAMES, TIER_TEAMS):
        return "not enough evidence"
    if candidate.evidence_days < AUTO_EVIDENCE_DAYS:
        return "seen on one day only"
    if candidate.stream_count > max_streams:
        return f"more than {max_streams} streams"
    if tier == TIER_GAMES:
        total = sum(candidate.leagues.values())
        in_toggled = sum(n for lg, n in candidate.leagues.items() if lg.lower() in toggled)
        if not total or in_toggled / total < AUTO_LEAGUE_SHARE:
            return "its leagues are not set to automatic"
    else:
        if not any(lg.lower() in toggled for lg in team_stream_leagues(candidate)):
            return "its league is not set to automatic"
    return None


def auto_add_sources(
    conn: Connection,
    now: datetime,
    summary: ScanSummary,
    scanned_ids: set[int] | None = None,
    *,
    account_names: dict[int, str] | None = None,
) -> None:
    """Add qualifying candidates as managed sources for the toggled leagues (#997).

    Same machinery as pressing Add, pressed by the scan. Dismissed groups,
    name-only groups and replay groups never reach here; the stream-count cap
    keeps the network catch-alls the user's own call.
    """

    toggled = auto_leagues(conn)
    if not toggled:
        return
    max_streams = load_policy(conn).auto_max_streams
    stamp = to_db_utc(now)
    for candidate in get_candidates(conn, now, EVIDENCE_WINDOW_DAYS, status="new"):
        if scanned_ids is not None and candidate.m3u_group_id not in scanned_ids:
            continue
        if auto_add_decision(candidate, toggled, max_streams) is None:
            accept_candidate(conn, candidate, auto_added_at=stamp, account_names=account_names)
            summary.sources_auto_added += 1


def readd_approved_sources(
    conn: Connection,
    now: datetime,
    summary: ScanSummary,
    scanned_ids: set[int] | None = None,
    *,
    account_names: dict[int, str] | None = None,
) -> None:
    """Add back a source the user already approved once its group is back.

    A managed source is removed when its group has been gone long enough. If
    the group returns the user is not asked again: the candidate is still
    ``accepted``, just without a source, and qualifying evidence re-creates it.
    """
    for candidate in get_candidates(conn, now, EVIDENCE_WINDOW_DAYS, status="accepted"):
        if candidate.source_group_id is not None or (
            scanned_ids is not None and candidate.m3u_group_id not in scanned_ids
        ):
            continue
        if suggestion_tier(candidate) in (TIER_GAMES, TIER_TEAMS):
            accept_candidate(conn, candidate, account_names=account_names)
            summary.sources_readded += 1


def rebind_rotating_sources(
    conn: Connection,
    now: datetime,
    live_ids: set[int],
    evidence: list[ScanEvidence],
    summary: ScanSummary,
) -> None:
    """Follow a rotating group only after the bound ID disappears (#1259, #1265).

    Only a managed source is moved, only within its own account, and only when
    it is the one source of its family on that account: an install that keeps a
    source per day (``EPL (Fri)``, ``(Mon)``, ``(Sun)``) made them separate on
    purpose, and each comes back through the per-run exact-name heal alone.
    A day the user dismissed is never a destination, whatever id it has now.
    """
    by_key: dict[str, list[ScanEvidence]] = defaultdict(list)
    for ev in evidence:
        key = rotating_group_key(ev.m3u_group_name)
        if key and not ev.replay:
            by_key[key].append(ev)
    if not by_key:
        return

    sources = sorted(
        (s for s in get_all_groups(conn, include_disabled=True) if not s.is_channel_source),
        key=lambda s: s.id,
    )
    dismissed, dismissed_names = dismissed_groups(conn)
    accepted = {
        row["source_group_id"]: row
        for row in conn.execute(
            "SELECT id, source_group_id, m3u_group_name FROM source_candidates "
            "WHERE status = 'accepted' AND source_group_id IS NOT NULL ORDER BY id"
        )
    }

    def family_of(source: EventEPGGroup) -> str | None:
        candidate = accepted.get(source.id)
        name = source.m3u_group_name or (candidate["m3u_group_name"] if candidate else "")
        return rotating_group_key(name)

    held: dict[int, set[int]] = defaultdict(set)
    for source in sources:
        if source.m3u_group_id is not None:
            held[source.m3u_group_id].add(account_key(source.m3u_account_id))
    family_size = rotating_family_sizes(conn)

    for source in sorted(sources, key=lambda s: (not s.enabled, s.id)):
        if not source.managed or source.m3u_group_id is None or source.m3u_group_id in live_ids:
            continue
        key = family_of(source)
        if not key:
            continue
        account = account_key(source.m3u_account_id)
        if family_size.get((key, account), 0) > 1:
            continue  # Separate sources per day: none of them follows another day.
        candidate = accepted.get(source.id)
        replacements = sorted(
            (
                ev
                for ev in by_key.get(key, [])
                if account_key(ev.m3u_account_id) == account
                and not binding_conflicts(held.get(ev.m3u_group_id, ()), account)
                and (ev.m3u_group_id, account) not in dismissed
                and (ev.m3u_group_id, 0) not in dismissed
                and not is_dismissed_day(ev.m3u_group_name, account, dismissed_names)
            ),
            key=rotation_rank,
            reverse=True,
        )
        for replacement in replacements:
            if candidate and not move_accepted_candidate(conn, candidate["id"], replacement):
                continue
            conn.execute(
                "UPDATE event_epg_groups SET m3u_group_id = ?, m3u_group_name = ?, "
                "source_missing = 0, source_last_seen = ? WHERE id = ?",
                (replacement.m3u_group_id, replacement.m3u_group_name, to_db_utc(now), source.id),
            )
            if not candidate:
                # Older sources may lack a linked candidate. Give them one so the
                # same scan cannot offer their new binding as another source.
                upsert_accepted_candidate(
                    conn,
                    m3u_group_id=replacement.m3u_group_id,
                    m3u_group_name=replacement.m3u_group_name,
                    m3u_account_id=replacement.m3u_account_id,
                    name_leagues=replacement.name_leagues,
                    source_group_id=source.id,
                )
            held[replacement.m3u_group_id].add(account)
            summary.sources_rebound += 1
            logger.info(
                "[DISCOVERY] Rebound source %r from group %d to %d",
                source.name,
                source.m3u_group_id,
                replacement.m3u_group_id,
            )
            break


def _age_days(stamp: str | None, now: datetime) -> float | None:
    parsed = parse_db_timestamp(stamp) if stamp else None
    return (now - parsed).total_seconds() / 86400 if parsed else None


def maintain_managed_sources(
    conn: Connection,
    now: datetime,
    live_group_ids: set[int],
    evidence: dict[tuple[int, int], ScanEvidence],
    summary: ScanSummary,
    policy: SourceLifecyclePolicy | None = None,
) -> None:
    """Retire managed sources that went quiet and bring back ones with games again.

    Only sources discovery created are touched, and only while still marked
    managed: a hand edit clears the mark, and a hand-made source never has it.

    * enabled, matched nothing for the idle window -> disabled (settings kept)
    * disabled, its group shows games in this scan -> enabled again
    * disabled, its group gone for the gone window -> removed
    """
    policy = policy or load_policy(conn)
    named = {
        c.source_group_id: bool(c.name_leagues)
        for c in get_candidates(conn, now, EVIDENCE_WINDOW_DAYS, status="accepted")
        if c.source_group_id is not None
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
            limit = policy.idle_days_named if named.get(source.id) else policy.idle_days
            if idle is not None and idle >= limit:
                set_managed_source_enabled(conn, source.id, False)
                summary.sources_disabled += 1
                logger.info(
                    "[DISCOVERY] Disabled managed source %r: no match in %d days",
                    source.name,
                    int(idle),
                )
            continue
        found = _evidence_for(source, evidence)
        if group_live:
            # Generation runs stop looking at a disabled source, so the scan
            # keeps its "last seen" current; "gone" is counted from here.
            conn.execute(
                "UPDATE event_epg_groups SET source_last_seen = ? WHERE id = ?",
                (to_db_utc(now), source.id),
            )
        # Games in the group bring it back: two-sided matches, or one-team
        # matches in a league the group's name names — the same evidence
        # discovery accepts for a team-stream source (#1079).
        if group_live and found and (found.game_matches or team_stream_leagues(found)):
            set_managed_source_enabled(conn, source.id, True)
            summary.sources_reenabled += 1
            logger.info("[DISCOVERY] Re-enabled managed source %r: games again", source.name)
        elif not group_live:
            gone = _age_days(seen.get(source.id) or created.get(source.id), now)
            if gone is not None and gone >= policy.gone_days:
                delete_group(conn, source.id)
                forget_removed_source(conn, source.id)
                summary.sources_removed += 1
                logger.info(
                    "[DISCOVERY] Removed managed source %r: group gone %d days",
                    source.name,
                    int(gone),
                )
    conn.commit()


def _evidence_for(
    source: EventEPGGroup, evidence: dict[tuple[int, int], ScanEvidence]
) -> ScanEvidence | None:
    """This scan's evidence for the streams a retired managed source would read.

    Its own account's half of the group; for a source with no account binding,
    the busiest half the scan read.
    """
    if source.m3u_group_id is None:
        return None
    if source.m3u_account_id:
        return evidence.get((source.m3u_group_id, source.m3u_account_id))
    halves = [e for (group_id, _), e in evidence.items() if group_id == source.m3u_group_id]
    return max(halves, key=lambda e: (e.game_matches, e.team_only_matches), default=None)


def _missing_managed_rotation_keys(conn: Connection, live_ids: set[int]) -> set[tuple[str, int]]:
    """Rotating keys of managed sources whose bound group ID is currently absent."""
    accepted_names = {
        row["source_group_id"]: row["m3u_group_name"]
        for row in conn.execute(
            "SELECT source_group_id, m3u_group_name FROM source_candidates "
            "WHERE status = 'accepted' AND source_group_id IS NOT NULL"
        )
    }
    keys: set[tuple[str, int]] = set()
    for source in get_all_groups(conn, include_disabled=True):
        if (
            source.is_channel_source
            or not source.managed
            or source.m3u_group_id is None
            or source.m3u_group_id in live_ids
        ):
            continue
        name = source.m3u_group_name or accepted_names.get(source.id, "")
        if key := rotating_group_key(name):
            keys.add((key, account_key(source.m3u_account_id)))
    return keys


def _group_account_ids(group: Any) -> tuple[int, ...]:
    """M3U account ids reported on a group listing, or empty when unavailable."""
    accounts = getattr(group, "m3u_accounts", None) or []
    ids: set[int] = set()
    for acc in accounts:
        if isinstance(acc, int) and not isinstance(acc, bool):
            ids.add(acc)
        elif isinstance(acc, dict):
            acc_id = acc.get("m3u_account") or acc.get("account_id") or acc.get("id")
            if isinstance(acc_id, int) and not isinstance(acc_id, bool):
                ids.add(acc_id)
    return tuple(sorted(ids))


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
