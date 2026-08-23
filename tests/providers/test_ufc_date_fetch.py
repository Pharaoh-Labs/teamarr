"""UFC event fetch must be date-aware (#345, #590).

ESPN's default MMA scoreboard returns ONLY the current featured card, so
get_events("ufc", <any other card's date>) came back empty and those streams
failed with no_event_card_match. The fix passes a ±1-day dates= window.

Since #590 the provider returns everything in that window as a SUPERSET —
segment-aware day membership (a PPV rolling past midnight belongs to both
days) is decided by the user-day window at the service seam, not here.
"""

from datetime import date

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


def test_windowed_cards_pass_through_as_superset():
    """Everything ESPN returns for the ±1-day window comes back (#590).

    The neighbouring card is no longer dropped here — exact day membership
    (including midnight-spanning PPV coverage) is the service seam's job,
    pinned in tests/services/test_event_date_seam.py.
    """
    payload = {
        "events": [
            _card("403", "UFC on ABC", ["2026-08-07T18:00Z"]),
            _card(
                "402",
                "UFC 330: Someone vs Someone Else",
                ["2026-08-08T23:00Z", "2026-08-09T00:30Z", "2026-08-09T02:00Z"],
            ),
        ]
    }
    provider = ESPNProvider(client=CapturingClient(payload))

    events = provider.get_events("ufc", date(2026, 8, 8))

    assert [e.id for e in events] == ["403", "402"]
