---
title: EPG
parent: User Guide
nav_order: 6
has_children: true
docs_version: "2.7.0"
---

# EPG

The EPG section is where you shape and produce your guide data. In v2.7.0 the
Templates, Teams, and Output areas were grouped together here, since they all
contribute to the same XMLTV output.

| Area | What it does |
|------|--------------|
| [Templates](templates) | Define how programmes look — titles, descriptions, artwork, fillers, and conditional logic |
| [Teams](teams) | Per-team persistent XMLTV channels for team-based EPG |
| [Output](output) | Generate, download, and monitor your XMLTV output |

## Where to start

- **Shaping guide text and art?** Start with [Templates](templates) and the
  [Variables](variables) and [Conditions](conditions) references.
- **Team-based channels?** See [Teams](teams) for importing teams and assigning
  team templates.
- **Generating and verifying output?** See [Output](output).

Templates split into two types — [Team vs Event](team-vs-event) — depending on
whether you want a persistent per-team channel or dynamic per-game channels. Once
templates are built, you assign them with [Template Assignments](assignments).

Artwork fields can use a shared [Game Thumbs](game-thumbs) base URL so templates
store relative image paths.
