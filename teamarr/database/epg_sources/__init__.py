"""External EPG sources database module.

Separate SQLite database (epg_sources.db) for managing external XMLTV
EPG sources and their stream mappings. Isolated from the main teamarr.db
for easy upstream merge management.
"""

from .connection import get_epg_sources_db, init_epg_sources_db

__all__ = ["get_epg_sources_db", "init_epg_sources_db"]
