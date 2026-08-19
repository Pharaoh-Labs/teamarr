---
title: Game Thumbs
parent: EPG
grand_parent: User Guide
nav_order: 9
redirect_from:
  - /guide/game-thumbs/
  - /guide/game-thumbs.html
---

# Game Thumbs

[Game Thumbs](https://github.com/sethwv/game-thumbs) is an optional external service by [@sethwv](https://github.com/sethwv) for sports matchup thumbnail and logo generation.

Teamarr templates can use Game Thumbs URLs in artwork fields to display matchup images with team logos.

## Setting it up

Set the host once in **EPG → Output → Game Thumbs → Game-Thumbs Base URL** (e.g. `https://game-thumbs.swvn.io` or a self-hosted `http://<host>:<port>`), and keep **slash-less relative paths** in your templates:

```
{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true
```

The full path-joining rules (what counts as relative, why paths must not start with `/`, filters, URL-encoding) are in [Artwork & Game Thumbs](variables#artwork--game-thumbs) — they apply identically here.

The base URL is applied uniformly to all three art sinks — the EPG `<icon>`, the Dispatcharr channel logo, and filler art — so guide artwork and channel logos always match. Prefixing is idempotent and self-repairing: applying it twice never double-prefixes, and older values corrupted into `/https://…` form are fixed automatically.

### Conventions the starter templates use

The shipped [starter templates](../templates/defaults) use these Game Thumbs query parameters:

- `style=1` for team-channel covers, `style=6` for event matchup covers
- `logo=true` to include team logos, `fallback=true` to serve a generic image when a team is unknown
- a `badge=` overlay parameter on event channel logos

## Resources

- **Documentation**: [game-thumbs-docs.swvn.io](https://game-thumbs-docs.swvn.io)
- **GitHub**: [github.com/sethwv/game-thumbs](https://github.com/sethwv/game-thumbs)

## Options

### Hosted Instances

| URL | User |
|-----|------|
| `https://game-thumbs.swvn.io` | @sethwv |

{: .important }
Hosted instances are community-provided and may have usage limits.

### Self-Hosting

See the [GitHub repository](https://github.com/sethwv/game-thumbs) for self-hosting instructions.
