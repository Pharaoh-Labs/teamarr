"""Stream-profile precedence for Dispatcharr channel-source streams."""

from types import SimpleNamespace

from teamarr.consumers.lifecycle.stream_profiles import resolve_channel_stream_profile


def test_top_active_stream_without_override_uses_global_default(monkeypatch):
    monkeypatch.setattr(
        "teamarr.consumers.lifecycle.stream_profiles.get_channel_streams",
        lambda conn, channel_id: [
            SimpleNamespace(attach_at=None, detach_at=None, dispatcharr_channel_group_id=1),
            SimpleNamespace(attach_at=None, detach_at=None, dispatcharr_channel_group_id=2),
        ],
    )
    monkeypatch.setattr(
        "teamarr.consumers.lifecycle.stream_profiles.get_epg_settings",
        lambda conn: SimpleNamespace(
            stream_profile_overrides=[
                {
                    "target_type": "dispatcharr_channel_group",
                    "target_id": 2,
                    "stream_profile_id": 99,
                }
            ]
        ),
    )

    assert resolve_channel_stream_profile(None, 1, 10) == 10


def test_top_active_stream_override_wins(monkeypatch):
    monkeypatch.setattr(
        "teamarr.consumers.lifecycle.stream_profiles.get_channel_streams",
        lambda conn, channel_id: [
            SimpleNamespace(attach_at=None, detach_at=None, dispatcharr_channel_group_id=1),
            SimpleNamespace(attach_at=None, detach_at=None, dispatcharr_channel_group_id=2),
        ],
    )
    monkeypatch.setattr(
        "teamarr.consumers.lifecycle.stream_profiles.get_epg_settings",
        lambda conn: SimpleNamespace(
            stream_profile_overrides=[
                {
                    "target_type": "dispatcharr_channel_group",
                    "target_id": 1,
                    "stream_profile_id": 20,
                },
                {
                    "target_type": "dispatcharr_channel_group",
                    "target_id": 2,
                    "stream_profile_id": 99,
                },
            ]
        ),
    )

    assert resolve_channel_stream_profile(None, 1, 10) == 20
