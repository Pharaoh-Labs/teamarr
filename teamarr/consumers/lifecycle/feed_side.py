"""Resolve which side of an event a stream's feed belongs to (#533).

The side is a **tri-state**: ``"home"``, ``"away"``, or ``None`` meaning
UNKNOWN. ``None`` is a real answer, not a fallback — it covers three genuinely
different situations, none of which may be coerced into a side:

1. **Undeterminable** — a feed team resolved but matches neither side.
2. **Not told** — the stream carries no feed signal at all (national
   broadcasts, generic listings). This is the common case, not the edge case.
3. **Not applicable** — racing, combat, and individual sports have no home/away
   at all, so a stream there can legitimately carry a team and no side.

Nothing downstream may reach ``"away"`` by failing to prove ``"home"``. Callers
branch on three cases; consumers that can't represent unknown must say so
explicitly (ordering rules don't match it, labels render nothing) rather than
guessing.

Resolved once here, at creation time, where the event is in scope — then
persisted on ``managed_channel_streams.feed_side`` and read as a plain lookup.
"""

from __future__ import annotations

from teamarr.core import Event

HOME = "home"
AWAY = "away"

# The only values that may ever be persisted. UNKNOWN is the absence of a
# value (NULL / None), deliberately not a sentinel string — a sentinel invites
# equality checks that quietly treat it as a fourth side.
VALID_SIDES = frozenset({HOME, AWAY})


def resolve_feed_side(
    event: Event | None,
    feed_hint: str | None = None,
    matched_side: str | None = None,
    feed_team_id: str | None = None,
) -> str | None:
    """Resolve a stream's feed side, or None when unknown.

    Cascade, most explicit signal first:

    1. ``feed_hint`` — an explicit HOME/AWAY marker detected in the stream name
       (``classifier.detect_and_strip_feed_hint``).
    2. ``matched_side`` — the event side of the matched team, set for TEAM_ONLY
       matches (#489). Present even when no team object resolved.
    3. Derivation — ``feed_team_id`` compared against the event's two sides.

    Args:
        event: The event this stream is attached to (None → unknown)
        feed_hint: "home"/"away" from stream-name feed markers, else None
        matched_side: "home"/"away" for TEAM_ONLY matches, else None
        feed_team_id: Resolved feed team's provider id, else None

    Returns:
        "home", "away", or None when the side is unknown. Never guesses.
    """
    if feed_hint in VALID_SIDES:
        return feed_hint
    if matched_side in VALID_SIDES:
        return matched_side

    if event is None or not feed_team_id:
        return None

    # Neutral-site games keep the provider's nominal home designation (#533
    # design D3): we were told a side, so reporting it is fidelity, not
    # inference. Only a team matching neither side yields unknown.
    home_team = getattr(event, "home_team", None)
    if home_team is not None and home_team.id == feed_team_id:
        return HOME
    away_team = getattr(event, "away_team", None)
    if away_team is not None and away_team.id == feed_team_id:
        return AWAY
    return None
