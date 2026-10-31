# Hub web UI on phones, foldables and iPads — design

Date: 2026-10-31
Status: draft, awaiting owner approval
Mockup: https://claude.ai/artifact/GqpPZMv9vLGjmEfUfKcU5v (option B chosen)

## 1. Intent

The owner wants the hub web UI (`/ui`, `src/strata_kb/templates/web/`) to
work well in the mobile browser of flagship phones, of foldables (Samsung
Galaxy Z Fold / Flip, Apple's foldable), and of every iPad size, with **every
feature the desktop web has**. It stays a website opened in the browser (no
installable app). The owner's bar: "not ugly, good UX".

Today the UI has a `viewport` meta but only two breakpoints, and both hide
features instead of moving them:

- below 1280px, `.rail-right` is `display: none`: the page's table of
  contents, citation + copy button, doc coverage, overview store health /
  last publish, and **the search page's token-budget slider and semantic
  toggle** are unreachable. That covers every iPad in portrait and most iPads
  in landscape.
- below 900px, `.rail-left` is `display: none` too: the main navigation
  (Overview, Document, Ticket, Code, Q&A, Registry, Sign in), the tag filter
  and the section tree are gone. **On a phone you cannot navigate.**
- the 56px top bar packs search, up to 5 status chips and Sign out into one
  row; it overflows at phone widths.
- the section table (`.sec-grid`, `min-width: 720px`) and the registry table
  (`.reg-grid`, `min-width: 760px`) scroll sideways.

## 2. Goals

- Every feature reachable on desktop is reachable at every width from 320px
  up: navigation, global search, tag filter, section tree + filter, page
  context (TOC, citation copy, coverage, store health, publish info, search
  filters), every form (login, setup, ticket release, registry add / remove /
  auto-merge), status chips, Sign in / Sign out.
- Phone-class widths (below 900px) use the owner's chosen pattern, **option
  B**: a bottom tab bar for the main menus plus bottom sheets for what the
  rails hold today.
- The layout follows the CSS viewport width, not the device model, so
  folding / unfolding a Fold or rotating an iPad re-lays the page live.
- No page body scrolls sideways at any width. Only code blocks, markdown
  tables and mermaid diagrams may scroll inside their own box (as today).
- Touch-friendly: tap targets at least 44×44 CSS px on touch screens; inputs
  at least 16px font on touch screens so iOS Safari does not zoom on focus;
  content and fixed bars clear the notch / Dynamic Island / home indicator.

## 3. Non-goals

- No PWA: no manifest, service worker, "add to home screen" or standalone
  mode. The owner said browser only.
- No dark theme. The hub UI is light-only today; this work keeps that.
- No new features, routes or API changes. Only layout, CSS, templates and a
  small amount of progressive JS.
- No gestures beyond what is listed here (no swipe between tabs, no
  pull-to-refresh).

## 4. Anti-goals (failure even if it "works")

- **Desktop changes.** At 1280px and wider the UI must look and behave as it
  does today.
- **Feature drift.** Any rail content duplicated into a separate mobile copy
  that can fall out of sync with the desktop copy.
- **Hidden features.** Anything left as `display: none` at some width with no
  other way to reach it.
- **JS-only access.** Every feature must still work with JavaScript off
  (`app.js` header: "every page works without this file").
- **Inline scripts.** CSP is `script-src 'self'` (`web/headers.py`); all JS
  goes in `static/app.js`. Inline `style=` and `<noscript><style>` are allowed
  (`style-src 'self' 'unsafe-inline'`).

## 5. Constraints

- Server-rendered Jinja (`web/templating.py`), one stylesheet
  (`static/style.css`, 416 lines), one script (`static/app.js`, 266 lines),
  IBM Plex fonts and the existing color tokens. Keep that design system.
- No new dependencies.
- `tests/test_web_ui.py::test_left_rail_is_288px` asserts the CSS contains
  `grid-template-columns: 288px` exactly twice. Update that assertion if the
  breakpoint rewrite changes the count; keep its intent (rail stays 288px).
- Tests slice `<main>` to avoid matching rail markup (`test_web_ui.py:20`).
  New shell markup (tab bar, sheets) must sit outside `<main>`.
- `.topbar` has `backdrop-filter`, which makes it the containing block for
  `position: fixed` descendants. Sheets and the scrim must **not** live inside
  `.topbar`.
- Supported browsers: current iOS / iPadOS Safari, Samsung Internet, Chrome
  on Android, plus the desktop browsers supported today. Safari < 16 must
  still work (`app.js` already has fallbacks for it).

## 6. Approaches considered

1. **One markup, CSS gives the rails a second role (chosen).** Below the
   breakpoint the existing `<aside class="rail-left">` and
   `<aside class="rail-right">` stop being `display: none` and become bottom
   sheets (`position: fixed`, slide up from the bottom). A tab-bar partial is
   added to `base.html`; ~40–80 lines in `app.js` open and close sheets.
   Rail content renders once, so mobile can never drift from desktop. Cost:
   one sheet per rail, so the section page gets two triggers (**Sections**,
   **Page info**) instead of the mockup's three (TOC and citation share the
   Page info sheet).
2. **Separate mobile markup.** Partials with their own copies of rail
   content, split as finely as wanted. Rejected: every page renders rail
   content twice, and a desktop change that misses the mobile copy is exactly
   the feature drift the owner forbids.
3. **Separate mobile pages** (`/m/...` routes or user-agent detection).
   Rejected: a Fold is one device whose width changes while open, so device
   detection picks the wrong layout; it also doubles every template.

The owner chose approach 1.

## 7. Decided design

### 7.1 Layout per width

Widths are CSS px of the viewport. Examples are portrait unless noted.

| Width | Devices (examples) | Layout |
|---|---|---|
| < 900 | iPhone (375–440), Galaxy S (360–412), Fold cover screen, Flip, Fold unfolded (~600–900), iPad mini / Air 11 / Pro 11 portrait (744–834) | **Phone layout**: compact top bar, one content column, bottom tab bar, left rail → sheet, right rail → sheet |
| 900–1279 | iPad 13″ portrait (1024–1032), iPad mini / Air / Pro 11 landscape (1133–1194) | Left rail visible (288px) + content, as today; right rail → sheet (new: today it is hidden) |
| ≥ 1280 | iPad Pro 13″ landscape (1366–1376), desktop | **Unchanged**: three columns |

The owner confirmed: Fold unfolded and iPad portrait keep the bottom tab bar
like a phone, not a left rail.

### 7.2 Top bar below 900px

- Shows: brand, a hub-status dot (green online / red offline, same data as
  the `hub online` chip), a search button (⌕) and a More button (⋯).
- Hidden from the bar (moved into the More sheet, §7.4): the status chips
  (hub online/offline, pull state, commit, `federation · N repos`, version)
  and the Sign out form.
- Search: tapping ⌕ expands the existing `topbar-search` form to the full bar
  width with a Cancel button and focuses the input (keyboard opens). Submit
  goes to `/ui?q=…` as today, keeping the hidden `tags` / `budget` inputs.
- Sticky, with `top: 0` plus `padding-top: env(safe-area-inset-top)`.
- No JS: the search input stays visible in the bar (narrower), the ⌕ button
  is hidden (via `<noscript><style>`).

### 7.3 Bottom tab bar below 900px

- Five tabs, the main menus: **Overview** (`/ui`), **Docs** (`/ui/docs`),
  **Tickets** (`/ui/tickets`), **Code** (`/ui/code`), **Q&A**
  (`/ui/questions`). Each tab: small icon + label, ≥44px tall.
- Active tab uses the same rule as the left-rail nav: `shell.screen` for
  Overview and Q&A, the menu kind (`shell.tree_doc.kind` or
  `shell.menu_kind`) for Docs / Tickets / Code. The section reader marks its
  doc's menu tab active.
- `position: fixed; bottom: 0`, with `padding-bottom:
  env(safe-area-inset-bottom)`; `main.content` gets matching bottom padding so
  the last content is never hidden behind the bar.
- It lives in `base.html`, so every shell page gets it, `error.html`
  included. `login.html` and `setup.html` do not extend `base.html` and stay
  without it.
- Hidden at ≥ 900px.
- It is plain links, so it works without JS.

### 7.4 Sheets

Three bottom sheets, all the same component:

| Sheet | Content | Trigger | Shown below |
|---|---|---|---|
| Left-rail sheet | the existing `.rail-left` minus its `.nav` links (tabs + More replace them): section tree + filter on reader pages, tag cloud + search elsewhere, status legend | pill under the page head: **Sections · N** on pages with `shell.tree`, **Tags** elsewhere | 900px |
| Right-rail sheet | the existing `.rail-right` (`{% block rail %}`) unchanged | pill under the page head, labelled per page (below) | 1280px |
| More sheet | status chips, Registry link (admins only, `shell.is_admin`), Sign in link, Sign out form | ⋯ in the top bar | 900px |

Right-rail pill label per page, from a new `{% block rail_label %}` in
`base.html` (default **Page info**): overview **Store health**, doc
**Coverage**, search **Filters**, section / plan_mission / plan_ticket
**On this page**. The pill only renders when the page's rail block is not
empty (e.g. `{% set rail_html = self.rail() %}` and test `rail_html | trim`).

The More sheet's status chips and Sign out must not be a second hand-written
copy: move the chip markup into a macro rendered both in the desktop top bar
and in the More sheet. The More sheet is the one exception to "rail content
renders once", and the macro keeps it single-sourced.

Sheet behaviour (JS in `app.js`):

- Opens with a slide-up (≈200ms, none under `prefers-reduced-motion`) over a
  dimmed scrim. Max height ≈ 80% of the viewport (`dvh`, `vh` fallback);
  content scrolls inside. At ≥ 600px width the sheet is capped (≈ 640px) and
  centered, so it does not stretch across an unfolded Fold or an iPad.
- Closes on: scrim tap, Esc, a close button, a swipe-down on the grab handle,
  and after following an in-page anchor (TOC link) so the page scrolls to it.
- Accessibility: trigger is a `<button>` with `aria-controls` and
  `aria-expanded`; the open sheet has `role="dialog"`, `aria-modal="true"`
  and a label; focus moves into the sheet and returns to the trigger on
  close; page behind does not scroll while open.
- Live filters inside the sheets (`data-filter-list`, tree chapters) keep
  working because the DOM is the same.
- No JS: sheets are not fixed. A `<noscript><style>` block (the pattern
  `left_rail.html` already uses) shows the left rail as an in-flow panel above
  the content and the right rail below it, and hides the pill triggers and ⋯.
  The More sheet's content renders in-flow at the end of the page.

### 7.5 Per-page content changes below 900px

- **Doc page** section table (`.sec-grid`): becomes one card per section
  (id + status on the first line, title, summary, token count), head row
  hidden, no `min-width`.
- **Registry** (`.reg-grid`): one card per repo, with the auto-merge switch
  and Remove button at ≥44px; the add form (`.reg-add-grid`) is one column;
  the remove-confirm banner stacks its text above its buttons.
- **Overview** stat grid: 2 columns (already) down to ≥ 360px; 1 column below.
- **Search**: Compact / Full text buttons stay in `<main>`; the J / C keyboard
  shortcuts have no touch equivalent and need none, because each result card
  already has `copy citation` and `open reader` buttons.
- **Section reader**: level tabs and pager stay in `<main>`; reader padding
  shrinks to ~16px.
- **Login / setup**: card full width with the 16px side gutter.
- **Mission / ticket pages**: markdown tables, code and mermaid keep scrolling
  inside their own box.

### 7.6 Touch rules (all widths, `@media (pointer: coarse)`)

- Tap targets ≥ 44×44px: nav links, tree rows, tag chips, `.seg`, `.btn`,
  level tabs, switches, pager links, footer buttons on result cards. Grow
  padding / `min-height`, not font size.
- Inputs, selects and textareas ≥ 16px font (prevents the iOS focus zoom).
- `:hover`-only affordances get an equivalent visible state (nothing in the
  UI today depends on hover to reveal content; keep it that way).

### 7.7 Viewport and safe areas

- `base.html` viewport meta becomes
  `width=device-width, initial-scale=1, viewport-fit=cover`. Do not disable
  zoom.
- Side gutters use `max(16px, env(safe-area-inset-left/right))` on phones so
  a landscape iPhone notch never covers content.
- Rails' `height: calc(100vh - 56px)` gets a `dvh` variant so mobile browser
  toolbars don't hide the bottom of the rail.

## 8. Verification

- pytest (existing style, `tests/test_web_ui.py`): the tab bar renders 5
  links with the right active tab per screen; Registry appears in the More
  sheet only for admins; each page's right-rail pill label; no right-rail pill
  on pages with an empty rail block; sheet triggers carry `aria-controls` /
  `aria-expanded`; the viewport meta has `viewport-fit=cover`; the
  `<noscript>` fallback is present; `<main>` slicing still holds.
- Browser check with the pre-installed Playwright (Node, `require('playwright')`;
  not in the Python venv, so this is a script, not a CI test unless the
  builder wires it): load every screen at these viewports and assert
  `document.documentElement.scrollWidth <= innerWidth`, every sheet opens and
  closes, and take screenshots for the owner:
  344×882, 375×667, 402×874, 440×956, 412×915, 600×900, 884×1104,
  744×1133, 834×1194, 1024×1366, 1180×820, 1366×1024, 1440×900.
  At 1440 the screenshot must match today's desktop.

## 9. Left to the builder

- Icons for the tab bar (inline SVG in the template, or CSS; no icon font).
- Exact sheet sizes, easing, swipe threshold.
- Whether the five nav links become a shared macro used by the left rail and
  the tab bar.
- Exact card markup for the doc and registry tables, within §7.5.
- The 600px intermediate breakpoint (wider cards, 2-column card lists) if it
  helps the Fold unfolded / iPad portrait widths.
