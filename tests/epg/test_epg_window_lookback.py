"""One lookback for every match method (#744).

The name matcher has always looked back ``MATCH_WINDOW_DAYS`` (30) so past
games keep feeding stats. The EPG programme window was meant to mirror it but
read the retired ``event_match_days_back`` column (default 7) instead, so the
two paths silently disagreed and the column — invisible in the UI and API since
January 2026 — still steered one of them. The window now derives from the same
constant and the column is unread.
"""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from teamarr.consumers.event_group_processor import matching as matching_mod
from teamarr.consumers.event_group_processor.matching import StreamMatching
from teamarr.consumers.matching import MATCH_WINDOW_DAYS
from teamarr.consumers.matching.epg_index import EPGProgramIndex

TARGET = date(2026, 9, 10)
UTC = ZoneInfo("UTC")


class _Harness(StreamMatching):
    def __init__(self):
        self._dispatcharr_client = SimpleNamespace(epg=object())

    def _epg_resolution_inputs(self):
        return SimpleNamespace(
            epg_data_list=[],
            stream_channels={},
            active_source_ids=set(),
            channel_by_uuid={},
            own_source_id=None,
            catalog=None,
        )


def _capture_window(monkeypatch):
    seen: dict[str, datetime] = {}

    def fake_build(_epg, _resolution, window_start, window_end):
        seen["start"], seen["end"] = window_start, window_end
        return EPGProgramIndex({})

    monkeypatch.setattr(EPGProgramIndex, "build", staticmethod(fake_build))
    monkeypatch.setattr(
        "teamarr.consumers.matching.epg_resolver.resolve_program_tvg_ids",
        lambda *a, **k: ({"espn.us": "1"}, None),
    )
    monkeypatch.setattr(matching_mod, "get_user_timezone", lambda: UTC)
    return seen


def test_epg_programme_window_looks_back_match_window_days(monkeypatch):
    seen = _capture_window(monkeypatch)
    group = SimpleNamespace(id=1, epg_match_enabled=True)

    _Harness()._build_epg_index(group, [{"tvg_id": "espn.us"}], TARGET, 3)

    day_start = datetime.combine(TARGET, time.min, tzinfo=UTC)
    assert seen["start"] == day_start - timedelta(days=MATCH_WINDOW_DAYS)
    assert seen["end"] == day_start + timedelta(days=3 + 1)
    assert MATCH_WINDOW_DAYS == 30


def test_settings_query_no_longer_reads_the_retired_column():
    import inspect

    # A quoted occurrence is SQL or a row lookup; the comment naming the
    # retired column is allowed to stay.
    source = inspect.getsource(StreamMatching)
    assert '"event_match_days_back' not in source
    assert "event_match_days_back," not in source
