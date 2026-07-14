"""UFC live-sample cascade for the template preview (#260).

Combat previews always fell back to static samples mid-week: candidate
gathering only scanned today/yesterday (cards are ~weekly) and the deep
recent-final lookback explicitly skipped UFC. Now candidates come from one
±7-day range call, and get_recent_final walks back in 35-day windows so the
finished-first strategy works for combat — a final card is the only sample
that populates fight_result/finish_* variables.
"""

from datetime import date, timedelta

from teamarr.providers.espn.provider import ESPNProvider


def _card(event_id: str, name: str, comp_dates: list[str], state: str = "pre") -> dict:
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
                "status": {"type": {"state": state}},
            }
            for d in comp_dates
        ],
    }


class CapturingClient:
    """Fake ESPNClient returning one payload per get_ufc_scoreboard call."""

    def __init__(self, payloads: list[dict | None]):
        self.payloads = payloads
        self.requested_dates: list[str | None] = []

    def get_ufc_scoreboard(self, date_str=None):
        self.requested_dates.append(date_str)
        if not self.payloads:
            return {"events": []}
        return self.payloads.pop(0)


def _window(start: date, end: date) -> str:
    return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"


# ---------------------------------------------------------------------------
# get_sample_candidates
# ---------------------------------------------------------------------------


def test_sample_candidates_single_range_call_no_date_filter():
    # Last Saturday's finished card + next Saturday's scheduled card — neither
    # touches today, both must surface as candidates.
    payload = {
        "events": [
            _card("501", "UFC 331", ["2026-08-01T23:00Z"], state="post"),
            _card("502", "UFC Fight Night", ["2026-08-15T21:00Z"], state="pre"),
        ]
    }
    client = CapturingClient([payload])
    provider = ESPNProvider(client=client)

    events = provider.get_sample_candidates("ufc")

    today = date.today()
    assert client.requested_dates == [
        _window(today - timedelta(days=7), today + timedelta(days=7))
    ]
    assert sorted(e.id for e in events) == ["501", "502"]


def test_sample_candidates_empty_scoreboard():
    provider = ESPNProvider(client=CapturingClient([None]))
    assert provider.get_sample_candidates("ufc") == []


# ---------------------------------------------------------------------------
# get_recent_final
# ---------------------------------------------------------------------------


def test_recent_final_returns_most_recent_finished_card():
    payload = {
        "events": [
            _card("503", "UFC 330", ["2026-07-04T23:00Z"], state="post"),
            _card("504", "UFC Fight Night", ["2026-07-11T21:00Z"], state="post"),
            _card("505", "UFC 332", ["2026-07-18T21:00Z"], state="pre"),
        ]
    }
    client = CapturingClient([payload])
    provider = ESPNProvider(client=client)

    ev = provider.get_recent_final("ufc")

    assert ev is not None
    assert ev.id == "504"  # most recent FINAL; scheduled 505 ignored
    today = date.today()
    assert client.requested_dates == [
        _window(today - timedelta(days=35), today)
    ]


def test_recent_final_walks_back_when_first_window_empty():
    final_payload = {
        "events": [_card("506", "UFC 329", ["2026-05-30T21:00Z"], state="post")]
    }
    client = CapturingClient([{"events": []}, final_payload])
    provider = ESPNProvider(client=client)

    ev = provider.get_recent_final("ufc")

    assert ev is not None and ev.id == "506"
    today = date.today()
    assert client.requested_dates == [
        _window(today - timedelta(days=35), today),
        _window(today - timedelta(days=70), today - timedelta(days=35)),
    ]


def test_recent_final_gives_up_after_three_windows():
    client = CapturingClient([{"events": []}] * 3)
    provider = ESPNProvider(client=client)

    assert provider.get_recent_final("ufc") is None
    assert len(client.requested_dates) == 3
