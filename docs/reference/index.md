---
title: Technical Reference
nav_order: 3
has_children: true
---

# Technical Reference

Developer documentation covering Teamarr's architecture, data providers, database, and deployment configuration.

## Sections

| Section | Contents |
|---------|----------|
| [Supported Leagues](supported-leagues) | All 170 pre-configured leagues and the discovered soccer leagues, organized by sport |
| [Providers](providers/) | Data provider system — ESPN, Squiggle, NASCAR, MLB Stats, HockeyTech, Supabase, TheSportsDB — priority chain, API details, rate limiting |
| [Architecture](architecture/) | API layer, consumer layer, Dispatcharr integration, detection keywords, database, template engine, migrations |
| [Deployment](deployment/) | Environment variables, Docker configuration, logging |
| [Frontend](frontend/) | React + TypeScript + Vite architecture, component library, state management |

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLite (WAL mode) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Query |
| Providers | ESPN (primary) plus six specialty providers — see [Providers](providers/) |
