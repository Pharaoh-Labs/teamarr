"""Tests for the per-source name_match_enabled gate (epic ahow).

A source declares which matching pipeline(s) it runs. When Stream Name matching
is OFF, the matcher must exclude the name-identifies-event categories
(TEAM_VS_TEAM / EVENT_CARD / RACING_EVENT) with reason ``name_match_disabled``,
WITHOUT affecting Team matching (TEAM_ONLY, gated by team_streams_enabled) or the
EPG path (gated by epg_match_enabled). Classification still runs so the other
declared types can use it.
"""

import sqlite3
from datetime import date
from unittest.mock import MagicMock

from teamarr.consumers.matching.matcher import StreamMatcher
from tests.helpers import SCHEMA_PATH

SCHEMA = SCHEMA_PATH
TARGET = date(2026, 6, 16)


def _db_factory():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def _matcher(**flags) -> StreamMatcher:
    return StreamMatcher(
        service=MagicMock(),
        db_factory=_db_factory,
        group_id=1,
        search_leagues=["nfl"],
        include_leagues=["nfl"],
        **flags,
    )


def _reason(matcher, stream_name):
    return matcher._match_single(1, stream_name, TARGET)[0].exclusion_reason


def test_name_off_excludes_team_vs_team():
    m = _matcher(name_match_enabled=False)
    assert _reason(m, "Bills vs Dolphins") == "name_match_disabled"


def test_name_off_excludes_event_card():
    m = _matcher(name_match_enabled=False)
    assert _reason(m, "UFC 300: Jones vs Miocic") == "name_match_disabled"


def test_name_off_team_on_does_not_disable_team_only():
    # A single-team stream must still route to Team matching, not be vetoed by
    # the name gate — the two types are independent.
    m = _matcher(name_match_enabled=False, team_streams_enabled=True)
    assert _reason(m, "NHL | Toronto Maple Leafs") != "name_match_disabled"


def test_name_on_team_off_team_only_still_team_disabled():
    # Unchanged pre-existing behavior: TEAM_ONLY gated by team_streams_enabled.
    m = _matcher(name_match_enabled=True, team_streams_enabled=False)
    assert _reason(m, "NHL | Toronto Maple Leafs") == "team_streams_disabled"


def test_name_on_default_does_not_gate_name():
    # Default (name on): a vs-named stream is NOT excluded by the name gate.
    m = _matcher(name_match_enabled=True)
    assert _reason(m, "Bills vs Dolphins") != "name_match_disabled"


# ---------------------------------------------------------------------------
# >=1 matching type required (ahow.3)
# ---------------------------------------------------------------------------


def test_require_matching_type_rejects_all_off():
    import pytest
    from fastapi import HTTPException

    from teamarr.api.routes.groups import require_matching_type

    with pytest.raises(HTTPException) as exc:
        require_matching_type(False, False, False)
    assert exc.value.status_code == 400


def test_require_matching_type_accepts_any_single():
    from teamarr.api.routes.groups import require_matching_type

    require_matching_type(True, False, False)  # name only
    require_matching_type(False, True, False)  # team only
    require_matching_type(False, False, True)  # epg only
