---
title: Bullpen
parent: Providers
grand_parent: Technical Reference
nav_order: 8
---

# Bullpen Proxy

[Bullpen](https://bullpen.direct) is an optional caching proxy that fronts several of Teamarr's provider upstreams (ESPN, Bell Media, Squiggle, NASCAR, MLB Stats, HockeyTech, TheSportsDB). It is off by default and configured per-provider.

Bullpen is a Teamarr-operated service. When enabled for a provider, it receives that
provider's request path and query parameters, any configured Bullpen API key, and the upstream
response needed to cache and return the request. Do not enable it for traffic you do
not want routed through the service.

## Configuration

Bullpen has its own settings page at `/bullpen` — it has no sidebar entry and must be navigated to directly by URL.

| Setting | Description |
|---|---|
| Enable bullpen proxy | Master switch. Must be on for any per-provider toggle to take effect. |
| API Key | Optional. Sent as the `X-Bullpen-Key` header on proxied requests when configured. Leave it blank for a Bullpen deployment with anonymous access enabled by its administrator. |
| Base URL | Defaults to `https://bullpen.direct`. |
| Per-provider toggles | One switch each for ESPN, Bell Media, Squiggle, NASCAR, MLB Stats, HockeyTech, and TheSportsDB. All default off — enabling bullpen doesn't change any provider's behavior until its own toggle is also flipped. |

Supabase has no bullpen target and is unaffected by these settings.

## Scope

This is JSON API routing only — image/binary CDN traffic (team logos, flags) is not proxied through bullpen in Teamarr today.

## Request shape

When a provider's bullpen toggle is on, its origin base URL is rewritten to `{base_url}/v1/{target}/{path}`, where `path` is the origin URL's path from host root. For example, ESPN's site API (`https://site.api.espn.com/apis/site/v2/sports/...`) becomes `https://bullpen.direct/v1/espn-site/apis/site/v2/sports/...`. Every request also carries the `X-Bullpen-Key` header.

| Provider | Bullpen target(s) |
|---|---|
| ESPN | `espn-site` (site.api.espn.com), `espn-core` (sports.core.api.espn.com — UFC athlete endpoint) |
| Bell Media | `bellmedia` (next-gen.sports.bellmedia.ca; preserves the `/v2` API path) |
| Squiggle | `squiggle` |
| NASCAR | `nascar` |
| MLB Stats | `mlb-stats` |
| HockeyTech | `hockeytech` |
| TheSportsDB | `thesportsdb` |

## TheSportsDB premium equivalence

Enabling bullpen for TheSportsDB is treated as equivalent to holding a [premium key](tsdb#configuration): `is_premium` reports `True` (100 req/min rate limit, full forward guide, working team channels) regardless of whether `tsdb_api_key` is also configured.

## Failure behavior

There is no fallback to the direct origin if a bullpen request fails (rate limit, upstream error, or bullpen itself unreachable) — the request fails like any other failed provider call, subject to the normal retry/backoff behavior in `teamarr/providers/base_client.py`.
