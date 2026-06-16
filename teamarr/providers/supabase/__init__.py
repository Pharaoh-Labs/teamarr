"""Supabase-backed sports data provider.

Generic provider for leagues whose backend is Supabase. Credentials (URL +
API key) are extracted dynamically from the league's public website so they
never need to be hardcoded. CBL is the first supported league.

Adding a new Supabase-backed league requires only a new row in schema.sql:
    provider = 'supabase'
    provider_league_id = '<website URL to scrape>'
"""

from teamarr.providers.supabase.client import SupabaseLeagueClient
from teamarr.providers.supabase.provider import SupabaseProvider

__all__ = ["SupabaseLeagueClient", "SupabaseProvider"]
