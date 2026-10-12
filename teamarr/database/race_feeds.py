"""Race feeds: per-league driver and feed-variant rows on the exception-keyword engine (#245).

A race weekend's providers carry many simultaneous views of one session —
per-driver onboards, pit lane, driver tracker, timing, team radio. Each is
exactly the shape an exception keyword already handles (Sub-Consolidate = its
own channel per event/session keyed on the label; Ignore = dropped), so these
rows are keywords with three extra properties:

* **league-scoped** — a driver surname is somebody else's team elsewhere;
* **managed** — the label and terms come from the provider roster and are
  refreshed with the cache, while ``behavior``/``enabled`` stay the user's;
* **default Ignore** — no onboard reaches a channel until the user picks it.

Precedence at check time is race feeds first (more specific), then the
global exception keywords — see ``teamarr.database.channels.keywords``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Literal

from unidecode import unidecode

from teamarr.database.exception_keywords import ExceptionKeyword

logger = logging.getLogger(__name__)

FeedKind = Literal["driver", "variant"]
FeedBehavior = Literal["consolidate", "separate", "ignore"]

# The feed-variant vocabulary. Measured over a 121,957-stream install
# (2026-09-12): tracker 107, mixed 99, timing/data 94, pit lane 94,
# on-board 111. Six words; providers phrase them a handful of ways.
VARIANT_FEEDS: tuple[tuple[str, str, str], ...] = (
    # (feed_key suffix, label, match terms)
    ("pit-lane", "Pit Lane", "Pit Lane, Pitlane, Bonus Pit Lane"),
    ("driver-tracker", "Driver Tracker", "Driver Tracker, Tracker"),
    ("timing", "Timing", "Timing Channel, Live Timing, Data Channel, Driver Data, F1-DATA"),
    ("mixed-onboard", "Mixed Onboard", "Mixed On-Board, Mixed Onboard, Mixed On Board"),
    ("team-radio", "Team Radio", "Team Radio"),
    # Generic onboard with no driver named (Viaplay: "Onboard | Motorsport").
    # Listed LAST so a driver row wins for any stream that names one.
    ("onboard", "Onboard", "On-Board Camera, Onboard, On-Board, On Board"),
)


@dataclass
class RaceFeed:
    id: int | None
    league: str
    feed_key: str
    kind: FeedKind
    label: str
    match_terms: str
    behavior: FeedBehavior = "ignore"
    enabled: bool = True
    managed: bool = True
    last_seen: datetime | None = None
    created_at: datetime | None = None

    @property
    def match_term_list(self) -> list[str]:
        return [t.strip() for t in self.match_terms.split(",") if t.strip()]

    def as_keyword(self) -> ExceptionKeyword:
        """The keyword the channel creator/enforcer/EPG writer understand."""
        return ExceptionKeyword(
            id=self.id,
            label=self.label,
            match_terms=self.match_terms,
            behavior=self.behavior,
            enabled=self.enabled,
            created_at=self.created_at,
        )


@dataclass(frozen=True)
class RosterEntry:
    """One driver as a provider reports it — the input to ``upsert_roster``."""

    name: str  # "Charles Leclerc"
    short_name: str | None = None  # "C. Leclerc"
    code: str | None = None  # "LEC"
    logo_url: str | None = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", unidecode(text).lower()).strip("-")


def driver_feed_key(name: str) -> str:
    return f"driver:{_slug(name)}"


def driver_match_terms(entry: RosterEntry) -> str:
    """Every form a provider writes a driver in, accented and plain.

    Captured shapes: ``On-Board Camera: Charles Leclerc``, ``- Charles
    Leclerc (English)``, ``Ferrari: Charles Leclerc``, ``ESTEBAN OCON: HAAS
    F1 TEAM: OCO``, ``LEC - LECLERC FERRARI``. The keyword matcher is
    word-bounded and case-insensitive but keeps accents, so ``Pérez`` and
    ``Perez`` are both listed.
    """
    terms: list[str] = []

    def add(term: str | None) -> None:
        for form in (term, unidecode(term) if term else None):
            if form and form.strip() and form.strip() not in terms:
                terms.append(form.strip())

    add(entry.name)
    parts = entry.name.split()
    if len(parts) >= 2:
        add(" ".join(parts[1:]))  # surname(s): "Leclerc", "Sainz Jr."
    add(entry.short_name)
    if entry.code and len(entry.code) == 3:
        add(entry.code.upper())
    return ", ".join(terms)


def _row(row) -> RaceFeed:
    def ts(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    return RaceFeed(
        id=row["id"],
        league=row["league"],
        feed_key=row["feed_key"],
        kind=row["kind"],
        label=row["label"],
        match_terms=row["match_terms"],
        behavior=row["behavior"],
        enabled=bool(row["enabled"]),
        managed=bool(row["managed"]),
        last_seen=ts(row["last_seen"]),
        created_at=ts(row["created_at"]),
    )


def list_race_feeds(
    conn: Connection, league: str | None = None, include_disabled: bool = True
) -> list[RaceFeed]:
    sql = "SELECT * FROM race_feeds"
    where: list[str] = []
    params: list = []
    if league:
        where.append("league = ?")
        params.append(league)
    if not include_disabled:
        where.append("enabled = 1")
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Drivers before variants, then insertion order: a driver row must win
    # over the generic "Onboard" row for a stream that names the driver.
    sql += " ORDER BY CASE kind WHEN 'driver' THEN 0 ELSE 1 END, id"
    return [_row(r) for r in conn.execute(sql, params).fetchall()]


def race_feed_keywords(conn: Connection, league: str | None) -> list[ExceptionKeyword]:
    """Enabled race feeds for ``league`` as keywords, in precedence order."""
    if not league:
        return []
    return [feed.as_keyword() for feed in list_race_feeds(conn, league, include_disabled=False)]


def race_feed_leagues(conn: Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT league FROM race_feeds ORDER BY league")]


def get_race_feed(conn: Connection, feed_id: int) -> RaceFeed | None:
    row = conn.execute("SELECT * FROM race_feeds WHERE id = ?", (feed_id,)).fetchone()
    return _row(row) if row else None


def update_race_feed(
    conn: Connection,
    feed_id: int,
    *,
    behavior: FeedBehavior | None = None,
    enabled: bool | None = None,
) -> RaceFeed | None:
    """Change the user-owned fields. Label/terms belong to the refresh."""
    sets: list[str] = []
    params: list = []
    if behavior is not None:
        sets.append("behavior = ?")
        params.append(behavior)
    if enabled is not None:
        sets.append("enabled = ?")
        params.append(1 if enabled else 0)
    if sets:
        params.append(feed_id)
        conn.execute(f"UPDATE race_feeds SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
    return get_race_feed(conn, feed_id)


def set_behavior_for_kind(
    conn: Connection, league: str, kind: FeedKind, behavior: FeedBehavior
) -> int:
    cur = conn.execute(
        "UPDATE race_feeds SET behavior = ? WHERE league = ? AND kind = ?",
        (behavior, league, kind),
    )
    conn.commit()
    return cur.rowcount


def upsert_roster(conn: Connection, league: str, roster: list[RosterEntry]) -> dict:
    """Write the provider roster plus the variant vocabulary for ``league``.

    Managed rows get their label/terms/last_seen replaced; ``behavior`` and
    ``enabled`` are never touched, so a driver the user switched on stays on
    across a refresh. Rows for drivers no longer on the roster are kept (a
    mid-season substitute comes and goes; the user's choice should not) but
    stop being refreshed, which ``last_seen`` makes visible.
    """
    now = datetime.now(UTC).isoformat()
    inserted = updated = 0

    def write(feed_key: str, kind: str, label: str, terms: str) -> None:
        nonlocal inserted, updated
        cur = conn.execute(
            """UPDATE race_feeds
               SET label = ?, match_terms = ?, last_seen = ?
               WHERE league = ? AND feed_key = ? AND managed = 1""",
            (label, terms, now, league, feed_key),
        )
        if cur.rowcount:
            updated += 1
            return
        conn.execute(
            """INSERT OR IGNORE INTO race_feeds
               (league, feed_key, kind, label, match_terms, behavior, enabled, managed, last_seen)
               VALUES (?, ?, ?, ?, ?, 'ignore', 1, 1, ?)""",
            (league, feed_key, kind, label, terms, now),
        )
        inserted += 1

    for entry in roster:
        write(driver_feed_key(entry.name), "driver", entry.name, driver_match_terms(entry))
    for suffix, label, terms in VARIANT_FEEDS:
        write(f"variant:{suffix}", "variant", label, terms)
    conn.commit()
    logger.info(
        "[RACE_FEEDS] %s: %d drivers, %d inserted, %d updated",
        league,
        len(roster),
        inserted,
        updated,
    )
    return {"league": league, "drivers": len(roster), "inserted": inserted, "updated": updated}
