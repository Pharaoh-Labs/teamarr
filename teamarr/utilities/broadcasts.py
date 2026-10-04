"""Facts read off an event's broadcast listing."""

from typing import Any

LOCAL_MARKETS = ("home", "away")


def has_local_broadcast(event: Any) -> bool | None:
    """Whether the event lists a home- or away-market broadcaster (#539).

    Providers tag each broadcaster as national or home/away market. A game
    whose listing carries no home- or away-market name is one neither team's
    own broadcast is showing: the exclusive national games where a
    team-branded stream is dark. The check is deliberately "either side":
    providers sometimes file both local broadcasters under one side, or omit
    one team's, so a single missing side says nothing.

    Returns None when the listing carries no market tags at all (a provider
    without them, or a summary-format payload): unknown, never "no".
    """
    markets = getattr(event, "broadcast_markets", None) or {}
    if not markets:
        return None
    return any(market in LOCAL_MARKETS for market in markets.values())
