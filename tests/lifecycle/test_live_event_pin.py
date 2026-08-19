"""Live-event #1 stream pin (#232) — is_channel_event_live unit coverage.

The pin's gate: a channel is protected while its event is airing,
[event_date, scheduled_delete_at]. scheduled_delete_at already encodes the
sessions-aware end estimate + post buffer, so no duration math happens here.
"""

from datetime import UTC, datetime, timedelta

from teamarr.consumers.lifecycle.timing import is_channel_event_live

NOW = datetime(2026, 7, 12, 20, 0, tzinfo=UTC)


def _iso(delta_hours: float) -> str:
    return (NOW + timedelta(hours=delta_hours)).isoformat()


def test_live_inside_window():
    assert is_channel_event_live(_iso(-1), _iso(+2), now=NOW) is True


def test_not_live_before_start():
    assert is_channel_event_live(_iso(+1), _iso(+4), now=NOW) is False


def test_not_live_after_delete_threshold():
    assert is_channel_event_live(_iso(-8), _iso(-1), now=NOW) is False


def test_boundaries_inclusive():
    assert is_channel_event_live(_iso(0), _iso(+3), now=NOW) is True
    assert is_channel_event_live(_iso(-3), _iso(0), now=NOW) is True


def test_no_event_date_is_never_live():
    # Unknown timing must not freeze a channel forever.
    assert is_channel_event_live(None, _iso(+2), now=NOW) is False


def test_missing_delete_at_falls_back_to_six_hours():
    assert is_channel_event_live(_iso(-2), None, now=NOW) is True
    assert is_channel_event_live(_iso(-8), None, now=NOW) is False


def test_naive_strings_assumed_utc():
    naive_start = (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    naive_end = (NOW + timedelta(hours=2)).replace(tzinfo=None).isoformat()
    assert is_channel_event_live(naive_start, naive_end, now=NOW) is True


def test_unparseable_event_date_is_never_live():
    assert is_channel_event_live("not-a-date", _iso(+2), now=NOW) is False


def test_datetime_inputs_accepted():
    assert (
        is_channel_event_live(NOW - timedelta(hours=1), NOW + timedelta(hours=1), now=NOW)
        is True
    )
