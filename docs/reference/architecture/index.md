---
title: Architecture
parent: Technical Reference
nav_order: 3
has_children: true
docs_version: "2.3.1"
---

# Architecture

Internal design documentation for Teamarr's backend systems.

| Page | Contents |
|------|----------|
| [API Layer](api-layer) | Route modules, startup flow, generation status, SPA fallback |
| [Consumer Layer](consumer-layer) | Generation workflow, stream matching, channel lifecycle, caching |
| [Headendarr Integration](headendarr-layer) | HTTP client, managers, playlist discovery, XMLTV provisioning, channel sync |
| [Dispatcharr Integration](dispatcharr-layer) | HTTP client, managers, OperationResult pattern, self-healing sync |
| [Detection Keyword Service](detection-keywords) | Stream classification patterns, sport/league hints, multi-sport hints |
| [Database](database) | SQLite schema, settings, channel numbering, database modules |
| [Template Engine](template-engine) | 197 variables, 20 conditions, suffix rules, resolution pipeline |
| [Database Migrations](migrations) | Checkpoint + incremental migration system, schema versioning |
