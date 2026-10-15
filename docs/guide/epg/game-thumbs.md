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

### Tennis doubles

Game Thumbs addresses a doubles pair with a `+` between the two players
(`/wta/haverlag+radisic/fernandez+tjen/logo.png`). Providers publish a doubles side as a
single `/`-joined name, and the `pascal`/`slug` filters preserve that pairing as `+`, so
the shipped art paths compose **both** players per side with no template changes. Without
the separator Game Thumbs matches the joined string to a single athlete and renders one
player per side.

### Conventions the starter templates use

The shipped [starter templates](../templates/defaults) use these Game Thumbs query parameters:

- `style=1` for team-channel covers, `style=6` for event matchup covers
- `logo=true` to include team logos, `fallback=true` to serve a generic image when a team is unknown
- a `badge=` overlay parameter on event channel logos

### Playoff game badges (opt-in)

To put a `GAME 2` badge on a matchup **channel tile**, add a row to an
**event** template's Conditions tab with **Condition = Playoff/postseason game**
(`is_playoff`). Set **Channel Logo URL Override** to:

```text
{league_code}/{away_team|pascal}/{home_team|pascal}/thumb.png?aspect=16-9&style=6&logo=true&fallback=true&badge={series_game|url}
```

Set **Game-Thumbs Base URL** under EPG → Output first. The `thumb.png` route
provides a wide matchup image for tiles; use `logo.png` instead if your client
expects a square channel logo. For the programme's EPG cover/thumbnail *as well*,
set the row's **Artwork URL Override** to a suitable `thumb.png` or `cover.png`
path with the same `badge={series_game|url}` query parameter. The two overrides
are independent; a programme `<icon>` does not set the channel's icon.

{: .important }
> **Custom text requires a self-hosted Game Thumbs instance with
> `ALLOW_CUSTOM_BADGES=true`.** Game Thumbs' default badge allowlist accepts
> keywords such as `PLAYOFFS` and `4K`, but not `GAME 2`. Without that setting,
> it still serves the image **without** the game-number overlay. The hosted
> instance may not permit custom badges; check your resolved URL in a browser.

For Docker, set `-e ALLOW_CUSTOM_BADGES=true` when starting Game Thumbs (or
`ALLOW_CUSTOM_BADGES: "true"` in its Compose environment). This setting belongs
to the **Game Thumbs container**, not Teamarr.

`{series_game}` is populated only for postseason events whose provider note
includes a game number; for other games it is empty. Teamarr constructs the
URL but does not render the badge or the matchup artwork itself. Starters are
not automatically changed to use custom badges, so existing channel art keeps
working when Game Thumbs runs with its default configuration. The guide's
`LIVE`/`UPCOMING` labels are displayed by the viewing app, not by Game Thumbs.

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
