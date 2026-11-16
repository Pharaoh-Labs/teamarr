"""Summary-endpoint odds survive ESPN's reshaped competition odds block (#1228).

ESPN reshaped the NFL summary's ``header.competitions[0].odds`` (early Nov 2026):
the flat ``details`` / ``spread`` / ``overUnder`` / ``provider.name`` fields
``_parse_odds`` reads moved under ``current.*`` and only the moneylines stayed
top-level — a truthy-but-hollow block. The same response still carries a full
``pickcenter`` entry with the flat shape, but the old conversion only fired when
``competition.odds`` was absent, so the hollow block won and the matching phase's
``refresh_event_status`` overlay (truthy-replaces-falsy) then clobbered the
scoreboard's complete odds on every generation — NFL channel names and EPG
rendered blank odds while college (unreshaped summary) kept working.

Fixture: live capture of a Monday-night NFL summary (trimmed to the keys
``get_event`` reads; propBets truncated — shape, not content).
"""

import json
import os
from unittest.mock import MagicMock

from teamarr.providers.espn.provider import ESPNProvider

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "espn_nfl_summary_odds_reshape_2026.json"
)


def _summary_provider(payload: dict) -> ESPNProvider:
    provider = ESPNProvider(client=MagicMock())
    provider._client.get_event.return_value = payload
    return provider


def _load_fixture() -> dict:
    with open(FIXTURE) as f:
        return json.load(f)


def _flat_competition_odds() -> list[dict]:
    """The pre-reshape shape: flat line fields at the top of the entry."""
    return [
        {
            "provider": {"name": "ESPN BET"},
            "details": "BUF -6.5",
            "spread": -6.5,
            "overUnder": 44.5,
            "homeTeamOdds": {"moneyLine": -280},
            "awayTeamOdds": {"moneyLine": 230},
        }
    ]


class TestReshapedSummaryPrefersPickcenter:
    def test_reshaped_nfl_summary_yields_full_odds(self):
        event = _summary_provider(_load_fixture()).get_event("401873065", "nfl")

        assert event is not None
        odds = event.odds_data
        assert odds, "odds_data must not be None"
        # The flat line fields come from pickcenter, not the hollow block.
        assert odds["details"] == "BAL -4.5"
        assert odds["over_under"] == 38.5
        assert odds["provider"] == "DraftKings"
        assert odds["spread"] == -4.5
        # Moneylines agree across both blocks.
        assert odds["home_moneyline"] == -225
        assert odds["away_moneyline"] == 185

    def test_flat_competition_odds_are_kept_over_pickcenter(self):
        payload = _load_fixture()
        competition = payload["header"]["competitions"][0]
        competition["odds"] = _flat_competition_odds()

        event = _summary_provider(payload).get_event("401873065", "nfl")

        assert event.odds_data["provider"] == "ESPN BET"
        assert event.odds_data["details"] == "BUF -6.5"

    def test_hollow_competition_odds_with_no_pickcenter_stay_moneyline_only(self):
        # No lines posted yet: pickcenter empty, competition block hollow.
        # Nothing richer exists, so the moneyline-only parse is the best truth.
        payload = _load_fixture()
        payload["pickcenter"] = []

        event = _summary_provider(payload).get_event("401873065", "nfl")

        odds = event.odds_data
        assert odds is not None
        assert odds["details"] == ""
        assert odds["over_under"] == 0.0
        assert odds["home_moneyline"] == -225

    def test_absent_competition_odds_fall_back_to_pickcenter(self):
        # The original conversion: pickcenter used when the block is absent.
        payload = _load_fixture()
        del payload["header"]["competitions"][0]["odds"]

        event = _summary_provider(payload).get_event("401873065", "nfl")

        assert event.odds_data["details"] == "BAL -4.5"


class TestParseOddsOnReshapedBlock:
    def test_reshaped_block_parses_moneyline_only(self):
        # Pins what the reshaped competition block alone yields, so a further
        # upstream reshape is visible in the diff rather than silent.
        reshaped = _load_fixture()["header"]["competitions"][0]["odds"]
        odds = ESPNProvider(client=MagicMock())._parse_odds(reshaped)

        assert odds is not None
        assert odds["details"] == ""
        assert odds["over_under"] == 0.0
        assert odds["home_moneyline"] == -225
        assert odds["away_moneyline"] == 185

    def test_odds_entry_hollowness_is_judged_on_details_and_over_under(self):
        assert ESPNProvider._odds_entry_has_lines(_flat_competition_odds()) is True

        hollow = [{"provider": {"name": "DraftKings"}, "spread": 0.0}]
        assert ESPNProvider._odds_entry_has_lines(hollow) is False
        assert ESPNProvider._odds_entry_has_lines([]) is False
