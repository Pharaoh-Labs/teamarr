"""FastAPI dependencies for dependency injection."""

from functools import lru_cache

from teamarr.providers.espn import ESPNProvider
from teamarr.services import SportsDataService


@lru_cache
def get_sports_service() -> SportsDataService:
    """Get singleton SportsDataService with providers configured."""
    service = SportsDataService()
    service.add_provider(ESPNProvider())
    return service
