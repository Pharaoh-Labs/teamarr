"""Sources page folders and arrangement (#1110).

Folders are one level deep, optional, and cosmetic: the run reads sources by
id and stream priority never looks at them (#1109), so everything here may be
rearranged, undone or wiped without touching a channel. Three shapes live
here: the folder rows and each source's place in them (``set_arrangement``),
the one-level undo every destructive action writes first, and the auto-arrange
actions that build folders from a source's provider or its last-run evidence.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from sqlite3 import Connection

from teamarr.database.source_league_shares import LeagueShare, get_group_league_shares

logger = logging.getLogger(__name__)

# A source is filed under its top sport or league when that one accounts for
# at least this share of its matched streams in the last run; otherwise it
# goes under MULTI_FOLDER. Measured on a real install (84 matched sources,
# 2026-10-21): 80 and 100 differ on four sources, and the one that decides it
# is an NHL team-stream source with 32 NHL matches and one stray — strict
# would file it as mixed over a single bad match. Not a setting on purpose.
AUTO_ARRANGE_SHARE = 0.8
MULTI_FOLDER = "Multi"
CHANNEL_SOURCE_FOLDER = "Dispatcharr channels"
UNKNOWN_PROVIDER_FOLDER = "Other"


@dataclass
class SourceFolder:
    id: int
    name: str
    sort_order: int
    collapsed: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "sort_order": self.sort_order,
            "collapsed": self.collapsed,
        }


def _row(row) -> SourceFolder:
    return SourceFolder(
        id=row["id"],
        name=row["name"],
        sort_order=row["sort_order"],
        collapsed=bool(row["collapsed"]),
    )


def list_folders(conn: Connection) -> list[SourceFolder]:
    rows = conn.execute("SELECT * FROM source_folders ORDER BY sort_order, name, id").fetchall()
    return [_row(r) for r in rows]


def get_folder(conn: Connection, folder_id: int) -> SourceFolder | None:
    row = conn.execute("SELECT * FROM source_folders WHERE id = ?", (folder_id,)).fetchone()
    return _row(row) if row else None


def create_folder(conn: Connection, name: str) -> SourceFolder:
    name = name.strip()
    if not name:
        raise ValueError("Folder name is required")
    row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM source_folders").fetchone()
    cursor = conn.execute(
        "INSERT INTO source_folders (name, sort_order) VALUES (?, ?)", (name, row[0])
    )
    # lastrowid is Optional in the sqlite3 types but always set after a
    # successful INSERT; narrow before the read-back so pyright stays green.
    inserted_id = cursor.lastrowid
    assert inserted_id is not None
    conn.commit()
    folder = get_folder(conn, inserted_id)
    assert folder is not None
    return folder


def update_folder(
    conn: Connection,
    folder_id: int,
    *,
    name: str | None = None,
    collapsed: bool | None = None,
) -> SourceFolder | None:
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Folder name is required")
        conn.execute("UPDATE source_folders SET name = ? WHERE id = ?", (name, folder_id))
    if collapsed is not None:
        conn.execute(
            "UPDATE source_folders SET collapsed = ? WHERE id = ?", (int(collapsed), folder_id)
        )
    conn.commit()
    return get_folder(conn, folder_id)


def delete_folder(conn: Connection, folder_id: int) -> bool:
    """Delete a folder; its sources move to the top level, positions kept."""
    conn.execute("UPDATE event_epg_groups SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
    cursor = conn.execute("DELETE FROM source_folders WHERE id = ?", (folder_id,))
    conn.commit()
    return cursor.rowcount > 0


def set_arrangement(
    conn: Connection,
    sources: list[tuple[int, int | None, int]],
    folders: list[tuple[int, int]] | None = None,
) -> int:
    """Store where each source sits: ``(group_id, folder_id, sort_order)``.

    ``folders`` is ``(folder_id, sort_order)`` for the folder rows themselves.
    A folder id that does not exist files the source at the top level rather
    than failing the whole drop.
    """
    known = {f.id for f in list_folders(conn)}
    updated = 0
    for group_id, folder_id, sort_order in sources:
        if folder_id is not None and folder_id not in known:
            folder_id = None
        conn.execute(
            "UPDATE event_epg_groups SET folder_id = ?, sort_order = ? WHERE id = ?",
            (folder_id, sort_order, group_id),
        )
        updated += 1
    for folder_id, sort_order in folders or []:
        conn.execute(
            "UPDATE source_folders SET sort_order = ? WHERE id = ?", (sort_order, folder_id)
        )
    conn.commit()
    return updated


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


def _arrangement_payload(conn: Connection) -> dict:
    sources = conn.execute("SELECT id, folder_id, sort_order FROM event_epg_groups").fetchall()
    return {
        "folders": [f.to_dict() for f in list_folders(conn)],
        "sources": [
            {"id": r["id"], "folder_id": r["folder_id"], "sort_order": r["sort_order"]}
            for r in sources
        ],
    }


def snapshot_arrangement(conn: Connection) -> None:
    """Remember the current arrangement so the next action can be undone."""
    conn.execute(
        "INSERT OR REPLACE INTO source_arrangement_undo (id, payload, created_at)"
        " VALUES (1, ?, CURRENT_TIMESTAMP)",
        (json.dumps(_arrangement_payload(conn)),),
    )


def has_undo(conn: Connection) -> bool:
    return conn.execute("SELECT 1 FROM source_arrangement_undo WHERE id = 1").fetchone() is not None


def restore_arrangement(conn: Connection) -> bool:
    """Put the folders and every source back where the snapshot had them.

    Folders are recreated with their old ids so a source's folder_id means
    the same thing. A source created since the snapshot is left where it
    is; one deleted since is skipped. One level: restoring consumes it.
    """
    row = conn.execute("SELECT payload FROM source_arrangement_undo WHERE id = 1").fetchone()
    if not row:
        return False
    payload = json.loads(row["payload"])
    conn.execute("DELETE FROM source_folders")
    for f in payload["folders"]:
        conn.execute(
            "INSERT INTO source_folders (id, name, sort_order, collapsed) VALUES (?, ?, ?, ?)",
            (f["id"], f["name"], f["sort_order"], int(f.get("collapsed", False))),
        )
    known = {f["id"] for f in payload["folders"]}
    conn.execute("UPDATE event_epg_groups SET folder_id = NULL")
    for s in payload["sources"]:
        folder_id = s["folder_id"] if s["folder_id"] in known else None
        conn.execute(
            "UPDATE event_epg_groups SET folder_id = ?, sort_order = ? WHERE id = ?",
            (folder_id, s["sort_order"], s["id"]),
        )
    conn.execute("DELETE FROM source_arrangement_undo WHERE id = 1")
    conn.commit()
    return True


def clear_folders(conn: Connection) -> int:
    """Remove every folder; sources keep their positions at the top level."""
    snapshot_arrangement(conn)
    count = conn.execute("SELECT COUNT(*) FROM source_folders").fetchone()[0]
    conn.execute("UPDATE event_epg_groups SET folder_id = NULL")
    conn.execute("DELETE FROM source_folders")
    conn.commit()
    return count


# ---------------------------------------------------------------------------
# Auto-arrange
# ---------------------------------------------------------------------------


@dataclass
class ArrangeResult:
    folders: int
    filed: int
    unfiled: int


def _listed_sources(conn: Connection) -> list:
    """The rows the Sources page shows: every M3U source, enabled or not, and
    only the active channel-source rows (a deselected one is kept for its
    scope and never listed)."""
    rows = conn.execute(
        "SELECT id, enabled, is_channel_source, m3u_account_id, m3u_account_name, sort_order"
        " FROM event_epg_groups ORDER BY sort_order, name"
    ).fetchall()
    return [r for r in rows if r["enabled"] or not r["is_channel_source"]]


def _file(conn: Connection, filing: dict[str, list[int]], order: list[str]) -> ArrangeResult:
    """Replace the arrangement with ``filing`` (folder name -> group ids), the
    folders in ``order``. Snapshots first; positions inside a folder follow
    the sources' current order."""
    snapshot_arrangement(conn)
    conn.execute("UPDATE event_epg_groups SET folder_id = NULL")
    conn.execute("DELETE FROM source_folders")
    filed = 0
    for position, name in enumerate(order):
        ids = filing.get(name) or []
        if not ids:
            continue
        cursor = conn.execute(
            "INSERT INTO source_folders (name, sort_order) VALUES (?, ?)", (name, position)
        )
        folder_id = cursor.lastrowid
        for group_id in ids:
            conn.execute(
                "UPDATE event_epg_groups SET folder_id = ? WHERE id = ?", (folder_id, group_id)
            )
            filed += 1
    conn.commit()
    total = len(_listed_sources(conn))
    folders = conn.execute("SELECT COUNT(*) FROM source_folders").fetchone()[0]
    return ArrangeResult(folders=folders, filed=filed, unfiled=total - filed)


def arrange_by_provider(conn: Connection) -> ArrangeResult:
    """One folder per M3U account, plus one for Dispatcharr channel sources."""
    filing: dict[str, list[int]] = defaultdict(list)
    for r in _listed_sources(conn):
        if r["is_channel_source"]:
            name = CHANNEL_SOURCE_FOLDER
        else:
            name = r["m3u_account_name"] or UNKNOWN_PROVIDER_FOLDER
        filing[name].append(r["id"])
    order = sorted(
        filing,
        key=lambda n: (n == CHANNEL_SOURCE_FOLDER, n == UNKNOWN_PROVIDER_FOLDER, n.lower()),
    )
    return _file(conn, filing, order)


def _top(shares: list[LeagueShare], by: str) -> tuple[str, float] | None:
    """The source's top sport or league and its share of matched streams."""
    if not shares:
        return None
    totals: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for s in shares:
        key = s.sport if by == "sport" else s.league
        totals[key] += s.count
        labels.setdefault(key, s.sport_display_name if by == "sport" else s.display_name)
    total = sum(totals.values())
    if not total:
        return None
    key = max(totals, key=lambda k: (totals[k], k))
    return labels[key], totals[key] / total


def arrange_by_evidence(conn: Connection, by: str) -> ArrangeResult:
    """Folders from last-run matches: a source goes under its top sport or
    league at ``AUTO_ARRANGE_SHARE`` or above, else under Multi; a source
    with no matches in that run stays at the top level."""
    if by not in ("sport", "league"):
        raise ValueError(f"Unknown arrangement: {by}")
    _, shares = get_group_league_shares(conn)
    filing: dict[str, list[int]] = defaultdict(list)
    for r in _listed_sources(conn):
        top = _top(shares.get(r["id"], []), by)
        if top is None:
            continue
        name, share = top
        filing[name if share >= AUTO_ARRANGE_SHARE else MULTI_FOLDER].append(r["id"])
    order = sorted(filing, key=lambda n: (n == MULTI_FOLDER, n.lower()))
    return _file(conn, filing, order)
