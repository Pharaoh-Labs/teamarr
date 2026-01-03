"""Cricbuzz data provider package.

Scrapes cricket data from Cricbuzz.com for leagues like IPL, CPL, BPL, BBL.
Used as an alternative to TSDB for cricket leagues.
"""

from teamarr.providers.cricbuzz.client import CricbuzzClient
from teamarr.providers.cricbuzz.provider import CricbuzzProvider

__all__ = ["CricbuzzClient", "CricbuzzProvider"]
