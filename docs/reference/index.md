---
title: Technical Reference
nav_order: 3
has_children: true
docs_version: "2.3.1"
---

# Technical Reference

Developer documentation covering Teamarr's architecture, data providers, database, and deployment configuration.

## Sections

| Section | Contents |
|---------|----------|
| [Supported Leagues](supported-leagues) | All 132 pre-configured leagues and ~250 discovered soccer leagues, organized by sport |
| [Providers](providers/) | Data provider system — ESPN, Squiggle, MLB Stats, HockeyTech, TheSportsDB, Supabase — priority chain, API details, rate limiting |
| [Architecture](architecture/) | API layer, consumer layer, Dispatcharr integration, detection keywords, database, template engine, migrations |
| [Frontend](frontend/) | React + TypeScript + Vite architecture, component library, state management |
| [Deployment](deployment/) | Environment variables, Docker configuration, logging |

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLite (WAL mode) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Query |
| Providers | ESPN (primary), Squiggle (AFL), MLB Stats, HockeyTech, TheSportsDB (fallback) |
