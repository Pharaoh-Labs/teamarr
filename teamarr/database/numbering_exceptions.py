"""Numbering exceptions — pinned channel-number blocks (#333).

A *pinned block* numbers a scope's channels from a fixed start: a team
("Detroit Lions at 800"), a league ("NFL at 1700"), or a sport ("soccer at
1800"). Rows that share ``start`` + ``label`` form a *group* ("Big events" =
World Cup + Olympics at 850). Everything unmatched numbers from the global
channel range — the *default lane*.

Every channel resolves to exactly one lane via :meth:`LaneResolver.resolve`:
most specific wins (home-team pin › away-team pin › league › sport ›
default). Resolution reads only fields that never change during an event, so
a channel's lane is stable for its lifetime.

A pin may carry a *season condition* (#950): it then applies only to events
of that season type ("NBA postseason at 900") and outranks an unconditioned
pin of the same scope; when the season does not match it is skipped and
resolution falls through to the next scope or the default lane. A pin may
also name the output channel group for the channels it holds, which keeps the
number range and the group in step.

A pin may also carry a *segments condition* (session or card-segment codes,
"race, qualifying") and a *feed condition* (main channel, any keyword channel,
any driver or variant race feed, one race feed, or one keyword), both #1018.
A pin with conditions is a candidate only for channels that satisfy every one
of them; a channel with no segment satisfies no segments condition, and a
channel with no feed identity (rows created before the columns) satisfies only
``main`` and ``any``-by-keyword. Within one scope the candidate with the most
conditions wins, then ``(sort_order, id)``; scope rank still comes first. A
pin with no conditions behaves exactly as before.

A start belongs to one block. Two rows may share a start only as members of
the same named group — the lane is keyed on ``start``, so an ungrouped
collision ("Brewers at 550" *and* "MLB at 550") would silently merge into one
block ordered by the normal lineup sort, which is never what the user meant
(they want Priority Teams, or a different start). :func:`add_numbering_exception`
and :func:`update_numbering_exception` raise :class:`StartConflict` instead.

The allocator in :mod:`teamarr.database.channel_numbers` runs the same
placement code (compact / gap / strict) inside each lane. See
``docs/reference/architecture/channel-numbering.md``.
"""

import logging
import re
import sqlite3
from dataclasses import dataclass
from sqlite3 import Connection

logger = logging.getLogger(__name__)

SCOPES = ("team", "league", "sport")
SEASON_TYPES = ("preseason", "regular", "postseason", "offseason")
FEED_KINDS = ("main", "any", "driver", "variant")

_SEGMENT_CODE = re.compile(r"^[a-z0-9_]+$")
_FEED_KEY = re.compile(r"^(driver|variant):[a-z0-9][a-z0-9-]*$")

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
    season_type: str | None = None
    channel_group_id: int | None = None
    channel_group_mode: str | None = None
    segments: list[str] | None = None
    feed: str | None = None

    @property
    def has_channel_group(self) -> bool:
        return self.channel_group_id is not None or bool(self.channel_group_mode)

    @property
    def lane(self) -> Lane:
        return Lane(id=self.id, start=self.start, end=self.end, label=self.label)


_COLUMNS = (
    'id, scope, sport, league_code, team_name, provider, provider_team_id, '
    'start, "end", label, sort_order, enabled, created_at, updated_at, '
    "season_type, channel_group_id, channel_group_mode, segments, feed"
)


def normalize_segments(raw: str | list[str] | None) -> list[str] | None:
    """Segment codes as stored: trimmed, lowercase, deduped in first-seen order.

    Accepts a comma-separated string or a list; empty becomes None (any).
    """
    if raw is None:
        return None
    items = raw.split(",") if isinstance(raw, str) else [str(i) for i in raw]
    seen: list[str] = []
    for item in items:
        code = item.strip().lower()
        if code and code not in seen:
            seen.append(code)
    return seen or None


def normalize_feed(raw: str | None) -> str | None:
    """Feed condition as stored: kinds and prefixes lowercase, a keyword label
    keeps its case. Empty becomes None (any)."""
    value = (raw or "").strip()
    if not value:
        return None
    head, sep, rest = value.partition(":")
    head = head.strip().lower()
    if not sep:
        return head
    rest = rest.strip()
    if head == "feed":
        rest = rest.lower()
    return f"{head}:{rest}"


def _feed_matches(feed: str, exception_keyword: str | None, feed_key: str | None) -> bool:
    """Whether a channel's keyword / race-feed identity satisfies a feed condition."""
    keyword = (exception_keyword or "").strip()
    if feed == "main":
        return not keyword
    if feed == "any":
        return bool(keyword)
    if feed in ("driver", "variant"):
        return bool(feed_key) and feed_key.startswith(f"{feed}:")
    if feed.startswith("feed:"):
        return bool(feed_key) and feed_key == feed[5:]
    if feed.startswith("keyword:"):
        return bool(keyword) and keyword.lower() == feed[8:].lower()
    return False


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
        season_type=row["season_type"] or None,
        channel_group_id=row["channel_group_id"],
        channel_group_mode=row["channel_group_mode"] or None,
        segments=normalize_segments(row["segments"]),
        feed=normalize_feed(row["feed"]),
    )


class StartConflict(ValueError):
    """A block start is already used by another block outside this group."""


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
    """All pinned blocks in placement order (ascending start, then id).

    This is the UI list order too, so the list reads like the effective
    layout: lower starts first, group members adjacent.
    """
    if not _table_exists(conn):
        return []
    where = "WHERE enabled = 1" if enabled_only else ""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM numbering_exceptions {where} "
        "ORDER BY start ASC, sort_order ASC, id ASC"
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


def _validate(
    scope: str,
    start: int,
    end: int | None,
    season_type: str | None = None,
    segments: list[str] | None = None,
    feed: str | None = None,
) -> str | None:
    if scope not in SCOPES:
        return f"invalid scope '{scope}'"
    if season_type is not None and season_type not in SEASON_TYPES:
        return f"invalid season_type '{season_type}'"
    for code in segments or ():
        if not _SEGMENT_CODE.match(code):
            return f"invalid segment '{code}'"
    if feed is not None and not _valid_feed(feed):
        return f"invalid feed '{feed}'"
    if start < 1:
        return "start must be >= 1"
    if end is not None and end < start:
        return "end must be >= start"
    return None


def _valid_feed(feed: str) -> bool:
    if feed in FEED_KINDS:
        return True
    if feed.startswith("feed:"):
        return bool(_FEED_KEY.match(feed[5:]))
    if feed.startswith("keyword:"):
        return bool(feed[8:].strip())
    return False


def _check_start_conflict(
    conn: Connection, start: int, label: str | None, *, exclude_id: int | None = None
) -> None:
    """Raise :class:`StartConflict` unless ``start`` is free or every block
    already at ``start`` is in the same non-empty group ``label``."""
    if not _table_exists(conn):
        return
    rows = conn.execute(
        "SELECT id, scope, sport, league_code, team_name, label FROM numbering_exceptions "
        "WHERE start = ? AND (? IS NULL OR id != ?) ORDER BY id",
        (int(start), exclude_id, exclude_id),
    ).fetchall()
    if not rows:
        return
    label = (label or "").strip()
    if label and all((r["label"] or "").strip().lower() == label.lower() for r in rows):
        return
    r = rows[0]
    holder = r["team_name"] or r["league_code"] or r["sport"] or "another block"
    hint = (
        f'Give it the group name "{r["label"]}" to share that block, '
        if r["label"]
        else "Give both blocks the same group name to share it, "
    )
    raise StartConflict(
        f"Channel {start} already starts the {holder} block. {hint}"
        "pick a different start, or use Priority Teams to put a team first "
        "inside its league's block."
    )


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
    season_type: str | None = None,
    channel_group_id: int | None = None,
    channel_group_mode: str | None = None,
    segments: list[str] | str | None = None,
    feed: str | None = None,
) -> NumberingException | None:
    """Add a pinned block.

    - ``scope='team'``: pass ``provider`` + ``provider_team_id`` (a TeamPicker
      entry); name + sport are resolved from ``team_cache`` so the match key
      stays canonical. ``team_league`` narrows the cache lookup.
    - ``scope='league'``: pass ``league_code`` (+ ``sport`` if known; resolved
      from ``leagues``, then ``league_cache``, otherwise).
    - ``scope='sport'``: pass ``sport``.

    Returns the stored row, or ``None`` on validation / lookup failure.
    Raises :class:`StartConflict` when ``start`` is taken by a block outside
    the group ``label``.
    """
    season_type = (season_type or "").strip().lower() or None
    segment_codes = normalize_segments(segments)
    feed = normalize_feed(feed)
    err = _validate(scope, start, end, season_type, segment_codes, feed)
    if err:
        logger.warning("[NUMBERING_EXC] %s", err)
        return None
    _check_start_conflict(conn, start, label)

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
            # The league dropdown offers configured leagues UNION discovered
            # ones from league_cache (#720), so resolve the sport across both
            # — gating on the leagues table alone rejected every discovered
            # league with "Unknown league (no sport)".
            row = conn.execute(
                """
                SELECT sport FROM leagues WHERE league_code = ?
                UNION ALL
                SELECT sport FROM league_cache WHERE league_slug = ?
                LIMIT 1
                """,
                (league_code, league_code),
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
             start, "end", label, sort_order,
             season_type, channel_group_id, channel_group_mode, segments, feed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scope, sport, league_code, team_name, provider, provider_team_id,
            int(start), int(end) if end is not None else None,
            (label or "").strip() or None, _next_sort_order(conn),
            season_type, channel_group_id, (channel_group_mode or "").strip() or None,
            ",".join(segment_codes) if segment_codes else None, feed,
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
    season_type: str | None | object = ...,
    channel_group_id: int | None | object = ...,
    channel_group_mode: str | None | object = ...,
    segments: list[str] | str | None | object = ...,
    feed: str | None | object = ...,
) -> NumberingException | None:
    """Update a block's range / label / enabled flag / season, segments and
    feed conditions / channel group. Scope and identity are immutable — delete
    and re-add to re-scope. ``end``, ``label``, ``season_type``, ``segments``,
    ``feed`` and the channel group fields accept ``None`` to clear; leave at
    the default sentinel to keep."""
    current = get_numbering_exception(conn, exception_id)
    if current is None:
        return None
    new_start = int(start) if start is not None else current.start
    if end is ...:
        new_end = current.end
    else:
        new_end = int(end) if isinstance(end, int) else None
    if season_type is ...:
        new_season = current.season_type
    else:
        new_season = (season_type.strip().lower() or None) if isinstance(season_type, str) else None
    if segments is ...:
        new_segments = current.segments
    else:
        new_segments = normalize_segments(
            segments if isinstance(segments, (str, list)) else None
        )
    if feed is ...:
        new_feed = current.feed
    else:
        new_feed = normalize_feed(feed) if isinstance(feed, str) else None
    err = _validate(current.scope, new_start, new_end, new_season, new_segments, new_feed)
    if err:
        logger.warning("[NUMBERING_EXC] %s", err)
        return None
    if channel_group_id is ...:
        new_group_id = current.channel_group_id
    else:
        new_group_id = int(channel_group_id) if isinstance(channel_group_id, int) else None
    if channel_group_mode is ...:
        new_group_mode = current.channel_group_mode
    else:
        new_group_mode = (
            (channel_group_mode.strip() or None) if isinstance(channel_group_mode, str) else None
        )
    if label is ...:
        new_label = current.label
    else:
        new_label = (label.strip() or None) if isinstance(label, str) else None
    if new_start != current.start or new_label != current.label:
        _check_start_conflict(conn, new_start, new_label, exclude_id=exception_id)
    new_enabled = current.enabled if enabled is None else bool(enabled)
    conn.execute(
        """
        UPDATE numbering_exceptions
        SET start = ?, "end" = ?, label = ?, enabled = ?,
            season_type = ?, channel_group_id = ?, channel_group_mode = ?,
            segments = ?, feed = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            new_start, new_end, new_label, int(new_enabled),
            new_season, new_group_id, new_group_mode,
            ",".join(new_segments) if new_segments else None, new_feed, exception_id,
        ),
    )
    _arm_relayout(conn)
    return get_numbering_exception(conn, exception_id)


def delete_numbering_exception(conn: Connection, exception_id: int) -> bool:
    cursor = conn.execute("DELETE FROM numbering_exceptions WHERE id = ?", (exception_id,))
    if cursor.rowcount > 0:
        _arm_relayout(conn)
        return True
    return False




# =============================================================================
# Resolution
# =============================================================================


class LaneResolver:
    """Resolve channels to lanes from one snapshot of the enabled pins.

    Built once per allocation pass (``LaneResolver.load(conn)``) so resolving
    hundreds of channels costs no queries. ``default`` is the global range lane.

    Within one precedence level a row is a candidate only if the channel
    satisfies every condition it carries (season #950, segments and feed
    #1018). Among the candidates the row with the most conditions outranks the
    rest, so a season-conditioned pin beats the unconditioned one and a pin
    with segments and a feed beats a pin with either alone. The
    ``(sort_order, id)`` ordering breaks ties, and is the deterministic
    fallback for legacy rows created before starts became unique per group.
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
        season_type: str | None = None,
        segment: str | None = None,
        exception_keyword: str | None = None,
        feed_key: str | None = None,
    ) -> Lane:
        """Most-specific-wins lane for one channel; default when nothing matches."""
        e = self.match(
            sport, league, home_team, away_team, season_type,
            segment, exception_keyword, feed_key,
        )
        return self.lane_for(e) if e is not None else self.default

    def match(
        self,
        sport: str | None,
        league: str | None,
        home_team: str | None = None,
        away_team: str | None = None,
        season_type: str | None = None,
        segment: str | None = None,
        exception_keyword: str | None = None,
        feed_key: str | None = None,
    ) -> NumberingException | None:
        """The pinned-block row a channel resolves to, or None for the default lane.

        ``season_type`` None (unknown) satisfies no season condition, and
        ``segment`` None satisfies no segments condition, so such a channel can
        only land on pins without that condition. ``exception_keyword`` and
        ``feed_key`` identify a keyword channel and, when its keyword came from
        a race feed, the feed.
        """
        if not self._exceptions:
            return None
        s = (sport or "").lower()
        season = (season_type or "").lower() or None
        seg = (segment or "").strip().lower() or None
        candidates: list[tuple[int, int, int, int, NumberingException]] = []

        def consider(rank: int, lst: list[NumberingException] | None) -> None:
            for e in lst or ():
                conditions = 0
                if e.season_type is not None:
                    if e.season_type != season:
                        continue
                    conditions += 1
                if e.segments:
                    if seg is None or seg not in e.segments:
                        continue
                    conditions += 1
                if e.feed is not None:
                    if not _feed_matches(e.feed, exception_keyword, feed_key):
                        continue
                    conditions += 1
                candidates.append((rank, -conditions, e.sort_order, e.id, e))

        consider(_RANK_TEAM_HOME, self._teams.get((s, (home_team or "").lower())))
        consider(_RANK_TEAM_AWAY, self._teams.get((s, (away_team or "").lower())))
        consider(_RANK_LEAGUE, self._leagues.get((s, (league or "").lower())))
        consider(_RANK_SPORT, self._sports.get(s))
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[:4])
        return candidates[0][4]

    def lane_for(self, e: NumberingException) -> Lane:
        """The (possibly shared, grouped) lane a pinned-block row belongs to."""
        return self._lane_by_start.get(e.start, e.lane)
