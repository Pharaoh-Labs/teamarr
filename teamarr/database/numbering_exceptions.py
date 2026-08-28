"""Numbering exceptions — pinned channel-number blocks (#333).

A *pinned block* numbers a scope's channels from a fixed start: a team
("Detroit Lions at 800"), a league ("NFL at 1700"), or a sport ("soccer at
1800"). Rows that share ``start`` + ``label`` form a *group* ("Big events" =
World Cup + Olympics at 850). Everything unmatched numbers from the global
channel range — the *default lane*.

Every channel resolves to exactly one lane via :func:`resolve_lane`:
most specific wins (home-team pin › away-team pin › league › sport ›
default), ties broken by ``sort_order``. Resolution reads only fields that
never change during an event, so a channel's lane is stable for its lifetime.

The allocator in :mod:`teamarr.database.channel_numbers` runs the same
placement code (compact / gap / strict) inside each lane. See
``docs/reference/architecture/channel-numbering.md``.
"""

import logging
import sqlite3
from dataclasses import dataclass
from sqlite3 import Connection

logger = logging.getLogger(__name__)

SCOPES = ("team", "league", "sport")

# Precedence rank per scope — lower wins. Team pins are split by which side
# matched so a home-team pin beats an away-team pin when both are pinned.
_RANK_TEAM_HOME = 0
_RANK_TEAM_AWAY = 1
_RANK_LEAGUE = 2
_RANK_SPORT = 3


@dataclass(frozen=True)
class Lane:
    """A numbering lane: the range a channel is placed in.

    ``id`` is the ``numbering_exceptions`` row id for pinned lanes, or ``None``
    for the default lane (the global channel range). ``end`` ``None`` means the
    block spills forward past its neighbours rather than overflowing.
    """

    id: int | None
    start: int
    end: int | None = None
    label: str | None = None

    @property
    def is_default(self) -> bool:
        return self.id is None


@dataclass
class NumberingException:
    """One pinned-block row."""

    id: int
    scope: str
    sport: str
    start: int
    league_code: str | None = None
    team_name: str | None = None
    provider: str | None = None
    provider_team_id: str | None = None
    end: int | None = None
    label: str | None = None
    sort_order: int = 0
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def lane(self) -> Lane:
        return Lane(id=self.id, start=self.start, end=self.end, label=self.label)


_COLUMNS = (
    'id, scope, sport, league_code, team_name, provider, provider_team_id, '
    'start, "end", label, sort_order, enabled, created_at, updated_at'
)


def _row_to_exception(row: sqlite3.Row) -> NumberingException:
    return NumberingException(
        id=row["id"],
        scope=row["scope"],
        sport=row["sport"],
        start=int(row["start"]),
        league_code=row["league_code"],
        team_name=row["team_name"],
        provider=row["provider"],
        provider_team_id=row["provider_team_id"],
        end=int(row["end"]) if row["end"] is not None else None,
        label=row["label"],
        sort_order=int(row["sort_order"] or 0),
        enabled=bool(row["enabled"]) if row["enabled"] is not None else True,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _table_exists(conn: Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'numbering_exceptions'"
    ).fetchone()
    return row is not None


# =============================================================================
# Read
# =============================================================================


def get_numbering_exceptions(
    conn: Connection, *, enabled_only: bool = False
) -> list[NumberingException]:
    """All pinned blocks in precedence order (sort_order, then id).

    This is the UI list order: the reorder arrows edit ``sort_order``, so the
    list must follow it rather than ``start`` or a move would be invisible.
    Placement order (ascending start) is derived separately by
    ``LaneResolver.lanes``.
    """
    if not _table_exists(conn):
        return []
    where = "WHERE enabled = 1" if enabled_only else ""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM numbering_exceptions {where} ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    return [_row_to_exception(r) for r in rows]


def get_numbering_exception(conn: Connection, exception_id: int) -> NumberingException | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM numbering_exceptions WHERE id = ?", (exception_id,)
    ).fetchone()
    return _row_to_exception(row) if row else None


# =============================================================================
# Write
# =============================================================================


def _arm_relayout(conn: Connection) -> None:
    # Block edits change where channels belong; arm a one-shot re-grid so sticky
    # modes apply the change on the next generation (no-op in compact).
    from teamarr.database.channel_numbers import arm_channel_relayout

    arm_channel_relayout(conn)


def _next_sort_order(conn: Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM numbering_exceptions"
    ).fetchone()
    return int(row[0]) if row else 0


def _validate(scope: str, start: int, end: int | None) -> str | None:
    if scope not in SCOPES:
        return f"invalid scope '{scope}'"
    if start < 1:
        return "start must be >= 1"
    if end is not None and end < start:
        return "end must be >= start"
    return None


def add_numbering_exception(
    conn: Connection,
    *,
    scope: str,
    start: int,
    sport: str | None = None,
    league_code: str | None = None,
    provider: str | None = None,
    provider_team_id: str | None = None,
    team_league: str | None = None,
    end: int | None = None,
    label: str | None = None,
) -> NumberingException | None:
    """Add a pinned block.

    - ``scope='team'``: pass ``provider`` + ``provider_team_id`` (a TeamPicker
      entry); name + sport are resolved from ``team_cache`` so the match key
      stays canonical. ``team_league`` narrows the cache lookup.
    - ``scope='league'``: pass ``league_code`` (+ ``sport`` if known; resolved
      from ``leagues`` otherwise).
    - ``scope='sport'``: pass ``sport``.

    Returns the stored row, or ``None`` on validation / lookup failure.
    """
    err = _validate(scope, start, end)
    if err:
        logger.warning("[NUMBERING_EXC] %s", err)
        return None

    team_name: str | None = None
    if scope == "team":
        if not provider or not provider_team_id:
            logger.warning("[NUMBERING_EXC] team pin needs provider + provider_team_id")
            return None
        lookup = conn.execute(
            """
            SELECT team_name, sport FROM team_cache
            WHERE provider = ? AND provider_team_id = ?
              AND (league = ? OR ? IS NULL)
            LIMIT 1
            """,
            (provider, provider_team_id, team_league, team_league),
        ).fetchone()
        if lookup is None:
            logger.warning(
                "[NUMBERING_EXC] No team_cache row for provider=%s team_id=%s league=%s",
                provider, provider_team_id, team_league,
            )
            return None
        team_name = lookup["team_name"]
        sport = lookup["sport"]
        league_code = None
    elif scope == "league":
        if not league_code:
            logger.warning("[NUMBERING_EXC] league pin needs league_code")
            return None
        league_code = league_code.lower()
        if not sport:
            row = conn.execute(
                "SELECT sport FROM leagues WHERE league_code = ?", (league_code,)
            ).fetchone()
            sport = row["sport"] if row else None
        if not sport:
            logger.warning("[NUMBERING_EXC] Unknown league '%s' (no sport)", league_code)
            return None
        provider = provider_team_id = None
    else:  # sport
        if not sport:
            logger.warning("[NUMBERING_EXC] sport pin needs sport")
            return None
        league_code = provider = provider_team_id = None

    sport = (sport or "").lower()
    cursor = conn.execute(
        """
        INSERT INTO numbering_exceptions
            (scope, sport, league_code, team_name, provider, provider_team_id,
             start, "end", label, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scope, sport, league_code, team_name, provider, provider_team_id,
            int(start), int(end) if end is not None else None,
            (label or "").strip() or None, _next_sort_order(conn),
        ),
    )
    _arm_relayout(conn)
    assert cursor.lastrowid is not None  # INSERT always yields a rowid
    created = get_numbering_exception(conn, cursor.lastrowid)
    logger.info(
        "[NUMBERING_EXC] Added %s pin → %d (%s)",
        scope, start, team_name or league_code or sport,
    )
    return created


def update_numbering_exception(
    conn: Connection,
    exception_id: int,
    *,
    start: int | None = None,
    end: int | None | object = ...,
    label: str | None | object = ...,
    enabled: bool | None = None,
) -> NumberingException | None:
    """Update a block's range / label / enabled flag. Scope and identity are
    immutable — delete and re-add to re-scope. ``end`` / ``label`` accept
    ``None`` to clear; leave at the default sentinel to keep."""
    current = get_numbering_exception(conn, exception_id)
    if current is None:
        return None
    new_start = int(start) if start is not None else current.start
    if end is ...:
        new_end = current.end
    else:
        new_end = int(end) if isinstance(end, int) else None
    err = _validate(current.scope, new_start, new_end)
    if err:
        logger.warning("[NUMBERING_EXC] %s", err)
        return None
    if label is ...:
        new_label = current.label
    else:
        new_label = (label.strip() or None) if isinstance(label, str) else None
    new_enabled = current.enabled if enabled is None else bool(enabled)
    conn.execute(
        """
        UPDATE numbering_exceptions
        SET start = ?, "end" = ?, label = ?, enabled = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (new_start, new_end, new_label, int(new_enabled), exception_id),
    )
    _arm_relayout(conn)
    return get_numbering_exception(conn, exception_id)


def delete_numbering_exception(conn: Connection, exception_id: int) -> bool:
    cursor = conn.execute("DELETE FROM numbering_exceptions WHERE id = ?", (exception_id,))
    if cursor.rowcount > 0:
        _arm_relayout(conn)
        return True
    return False


def reorder_numbering_exceptions(conn: Connection, ordered_ids: list[int]) -> bool:
    """Persist UI drag order as sort_order (the within-level tie-break)."""
    for position, exception_id in enumerate(ordered_ids):
        conn.execute(
            "UPDATE numbering_exceptions SET sort_order = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (position, int(exception_id)),
        )
    _arm_relayout(conn)
    return True


# =============================================================================
# Resolution
# =============================================================================


class LaneResolver:
    """Resolve channels to lanes from one snapshot of the enabled pins.

    Built once per allocation pass (``LaneResolver.load(conn)``) so resolving
    hundreds of channels costs no queries. ``default`` is the global range lane.
    """

    def __init__(self, exceptions: list[NumberingException], default: Lane):
        self.default = default
        self._exceptions = [e for e in exceptions if e.enabled]
        self._teams: dict[tuple[str, str], list[NumberingException]] = {}
        self._leagues: dict[tuple[str, str], list[NumberingException]] = {}
        self._sports: dict[str, list[NumberingException]] = {}
        for e in self._exceptions:
            sport = (e.sport or "").lower()
            if e.scope == "team" and e.team_name:
                self._teams.setdefault((sport, e.team_name.lower()), []).append(e)
            elif e.scope == "league" and e.league_code:
                self._leagues.setdefault((sport, e.league_code.lower()), []).append(e)
            elif e.scope == "sport":
                self._sports.setdefault(sport, []).append(e)
        for bucket in (self._teams, self._leagues, self._sports):
            for lst in bucket.values():
                lst.sort(key=lambda e: (e.sort_order, e.id))
        # Rows sharing a start collapse to one lane (a group), keyed on the lowest
        # (sort_order, id) row so lane identity is stable whichever member matched.
        by_start: dict[int, Lane] = {}
        for e in sorted(self._exceptions, key=lambda e: (e.start, e.sort_order, e.id)):
            if e.start not in by_start:
                by_start[e.start] = e.lane
        self._lane_by_start = by_start
        self._lanes = [*by_start.values(), default]

    @classmethod
    def load(cls, conn: Connection, default: Lane) -> "LaneResolver":
        return cls(get_numbering_exceptions(conn, enabled_only=True), default)

    @property
    def has_pins(self) -> bool:
        return bool(self._exceptions)

    def lanes(self) -> list[Lane]:
        """Distinct pinned lanes in placement order (ascending start), then default."""
        return list(self._lanes)

    def resolve(
        self,
        sport: str | None,
        league: str | None,
        home_team: str | None = None,
        away_team: str | None = None,
    ) -> Lane:
        """Most-specific-wins lane for one channel; default when nothing matches."""
        if not self._exceptions:
            return self.default
        s = (sport or "").lower()
        candidates: list[tuple[int, int, int, NumberingException]] = []

        def consider(rank: int, lst: list[NumberingException] | None) -> None:
            if lst:
                e = lst[0]
                candidates.append((rank, e.sort_order, e.id, e))

        consider(_RANK_TEAM_HOME, self._teams.get((s, (home_team or "").lower())))
        consider(_RANK_TEAM_AWAY, self._teams.get((s, (away_team or "").lower())))
        consider(_RANK_LEAGUE, self._leagues.get((s, (league or "").lower())))
        consider(_RANK_SPORT, self._sports.get(s))
        if not candidates:
            return self.default
        candidates.sort(key=lambda c: c[:3])
        return self.lane_for(candidates[0][3])

    def lane_for(self, e: NumberingException) -> Lane:
        """The (possibly shared, grouped) lane a pinned-block row belongs to."""
        return self._lane_by_start.get(e.start, e.lane)
