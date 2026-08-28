---
title: Bell Media
parent: Providers
grand_parent: Technical Reference
nav_order: 8
---

# Bell Media Provider

Bell Media powers TSN's public scores widgets. Teamarr uses the undocumented,
unauthenticated API for Canadian Football League data.

## API Details

| | |
|---|---|
| **Base URL** | `https://next-gen.sports.bellmedia.ca/v2` |
| **Auth** | None |
| **Priority** | 20 |
| **Supported league** | CFL (`cfl`) |
| **Rate limit** | None observed. Responses are cached. |

Requests include `brand=tsn` and `lang=en`. The provider uses the league
calendar to resolve a requested date to a weekly schedule group, then filters
that group locally. Event detail uses the numeric TSN event ID.

Teamarr can optionally route these JSON requests through the [Bullpen](bullpen)
proxy's `bellmedia` target. This preserves the `/v2` path and adds Bullpen's
`X-Bullpen-Key` header; the direct public API remains the default.

This is an unofficial API discovered from TSN's public scores page. It may
change without notice. OHL and PWHL remain on HockeyTech because it provides
their established schedule and postseason metadata.

## File Locations

| File | Purpose |
|---|---|
| `teamarr/providers/bellmedia/client.py` | Bell Media HTTP client and cache |
| `teamarr/providers/bellmedia/provider.py` | CFL response normalization |
