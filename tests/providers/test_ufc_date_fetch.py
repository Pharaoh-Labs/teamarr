"""UFC event fetch must be date-aware (#345).

ESPN's default MMA scoreboard returns ONLY the current featured card, so
get_events("ufc", <any other card's date>) came back empty and those streams
failed with no_event_card_match. The fix passes a ±1-day dates= window and
filters by card coverage (any segment touching target_date), which also
handles PPVs rolling past midnight.
"""

from datetime import date

import pytest

from teamarr.providers.espn.provider import ESPNProvider


def _card(event_id: str, name: str, comp_dates: list[str]) -> dict:
    """Minimal ESPN MMA scoreboard event: one competition per bout time."""
    return {
        "id": event_id,
        "name": name,
        "competitions": [
            {
                "date": d,
                "competitors": [
                    {"athlete": {"displayName": "Fighter A", "shortName": "A"}},
                    {"athlete": {"displayName": "Fighter B", "shortName": "B"}},
                ],
                "status": {"type": {"name": "STATUS_SCHEDULED"}},
            }
            for d in comp_dates
        ],
    }


class CapturingClient:
    """Fake ESPNClient capturing the dates= argument."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.requested_dates: list[str | None] = []

    def get_ufc_scoreboard(self, date_str=None):
        self.requested_dates.append(date_str)
        return self.payload


@pytest.fixture(autouse=True)
def _utc_user_tz(monkeypatch):
    """Pin to_user_tz to identity so assertions are TZ-independent."""
    monkeypatch.setattr(
        "teamarr.providers.espn.provider.to_user_tz", lambda dt: dt
    )


def test_ufc_fetch_passes_date_window():
    client = CapturingClient({"events": []})
    provider = ESPNProvider(client=client)

    provider.get_events("ufc", date(2026, 8, 8))

    assert client.requested_dates == ["20260807-20260809"]


def test_future_card_visible_on_its_date():
    # Fight Night entirely on Aug 8 UTC
    payload = {
        "events": [
            _card(
                "401",
                "UFC Fight Night: Gamrot vs Salkilld",
                ["2026-08-08T16:00Z", "2026-08-08T19:00Z"],
            )
        ]
    }
    provider = ESPNProvider(client=CapturingClient(payload))

    events = provider.get_events("ufc", date(2026, 8, 8))

    assert [e.id for e in events] == ["401"]


def test_midnight_spanning_ppv_covers_both_days():
    # PPV: early prelims 23:00 Aug 8, prelims 00:30 Aug 9, main card 02:00 Aug 9
    payload = {
        "events": [
            _card(
                "402",
                "UFC 330: Someone vs Someone Else",
                ["2026-08-08T23:00Z", "2026-08-09T00:30Z", "2026-08-09T02:00Z"],
            )
        ]
    }
    provider = ESPNProvider(client=CapturingClient(payload))

    assert [e.id for e in provider.get_events("ufc", date(2026, 8, 8))] == ["402"]
    assert [e.id for e in provider.get_events("ufc", date(2026, 8, 9))] == ["402"]
    # But not for an unrelated day
    assert provider.get_events("ufc", date(2026, 8, 11)) == []


def test_unrelated_card_filtered_out():
    # ESPN may return neighbours inside the window — only covering cards pass.
    payload = {
        "events": [
            _card("403", "UFC on ABC", ["2026-08-07T18:00Z"]),
            _card("404", "UFC Fight Night", ["2026-08-08T18:00Z"]),
        ]
    }
    provider = ESPNProvider(client=CapturingClient(payload))

    events = provider.get_events("ufc", date(2026, 8, 8))

    assert [e.id for e in events] == ["404"]
