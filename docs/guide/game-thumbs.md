---
title: Game Thumbs
parent: User Guide
nav_order: 9
docs_version: "2.3.0"
---

# Game Thumbs

[Game Thumbs](https://github.com/sethwv/game-thumbs) is an optional external service by [@sethwv](https://github.com/sethwv) for sports matchup thumbnail and logo generation.

Teamarr templates can use Game Thumbs URLs in artwork fields to display matchup images with team logos.

## Base URL setting

Rather than repeating the full Game Thumbs host in every template, set it once in
**EPG → Output → Game Thumbs → Game-Thumbs Base URL** (e.g. `https://game-thumbs.swvn.io`
or a self-hosted `http://<host>:<port>`). The full base — host **and port** — comes
entirely from this setting. Templates then store only the **relative
path** (always starting with `/`):

```
/{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png?style=6&logo=true
```

At EPG generation the base URL is prefixed onto each relative art path. Rules:

- **Relative paths** (start with `/` or a variable) are joined onto the base URL.
- **Absolute URLs** (anything with `http://` / `https://`) are left untouched, so
  you can still hardcode a one-off full URL in a single field.
- Leaving the base URL empty disables prefixing — every art field must then be a
  full URL (legacy behavior).

The live template preview applies the same base URL, so the artwork you see while
editing matches the generated EPG.

{: .note }
**Upgrading?** On first launch after this feature lands, Teamarr inspects your
existing templates: if they share a common Game Thumbs host it's adopted as your
base URL automatically and the template art is converted to relative paths. If
your templates span multiple hosts, the most common one wins and the others stay
as full URLs.

## Resources

- **Documentation**: [game-thumbs-docs.swvn.io](https://game-thumbs-docs.swvn.io)
- **GitHub**: [github.com/sethwv/game-thumbs](https://github.com/sethwv/game-thumbs)

## Options

### Hosted Instances

| URL | User |
|-----|------|
| `https://game-thumbs.swvn.io` | @sethwv |
| `https://sportslogos.jesmann.com` | @jesmannstlPanda |

{: .important }
Hosted instances are community-provided and may have usage limits.

### Self-Hosting

See the [GitHub repository](https://github.com/sethwv/game-thumbs) for self-hosting instructions.
