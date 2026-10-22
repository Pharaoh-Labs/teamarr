"""Run-scoped provider HTTP call counter.

Counts provider API calls per generation run, keyed by ``provider:endpoint``,
so a call-volume regression — the bug class that hid the #254 164x event
refetch for months — becomes a visible metric instead of a silent performance
cliff. Generation surfaces the snapshot in the run summary.

Three outcomes are counted apart (#1127): successful calls, rate-limit hits
(every 429 a provider answered, recovered by a retry or not) and final
failures (a 4xx, retries exhausted on a 5xx/429, a connection error). The
dashboard shows the success total, turns yellow on any rate limit and red on
any failure — the count alone said nothing about whether calls were lost.

Thread-safety: within a run, matching fans out across threads, so increments
take a lock. Generation runs are serialized (the ``BEGIN IMMEDIATE`` lock in
``run_full_generation`` rejects overlapping ``full_epg`` runs), so a single
process-global counter that is :func:`reset` at run start is sufficient —
there is never more than one active run mutating it.
"""

from __future__ import annotations

import threading
from collections import Counter

_lock = threading.Lock()
_calls: Counter[str] = Counter()
_rate_limits: Counter[str] = Counter()
_failures: Counter[str] = Counter()


def _endpoint_label(value: str) -> str:
    """Reduce a URL or path to a low-cardinality endpoint label.

    Strips any query string and returns the last *non-numeric* path segment, so
    ``.../basketball/nba/summary?event=1`` -> ``summary`` and a resource URL like
    ``.../teams/8`` -> ``teams`` instead of exploding into one label per id.
    Falls back to the whole (trimmed) value when there is no path separator.
    """
    path = value.split("?", 1)[0].rstrip("/")
    if "/" not in path:
        return path or "request"
    for segment in reversed(path.split("/")):
        if segment and not segment.isdigit():
            return segment
    return "request"


def record_call(provider: str, endpoint: str) -> None:
    """Count one successful provider HTTP call.

    ``endpoint`` may be a bare label (e.g. ``"summary"``) or a URL/path — the
    latter is reduced to its last path segment so cardinality stays low.
    """
    label = _endpoint_label(endpoint)
    with _lock:
        _calls[f"{provider}:{label}"] += 1


def record_rate_limit(provider: str, endpoint: str) -> None:
    """Count one 429 answer, whether or not a later retry recovers the call."""
    label = _endpoint_label(endpoint)
    with _lock:
        _rate_limits[f"{provider}:{label}"] += 1


def record_failure(provider: str, endpoint: str, reason: str) -> None:
    """Count one call that returned nothing after all retries.

    ``reason`` is the HTTP status (``"404"``, ``"503"``, ``"429"``) or a short
    word for a transport failure (``"connection"``). Retries of one request
    are one failure — the caller records only when it gives up.
    """
    label = _endpoint_label(endpoint)
    with _lock:
        _failures[f"{provider}:{label}:{reason}"] += 1


def reset() -> None:
    """Clear all counts. Call at the start of each generation run."""
    with _lock:
        _calls.clear()
        _rate_limits.clear()
        _failures.clear()


def snapshot() -> dict[str, int]:
    """Return current success counts, ordered high to low."""
    with _lock:
        return dict(_calls.most_common())


def total() -> int:
    """Return the total number of successful provider calls this run."""
    with _lock:
        return sum(_calls.values())


def rate_limits_snapshot() -> dict[str, int]:
    """Return rate-limit hits per ``provider:endpoint``, ordered high to low."""
    with _lock:
        return dict(_rate_limits.most_common())


def failures_snapshot() -> dict[str, int]:
    """Return final failures per ``provider:endpoint:reason``, high to low."""
    with _lock:
        return dict(_failures.most_common())
