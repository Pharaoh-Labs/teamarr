"""Headendarr API client package."""

from teamarr.headendarr.auth import TokenManager
from teamarr.headendarr.client import HeadendarrClient
from teamarr.headendarr.factory import (
    ConnectionTestResult,
    HeadendarrConnection,
    HeadendarrFactory,
    close_headendarr,
    get_factory,
    get_headendarr_connection,
)
from teamarr.headendarr.managers import ChannelManager, EPGManager, PlaylistManager
from teamarr.headendarr.types import (
    HeadendarrChannelSource,
    HeadendarrEPGSource,
    HeadendarrPlaylist,
    HeadendarrStream,
)

__all__ = [
    "ChannelManager",
    "ConnectionTestResult",
    "EPGManager",
    "HeadendarrChannelSource",
    "HeadendarrClient",
    "HeadendarrConnection",
    "HeadendarrEPGSource",
    "HeadendarrFactory",
    "HeadendarrPlaylist",
    "HeadendarrStream",
    "PlaylistManager",
    "TokenManager",
    "close_headendarr",
    "get_factory",
    "get_headendarr_connection",
]
