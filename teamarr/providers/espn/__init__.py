"""ESPN provider package."""

from teamarr.providers.espn.client import COLLEGE_SCOREBOARD_DIVISIONS, ESPNClient
from teamarr.providers.espn.provider import ESPNProvider

__all__ = ["COLLEGE_SCOREBOARD_DIVISIONS", "ESPNClient", "ESPNProvider"]
