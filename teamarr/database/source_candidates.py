"""Evidence store for source discovery (#997).

A candidate is an M3U group that is not a source. Each scan appends one row of
evidence for it; whether the group is worth suggesting is decided over a window
of scans, because a single day sees most real sources as empty or placeholders.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from sqlite3 import Connection

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


def record_scan(conn: Connection, evidence: list[ScanEvidence], scanned_at: datetime) -> None:
    """Store one scan's evidence and drop scans past retention.

    Status is never changed here: a dismissed group stays dismissed however
    much it matches, and an accepted one stays accepted.
    """
    stamp = to_db_utc(scanned_at)
    for ev in evidence:
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
        conn.execute(
            """INSERT INTO source_candidate_scans
                   (candidate_id, scanned_at, streams_read, game_matches,
                    team_only_matches, leagues, team_leagues, event_ids)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                candidate_id,
                stamp,
                ev.streams_read,
                ev.game_matches,
                ev.team_only_matches,
                json.dumps(ev.leagues, sort_keys=True),
                json.dumps(ev.team_leagues, sort_keys=True),
                json.dumps(sorted(ev.event_ids)),
            ),
        )
        if ev.game_matches:
            conn.execute(
                "UPDATE source_candidates SET last_matched_at = ? WHERE id = ?",
                (stamp, candidate_id),
            )
    conn.execute(
        "DELETE FROM source_candidate_scans WHERE scanned_at < ?",
        (to_db_utc(scanned_at - timedelta(days=SCAN_RETENTION_DAYS)),),
    )
    conn.commit()


def get_candidates(
    conn: Connection, now: datetime, window_days: int, status: str | None = None
) -> list[CandidateEvidence]:
    """Every candidate with its evidence over the last ``window_days``."""
    since = to_db_utc(now - timedelta(days=window_days))
    query = "SELECT * FROM source_candidates"
    params: list = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    candidates: dict[int, CandidateEvidence] = {}
    for row in conn.execute(query, params).fetchall():
        candidates[row["id"]] = CandidateEvidence(
            id=row["id"],
            m3u_group_id=row["m3u_group_id"],
            m3u_group_name=row["m3u_group_name"],
            m3u_account_ids=json.loads(row["m3u_account_ids"] or "[]"),
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
