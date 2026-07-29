---
title: Examples
parent: EPG
grand_parent: User Guide
nav_order: 5
redirect_from:
  - /guide/templates/examples/
  - /guide/templates/examples.html
---

# Template Examples

Looking for ready-made templates? Start with the shipped [starter set](../templates/defaults) — ten Gracenote-modeled templates seeded on every install. The community templates below predate the starter set but remain available.

## Community Templates by @jesmannstlPanda

Production-ready templates designed to match real Gracenote EPG data as closely as possible, with dynamic artwork via [Game Thumbs](game-thumbs).

- [Download Team Template](../../assets/templates/team-template-jesmannstlpanda.json){: .btn .btn-primary }
- [Download Event Template](../../assets/templates/event-template-jesmannstlpanda.json){: .btn .btn-primary }

{: .note }
> These files predate two newer conventions: they hardcode a `<game-thumbs-base-url>` placeholder in each art field (the current approach is to set the base URL once in **EPG → Output → Game Thumbs** and keep slash-less relative paths in templates — see [Artwork](variables#artwork--game-thumbs)), and they use retired transform variables like `{away_team_pascal}` (still rendered forever via permanent aliases, but the current syntax is `{away_team|pascal}` — see [Filters](variables#filters-transforming-variable-values)).

## Importing and Exporting

1. Download the template JSON file
2. Open the file and replace `<game-thumbs-base-url>` with your Game Thumbs URL (or blank it and rely on the base-URL setting)
3. In Teamarr, go to **EPG → Templates** and click **Import**
4. Select your modified JSON file

Any template can also be **exported** from its row actions on the Templates page — the natural way to share your own or move templates between installs.

## Contributing Templates

Have a template you'd like to share? Join the Dispatcharr Discord and share it in the Teamarr channel.
