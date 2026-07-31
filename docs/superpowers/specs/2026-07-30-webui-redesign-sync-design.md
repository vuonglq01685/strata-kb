# Web UI redesign sync — spec (2026-07-30)

Sync the Jinja web UI with the latest `CENTER-KB Redesign.dc.html` from the
Claude Design project (`d35a1ec7-d692-4126-b952-d391865da6df`). The current UI
(PR #26) already implements most of that design; this spec covers the
remaining deltas only.

## Approach

Diff-in-place: edit the existing templates, `static/style.css`,
`static/app.js`, and `web/uidata.py`. Keep the server-rendered +
progressive-enhancement architecture (every control works without JS via GET
forms/links; JS only upgrades). No template regeneration, no client-side
rendering.

Files touched:

- `src/center_kb/templates/web/_partials/left_rail.html`
- `src/center_kb/templates/web/docs.html`
- `src/center_kb/templates/web/search.html`
- `src/center_kb/templates/web/section.html`
- `src/center_kb/templates/web/static/style.css`
- `src/center_kb/templates/web/static/app.js`
- `src/center_kb/web/uidata.py` (shell context: tree, tags, counts, TOC)
- `src/center_kb/web/ui.py` (semantic param pass-through)
- tests under `tests/` (extend existing web UI render tests)

## 1. Left rail

**Doc/reader screens (`screen in ("doc", "section")`):** replace the catalog
cards with a section tree block:

- "← all documents" link → `/ui/docs`
- Doc name + meta line (`revision · N sections`) linking to the doc screen
- "Filter sections…" input — client-side JS filter over the rendered tree
  rows (`data-text` match, same pattern as the doc table filter); hidden via
  `noscript`
- Tree rows: chapter header rows (mono uppercase; derived by grouping
  sections on their `file` field — the manifest has no chapter entity;
  omit headers when the doc has a single file) + section rows with a
  status dot (pending `#92600a`, summarized `#1349a5`, reviewed `#1a6e3c`),
  `§id` + title, active section highlighted (`#eef3fc` bg + inset 2px
  `#1349a5`). Rows link to the reader.
- Tree data built in `uidata.py` from the doc manifest already loaded for the
  screen. If the manifest is unavailable, fall back to nav-only rail (no
  crash).

**Other screens:** replace the plain tag cloud with the tag panel:

- Header "Tags" + count `shown / total`
- "Search tags…" input — client-side filter, `noscript`-hidden
- Chips capped at 8 after filtering; hint line "+N more — keep typing to
  narrow" or "click to add or remove a tag filter"
- Chip = toggle link that adds/removes the tag in the `tags=` query param
  (works without JS). Selected tags render filled (`#1349a5` bg, white text).

**Nav:** add "Sign in" entry, shown only when token auth is enabled and the
session is not authenticated. "Reader" entry appears when on the section
screen (unchanged).

**Legend:** compact horizontal box at the rail bottom (three dot+label chips
in a bordered `#f4f2ee` box), replacing the verbose vertical legend.

**Catalog cards are removed from the rail** (the catalog lives on
`/ui/docs`).

## 2. Docs + Search screens

**`docs.html`:**

- Filter bar (white panel): input "Filter documents by name, id or tag…" —
  client-side filter over cards via `data-text`, plus GET `?filter=` fallback;
  active tag chips with ✕ (toggle links); label "N of M documents"
- Each card adds: clickable tag chips (toggle `tags=` filter) and an "open
  sections →" link; keeps title, revision badge, counts, progress bar
- Empty state: "No document matches that filter."

**`search.html`:**

- "Tag filter" row: active tags as removable ✕ chips (link drops that tag);
  when empty, show "none — searching the whole store"
- Meta line becomes `N sections · M docs · budget B tk · scope hub
  federation` (distinct doc count computed from results)

## 3. Search rail — functional controls

- **Match mode:** GET form. `semantic` checkbox is real: `ui.py` passes
  `semantic=` through to `query.search(...)`; unchecked skips the semantic
  leg. `keyword` checkbox renders checked + disabled (backend always runs the
  keyword leg — the UI must not pretend otherwise). Helper text about RRF
  fusion stays.
- **Shortcuts (`app.js`):** `J` focuses the next result card, `C` copies the
  citation of the focused result (falls back to the first result). Ignore
  keystrokes when an input/textarea has focus. Shortcuts box in the rail
  lists ⌘K / J / C.

## 4. Reader "On this page"

- `uidata.py` extracts h2/h3 headings from the rendered section HTML, injects
  anchor `id`s (slugified, de-duplicated), and passes a TOC list to the
  template
- Right rail renders the TOC (active-style first entry, hover states per the
  design); block hidden entirely when there are no headings

## Error handling

- Manifest load failure on doc/reader screens → rail degrades to nav-only
- No results / no docs / no tags → existing empty states preserved
- All new controls work with JS disabled (GET links/forms); JS-only controls
  (tree filter, tag search, J/C) are hidden or inert under `noscript`

## Testing

Extend the existing web UI tests (template render + route tests):

- Rail: tree renders on doc/reader screens with correct active row + status
  dots; catalog cards absent; tag toggle URLs add/remove tags; Sign in
  visibility per auth state
- Docs: filter fallback GET param filters server-side; card tag chips render
- Search: doc count in meta; semantic checkbox off → `query.search` called
  with `semantic=False` (assert via monkeypatch); tag ✕ URLs correct
- Reader: TOC extracted with anchors; hidden when no headings
- `app.js` behaviors (J/C, client filters) are progressive enhancements —
  covered by noscript fallbacks, not unit-tested

## Out of scope

- Visual changes already shipped in PR #26 (tokens, typography, layout grid)
- Backend search changes beyond plumbing the existing `semantic` flag
- Mobile/responsive work (design is desktop-first, min-width 1280px)
