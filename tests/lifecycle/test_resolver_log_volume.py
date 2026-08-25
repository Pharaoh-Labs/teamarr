"""Group resolution is announced once per distinct outcome, not per channel.

`_get_or_create_group` answers from a cache, so the same mapping is re-derived
once per channel — 722 INFO lines in one observed run, 330 of them
character-identical. The distinct mappings are what a reader scans for ("which
group did MLB land in?"); the repeats are noise that costs real signal.

The dedupe must never drop a *distinct* mapping — that is the diagnostic
content — so these pin both halves.
"""

from __future__ import annotations

import logging

import pytest

from teamarr.consumers.lifecycle.dynamic_resolver import DynamicResolver


@pytest.fixture
def captured(monkeypatch):
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("teamarr.consumers.lifecycle.dynamic_resolver")
    monkeypatch.setattr(logger, "handlers", [_Capture()])
    monkeypatch.setattr(logger, "propagate", False)
    logger.setLevel(logging.DEBUG)
    return records


def _resolve(resolver, name, times=1):
    for _ in range(times):
        resolver._log_resolution(
            ("pattern", "Auto | {sport} | {league}", name, 1),
            "[RESOLVER] Pattern mode: %s -> '%s' -> group_id=%s",
            "Auto | {sport} | {league}",
            name,
            1,
        )


def test_every_distinct_mapping_is_announced(captured):
    """The diagnostic content must survive — one INFO per distinct outcome."""
    resolver = DynamicResolver()
    names = [f"Auto | Baseball | {lg}" for lg in ("MLB", "AAA", "AA", "High-A")]
    for name in names:
        _resolve(resolver, name)

    info = [r for r in captured if r.levelno == logging.INFO]
    assert len(info) == len(names)
    announced = {r.getMessage() for r in info}
    for name in names:
        assert any(name in m for m in announced), f"{name} was never announced"


def test_repeats_do_not_reach_info(captured):
    """The 330-identical-lines case."""
    resolver = DynamicResolver()
    _resolve(resolver, "Auto | Baseball | MLB", times=330)

    info = [r for r in captured if r.levelno == logging.INFO]
    debug = [r for r in captured if r.levelno == logging.DEBUG]
    assert len(info) == 1, f"{len(info)} INFO lines for one mapping"
    assert len(debug) == 329, "repeats must still be recoverable at DEBUG"


def test_a_changed_group_id_is_announced_again(captured):
    """The same name resolving somewhere new is a different outcome, and is
    exactly what someone reading the log needs to see."""
    resolver = DynamicResolver()
    for gid in (1, 1, 2):
        resolver._log_resolution(
            ("pattern", "m", "Auto | Baseball | MLB", gid),
            "[RESOLVER] Pattern mode: %s -> '%s' -> group_id=%s",
            "m",
            "Auto | Baseball | MLB",
            gid,
        )

    info = [r for r in captured if r.levelno == logging.INFO]
    assert len(info) == 2, "a new group_id for the same name must be announced"
