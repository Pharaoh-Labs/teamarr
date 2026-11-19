"""Evidence store for source discovery (#997).

A candidate is an M3U group that is not a source. Each scan appends one row of
evidence for it; whether the group is worth suggesting is decided over a window
of scans, because a single day sees most real sources as empty or placeholders.
"""

import json
from collections import defaultdict
from collections.abc import Iterator
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
    streams_read: int = 0
    game_matches: int = 0
    team_only_matches: int = 0
    leagues: dict[str, int] = field(default_factory=dict)
    team_leagues: dict[str, int] = field(default_factory=dict)
    event_ids: set[str] = field(default_factory=set)
    name_leagues: list[str] = field(default_factory=list)
    replay: bool = False


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


def rotation_rank(ev: ScanEvidence) -> tuple[bool, int, int]:
    """Prefer live games, then stream count, then the newer Dispatcharr ID."""
    return bool(ev.game_matches), ev.stream_count, ev.m3u_group_id


def _merge_scan_history(conn: Connection, keeper_id: int, duplicate_id: int) -> None:
    conn.execute(
        "UPDATE source_candidate_scans SET candidate_id = ? WHERE candidate_id = ? "
        "AND NOT (SELECT replay FROM source_candidates WHERE id = ?)",
        (keeper_id, duplicate_id, duplicate_id),
    )
    conn.execute("DELETE FROM source_candidates WHERE id = ?", (duplicate_id,))


def move_accepted_candidate(conn: Connection, candidate_id: int, replacement: ScanEvidence) -> bool:
    """Move a linked candidate without overwriting another source or dismissal."""
    target = conn.execute(
        "SELECT id, status, source_group_id FROM source_candidates WHERE m3u_group_id = ?",
        (replacement.m3u_group_id,),
    ).fetchone()
    if target and target["id"] != candidate_id:
        if target["source_group_id"] is not None or target["status"] == "dismissed":
            return False
        _merge_scan_history(conn, candidate_id, target["id"])
    conn.execute(
        "UPDATE source_candidates SET m3u_group_id = ?, m3u_group_name = ?, "
        "m3u_account_ids = ? WHERE id = ?",
        (
            replacement.m3u_group_id,
            replacement.m3u_group_name,
            json.dumps(sorted(replacement.m3u_account_ids)),
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
    rotating: dict[tuple[str, tuple[int, ...]], list[ScanEvidence]] = defaultdict(list)
    for ev in evidence:
        key = rotating_group_key(ev.m3u_group_name)
        if key and not ev.replay:
            rotating[key, tuple(sorted(ev.m3u_account_ids))].append(ev)
        else:
            yield ev, [ev]
    if not rotating:
        return

    prior = defaultdict(list)
    dismissed = dismissed_rotation_keys(conn)
    for row in conn.execute(
        "SELECT c.*, g.m3u_group_id AS bound_id FROM source_candidates c "
        "LEFT JOIN event_epg_groups g ON g.id = c.source_group_id ORDER BY c.id"
    ):
        key = (
            rotating_group_key(row["m3u_group_name"]),
            tuple(sorted(json.loads(row["m3u_account_ids"] or "[]"))),
        )
        if key in rotating:
            prior[key].append(row)

    for key, batch in rotating.items():
        rows = prior[key]
        linked = [row for row in rows if row["bound_id"] is not None]
        if len(linked) > 1:
            # Legacy installs may have deliberately created separate sources.
            for ev in batch:
                yield ev, [ev]
            continue
        if _is_dismissed_rotation(key[0], key[1], dismissed):
            continue
        if linked:
            representative = next(
                (ev for ev in batch if ev.m3u_group_id == linked[0]["bound_id"]), None
            )
            if representative is None:
                continue  # Never change a candidate's binding ahead of its source.
        else:
            representative = max(batch, key=rotation_rank)

        # An ID is still unique in SQLite. If Dispatcharr reused it for a
        # different name, keep the existing per-ID behavior for this batch.
        target = conn.execute(
            "SELECT id FROM source_candidates WHERE m3u_group_id = ?",
            (representative.m3u_group_id,),
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
                   (m3u_group_id, m3u_group_name, m3u_account_ids, stream_count,
                    name_leagues, last_seen_at, replay)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(m3u_group_id) DO UPDATE SET
                   m3u_group_name = excluded.m3u_group_name,
                   m3u_account_ids = excluded.m3u_account_ids,
                   stream_count = excluded.stream_count,
                   name_leagues = excluded.name_leagues,
                   last_seen_at = excluded.last_seen_at,
                   replay = excluded.replay""",
            (
                ev.m3u_group_id,
                ev.m3u_group_name,
                json.dumps(sorted(ev.m3u_account_ids)),
                ev.stream_count,
                json.dumps(sorted(ev.name_leagues)),
                stamp,
                int(ev.replay),
            ),
        )
        candidate_id = conn.execute(
            "SELECT id FROM source_candidates WHERE m3u_group_id = ?", (ev.m3u_group_id,)
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
    rejected_keys = dismissed_rotation_keys(conn)
    query = "SELECT * FROM source_candidates"
    params: list = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    candidates: dict[int, CandidateEvidence] = {}
    for row in conn.execute(query, params).fetchall():
        account_ids = json.loads(row["m3u_account_ids"] or "[]")
        if row["status"] == "new" and _is_dismissed_rotation(
            rotating_group_key(row["m3u_group_name"]),
            tuple(sorted(account_ids)),
            rejected_keys,
        ):
            continue
        candidates[row["id"]] = CandidateEvidence(
            id=row["id"],
            m3u_group_id=row["m3u_group_id"],
            m3u_group_name=row["m3u_group_name"],
            m3u_account_ids=account_ids,
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
    m3u_account_ids: list[int],
    name_leagues: list[str],
    source_group_id: int,
) -> None:
    """Record a group as an accepted candidate linked to ``source_group_id``.

    The Automate switch (#1079) gives a source the user made the row a
    discovered source has. An existing row keeps its scan history; only its
    status and link change, and a dismissal is lifted — the user just said yes.
    """
    conn.execute(
        """INSERT INTO source_candidates
               (m3u_group_id, m3u_group_name, m3u_account_ids, name_leagues,
                status, source_group_id)
           VALUES (?, ?, ?, ?, 'accepted', ?)
           ON CONFLICT(m3u_group_id) DO UPDATE SET
               m3u_group_name = excluded.m3u_group_name,
               name_leagues = excluded.name_leagues,
               status = 'accepted',
               source_group_id = excluded.source_group_id""",
        (
            m3u_group_id,
            m3u_group_name,
            json.dumps(sorted(m3u_account_ids)),
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


def dismissed_groups(conn: Connection) -> tuple[set[int], set[str]]:
    """Dismissed M3U groups as ``(ids, names)`` — a scan does not read them again.

    Names as well as ids: a provider rename gives the group a new id in
    Dispatcharr, and the user's "no" has to survive that.
    """
    rows = conn.execute(
        "SELECT m3u_group_id, m3u_group_name FROM source_candidates WHERE status = 'dismissed'"
    ).fetchall()
    return {row[0] for row in rows}, {(row[1] or "").strip().lower() for row in rows}


def _is_dismissed_rotation(
    key: str | None,
    accounts: tuple[int, ...],
    dismissed: set[tuple[str, tuple[int, ...]]],
) -> bool:
    return key is not None and ((key, accounts) in dismissed or (key, ()) in dismissed)


def dismissed_rotation_keys(conn: Connection) -> set[tuple[str, tuple[int, ...]]]:
    """Dismissed rotating identities, scoped to the accounts that carry them."""
    rows = conn.execute(
        "SELECT m3u_group_name, m3u_account_ids FROM source_candidates WHERE status = 'dismissed'"
    ).fetchall()
    keys: set[tuple[str, tuple[int, ...]]] = set()
    for row in rows:
        key = rotating_group_key(row["m3u_group_name"] or "")
        if key is not None:
            accounts = tuple(sorted(json.loads(row["m3u_account_ids"] or "[]")))
            keys.add((key, accounts))
    return keys


def dismiss_group(conn: Connection, m3u_group_id: int, m3u_group_name: str) -> None:
    """Record a group as dismissed, creating its candidate row when it has none."""
    conn.execute(
        """INSERT INTO source_candidates (m3u_group_id, m3u_group_name, status)
           VALUES (?, ?, 'dismissed')
           ON CONFLICT(m3u_group_id) DO UPDATE SET status = 'dismissed'""",
        (m3u_group_id, m3u_group_name),
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
