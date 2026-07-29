# Web UI Redesign — Design

**Date:** 2026-07-29
**Source design:** claude.ai/design project `CENTER-KB UI redesign` (d35a1ec7-d692-4126-b952-d391865da6df), file `CENTER-KB Redesign.dc.html`
**Branch/workspace:** dedicated worktree `ui-redesign`, branched from `main`

## Goal

Replace the current minimal server-rendered web UI (`/ui`) with the approved
redesign: IBM Plex typography, 3-column layout (left rail, main, right rail),
five screens — Overview (new), Search, Documents, Reader, Login — while keeping
the existing auth, routing and hub-read semantics intact.

## Decisions (approved)

| Question | Decision |
|---|---|
| Scope | All 5 screens; Overview gets full data (review queue, store health, last publish) |
| Interactivity | Server-rendered; primary state in URL; one small vanilla JS file, no build step |
| Fonts | Self-hosted IBM Plex Sans + Mono woff2, bundled in the package |
| Responsive | ≥1280px: 3 columns per design; <1280px hide right rail; <~900px hide left rail |
| Templating | Jinja2 (added to the `server` extra), replaces `string.Template` + f-string builders |

## Architecture

```
src/center_kb/
├── templates/web/
│   ├── base.html           # shell: sticky header + 3-column grid
│   ├── overview.html       # NEW
│   ├── search.html
│   ├── docs.html
│   ├── doc.html            # section table + filter + status tabs
│   ├── section.html        # reader, L2/L3 tabs, prev/next
│   ├── login.html          # standalone card, no rails
│   ├── _partials/          # status badge, chip, doc card, result card, rails
│   └── static/
│       ├── style.css       # design tokens as CSS variables + all screen styles
│       ├── app.js          # ⌘K, copy citation, live table filter, compact/expand
│       └── fonts/          # IBM Plex Sans 400/500/600/700, Mono 400/600 (woff2)
└── web/
    ├── ui.py               # route handlers: gather data, render Jinja2
    ├── uidata.py           # NEW: aggregation for Overview and rails
    └── ...
```

- `jinja2` added to the `server` optional-dependency group. Autoescape ON
  (replaces the manual `_e()` escaping).
- Routes keep existing URLs. `/ui` with no query renders **Overview**; with
  `q` or `tags` it renders Search results. Nav "Search" links to `/ui?q=`.
- `/ui/static/*` extended to serve `app.js` and fonts with correct
  content-types.
- Login flow (token form, hmac compare, sliding-window rate limit, cookie) is
  unchanged — markup/style only.
- Left rail (catalog, tags, review-status legend) renders on every page from a
  single context builder; right rail content varies per screen as in the
  design.

## Data flow

`uidata.py` — per-request aggregation from the hub handle + cached manifests:

- `catalog()` — docs with title, revision, section count, summarized/pending
  counts, progress ratio → left rail.
- `all_tags()` — union of manifest tags → left rail.
- `review_queue(limit=8)` — sections with status ≠ reviewed, pending first →
  Overview.
- `store_stats()` — totals: docs, sections, repos, L0 catalog tokens →
  Overview stat cards.
- `store_health()` — lightweight runtime checks only: hub reachable, index
  present, pending count. No heavy verification per request.
- `last_publish()` — hub clone git HEAD via `gitio`; repos list; PR number
  shown only if present in metadata, otherwise the row is hidden.
- `doc_coverage(doc)` — reviewed/summarized/pending breakdown → right rail on
  the doc page.
- `prev_next(manifest, section_id)` — manifest order → reader footer nav.

State in URL (server-rendered, shareable):

- Search: `q`, `tags`, `budget` (range slider submits GET form), `mode`
  (keyword/semantic checkboxes). If the backend cannot split keyword/semantic
  at query time, phase 1 renders the fused (RRF) results as today and the
  checkboxes are deferred — verify during planning.
- Doc: `filter`, `status` are applied live client-side (rows are all rendered;
  JS hides/shows and updates the "N of M shown" label). The URL still accepts
  both params for deep links and no-JS fallback (GET form submit).
- Section: `level=l2|l3`, `repo` — unchanged; tabs are links.

`app.js` (~100 lines, no dependencies):

- ⌘K focuses the header search input.
- Copy citation buttons (right rail + result footer).
- Live section-table filter + status tabs.
- Compact/expand toggle on result cards (CSS 2-line clamp).
- Progressive enhancement: without JS every screen still works — filter falls
  back to GET submit, expand falls back to opening the reader.

## Error handling

- Hub unreachable: header chip flips to a red "hub offline" banner; main shows
  the empty-state; section page returns 503 as today. Overview renders
  whatever parts it can.
- 404 (unknown doc/section) and 400 (ambiguous doc) render inside the new
  shell with breadcrumbs preserved.
- `last_publish()` / `store_health()` failures (e.g. git errors): log a
  warning with context, render "—" in the rail; the page never 500s for rail
  data. No silently swallowed errors.
- Missing static assets: `font-display: swap` falls back to system-ui; the
  no-JS fallback covers a missing `app.js`.
- Login: behavior unchanged; the error banner uses the new design style.

## Testing

pytest, following the existing web test conventions (httpx test client):

- **Unit (`uidata.py`)**: catalog / review_queue / doc_coverage / store_stats /
  prev_next against manifest fixtures; `last_publish` with mocked `gitio`;
  `store_health` when the hub is down.
- **Routes**: each screen returns 200 and contains its key markers (h1,
  status badge, citation); level toggle; filter deep links; 404/400/503;
  login + rate-limit regression tests unchanged.
- **Escaping**: Jinja2 autoescape — titles/summaries containing `<script>`
  must render escaped.
- **Static**: css/js/fonts routes return 200 with correct content-type.
- No screenshot/Playwright harness — route + unit coverage is the repo
  standard.

## Out of scope

- Mobile drawer navigation (basic responsive collapse only).
- Splitting keyword/semantic search modes if the backend cannot do it at
  lookup time (deferred, verified during planning).
- Any change to `/api`, `/mcp`, auth semantics, or hub publish flow.
