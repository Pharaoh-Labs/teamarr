---
title: Bell Media
parent: Providers
grand_parent: Technical Reference
nav_order: 8
---

# Bell Media Provider

Bell Media powers TSN's public scores widgets. Teamarr uses the undocumented,
unauthenticated API for Canadian Football League and selected hockey data.

## API Details

| | |
|---|---|
| **Base URL** | `https://next-gen.sports.bellmedia.ca/v2` |
| **Auth** | None |
| **Priority** | 20 |
| **Supported leagues** | CFL, CHL, OHL, WHL, QMJHL, AHL, PWHL |
| **Rate limit** | None observed. Responses are cached. |

Requests include `brand=tsn` and `lang=en`. The provider uses the league
calendar to resolve a requested date to a weekly or daily schedule group, then filters
that group locally. Event detail uses the numeric TSN event ID. Hockey `seasonTypeId`
values are normalized as preseason (0), regular season (1), and postseason (2).
Competitor responses include `seoIdentifier` but no logo URL, so Teamarr uses the TSN
widget CDN at `https://widgets.sports.bellmedia.ca/img/{league}/{seoIdentifier}.webp`
for team artwork across Bell Media-supported leagues.

Teamarr can optionally route these JSON requests through Settings → Proxy using
a SOCKS5 transport. The direct public API remains the default.

This is an unofficial API discovered from TSN's public scores page. It may
change without notice. The `chl` feed currently covers the Memorial Cup window,
not a full season-wide CHL schedule.

## File Locations

| File | Purpose |
|---|---|
| `teamarr/providers/bellmedia/client.py` | Bell Media HTTP client and cache |
| `teamarr/providers/bellmedia/provider.py` | Bell Media response normalization |
