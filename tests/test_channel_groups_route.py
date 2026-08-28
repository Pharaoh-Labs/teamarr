"""channel-groups endpoint: the with_channels variant (#631).

The channel-source picker must list the groups that hold channels, NOT the
groups without an M3U association. Dispatcharr writes ``m3u_accounts`` for any
group name a playlist carries, so the old exclude_m3u filter hid groups users
had curated channels into. Tests drive the route function directly.
"""

from types import SimpleNamespace

import pytest

import teamarr.api.routes.dispatcharr as route
from teamarr.dispatcharr.types import DispatcharrChannelGroup


def _conn(groups: list[DispatcharrChannelGroup], counts: dict[int, int], seen: dict):
    def list_groups(exclude_m3u: bool = False):
        seen["exclude_m3u"] = exclude_m3u
        return groups

    return SimpleNamespace(
        m3u=SimpleNamespace(list_groups=list_groups),
        channels=SimpleNamespace(
            count_channels_by_group=lambda exclude_channel_ids=None: counts
        ),
    )


CURATED = DispatcharrChannelGroup(id=1, name="SPORTS - CA", m3u_accounts=(7,))
CUSTOM = DispatcharrChannelGroup(id=2, name="SPORTS - CFL")
PROVIDER_ONLY = DispatcharrChannelGroup(id=3, name="US | ENTERTAINMENT", m3u_accounts=(7,))


@pytest.fixture
def patched(monkeypatch):
    seen: dict = {}

    def _install(groups, counts):
        monkeypatch.setattr(
            route,
            "get_dispatcharr_connection",
            lambda db_factory=None: _conn(groups, counts, seen),
        )
        monkeypatch.setattr(route, "managed_channel_ids", lambda db_factory: {900})
        return seen

    return _install


def test_m3u_associated_group_is_listed_when_it_holds_channels(patched):
    # The bug: SPORTS - CA carries an m3u_accounts link (a playlist has a group
    # by that name) but the user curates channels into it — it must be offered.
    patched([CURATED, CUSTOM, PROVIDER_ONLY], {1: 14, 2: 3})
    result = route.list_channel_groups(with_channels=True)

    assert [g["name"] for g in result] == ["SPORTS - CA", "SPORTS - CFL"]
    assert result[0]["channel_count"] == 14
    assert result[0]["from_m3u"] is True


def test_groups_without_channels_are_dropped(patched):
    patched([CURATED, PROVIDER_ONLY], {1: 14})
    result = route.list_channel_groups(with_channels=True)
    assert [g["id"] for g in result] == [1]


def test_with_channels_ignores_exclude_m3u(patched):
    # exclude_m3u defaults to True; with_channels must not honour it.
    seen = patched([CURATED], {1: 2})
    assert len(route.list_channel_groups(exclude_m3u=True, with_channels=True)) == 1
    assert seen["exclude_m3u"] is False


def test_zero_count_is_dropped_not_reported(patched):
    patched([CURATED], {1: 0})
    assert route.list_channel_groups(with_channels=True) == []


def test_default_variant_keeps_exclude_m3u_behaviour(patched):
    # Other pickers (output, per-league) are unchanged: no channel_count, and
    # filtering stays with m3u.list_groups(exclude_m3u=...).
    seen = patched([CURATED, CUSTOM], {})
    result = route.list_channel_groups()
    assert seen["exclude_m3u"] is True
    assert [g["name"] for g in result] == ["SPORTS - CA", "SPORTS - CFL"]
    assert "channel_count" not in result[0]
