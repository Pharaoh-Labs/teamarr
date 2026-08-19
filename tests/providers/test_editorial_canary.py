"""ESPN editorial-field drift canary (#375 gap 2, #506).

The editorial features are empty-safe: a renamed scoreboard key makes them go
dark silently. The canary counts key PRESENCE (not value truthiness) across
eligible events and warns once per field when a sustained sample carries zero.
"""

import logging

import pytest

from teamarr.providers.espn.editorial_canary import EditorialDriftCanary

HEALTHY = {"neutralSite": False, "notes": [], "headlines": [], "altGameNote": ""}


def _feed(canary, competition, n, *, sport="football", is_final=False):
    for _ in range(n):
        canary.record(competition, sport=sport, is_final=is_final)


class TestEditorialDriftCanary:
    def test_healthy_payloads_never_warn(self, caplog):
        canary = EditorialDriftCanary()
        with caplog.at_level(logging.WARNING):
            _feed(canary, HEALTHY, 600, is_final=True)
            _feed(canary, HEALTHY, 400, sport="soccer", is_final=True)
        assert not caplog.records

    def test_empty_values_count_as_present(self):
        # Presence is the signal — empty notes/headlines are normal and must
        # not trip the canary even at scale.
        canary = EditorialDriftCanary()
        _feed(canary, HEALTHY, 1000, sport="soccer", is_final=True)
        assert not canary._warned

    def test_renamed_structural_key_warns_at_threshold(self, caplog):
        canary = EditorialDriftCanary()
        dropped = {k: v for k, v in HEALTHY.items() if k != "neutralSite"}
        with caplog.at_level(logging.WARNING):
            _feed(canary, dropped, 499)
            assert not caplog.records  # below threshold: silent
            _feed(canary, dropped, 1)
        assert any("neutralSite" in r.message for r in caplog.records)

    def test_warns_only_once_per_field(self, caplog):
        canary = EditorialDriftCanary()
        dropped = {k: v for k, v in HEALTHY.items() if k != "notes"}
        with caplog.at_level(logging.WARNING):
            _feed(canary, dropped, 2000)
        assert sum("notes" in r.message for r in caplog.records) == 1

    def test_single_presence_disarms_field(self, caplog):
        # One real sighting proves the key still exists — no warning even if
        # the rest of a large sample lacks it.
        canary = EditorialDriftCanary()
        dropped = {k: v for k, v in HEALTHY.items() if k != "notes"}
        canary.record(HEALTHY, sport="football", is_final=False)
        with caplog.at_level(logging.WARNING):
            _feed(canary, dropped, 2000)
        assert not any("notes" in r.message for r in caplog.records)

    def test_headlines_only_counts_finals(self, caplog):
        # Scheduled events don't carry Recap headlines — they must not build
        # toward the headlines threshold.
        canary = EditorialDriftCanary()
        dropped = {k: v for k, v in HEALTHY.items() if k != "headlines"}
        with caplog.at_level(logging.WARNING):
            _feed(canary, dropped, 5000, is_final=False)
        assert not caplog.records
        assert canary._eligible["headlines"] == 0

    def test_alt_game_note_only_counts_soccer(self, caplog):
        canary = EditorialDriftCanary()
        dropped = {k: v for k, v in HEALTHY.items() if k != "altGameNote"}
        with caplog.at_level(logging.WARNING):
            _feed(canary, dropped, 5000, sport="football", is_final=True)
        assert not any("altGameNote" in r.message for r in caplog.records)
        assert canary._eligible["altGameNote"] == 0
        with caplog.at_level(logging.WARNING):
            _feed(canary, dropped, 300, sport="soccer", is_final=True)
        assert any("altGameNote" in r.message for r in caplog.records)


class TestProviderIntegration:
    @pytest.fixture
    def provider(self):
        from teamarr.providers.espn.provider import ESPNProvider

        return ESPNProvider(client=object())  # client unused by _parse_event

    def _scoreboard_event(self, **competition_extra):
        competition = {
            "date": "2026-07-20T00:00Z",
            "competitors": [
                {"homeAway": "home", "team": {"displayName": "A"}, "score": "1"},
                {"homeAway": "away", "team": {"displayName": "B"}, "score": "2"},
            ],
            "status": {"type": {"state": "post", "detail": "Final"}},
            **competition_extra,
        }
        return {
            "id": "401",
            "name": "A vs B",
            "date": "2026-07-20T00:00Z",
            "competitions": [competition],
        }

    def test_parse_event_records_presence(self, provider):
        event = self._scoreboard_event(neutralSite=False, notes=[])
        parsed = provider._parse_event(event, "nfl")
        assert parsed is not None
        canary = provider._editorial_canary
        assert canary._eligible["neutralSite"] == 1
        assert canary._present["neutralSite"] == 1
        assert canary._present["notes"] == 1
        # Keys absent from this payload counted eligible but not present
        assert canary._present["headlines"] == 0
