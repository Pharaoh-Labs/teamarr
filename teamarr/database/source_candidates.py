"""Evidence store for source discovery (#997).

A candidate is one M3U account's streams in one M3U group that no source reads
(#1226): a group two accounts carry is two candidates, because a source reads
one account's streams and each half is suggested, accepted and dismissed on its
own. Each scan appends one row of evidence for it; whether it is worth
suggesting is decided over a window of scans, because a single day sees most
real sources as empty or placeholders.

``m3u_account_id`` 0 stands for streams that carry no account.
"""

import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from sqlite3 import Connection

from teamarr.utilities.m3u_group_identity import rotating_group_key
from teamarr.utilities.tz import to_db_utc

# Scans older than this are dropped; the longest window anything reads is shorter.
SCAN_RETENTION_DAYS = 30


@dataclass
class ScanEvidence:
    """What one scan found in one M3U group."""

    m3u_group_id: int
    m3u_group_name: str
    m3u_account_ids: list[int] = field(default_factory=list)
    stream_count: int = 0
    m3u_account_id: int | None = None
    streams_read: int = 0
    game_matches: int = 0
    team_only_matches: int = 0
    leagues: dict[str, int] = field(default_factory=dict)
    team_leagues: dict[str, int] = field(default_factory=dict)
    event_ids: set[str] = field(default_factory=set)
    name_leagues: list[str] = field(default_factory=list)
    replay: bool = False

    def __post_init__(self) -> None:
        self.m3u_account_id, self.m3u_account_ids = _one_account(
            self.m3u_account_id, self.m3u_account_ids
        )


def _one_account(account_id: int | None, account_ids: list[int]) -> tuple[int | None, list[int]]:
    """A candidate has one account; the list form is kept for the API and callers."""
    if account_id is None and account_ids:
        account_id = account_ids[0]
    return account_id, ([account_id] if account_id else [])


def account_key(account_id: int | None) -> int:
    """The stored form of an account id: 0 for "no account"."""
    return account_id or 0


def binding_conflicts(held: Iterable[int], account: int) -> bool:
    """Whether a source reading ``account`` in a group would share streams there.

    ``held`` are the account keys of the sources already on the group. A source
    with no account (0) reads the whole group, so it conflicts with any holder
    and any newcomer conflicts with it (#1226).
    """
    holders = set(held)
    return bool(holders) and (account == 0 or 0 in holders or account in holders)


def group_name_key(name: str | None) -> str:
    """The form a group name is compared in for dismissals."""
    return (name or "").strip().lower()


def is_dismissed_day(name: str | None, account: int, dismissed_names: set[tuple[str, int]]) -> bool:
    """Whether this exact rotating group name was dismissed for the account (#1265).

    A day of a rotating family comes back under a new group id every time, so
    its dismissal is read by name. It covers that name only — never the other
    days of the family — and one recorded with no account covers every account.
    """
    key = group_name_key(name)
    return (key, account) in dismissed_names or (key, 0) in dismissed_names


@dataclass
class CandidateEvidence:
    """A candidate with its evidence summed up over a window of scans."""

    id: int
    m3u_group_id: int
    m3u_group_name: str
    m3u_account_ids: list[int]
    stream_count: int
    name_leagues: list[str]
    status: str
    source_group_id: int | None
    last_seen_at: str | None
    last_matched_at: str | None
    first_seen_at: str | None = None
    replay: bool = False
    scans: int = 0  # scans inside the window
    scan_days: int = 0  # distinct days inside the window with a scan
    scan_days_with_streams: int = 0  # ... on which the group had streams to match
    evidence_days: int = 0  # distinct days on which something matched (games or teams)
    best_game_matches: int = 0  # most game matches any one scan saw
    days_matched: int = 0  # scans inside the window with a game match
    team_only_matches: int = 0  # most team-only matches any one scan saw
    leagues: dict[str, int] = field(default_factory=dict)  # best per league
    team_leagues: dict[str, int] = field(default_factory=dict)  # best per league
    event_ids: set[str] = field(default_factory=set)  # every event matched in the window
    m3u_account_id: int | None = None

    def __post_init__(self) -> None:
        self.m3u_account_id, self.m3u_account_ids = _one_account(
            self.m3u_account_id, self.m3u_account_ids
        )


def rotation_rank(ev: ScanEvidence) -> tuple[bool, int, int]:
    """Prefer live games, then stream count, then the newer Dispatcharr ID."""
    return bool(ev.game_matches), ev.stream_count, ev.m3u_group_id


def rotating_family_sizes(conn: Connection) -> dict[tuple[str, int], int]:
    """How many sources each rotating family has per account (#1265).

    Every source counts, hand-made, managed, enabled or not. More than one on
    an account means the user keeps a source per day (``EPL (Fri)``, ``(Mon)``,
    ``(Sun)``): those are separate on purpose and stay bound per group id. A
    family with exactly one is the rotating case, where the source follows.
    """
    sizes: dict[tuple[str, int], int] = defaultdict(int)
    rows = conn.execute(
        """
        SELECT g.m3u_account_id AS account,
               COALESCE(NULLIF(g.m3u_group_name, ''), c.m3u_group_name, '') AS group_name
        FROM event_epg_groups g
        LEFT JOIN source_candidates c ON c.id = (
            SELECT MAX(id) FROM source_candidates
            WHERE source_group_id = g.id AND status = 'accepted'
        )
        WHERE g.m3u_group_id IS NOT NULL AND COALESCE(g.is_channel_source, 0) = 0
        ORDER BY g.id
        """
    ).fetchall()
    for row in rows:
        if key := rotating_group_key(row["group_name"]):
            sizes[key, account_key(row["account"])] += 1
    return sizes


def _merge_scan_history(conn: Connection, keeper_id: int, duplicate_id: int) -> None:
    conn.execute(
        "UPDATE source_candidate_scans SET candidate_id = ? WHERE candidate_id = ? "
        "AND NOT (SELECT replay FROM source_candidates WHERE id = ?)",
        (keeper_id, duplicate_id, duplicate_id),
    )
    conn.execute("DELETE FROM source_candidates WHERE id = ?", (duplicate_id,))


def move_accepted_candidate(conn: Connection, candidate_id: int, replacement: ScanEvidence) -> bool:
    """Move a linked candidate without overwriting another source or dismissal."""
    acc_key = account_key(replacement.m3u_account_id)
    target = conn.execute(
        "SELECT id, status, source_group_id FROM source_candidates "
        "WHERE m3u_group_id = ? AND m3u_account_id = ?",
        (replacement.m3u_group_id, acc_key),
    ).fetchone()
    if target and target["id"] != candidate_id:
        if target["source_group_id"] is not None or target["status"] == "dismissed":
            return False
        _merge_scan_history(conn, candidate_id, target["id"])
    conn.execute(
        "UPDATE source_candidates SET m3u_group_id = ?, m3u_group_name = ?, "
        "m3u_account_id = ? WHERE id = ?",
        (
            replacement.m3u_group_id,
            replacement.m3u_group_name,
            acc_key,
            candidate_id,
        ),
    )
    return True


def _scan_batches(
    conn: Connection, evidence: list[ScanEvidence]
) -> Iterator[tuple[ScanEvidence, list[ScanEvidence]]]:
    """Resolve rotating names to one candidate, keeping its ID and scan history.

    Derive the key from stored names so existing rows can be consolidated on
    their next scan without rewriting unrelated groups or requiring a migration.
    """
    rotating: dict[tuple[str, int], list[ScanEvidence]] = defaultdict(list)
    _, dismissed_names = dismissed_groups(conn)
    for ev in evidence:
        key = rotating_group_key(ev.m3u_group_name)
        if key and not ev.replay:
            account = account_key(ev.m3u_account_id)
            if is_dismissed_day(ev.m3u_group_name, account, dismissed_names):
                continue  # The user said no to this day; it is nobody's evidence.
            rotating[key, account].append(ev)
        else:
            yield ev, [ev]
    if not rotating:
        return

    prior = defaultdict(list)
    family_sizes = rotating_family_sizes(conn)
    for row in conn.execute(
        "SELECT c.*, g.m3u_group_id AS bound_id FROM source_candidates c "
        "LEFT JOIN event_epg_groups g ON g.id = c.source_group_id ORDER BY c.id"
    ):
        key = (
            rotating_group_key(row["m3u_group_name"]),
            row["m3u_account_id"] or 0,
        )
        # A dismissed day keeps its own row: it is never folded into the
        # family's candidate, or the dismissal would be lost with it.
        if key in rotating and row["status"] != "dismissed":
            prior[key].append(row)

    for key, batch in rotating.items():
        rows = prior[key]
        linked = [row for row in rows if row["bound_id"] is not None]
        if len(linked) > 1 or family_sizes.get(key, 0) > 1:
            # Legacy installs may have deliberately created separate sources.
            for ev in batch:
                yield ev, [ev]
            continue
        if linked:
            representative = next(
                (ev for ev in batch if ev.m3u_group_id == linked[0]["bound_id"]), None
            )
            if representative is None:
                continue  # Never change a candidate's binding ahead of its source.
        else:
            representative = max(batch, key=rotation_rank)

        # An (group_id, account_id) is still unique in SQLite. If Dispatcharr reused
        # it for a different name, keep the existing per-ID behavior for this batch.
        target = conn.execute(
            "SELECT id FROM source_candidates WHERE m3u_group_id = ? AND m3u_account_id = ?",
            (representative.m3u_group_id, account_key(representative.m3u_account_id)),
        ).fetchone()
        if target and all(row["id"] != target[0] for row in rows):
            for ev in batch:
                yield ev, [ev]
            continue

        if rows:
            keeper = linked[0] if linked else min(rows, key=lambda row: row["status"] != "accepted")
            for row in rows:
                if row["id"] == keeper["id"]:
                    continue
                _merge_scan_history(conn, keeper["id"], row["id"])
            last_match = max(
                (row["last_matched_at"] for row in rows if row["last_matched_at"]), default=None
            )
            conn.execute(
                "UPDATE source_candidates SET m3u_group_id = ?, last_matched_at = ? WHERE id = ?",
                (representative.m3u_group_id, last_match, keeper["id"]),
            )
        yield representative, batch


def record_scan(conn: Connection, evidence: list[ScanEvidence], scanned_at: datetime) -> set[int]:
    """Store one scan's evidence and drop scans past retention.

    Status is never changed here: a dismissed group stays dismissed however
    much it matches, and an accepted one stays accepted.
    Returns the live group IDs selected as candidates on this scan.
    """
    stamp = to_db_utc(scanned_at)
    recorded: set[int] = set()
    for ev, batch in _scan_batches(conn, evidence):
        recorded.add(ev.m3u_group_id)
        conn.execute(
            """INSERT INTO source_candidates
                   (m3u_group_id, m3u_group_name, m3u_account_id, stream_count,
                    name_leagues, last_seen_at, replay)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(m3u_group_id, m3u_account_id) DO UPDATE SET
                   m3u_group_name = excluded.m3u_group_name,
                   stream_count = excluded.stream_count,
                   name_leagues = excluded.name_leagues,
                   last_seen_at = excluded.last_seen_at,
                   replay = excluded.replay""",
            (
                ev.m3u_group_id,
                ev.m3u_group_name,
                account_key(ev.m3u_account_id),
                ev.stream_count,
                json.dumps(sorted(ev.name_leagues)),
                stamp,
                int(ev.replay),
            ),
        )
        candidate_id = conn.execute(
            "SELECT id FROM source_candidates WHERE m3u_group_id = ? AND m3u_account_id = ?",
            (ev.m3u_group_id, account_key(ev.m3u_account_id)),
        ).fetchone()[0]
        for scanned in batch:
            conn.execute(
                """INSERT INTO source_candidate_scans
                   (candidate_id, scanned_at, streams_read, game_matches,
                    team_only_matches, leagues, team_leagues, event_ids)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate_id,
                    stamp,
                    scanned.streams_read,
                    scanned.game_matches,
                    scanned.team_only_matches,
                    json.dumps(scanned.leagues, sort_keys=True),
                    json.dumps(scanned.team_leagues, sort_keys=True),
                    json.dumps(sorted(scanned.event_ids)),
                ),
            )
        if any(scanned.game_matches for scanned in batch):
            conn.execute(
                "UPDATE source_candidates SET last_matched_at = ? WHERE id = ?",
                (stamp, candidate_id),
            )
    conn.execute(
        "DELETE FROM source_candidate_scans WHERE scanned_at < ?",
        (to_db_utc(scanned_at - timedelta(days=SCAN_RETENTION_DAYS)),),
    )
    conn.commit()
    return recorded


def get_candidates(
    conn: Connection, now: datetime, window_days: int, status: str | None = None
) -> list[CandidateEvidence]:
    """Every candidate with its evidence over the last ``window_days``."""
    since = to_db_utc(now - timedelta(days=window_days))
    _, dismissed_names = dismissed_groups(conn)
    query = "SELECT * FROM source_candidates"
    params: list = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    candidates: dict[int, CandidateEvidence] = {}
    for row in conn.execute(query, params).fetchall():
        account_id = row["m3u_account_id"] or None
        if (
            row["status"] == "new"
            and rotating_group_key(row["m3u_group_name"]) is not None
            and is_dismissed_day(row["m3u_group_name"], account_key(account_id), dismissed_names)
        ):
            continue
        candidates[row["id"]] = CandidateEvidence(
            id=row["id"],
            m3u_group_id=row["m3u_group_id"],
            m3u_group_name=row["m3u_group_name"],
            m3u_account_ids=[],
            m3u_account_id=account_id,
            stream_count=row["stream_count"] or 0,
            name_leagues=json.loads(row["name_leagues"] or "[]"),
            status=row["status"],
            source_group_id=row["source_group_id"],
            last_seen_at=row["last_seen_at"],
            last_matched_at=row["last_matched_at"],
            first_seen_at=row["created_at"],
            replay=bool(row["replay"]),
        )
    scans = conn.execute(
        "SELECT * FROM source_candidate_scans WHERE scanned_at >= ? ORDER BY scanned_at",
        (since,),
    ).fetchall()
    days: dict[tuple[int, str], bool] = {}
    matched_days: set[tuple[int, str]] = set()
    for scan in scans:
        cand = candidates.get(scan["candidate_id"])
        if cand is None:
            continue
        cand.scans += 1
        day = (cand.id, str(scan["scanned_at"])[:10])
        days[day] = days.get(day, False) or bool(scan["streams_read"])
        if scan["game_matches"] or scan["team_only_matches"]:
            matched_days.add(day)
        for league, count in json.loads(scan["team_leagues"] or "{}").items():
            cand.team_leagues[league] = max(cand.team_leagues.get(league, 0), count)
        cand.event_ids |= set(json.loads(scan["event_ids"] or "[]"))
        cand.best_game_matches = max(cand.best_game_matches, scan["game_matches"])
        cand.team_only_matches = max(cand.team_only_matches, scan["team_only_matches"])
        if scan["game_matches"]:
            cand.days_matched += 1
        for league, count in json.loads(scan["leagues"] or "{}").items():
            cand.leagues[league] = max(cand.leagues.get(league, 0), count)
    for (candidate_id, _), had_streams in days.items():
        candidates[candidate_id].scan_days += 1
        candidates[candidate_id].scan_days_with_streams += int(had_streams)
    for candidate_id, _ in matched_days:
        candidates[candidate_id].evidence_days += 1
    return list(candidates.values())


def upsert_accepted_candidate(
    conn: Connection,
    *,
    m3u_group_id: int,
    m3u_group_name: str,
    m3u_account_id: int | None,
    name_leagues: list[str],
    source_group_id: int,
) -> None:
    """Record a group's account as an accepted candidate linked to ``source_group_id``.

    The Automate switch (#1079) gives a source the user made the row a
    discovered source has. An existing row keeps its scan history; only its
    status and link change, and a dismissal is lifted — the user just said yes.
    """
    conn.execute(
        """INSERT INTO source_candidates
               (m3u_group_id, m3u_group_name, m3u_account_id, name_leagues,
                status, source_group_id)
           VALUES (?, ?, ?, ?, 'accepted', ?)
           ON CONFLICT(m3u_group_id, m3u_account_id) DO UPDATE SET
               m3u_group_name = excluded.m3u_group_name,
               name_leagues = excluded.name_leagues,
               status = 'accepted',
               source_group_id = excluded.source_group_id""",
        (
            m3u_group_id,
            m3u_group_name,
            account_key(m3u_account_id),
            json.dumps(sorted(name_leagues)),
            source_group_id,
        ),
    )
    conn.commit()


def set_candidate_status(
    conn: Connection, candidate_id: int, status: str, source_group_id: int | None = None
) -> bool:
    """Mark a candidate new, accepted or dismissed. Returns False if it does not exist."""
    cursor = conn.execute(
        "UPDATE source_candidates SET status = ?, source_group_id = ? WHERE id = ?",
        (status, source_group_id, candidate_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def dismissed_groups(conn: Connection) -> tuple[set[tuple[int, int]], set[tuple[str, int]]]:
    """Dismissed candidates as ``({(group id, account)}, {(group name, account)})``.

    A scan does not record them again. Names as well as ids: a provider rename
    gives the group a new id in Dispatcharr, and the user's "no" has to survive
    that. The account is part of both: saying no to one account's copy of a
    group says nothing about another account's.
    """
    rows = conn.execute(
        "SELECT m3u_group_id, m3u_group_name, m3u_account_id FROM source_candidates "
        "WHERE status = 'dismissed'"
    ).fetchall()
    return (
        {(row[0], row[2] or 0) for row in rows},
        {(group_name_key(row[1]), row[2] or 0) for row in rows},
    )


def dismiss_group(
    conn: Connection, m3u_group_id: int, m3u_group_name: str, m3u_account_id: int | None = None
) -> None:
    """Record a group's account as dismissed, creating its candidate row when it has none."""
    conn.execute(
        """INSERT INTO source_candidates (m3u_group_id, m3u_group_name, m3u_account_id, status)
           VALUES (?, ?, ?, 'dismissed')
           ON CONFLICT(m3u_group_id, m3u_account_id) DO UPDATE SET status = 'dismissed'""",
        (m3u_group_id, m3u_group_name, account_key(m3u_account_id)),
    )


def dismiss_candidate_for_source(conn: Connection, source_group_id: int) -> None:
    """The user deleted a source that came from a suggestion: do not offer it again."""
    conn.execute(
        "UPDATE source_candidates SET status = 'dismissed', source_group_id = NULL "
        "WHERE source_group_id = ?",
        (source_group_id,),
    )


def forget_removed_source(conn: Connection, source_group_id: int) -> None:
    """Discovery removed a managed source: keep the approval, drop the dead link.

    The candidate stays ``accepted`` with no source, which is how a scan knows
    to add it back when its group returns.
    """
    conn.execute(
        "UPDATE source_candidates SET source_group_id = NULL WHERE source_group_id = ?",
        (source_group_id,),
    )
