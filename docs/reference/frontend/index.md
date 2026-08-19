---
title: Frontend
parent: Technical Reference
nav_order: 5
has_children: false
---

# Frontend Architecture

React 19 + TypeScript + Vite single-page application with TanStack Query for server state and Tailwind CSS v4 for styling.

## Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19.x | UI framework |
| TypeScript | 5.9 | Type safety |
| Vite | 8.x | Build tool + dev server (port 5173) |
| TanStack Query | 5.x | Server state, caching, mutations |
| TanStack Virtual | 3.x | Virtualized lists/tables |
| Tailwind CSS | 4.x | Utility-first styling |
| React Router | 7.x | Client-side routing |
| Radix UI | Tooltips | Accessible tooltip primitives |
| Lucide React | Icons | Icon library |
| Sonner | Toasts | Toast notifications |

## Project Structure

```
frontend/src/
├── App.tsx              # Routes, lazy loading, providers
├── main.tsx             # Entry point
├── index.css            # Tailwind config, theme variables
├── pages/               # Page components (one per route)
├── components/          # Reusable components
│   └── ui/              # Generic primitives (button, dialog, input, etc.)
├── api/                 # API client modules (one per domain)
├── hooks/               # Custom hooks (queries, mutations, utilities)
├── contexts/            # React Context providers
├── layouts/             # Layout wrappers (MainLayout with sidebar)
├── lib/                 # Utility functions
└── utils/               # Additional shared utilities
```

## Pages

All pages are lazy-imported in `App.tsx`:

As of v2.7.0 the IA follows the user flow: Connect → Sources → Subscriptions → EPG → Matching → Channels. Old routes (`/event-groups`, `/teams`, `/templates`, `/detection-library`, `/custom-leagues`, plus `/epg` and `/epg/assignments`) redirect to their new homes.

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/` | Status strip, generation trigger, run history |
| EventGroups (Sources) | `/sources`, `/sources/new`, `/sources/:id`, `/sources/import` | Source list, editor, bulk import (formerly Event Groups) |
| Subscriptions | `/subscriptions` | League/sport subscription incl. custom leagues (`/subscriptions/leagues` redirects here) |
| DetectionLibrary (Matching) | `/matching` | Keywords, team aliases, separators, EPG-match tuning |
| Templates | `/epg/templates`, `/epg/templates/new`, `/epg/templates/:id` | Template list and editor with variable picker |
| Teams | `/epg/teams`, `/epg/teams/import` | Team list, management, bulk import |
| EpgOutput | `/epg/output` | Output path/window, default durations, XMLTV metadata |
| Channels | `/channels/lifecycle`, `/channels/consolidation`, `/channels/numbering`, `/channels/stream-priority`, `/channels/output` | Channel lifecycle, consolidation, numbering, stream priority, Dispatcharr output |
| Settings | `/settings` | System/integration tabs (General, Dispatcharr, Media Servers, Advanced) |

## API Client Pattern

`api/client.ts` provides a typed HTTP client (`api.get/post/put/patch/delete` against `/api/v1`). One API module per domain (teams, templates, groups, channels, settings, etc.) with type definitions and async functions wrapping the client.

## State Management

| Approach | Used For |
|----------|----------|
| TanStack Query | Server state (data fetching, caching, invalidation) |
| React Context | Generation progress (SSE polling + cancellation) |
| localStorage | Theme preference (dark/light) |
| React hooks | Local form state |

Query client defaults: `staleTime: 1min`, `retry: 1`.

## Key Components

The listings below are a representative subset — `components/`, `hooks/`, and `api/` each contain many more modules than are listed here.

### UI Primitives (`components/ui/`)

Generic building blocks: button, input, dialog, card, table, tooltip, badge, checkbox, switch, label, select, checkbox-list-picker (searchable multi-select with grouping), selected-badges (badge overflow with "+N more" tooltip), and more.

### Feature Components

| Component | Purpose |
|-----------|---------|
| `LeaguePicker` | League selection with sport grouping and logos |
| `SoccerModeSelector` | Soccer-specific league/team picker |
| `VariableSidebar` | Template variable browser (`pages/template-form/VariableSidebar.tsx`) |
| `ChannelProfileSelector` | Dispatcharr channel profile picker |
| `StreamProfileSelector` | Dispatcharr stream profile picker |
| `RunHistoryTable` | Shared EPG run history (Dashboard + EPG page) |
| `SortPriorityManager` | Drag-drop priority editor |
| `VirtualizedTable` | Large dataset rendering |
| `EventMatcherModal` | Manual stream-to-event match correction (Dashboard + EPG pages) |
| `TestPatternsModal/` | Custom regex pattern tester |
| `ChannelsLayout` / `ChannelsSubNav` | Channels section layout + sub-navigation |
| `EpgLayout` / `EpgSubNav` | EPG section layout + sub-navigation |

## Theme System

CSS custom properties in oklch color space, defined in `index.css`:

- **Dark theme** (default) + **Light theme** toggled via `html.dark`/`html.light`
- Tokens: `background`, `foreground`, `primary`, `secondary`, `muted`, `accent`, `destructive`, `success`, `warning`, `error`, `info`

## Development

```bash
npm run dev    # Vite dev server on :5173, proxies /api → :9195
npm run build  # TypeScript check + production build → dist/
```

The Vite dev proxy forwards `/api/*` and `/health` to the backend at `localhost:9195`. Use `:5173` during development for hot-reload. Production builds emit content-hash filenames for HTTP cache-busting.
