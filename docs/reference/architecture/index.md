---
title: Architecture
parent: Technical Reference
nav_order: 3
has_children: true
---

# Architecture

Internal design documentation for Teamarr's backend systems.

| Page | Contents |
|------|----------|
| [API Layer](api-layer) | Route modules, startup flow, generation status, SPA fallback |
| [Consumer Layer](consumer-layer) | Generation workflow, stream matching, channel lifecycle, caching |
| [Dispatcharr Integration](dispatcharr-layer) | HTTP client, managers, OperationResult pattern, self-healing sync |
| [Detection Keyword Service](detection-keywords) | Stream classification patterns, sport/league hints, multi-sport hints |
| [Detection Library](detection-library) | Why each event type has its own extraction flow |
| [Database](database) | SQLite schema, settings, database modules |
| [Channel Numbering](channel-numbering) | Lanes: pinned blocks + default range, precedence, stability modes inside lanes, v88 manual-mode migration |
| [Template Engine](template-engine) | Variables, conditions, suffix rules, art-URL reconstruction, resolution pipeline |
| [Gracenote Template Design](gracenote-template-design) | Gracenote-modeled template design, data sources, scoping, fallback |
| [Database Migrations](migrations) | Checkpoint + incremental migration system, schema versioning |
