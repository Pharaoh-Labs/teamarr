"""Keyword ordering swaps a channel at most once per pass (Pharaoh-Labs/teamarr#1119).

`KeywordOrderingEnforcer.enforce()` reads every (main, keyword) pair once. If a
channel appears in two pairs, the second swap works from numbers the first swap
already changed, and two channels end on one number. A channel must take part
in at most one swap per pass; the next run finishes the rest.
"""

from unittest.mock import MagicMock

import pytest

from teamarr.consumers.enforcement.ordering import KeywordOrderingEnforcer
from teamarr.database.connection import get_db, init_db
from teamarr.dispatcharr.types import OperationResult

GROUP_ID = 999992


def _seed(conn, rows):
    """rows: (id, number, keyword or None). Dispatcharr id = 1000 + id."""
    for cid, number, keyword in rows:
        conn.execute(
            """INSERT INTO managed_channels
               (id, event_id, event_provider, tvg_id, event_epg_group_id,
                channel_name, channel_number, dispatcharr_channel_id,
                exception_keyword)
               VALUES (?, 'evt-1', 'espn', ?, ?, ?, ?, ?, ?)""",
            (cid, f"tvg-{cid}", GROUP_ID, f"Chan {cid}", number, 1000 + cid, keyword),
        )
    conn.commit()


@pytest.fixture
def make_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) "
            f"VALUES ({GROUP_ID}, 'test-one-swap', '[\"nfl\"]')"
        )
        conn.commit()

    def seed(rows):
        with get_db() as conn:
            _seed(conn, rows)

    return seed


def _numbers() -> list[int]:
    """Channel numbers ordered by managed channel id."""
    with get_db() as conn:
        return [
            int(r["channel_number"])
            for r in conn.execute("SELECT channel_number FROM managed_channels ORDER BY id")
        ]


def _enforcer() -> KeywordOrderingEnforcer:
    manager = MagicMock()
    manager.update_channel.return_value = OperationResult(success=True)
    return KeywordOrderingEnforcer(db_factory=get_db, channel_manager=manager)


def _run_passes(n: int) -> list[list[int]]:
    seen = []
    for _ in range(n):
        _enforcer().enforce()
        seen.append(_numbers())
    return seen


def test_one_main_two_keywords_never_share_a_number(make_db):
    """Main 10, keywords 5 and 6: stock code ends with both keywords on 10."""
    make_db([(1, 10, None), (2, 5, "spanish"), (3, 6, "french")])

    _enforcer().enforce()
    after_one = _numbers()

    assert len(set(after_one)) == 3, f"two channels share a number: {after_one}"
    assert after_one == [5, 10, 6]


def test_four_mains_one_keyword_never_share_a_number(make_db):
    """Live shape (2026-10-13): four mains 31003-31006, one Spanish keyword 31002.

    Stock code put all four mains on 31002.
    """
    make_db(
        [
            (1, 31003, None),
            (2, 31004, None),
            (3, 31005, None),
            (4, 31006, None),
            (5, 31002, "spanish"),
        ]
    )

    passes = _run_passes(6)

    for numbers in passes:
        assert len(set(numbers)) == 5, f"two channels share a number: {numbers}"
    assert passes[0] == [31002, 31004, 31005, 31006, 31003]
    assert passes[-1] == [31002, 31003, 31004, 31005, 31006], "later passes finish the order"


def test_one_main_four_keywords_never_share_a_number(make_db):
    """Main 31006 above keywords 31002-31005: stock code put four keywords on 31006."""
    make_db(
        [
            (1, 31006, None),
            (2, 31002, "a"),
            (3, 31003, "b"),
            (4, 31004, "c"),
            (5, 31005, "d"),
        ]
    )

    passes = _run_passes(6)

    for numbers in passes:
        assert len(set(numbers)) == 5, f"two channels share a number: {numbers}"
    assert passes[-1][0] == 31002, "main ends on the lowest number"


def test_settled_order_is_not_touched(make_db):
    make_db([(1, 10, None), (2, 11, "spanish")])

    result = _enforcer().enforce()

    assert result.reordered_count == 0
    assert _numbers() == [10, 11]
