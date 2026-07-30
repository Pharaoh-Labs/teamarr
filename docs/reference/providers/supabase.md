---
title: Supabase
parent: Providers
grand_parent: Technical Reference
nav_order: 6
---

# Supabase Provider

The Supabase provider serves leagues whose official websites are backed by a public [Supabase](https://supabase.com/) database — currently the Canadian Baseball League (CBL). No API key or configuration is required: the provider scrapes the league's own website for its Supabase credentials and reads the same data the site itself displays.

## API Details

| | |
|---|---|
| **Base URL** | Per-league Supabase REST endpoint (`https://xxx.supabase.co/rest/v1/`), discovered at runtime |
| **Auth** | None required from the user — public credentials auto-extracted from the league website |
| **Priority** | 55 |
| **Rate Limit** | None observed |

## Supported Leagues

| League | Code | `provider_league_id` |
|--------|------|----------------------|
| Canadian Baseball League | `cbl` | `https://cbl.ca` |

Unlike other providers, the `provider_league_id` in `schema.sql` is the league's **website URL**. The provider fetches that site, locates its Vite JS bundle, and extracts the Supabase project URL and public API key (plus the team logo asset map in the same pass). A second Supabase-backed league needs only a new `leagues` row with `provider='supabase'` and its site URL.

## Credential Extraction & Caching

| Data | Cache TTL |
|------|-----------|
| Extracted credentials + logo map | 7 days (the site's asset hashes change on deploy) |
| Teams | 72 hours |
| Season schedule | 30 minutes |
| Completed games / box scores | 5 minutes (live scores) |

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SUPABASE_TIMEOUT` | `10.0` | HTTP timeout (seconds) |
| `SUPABASE_RETRY_COUNT` | `3` | Retry attempts per request |
| `{LEAGUE_CODE_UPPER}_SUPABASE_URL` | *(unset)* | Override Supabase project URL (e.g. `CBL_SUPABASE_URL`) |
| `{LEAGUE_CODE_UPPER}_SUPABASE_API_KEY` | *(unset)* | Override Supabase API key (e.g. `CBL_SUPABASE_API_KEY`) |

Setting both per-league overrides skips the website scrape entirely.

## Special Behaviors

- **Score merging** — the schedule and completed box scores live in separate tables; scores are joined onto schedule entries by game number (doubleheader-safe), falling back to a `(date, home city, away city)` key.
- **Team resolution** — schedule entries reference teams by city name; hyphenated cities ("Chatham-Kent") and missing-city teams are resolved via fallback keys.
- **Timezone** — CBL schedule times are Eastern (`America/Toronto`).
- **Lookback** — scans 7 days back to resolve `.last` template variables.
- **No stats** — `get_team_stats()` returns nothing; season type is always `regular`.

## File Locations

| File | Purpose |
|------|---------|
| `teamarr/providers/supabase/provider.py` | SupabaseProvider class |
| `teamarr/providers/supabase/client.py` | Credential/logo extraction and Supabase REST client |
