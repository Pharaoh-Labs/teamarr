---
title: Frontend
parent: Technical Reference
nav_order: 5
has_children: false
docs_version: "2.3.1"
---

# Frontend Architecture

React 19 + TypeScript + Vite single-page application with TanStack Query for server state and Tailwind CSS v4 for styling.

## Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19.x | UI framework |
| TypeScript | 5.9 | Type safety |
| Vite | 7.x | Build tool + dev server (port 5173) |
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
└── lib/                 # Utility functions
```

## Pages

All pages are lazy-imported in `App.tsx`:

As of v2.7.0 the IA follows the user flow: Connect → Sources → Subscriptions → EPG → Matching → Channels. Old routes (`/event-groups`, `/teams`, `/templates`, `/detection-library`, `/custom-leagues`) redirect to their new homes.

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/` | Status strip, generation trigger, run history |
| EventGroups (Sources) | `/sources`, `/sources/new`, `/sources/:id`, `/sources/import` | Source list, editor, bulk import (formerly Event Groups) |
| Subscriptions | `/subscriptions` | League/sport subscription; custom leagues at `/subscriptions/leagues` |
| DetectionLibrary (Matching) | `/matching` | Keywords, team aliases, separators, EPG-match tuning |
| Templates | `/epg/templates`, `/epg/templates/new`, `/epg/templates/:id` | Template list and editor with variable picker |
| Teams | `/epg/teams`, `/epg/teams/import` | Team list, management, bulk import |
| EpgOutput | `/epg/output` | Output path/window, default durations, XMLTV metadata |
| Channels | `/channels/lifecycle`, `/consolidation`, `/numbering`, `/stream-priority`, `/output` | Channel lifecycle, consolidation, numbering, stream priority, Dispatcharr output |
| Settings | `/settings` | System/integration tabs (General, Dispatcharr, Media Servers, Advanced) |

## API Client Pattern

`api/client.ts` provides a typed HTTP client:

```typescript
const API_BASE = "/api/v1"

export const api = {
  get<T>(path: string): Promise<T>,
  post<T>(path: string, data?): Promise<T>,
  put<T>(path: string, data): Promise<T>,
  patch<T>(path: string, data?): Promise<T>,
  delete<T>(path: string): Promise<T>,
}
```

One API module per domain (teams, templates, groups, channels, settings, etc.) with type definitions and async functions wrapping `api.get/post/put/delete`.

## State Management

| Approach | Used For |
|----------|----------|
| TanStack Query | Server state (data fetching, caching, invalidation) |
| React Context | Generation progress (SSE polling + cancellation) |
| localStorage | Theme preference (dark/light) |
| React hooks | Local form state |

Query client defaults: `staleTime: 1min`, `retry: 1`.

## Key Components

### UI Primitives (`components/ui/`)

Generic building blocks: button, input, dialog, card, table, tooltip, badge, checkbox, switch, label, select.

### Feature Components

| Component | Purpose |
|-----------|---------|
| `LeaguePicker` | League selection with sport grouping and logos |
| `SoccerModeSelector` | Soccer-specific league/team picker |
| `VariablePicker` | Template variable browser with auto-completion |
| `CheckboxListPicker` | Searchable multi-select with grouping |
| `SelectedBadges` | Badge overflow with "+N more" tooltip (maxBadges=10) |
| `ChannelProfileSelector` | Dispatcharr channel profile picker |
| `StreamProfileSelector` | Dispatcharr stream profile picker |
| `RunHistoryTable` | Shared EPG run history (Dashboard + EPG page) |
| `SortPriorityManager` | Drag-drop priority editor |
| `VirtualizedTable` | Large dataset rendering |

## Theme System

CSS custom properties in oklch color space, defined in `index.css`:

- **Dark theme** (default) + **Light theme** toggled via `html.dark`/`html.light`
- Tokens: `background`, `foreground`, `primary`, `secondary`, `muted`, `accent`, `destructive`, `success`, `warning`, `error`, `info`

## Development

```bash
npm run dev    # Vite dev server on :5173, proxies /api → :9195
npm run build  # TypeScript check + production build → dist/
```

The Vite dev proxy forwards `/api/*` and `/health` to the backend at `localhost:9195`. Use `:5173` during development for hot-reload.

## Build Output

```
dist/index.html           ~0.7 KB
dist/assets/index-*.css   ~66 KB (gzip: ~12 KB)
dist/assets/index-*.js    ~859 KB (gzip: ~232 KB)
```

Content-hash filenames for HTTP cache-busting. Single-chunk build (no code splitting beyond lazy routes).
