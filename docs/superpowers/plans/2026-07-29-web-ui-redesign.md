# Web UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the minimal server-rendered `/ui` with the approved redesign — IBM Plex typography, 3-column shell (left rail / main / right rail), five screens: Overview (new), Search, Documents, Reader, Login.

**Architecture:** Jinja2 templates (autoescape ON) replace `string.Template` + f-string builders. A new `web/uidata.py` aggregates Overview/rail data from federation manifests. State lives in URLs; one dependency-free `app.js` adds ⌘K, copy, live table filter, and card expand. Fonts are self-hosted woff2.

**Tech Stack:** Python 3.13, Starlette, Jinja2, pytest, vanilla JS/CSS (no build step).

**Spec:** `docs/superpowers/specs/2026-07-29-web-ui-redesign-design.md`

## Global Constraints

- Work happens in this worktree (`.claude/worktrees/ui-redesign`, branch `worktree-ui-redesign` off `main`).
- Only new dependency: `jinja2>=3.1` (added to `server` AND `dev` extras). Nothing else.
- Jinja2 autoescape always ON — never `| safe` except for `md_render()` output and pre-built rail/result HTML noted below.
- Existing URLs unchanged. New behavior: `/ui` with no `q`/`tags` renders Overview.
- Login/auth/rate-limit semantics unchanged (markup only). `/ui/static/` stays auth-exempt (already is).
- No JS build step; `app.js` is plain ES2020, no dependencies.
- Every screen must work without JS (forms submit GET; expand falls back to reader links).
- Deviations from the design mock (approved in spec): match-mode checkboxes deferred (search() fuses automatically when embedder present — no lookup-time split); reader "On this page" TOC omitted (mdrender emits no heading anchors); PR# row hidden (not recorded in hub data).
- Test commands: `python -m pytest tests/<file> -v` (venv python3.13). Lint: `python -m ruff check src tests`.
- Commit style: conventional (`feat:`/`test:`/`chore:`), no attribution footer.
- Design source of truth for colors/spacing: the token table in Task 3 (extracted from the .dc.html mock).

## File Structure

```
src/center_kb/
├── templates/web/
│   ├── base.html            # shell: header + left rail + main block + right-rail block
│   ├── overview.html        # NEW screen
│   ├── search.html          # rewrite
│   ├── docs.html            # rewrite
│   ├── doc.html             # rewrite
│   ├── section.html         # rewrite
│   ├── login.html           # rewrite
│   ├── _partials/
│   │   ├── status.html      # status badge macro
│   │   ├── cards.html       # doc card + result card macros
│   │   └── left_rail.html   # nav + catalog + tags + legend
│   └── static/
│       ├── style.css        # rewrite: tokens + all components
│       ├── app.js           # NEW
│       └── fonts/           # NEW: 6 woff2 files (IBM Plex Sans 400/500/600/700, Mono 400/600)
└── web/
    ├── templating.py        # NEW: Jinja env + render()
    ├── uidata.py            # NEW: aggregation
    └── ui.py                # rewrite handlers; keep asset route + login logic intact
tests/
    ├── test_web_templating.py  # NEW
    ├── test_web_uidata.py      # NEW
    └── test_web_ui.py          # extend/update
```

---

### Task 1: Jinja2 dependency + templating module

**Files:**
- Modify: `pyproject.toml` (extras `server`, `dev`)
- Create: `src/center_kb/web/templating.py`
- Test: `tests/test_web_templating.py`

**Interfaces:**
- Produces: `templating.render(template: str, **ctx) -> str` — used by every later task.

- [ ] **Step 1: Add jinja2 to extras in `pyproject.toml`**

In `[project.optional-dependencies]`, extend both lines:

```toml
dev = [
    "pytest>=8.0", "anyio>=4.0", "sqlite-vec>=0.1.6", "twine>=5.0", "build>=1.2",
    "PyJWT[crypto]>=2.8", "python-multipart>=0.0.9", "httpx>=0.27",
    "imagehash>=4.3", "Pillow>=10.0", "ruff>=0.15", "jinja2>=3.1",
]
server = ["PyJWT[crypto]>=2.8", "python-multipart>=0.0.9", "jinja2>=3.1"]
```

Then run: `python -m pip install -e ".[dev]"`
Expected: installs jinja2.

- [ ] **Step 2: Write the failing test**

`tests/test_web_templating.py`:

```python
from center_kb.web import templating


def test_render_loads_package_template_and_escapes():
    # base.html must exist and autoescape must be on
    html = templating.render(
        "login.html",
        error='<script>alert(1)</script>',
        shell=None,
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
```

(Will be adjusted when login.html lands in Task 4 — for now create a throwaway template in the test via the env, see Step 3 test below.)

Simpler, dependency-free version — use this instead:

```python
from center_kb.web import templating


def test_render_escapes_by_default(tmp_path):
    env = templating.make_env()
    tmpl = env.from_string("<p>{{ value }}</p>")
    assert tmpl.render(value="<script>x</script>") == (
        "<p>&lt;script&gt;x&lt;/script&gt;</p>"
    )


def test_render_reads_from_package():
    # any template that exists today
    out = templating.render("login.html", error="")
    assert "token" in out
```

Note: `test_render_reads_from_package` stays RED until Task 4 rewrites `login.html` for Jinja (the current file is a `string.Template` with `$error`). Mark it `@pytest.mark.xfail(reason="login.html becomes a Jinja template in Task 4", strict=True)` now; remove the marker in Task 4.

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_web_templating.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: make_env`

- [ ] **Step 4: Implement `src/center_kb/web/templating.py`**

```python
from __future__ import annotations

from jinja2 import Environment, PackageLoader, select_autoescape


def make_env() -> Environment:
    return Environment(
        loader=PackageLoader("center_kb", "templates/web"),
        autoescape=select_autoescape(enabled_extensions=("html",), default=True),
    )


_env = make_env()


def render(template: str, **ctx) -> str:
    return _env.get_template(template).render(**ctx)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_web_templating.py -v`
Expected: `test_render_escapes_by_default` PASS, `test_render_reads_from_package` XFAIL.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/center_kb/web/templating.py tests/test_web_templating.py
git commit -m "feat: jinja2 templating environment for web UI"
```

---

### Task 2: uidata aggregation module

**Files:**
- Create: `src/center_kb/web/uidata.py`
- Test: `tests/test_web_uidata.py`

**Interfaces:**
- Consumes: `HubHandle` (`hub.root`, `hub.federation_dir`), `federation.load_federation`, `models.Manifest`, `gitio.head_commit`.
- Produces (all consumed by ui.py in Tasks 4–8):
  - `catalog(hub) -> list[CatalogDoc]` — fields `id, repo, title, revision, total, reviewed, summarized, pending, done_pct`
  - `all_tags(hub) -> list[str]` (sorted, unique, lowercase order preserved as-is)
  - `review_queue(hub, limit=8) -> list[QueueItem]` — fields `repo, doc_id, section_id, title, status`; pending first, then summarized; reviewed excluded
  - `store_stats(hub) -> StoreStats` — fields `docs, sections, repos, l0_tokens`
  - `last_publish(hub) -> PublishInfo` — fields `commit, repos, published_at` (empty strings/list when unknown)
  - `doc_coverage(manifest) -> Coverage` — fields `total, reviewed, summarized, pending`
  - `prev_next(manifest, section_id) -> tuple[SectionEntry | None, SectionEntry | None]`
  - `status_map(hub) -> dict[tuple[str, str, str], str]` — `(repo, doc_id, section_id) -> status`

- [ ] **Step 1: Write the failing tests**

`tests/test_web_uidata.py` (the `fed_hub` fixture and `make_fed_entry` helper already exist in `tests/conftest.py` — reuse them; look at `tests/test_web_ui.py` for call shapes):

```python
from center_kb.hub import HubHandle
from center_kb.models import Manifest, SectionEntry, SectionTokens
from center_kb.web import uidata
from tests.conftest import make_fed_entry


def _hub(fed_hub) -> HubHandle:
    return HubHandle(root=fed_hub)


def test_catalog_counts_statuses(fed_hub):
    hub = _hub(fed_hub)
    docs = uidata.catalog(hub)
    assert docs, "fed_hub fixture must expose at least one doc"
    d = docs[0]
    assert d.total == d.reviewed + d.summarized + d.pending
    assert 0 <= d.done_pct <= 100


def test_all_tags_sorted_unique(fed_hub):
    tags = uidata.all_tags(_hub(fed_hub))
    assert tags == sorted(set(tags))


def test_review_queue_pending_first_and_excludes_reviewed(fed_hub):
    queue = uidata.review_queue(_hub(fed_hub), limit=50)
    assert all(item.status != "reviewed" for item in queue)
    statuses = [item.status for item in queue]
    if "summarized" in statuses and "pending" in statuses:
        assert statuses.index("pending") < statuses.index("summarized")


def test_store_stats_shapes(fed_hub):
    stats = uidata.store_stats(_hub(fed_hub))
    assert stats.docs >= 1
    assert stats.sections >= 1
    assert stats.repos >= 1
    assert stats.l0_tokens >= 0


def test_last_publish_no_git_is_empty_not_error(fed_hub):
    info = uidata.last_publish(_hub(fed_hub))
    assert info.commit == ""  # fed_hub fixture is not a git repo
    assert isinstance(info.repos, list)


def test_doc_coverage_and_prev_next():
    m = Manifest(
        id="d", title="D",
        sections=[
            SectionEntry(id="1", title="A", file="a.md", status="reviewed",
                         tokens=SectionTokens(l2=10, l3=20)),
            SectionEntry(id="2", title="B", file="b.md", status="pending"),
            SectionEntry(id="3", title="C", file="c.md", status="summarized"),
        ],
    )
    cov = uidata.doc_coverage(m)
    assert (cov.total, cov.reviewed, cov.summarized, cov.pending) == (3, 1, 1, 1)
    prev, nxt = uidata.prev_next(m, "2")
    assert prev.id == "1" and nxt.id == "3"
    prev, nxt = uidata.prev_next(m, "1")
    assert prev is None and nxt.id == "2"
    prev, nxt = uidata.prev_next(m, "3")
    assert prev.id == "2" and nxt is None
    assert uidata.prev_next(m, "zz") == (None, None)


def test_status_map_keys(fed_hub):
    smap = uidata.status_map(_hub(fed_hub))
    assert all(len(k) == 3 for k in smap)
    assert all(v in ("pending", "summarized", "reviewed") for v in smap.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_uidata.py -v`
Expected: FAIL — `ModuleNotFoundError: center_kb.web.uidata`

- [ ] **Step 3: Implement `src/center_kb/web/uidata.py`**

```python
# src/center_kb/web/uidata.py
"""Read-only aggregation for the web UI: Overview stats, rails, reader nav.

Everything derives from the hub federation mirror each request. Failures in
non-essential data (git metadata) degrade to empty values, never to a 500.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterator

from center_kb import gitio, models
from center_kb.federation import load_federation
from center_kb.hub import HubHandle
from center_kb.mdutils import count_tokens
from center_kb.models import Manifest, SectionEntry

logger = logging.getLogger("center_kb.web.uidata")

_QUEUE_ORDER = {"pending": 0, "summarized": 1}


@dataclass(frozen=True)
class CatalogDoc:
    id: str
    repo: str
    title: str
    revision: str
    total: int
    reviewed: int
    summarized: int
    pending: int

    @property
    def done_pct(self) -> int:
        if not self.total:
            return 0
        return round(100 * (self.total - self.pending) / self.total)


@dataclass(frozen=True)
class QueueItem:
    repo: str
    doc_id: str
    section_id: str
    title: str
    status: str


@dataclass(frozen=True)
class StoreStats:
    docs: int
    sections: int
    repos: int
    l0_tokens: int


@dataclass(frozen=True)
class PublishInfo:
    commit: str = ""
    repos: list[str] = field(default_factory=list)
    published_at: str = ""


@dataclass(frozen=True)
class Coverage:
    total: int
    reviewed: int
    summarized: int
    pending: int


def _iter_manifests(hub: HubHandle) -> Iterator[tuple[str, Manifest]]:
    for repo in load_federation(hub.federation_dir):
        for doc in repo.index.docs:
            path = repo.kb_dir / doc.id / "_manifest.yaml"
            if not path.exists():
                continue
            try:
                yield repo.meta.repo_id, models.load_yaml_model(path, Manifest)
            except Exception as exc:  # malformed manifest: skip, keep the page up
                logger.warning("skipping manifest %s: %s", path, exc)


def catalog(hub: HubHandle) -> list[CatalogDoc]:
    out: list[CatalogDoc] = []
    for repo_id, m in _iter_manifests(hub):
        counts = {"reviewed": 0, "summarized": 0, "pending": 0}
        for s in m.sections:
            counts[s.status] += 1
        out.append(
            CatalogDoc(
                id=m.id, repo=repo_id, title=m.title, revision=m.revision,
                total=len(m.sections), **counts,
            )
        )
    return out


def all_tags(hub: HubHandle) -> list[str]:
    tags = {
        t
        for repo in load_federation(hub.federation_dir)
        for doc in repo.index.docs
        for t in doc.tags
    }
    return sorted(tags)


def review_queue(hub: HubHandle, limit: int = 8) -> list[QueueItem]:
    items = [
        QueueItem(repo=repo_id, doc_id=m.id, section_id=s.id,
                  title=s.title, status=s.status)
        for repo_id, m in _iter_manifests(hub)
        for s in m.sections
        if s.status != "reviewed"
    ]
    items.sort(key=lambda i: (_QUEUE_ORDER[i.status], i.doc_id, i.section_id))
    return items[:limit]


def store_stats(hub: HubHandle) -> StoreStats:
    repos = load_federation(hub.federation_dir)
    docs = sum(len(r.index.docs) for r in repos)
    sections = sum(len(m.sections) for _, m in _iter_manifests(hub))
    index_path = hub.federation_dir / "index.yaml"
    l0 = count_tokens(index_path.read_text(encoding="utf-8")) if index_path.exists() else 0
    return StoreStats(docs=docs, sections=sections, repos=len(repos), l0_tokens=l0)


def last_publish(hub: HubHandle) -> PublishInfo:
    try:
        commit = gitio.head_commit(hub.root)[:7]
    except gitio.GitError:
        commit = ""
    index_path = hub.federation_dir / "index.yaml"
    repos: list[str] = []
    published_at = ""
    if index_path.exists():
        try:
            fed = models.load_yaml_model(index_path, models.FederationIndex)
            repos = sorted({e.repo_id for e in fed.docs})
            published_at = max((e.published_at for e in fed.docs), default="")
        except Exception as exc:
            logger.warning("federation index unreadable: %s", exc)
    return PublishInfo(commit=commit, repos=repos, published_at=published_at)


def doc_coverage(manifest: Manifest) -> Coverage:
    counts = {"reviewed": 0, "summarized": 0, "pending": 0}
    for s in manifest.sections:
        counts[s.status] += 1
    return Coverage(total=len(manifest.sections), **counts)


def prev_next(
    manifest: Manifest, section_id: str
) -> tuple[SectionEntry | None, SectionEntry | None]:
    ids = [s.id for s in manifest.sections]
    if section_id not in ids:
        return None, None
    i = ids.index(section_id)
    prev = manifest.sections[i - 1] if i > 0 else None
    nxt = manifest.sections[i + 1] if i < len(ids) - 1 else None
    return prev, nxt


def status_map(hub: HubHandle) -> dict[tuple[str, str, str], str]:
    return {
        (repo_id, m.id, s.id): s.status
        for repo_id, m in _iter_manifests(hub)
        for s in m.sections
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_web_uidata.py -v`
Expected: all PASS. If `HubHandle(root=fed_hub)` signature mismatches (extra kwargs), read `src/center_kb/hub.py:18-30` and adjust the test helper only.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/uidata.py tests/test_web_uidata.py
git commit -m "feat: uidata aggregation for overview and rails"
```

---

### Task 3: Static pipeline — fonts, stylesheet, generic static route

**Files:**
- Create: `src/center_kb/templates/web/static/fonts/` (6 woff2 files)
- Create: `src/center_kb/templates/web/static/app.js` (placeholder — real logic in Task 9)
- Rewrite: `src/center_kb/templates/web/static/style.css` (move from `templates/web/style.css` — note the new `static/` subdir)
- Modify: `src/center_kb/web/ui.py` (replace `static_css` with generic handler)
- Test: `tests/test_web_ui.py` (add static tests)

**Interfaces:**
- Produces: `GET /ui/static/{path}` serving `.css`, `.js`, `.woff2` from package dir `templates/web/static/`; 404 on anything else. Templates reference `/ui/static/style.css`, `/ui/static/app.js`, `/ui/static/fonts/<name>.woff2`.

- [ ] **Step 1: Download fonts**

```bash
cd src/center_kb/templates/web && mkdir -p static/fonts
BASE=https://cdn.jsdelivr.net/npm/@ibm/plex@6.4.1
curl -fsSL -o static/fonts/IBMPlexSans-Regular.woff2  "$BASE/IBM-Plex-Sans/fonts/complete/woff2/IBMPlexSans-Regular.woff2"
curl -fsSL -o static/fonts/IBMPlexSans-Medium.woff2   "$BASE/IBM-Plex-Sans/fonts/complete/woff2/IBMPlexSans-Medium.woff2"
curl -fsSL -o static/fonts/IBMPlexSans-SemiBold.woff2 "$BASE/IBM-Plex-Sans/fonts/complete/woff2/IBMPlexSans-SemiBold.woff2"
curl -fsSL -o static/fonts/IBMPlexSans-Bold.woff2     "$BASE/IBM-Plex-Sans/fonts/complete/woff2/IBMPlexSans-Bold.woff2"
curl -fsSL -o static/fonts/IBMPlexMono-Regular.woff2  "$BASE/IBM-Plex-Mono/fonts/complete/woff2/IBMPlexMono-Regular.woff2"
curl -fsSL -o static/fonts/IBMPlexMono-SemiBold.woff2 "$BASE/IBM-Plex-Mono/fonts/complete/woff2/IBMPlexMono-SemiBold.woff2"
ls -la static/fonts/  # expect 6 files, each > 40KB
cd ../../../..
```

If jsdelivr is unreachable, fall back to `https://github.com/IBM/plex/releases` (download the Sans/Mono zips and extract the same six woff2 files). Verify each file starts with the woff2 magic: `head -c4 static/fonts/IBMPlexSans-Regular.woff2` → `wOF2`.

- [ ] **Step 2: Write placeholder `app.js`**

`src/center_kb/templates/web/static/app.js`:

```js
// CENTER-KB UI enhancements. Progressive only — every page works without this file.
"use strict";
```

- [ ] **Step 3: Write the new `style.css`**

Delete `src/center_kb/templates/web/style.css` (git rm in the commit step). Create `src/center_kb/templates/web/static/style.css`:

```css
/* CENTER-KB web UI — design tokens from the approved redesign mock. */
@font-face { font-family: "IBM Plex Sans"; font-weight: 400; font-display: swap;
  src: url(/ui/static/fonts/IBMPlexSans-Regular.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-weight: 500; font-display: swap;
  src: url(/ui/static/fonts/IBMPlexSans-Medium.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-weight: 600; font-display: swap;
  src: url(/ui/static/fonts/IBMPlexSans-SemiBold.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-weight: 700; font-display: swap;
  src: url(/ui/static/fonts/IBMPlexSans-Bold.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 400; font-display: swap;
  src: url(/ui/static/fonts/IBMPlexMono-Regular.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 600; font-display: swap;
  src: url(/ui/static/fonts/IBMPlexMono-SemiBold.woff2) format("woff2"); }

:root {
  --bg: #faf9f7; --surface: #fff; --surface-alt: #fdfcfa; --field: #f4f2ee;
  --line: #e8e5df; --line-soft: #f2f0eb; --dash: #cfcac1;
  --ink: #16202c; --body-c: #2c3744; --muted: #66707c; --faint: #98a0aa;
  --accent: #1349a5; --accent-deep: #0d3a86; --accent-bg: #eef3fc;
  --accent-line: #c4d5f2; --accent-wash: #f4f8ff; --focus-ring: #e8effb;
  --ok: #1a6e3c; --ok-bg: #e4f3e9; --ok-line: #bfe2cb;
  --warn: #92600a; --warn-bg: #faf0dc; --warn-line: #ecd9b0;
  --err: #b3261e; --err-bg: #fdeeed; --err-line: #f3c9c5;
  --sans: "IBM Plex Sans", system-ui, "Segoe UI", Arial, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, monospace;
  --r-sm: 7px; --r-md: 8px; --r-lg: 10px; --r-xl: 12px;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); }
body { font-family: var(--sans); color: var(--ink); -webkit-font-smoothing: antialiased; }
a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-deep); }
::selection { background: #d9e5f9; }

/* labels & badges */
.kicker { margin: 0; font: 600 10px/1.4 var(--mono); letter-spacing: .18em;
  text-transform: uppercase; color: var(--faint); }
.kicker.accent { color: var(--accent); font-size: 11px; letter-spacing: .2em; }
.badge { font: 600 10px/1.6 var(--mono); letter-spacing: .08em; text-transform: uppercase;
  border-radius: 4px; padding: 1px 7px; border: 1px solid; }
.badge-pending { color: var(--warn); background: var(--warn-bg); border-color: var(--warn-line); }
.badge-summarized { color: var(--accent); background: var(--accent-bg); border-color: var(--accent-line); }
.badge-reviewed { color: var(--ok); background: var(--ok-bg); border-color: var(--ok-line); }
.badge-mode { color: var(--muted); background: var(--field); border-color: var(--line); font-weight: 500; }
.chip { font: 500 11px/1.7 var(--mono); color: var(--accent); background: var(--accent-bg);
  border: 1px solid #dbe6f8; border-radius: 999px; padding: 2px 9px; }
.chip:hover { color: #fff; background: var(--accent); border-color: var(--accent); }
.mono { font-family: var(--mono); }
.meta-line { margin: 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font: 400 11px/1.6 var(--mono); color: var(--muted); letter-spacing: .04em; }
.meta-line .sep { color: var(--dash); }

/* shell */
.shell { min-height: 100vh; display: flex; flex-direction: column; }
.topbar { position: sticky; top: 0; z-index: 20; display: flex; align-items: center;
  gap: 20px; padding: 0 22px; height: 56px; background: rgba(255,255,255,.88);
  backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 9px; font: 600 13px/1 var(--mono);
  letter-spacing: .14em; color: var(--ink); }
.brand-mark { width: 20px; height: 20px; border-radius: 5px; background: var(--accent);
  display: flex; align-items: center; justify-content: center; color: #fff;
  font-size: 10px; letter-spacing: 0; }
.brand-dot { color: var(--accent); }
.topbar-search { flex: 1; max-width: 560px; }
.topbar-search input { width: 100%; height: 34px; padding: 0 12px;
  font: 14px/1 var(--sans); color: var(--ink); background: var(--field);
  border: 1px solid var(--line); border-radius: var(--r-md); }
.topbar-search input:focus { background: #fff; border-color: var(--accent);
  outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
.topbar-status { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.hub-chip { display: flex; align-items: center; gap: 6px; font: 400 11px/1 var(--mono);
  letter-spacing: .06em; border-radius: 999px; padding: 4px 9px; border: 1px solid; }
.hub-chip .dot { width: 6px; height: 6px; border-radius: 50%; }
.hub-online { color: var(--ok); background: var(--ok-bg); border-color: var(--ok-line); }
.hub-online .dot { background: var(--ok); }
.hub-offline { color: var(--err); background: var(--err-bg); border-color: var(--err-line); }
.hub-offline .dot { background: var(--err); }
.topbar-fed { font: 400 11px/1 var(--mono); color: var(--muted); letter-spacing: .04em; }

.columns { flex: 1; display: grid; grid-template-columns: 248px minmax(0,1fr) 292px;
  align-items: start; }
.rail { position: sticky; top: 56px; height: calc(100vh - 56px); overflow-y: auto;
  background: var(--surface-alt); display: flex; flex-direction: column; }
.rail-left { border-right: 1px solid var(--line); padding: 20px 14px 32px; gap: 26px; }
.rail-right { border-left: 1px solid var(--line); padding: 24px 18px 32px; gap: 20px; }
main.content { padding: 28px 32px 56px; min-width: 0; }
@media (max-width: 1279px) { .columns { grid-template-columns: 248px minmax(0,1fr); }
  .rail-right { display: none; } }
@media (max-width: 899px) { .columns { grid-template-columns: minmax(0,1fr); }
  .rail-left { display: none; } }

/* left rail */
.nav { display: flex; flex-direction: column; gap: 2px; }
.nav a { display: flex; align-items: center; gap: 8px; padding: 7px 10px;
  border-radius: var(--r-md); font: 500 13.5px/1.4 var(--sans); color: var(--muted); }
.nav a.active { color: var(--ink); background: var(--accent-bg);
  box-shadow: inset 2px 0 0 var(--accent); }
.rail-group { display: flex; flex-direction: column; gap: 8px; }
.rail-group > .kicker { margin: 0 0 2px 8px; }
.catalog-card { display: flex; flex-direction: column; gap: 5px; padding: 9px 10px;
  border-radius: var(--r-md); border: 1px solid var(--line); background: var(--surface); }
.catalog-card .row { display: flex; align-items: baseline; gap: 6px; }
.catalog-card .name { font: 600 13px/1.4 var(--sans); color: var(--ink); }
.catalog-card .rev, .catalog-card .count { font: 400 10px/1.4 var(--mono); color: var(--muted); }
.catalog-card .count { margin-left: auto; }
.catalog-card .track { height: 3px; border-radius: 2px; background: #eceae4; overflow: hidden; }
.catalog-card .fill { display: block; height: 3px; background: var(--accent); }
.catalog-card .sub { font: 400 10px/1.5 var(--mono); color: var(--muted); letter-spacing: .04em; }
.tag-cloud { display: flex; flex-wrap: wrap; gap: 5px; padding: 0 6px; }
.legend { margin-top: auto; display: flex; flex-direction: column; gap: 6px;
  padding: 11px 12px; border-radius: var(--r-md); background: var(--field);
  border: 1px solid var(--line); }
.legend .item { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--muted); }
.legend .sw { width: 8px; height: 8px; border-radius: 2px; }

/* right rail blocks */
.rail-block { display: flex; flex-direction: column; gap: 8px; }
.rail-kv { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); }
.rail-kv .v { font-family: var(--mono); color: var(--ink); }
.rail-card { display: flex; flex-direction: column; gap: 6px; padding: 11px 12px;
  border-radius: 9px; border: 1px solid var(--line); background: var(--field); }
.rail-card.accent { background: var(--accent-wash); border-color: var(--accent-line); }
.health-item { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--body-c); }
.health-item .dot { width: 7px; height: 7px; border-radius: 50%; }
.dot-ok { background: var(--ok); } .dot-warn { background: var(--warn); } .dot-err { background: var(--err); }

/* headings / stat cards / panels */
.page-head { display: flex; flex-direction: column; gap: 6px; }
.page-head h1 { margin: 0; font-size: 30px; font-weight: 600; letter-spacing: -.02em; }
.page-head .lede { margin: 0; color: var(--muted); font-size: 15px; max-width: 60ch; }
.stack-lg { display: flex; flex-direction: column; gap: 24px; }
.stack-md { display: flex; flex-direction: column; gap: 18px; }
.stat-grid { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 12px; }
@media (max-width: 1100px) { .stat-grid { grid-template-columns: repeat(2, minmax(0,1fr)); } }
.stat-card { padding: 14px 16px; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-lg); display: flex; flex-direction: column; gap: 4px; }
.stat-card .kicker { font-size: 10px; letter-spacing: .16em; }
.stat-card .value { font-size: 26px; font-weight: 600; letter-spacing: -.02em; }
.stat-card .note { font-size: 12px; color: var(--muted); }
.stat-card.accent { background: var(--accent-wash); border-color: var(--accent-line); }
.stat-card.accent .value, .stat-card.accent .kicker { color: var(--accent); }
.panel { background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-lg); overflow: hidden; }
.panel-head { display: flex; align-items: baseline; gap: 10px; padding: 13px 18px;
  border-bottom: 1px solid #eceae4; }
.panel-head h2 { margin: 0; font-size: 15px; font-weight: 600; }
.panel-head .note { font: 400 11px/1.5 var(--mono); color: var(--muted); }
.panel-head .link { margin-left: auto; font: 400 11px/1.5 var(--mono); letter-spacing: .04em; }
.queue-row { display: flex; align-items: center; gap: 12px; padding: 12px 18px; }
.queue-row + .queue-row { border-top: 1px solid var(--line-soft); }
.queue-row .cite { font: 600 12px/1.4 var(--mono); color: var(--accent); min-width: 130px; }
.queue-row .file { font-size: 13px; flex: 1; min-width: 0; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }

/* search results */
.result-card { display: flex; flex-direction: column; gap: 9px; padding: 15px 18px;
  background: var(--surface); border: 1px solid var(--line); border-radius: 11px; }
.result-card.expanded { box-shadow: 0 1px 2px rgba(22,32,44,.05), 0 12px 28px -24px rgba(22,32,44,.5); }
.result-card header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.result-card .cite { font: 600 12px/1.4 var(--mono); color: var(--accent); }
.result-card h2 { margin: 0; font-size: 16px; font-weight: 600; letter-spacing: -.01em; }
.result-card .tk { margin-left: auto; display: flex; align-items: center; gap: 8px;
  font: 400 11px/1 var(--mono); color: var(--faint); }
.score-track { width: 52px; height: 4px; border-radius: 2px; background: #eceae4; overflow: hidden; }
.score-fill { display: block; height: 4px; background: var(--accent); }
.result-card .body { margin: 0; font-size: 13.5px; line-height: 1.65; color: var(--body-c); }
.result-card:not(.expanded) .body { color: var(--muted); display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.result-card footer { display: flex; align-items: center; gap: 10px; padding-top: 2px; }
.result-card footer a, .result-card footer button { font: 400 11px/1.5 var(--mono);
  letter-spacing: .04em; color: var(--accent); background: none; border: 0;
  padding: 0; cursor: pointer; }
.result-card footer .sep { color: var(--dash); }
.result-card footer .file { margin-left: auto; font: 400 10px/1.5 var(--mono); color: var(--faint); }
.seg-row { display: flex; gap: 6px; }
.seg { height: 28px; padding: 0 12px; font: 500 12px/1 var(--sans); border-radius: var(--r-sm);
  cursor: pointer; color: var(--muted); background: transparent; border: 1px solid var(--line); }
.seg.on { color: #fff; background: var(--accent); border-color: var(--accent); }

/* filter bar + section table */
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 10px 12px; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-lg); }
.filter-bar input { flex: 1 1 240px; height: 32px; padding: 0 11px;
  font: 13px/1 var(--sans); background: #f8f7f4; border: 1px solid var(--line);
  border-radius: var(--r-sm); color: var(--ink); }
.filter-bar input:focus { background: #fff; border-color: var(--accent); outline: none;
  box-shadow: 0 0 0 3px var(--focus-ring); }
.filter-bar .shown { font: 400 11px/1.5 var(--mono); color: var(--muted); }
.sec-table { overflow-x: auto; }
.sec-grid { display: grid; min-width: 720px;
  grid-template-columns: 86px minmax(90px,1.1fr) minmax(140px,1.6fr) 118px 62px;
  gap: 14px; padding: 12px 18px; align-items: start; }
.sec-grid.head { padding: 9px 18px; background: #f8f7f4; border-bottom: 1px solid var(--line);
  font: 600 10px/1.5 var(--mono); letter-spacing: .14em; text-transform: uppercase;
  color: var(--faint); }
.sec-grid + .sec-grid { border-top: 1px solid var(--line-soft); }
.sec-grid .sid { font: 600 13px/1.4 var(--mono); color: var(--accent); }
.sec-grid .title { font-size: 13px; font-weight: 500; min-width: 0; }
.sec-grid .sum { font-size: 13px; color: var(--muted); min-width: 0; }
.sec-grid .tk { font: 400 12px/1.5 var(--mono); color: var(--faint); text-align: right; }

/* doc cards (documents list) */
.doc-card { display: flex; flex-direction: column; gap: 8px; padding: 15px 18px;
  background: var(--surface); border: 1px solid var(--line); border-radius: 11px; }
.doc-card header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.doc-card .name { font-size: 15px; font-weight: 600; }
.doc-card .summary { margin: 0; font-size: 13.5px; color: var(--muted); line-height: 1.6; }
.doc-card .chips { display: flex; flex-wrap: wrap; gap: 5px; }

/* reader */
.reader { display: flex; flex-direction: column; gap: 16px; max-width: 760px; }
.level-tabs { display: flex; align-items: center; gap: 6px; padding: 4px;
  background: var(--field); border: 1px solid var(--line); border-radius: 9px; width: fit-content; }
.level-tabs a { height: 32px; padding: 0 15px; display: inline-flex; align-items: center;
  font: 500 13px/1 var(--sans); border-radius: var(--r-sm); border: 1px solid transparent;
  color: var(--muted); }
.level-tabs a.on { color: var(--ink); background: #fff; border-color: var(--line);
  box-shadow: 0 1px 2px rgba(22,32,44,.06); }
.reader-body { background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-xl); padding: 26px 32px; font-size: 15px; line-height: 1.7; }
.reader-body table { border-collapse: collapse; width: 100%; font-size: 13px;
  border: 1px solid var(--line); }
.reader-body th { text-align: left; padding: 8px 12px; background: #f8f7f4;
  border: 1px solid var(--line); font: 600 10px/1.5 var(--mono); letter-spacing: .12em;
  text-transform: uppercase; color: var(--muted); }
.reader-body td { padding: 8px 12px; border: 1px solid var(--line-soft); }
.reader-body img { max-width: 100%; }
.pager { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 12px 16px; background: var(--surface-alt); border: 1px solid var(--line);
  border-radius: var(--r-lg); }
.pager a { display: flex; flex-direction: column; gap: 2px; }
.pager .dir { font: 400 10px/1.5 var(--mono); letter-spacing: .14em;
  text-transform: uppercase; color: var(--faint); }
.pager .label { font-size: 13px; font-weight: 500; color: var(--ink); }
.pager a.next { text-align: right; }
.cite-box { display: flex; flex-direction: column; gap: 8px; padding: 11px 12px;
  background: var(--accent-wash); border: 1px solid var(--accent-line); border-radius: 9px; }
.cite-box code { font: 400 12px/1.5 var(--mono); color: var(--accent); }
.cite-box button { height: 29px; font: 500 12px/1 var(--sans); color: var(--accent);
  background: #fff; border: 1px solid var(--accent-line); border-radius: var(--r-sm);
  cursor: pointer; }
.cite-box button:hover { color: #fff; background: var(--accent); border-color: var(--accent); }

/* login */
.login-card { max-width: 400px; margin: 8vh auto 0; display: flex; flex-direction: column;
  gap: 18px; background: var(--surface); border: 1px solid var(--line);
  border-radius: 14px; padding: 30px 32px 34px;
  box-shadow: 0 1px 2px rgba(22,32,44,.04), 0 24px 48px -32px rgba(22,32,44,.4); }
.login-card h1 { margin: 8px 0 0; font-size: 21px; font-weight: 600; letter-spacing: -.015em; }
.login-card .lede { margin: 0; color: var(--muted); font-size: 14px; }
.login-card form { display: flex; flex-direction: column; gap: 10px; }
.login-card input { height: 38px; padding: 0 12px; font: 14px/1 var(--mono);
  background: #f8f7f4; border: 1px solid var(--line); border-radius: var(--r-md);
  color: var(--ink); }
.login-card input:focus { background: #fff; border-color: var(--accent); outline: none;
  box-shadow: 0 0 0 3px var(--focus-ring); }
.login-card button { height: 38px; font: 600 14px/1 var(--sans); color: #fff;
  background: var(--accent); border: 1px solid var(--accent); border-radius: var(--r-md);
  cursor: pointer; }
.login-card button:hover { background: var(--accent-deep); border-color: var(--accent-deep); }
.error-banner { display: flex; align-items: center; gap: 8px; padding: 9px 12px;
  background: var(--err-bg); border: 1px solid var(--err-line); border-radius: var(--r-md);
  color: var(--err); font-size: 13px; }
.error-banner::before { content: ""; width: 6px; height: 6px; border-radius: 50%;
  background: var(--err); }
.kbd { font-family: var(--mono); background: #fff; border: 1px solid var(--line);
  border-radius: 4px; padding: 0 5px; }
code.inline { font: 400 12.5px/1.5 var(--mono); background: var(--field);
  border: 1px solid var(--line); border-radius: 4px; padding: 1px 5px; }

/* misc */
.empty-state { padding: 34px 18px; text-align: center; color: var(--muted); font-size: 13px; }
.crumbs { margin: 0; font: 400 11px/1.6 var(--mono); color: var(--muted); letter-spacing: .04em; }
.crumbs .sep { color: var(--dash); }
```

- [ ] **Step 4: Write the failing static-route tests**

Append to `tests/test_web_ui.py`:

```python
def test_static_css_served_with_content_type(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/static/style.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")
    assert "--accent" in resp.text


def test_static_js_and_font_served(fed_hub):
    c = _client(fed_hub / ".kb", str(fed_hub))
    js = c.get("/ui/static/app.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("text/javascript")
    font = c.get("/ui/static/fonts/IBMPlexSans-Regular.woff2")
    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert font.content[:4] == b"wOF2"


def test_static_rejects_traversal_and_unknown_types(fed_hub):
    c = _client(fed_hub / ".kb", str(fed_hub))
    assert c.get("/ui/static/../ui.py").status_code == 404
    assert c.get("/ui/static/fonts/x.ttf").status_code == 404
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_ui.py -k static -v`
Expected: FAIL (old route serves only `style.css` from the old path).

- [ ] **Step 6: Replace `static_css` in `src/center_kb/web/ui.py`**

Remove the `static_css` handler and its route. Add:

```python
STATIC_TYPES = {".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2"}


async def static_file(request: Request) -> Response:
    name = request.path_params["path"]
    suffix = Path(name).suffix
    media = STATIC_TYPES.get(suffix)
    if media is None or ".." in name or name.startswith("/"):
        return Response("not found", status_code=404)
    target = resources.files("center_kb").joinpath("templates/web/static").joinpath(name)
    if not target.is_file():
        return Response("not found", status_code=404)
    data = await run_in_threadpool(target.read_bytes)
    return Response(
        data, media_type=media,
        headers={"Cache-Control": "public, max-age=86400"},
    )
```

Route list: replace `Route("/ui/static/style.css", static_css, ...)` with
`Route("/ui/static/{path:path}", static_file, methods=["GET"])`.

Keep old `templates/web/style.css` working until Task 4 rewrites `base.html`: temporarily copy nothing — the old base.html links `/ui/static/style.css`, which the new route now serves from the NEW file. The new stylesheet doesn't style the old markup; that's fine for one task (tests assert content, not looks).

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_web_ui.py -v`
Expected: static tests PASS; all pre-existing tests still PASS.

- [ ] **Step 8: Commit**

```bash
git rm src/center_kb/templates/web/style.css
git add src/center_kb/templates/web/static src/center_kb/web/ui.py tests/test_web_ui.py
git commit -m "feat: self-hosted IBM Plex fonts, design-token stylesheet, generic static route"
```

---

### Task 4: Shell — base.html, partials, login rewrite, ui.py render helpers

**Files:**
- Create: `src/center_kb/templates/web/_partials/status.html`, `_partials/left_rail.html`
- Rewrite: `src/center_kb/templates/web/base.html`, `login.html`
- Create: `src/center_kb/templates/web/error.html`
- Modify: `src/center_kb/web/ui.py` (shell context + login handlers + error pages)
- Modify: `tests/test_web_templating.py` (drop xfail marker)

**Interfaces:**
- Consumes: `templating.render`, `uidata.catalog/all_tags/store_stats`.
- Produces (used by Tasks 5–8):
  - `_shell_ctx(config, screen: str, q: str = "") -> dict` with keys `screen, hub_ok, q, repo_count, catalog, tags`
  - `_render_page(template, config, screen, status=200, q="", **ctx) -> HTMLResponse` — every screen handler calls this
  - `_error_page(config, title: str, message: str, status: int) -> HTMLResponse`
  - Jinja macro `status(s)` from `_partials/status.html`
  - base.html blocks: `{% block main %}`, `{% block rail %}`; template var `title`
- **Security deviation (intentional):** login.html is standalone — no shell — so unauthenticated visitors never see catalog/doc titles in the rail.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_ui.py`:

```python
def test_login_page_is_standalone_no_catalog_leak(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui/login")
    assert resp.status_code == 200
    assert 'name="token"' in resp.text
    assert "Demo Document" not in resp.text  # no rail on the login page


def test_shell_header_and_left_rail_on_docs_page(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui/docs")
    assert resp.status_code == 200
    assert "hub online" in resp.text
    assert 'id="global-search"' in resp.text
    assert "Demo Document" in resp.text  # catalog card in left rail
```

(The second test goes fully green in Task 7 when docs.html extends the new base; here it must at least fail before the shell exists.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_ui.py -k "standalone or shell_header" -v`
Expected: FAIL (old markup).

- [ ] **Step 3: Write `_partials/status.html`**

```html
{% macro status(s) %}<span class="badge badge-{{ s }}">{{ s }}</span>{% endmacro %}
```

- [ ] **Step 4: Write `_partials/left_rail.html`**

```html
<aside class="rail rail-left">
  <nav class="nav">
    <a href="/ui" class="{{ 'active' if shell.screen == 'overview' else '' }}">Overview</a>
    <a href="/ui?q=" class="{{ 'active' if shell.screen == 'search' else '' }}">Search</a>
    <a href="/ui/docs" class="{{ 'active' if shell.screen in ('docs', 'doc') else '' }}">Documents</a>
    {% if shell.screen == 'section' %}<a href="#" class="active">Reader</a>{% endif %}
  </nav>
  <div class="rail-group">
    <p class="kicker">Catalog</p>
    {% for d in shell.catalog %}
    <a class="catalog-card" href="/ui/docs/{{ d.id | urlencode }}?repo={{ d.repo | urlencode }}">
      <span class="row"><span class="name">{{ d.title }}</span>
        <span class="rev">{{ d.revision }}</span>
        <span class="count">{{ d.total }}</span></span>
      <span class="track"><span class="fill" style="width:{{ d.done_pct }}%"></span></span>
      <span class="sub">{{ d.summarized + d.reviewed }} summarized · {{ d.pending }} pending</span>
    </a>
    {% endfor %}
  </div>
  <div class="rail-group">
    <p class="kicker">Tags</p>
    <div class="tag-cloud">
      {% for t in shell.tags %}<a class="chip" href="/ui?tags={{ t | urlencode }}">{{ t }}</a>{% endfor %}
    </div>
  </div>
  <div class="legend">
    <p class="kicker">Review status</p>
    <span class="item"><span class="sw" style="background:#92600a"></span>pending — needs a summary</span>
    <span class="item"><span class="sw" style="background:#1349a5"></span>summarized — awaiting SME</span>
    <span class="item"><span class="sw" style="background:#1a6e3c"></span>reviewed — signed off</span>
  </div>
</aside>
```

- [ ] **Step 5: Write `base.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} — CENTER-KB</title>
<link rel="stylesheet" href="/ui/static/style.css">
<script src="/ui/static/app.js" defer></script>
</head>
<body>
<div class="shell">
<header class="topbar">
  <a class="brand" href="/ui"><span class="brand-mark">KB</span>CENTER<span class="brand-dot">·</span>KB</a>
  <form class="topbar-search" method="get" action="/ui">
    <input type="search" id="global-search" name="q" value="{{ shell.q }}"
           placeholder="Search sections, fields, codes…  ⌘K">
  </form>
  <div class="topbar-status">
    {% if shell.hub_ok %}
    <span class="hub-chip hub-online"><span class="dot"></span>hub online</span>
    {% else %}
    <span class="hub-chip hub-offline"><span class="dot"></span>hub offline</span>
    {% endif %}
    <span class="topbar-fed">federation · {{ shell.repo_count }} repos</span>
  </div>
</header>
<div class="columns">
  {% include "_partials/left_rail.html" %}
  <main class="content">{% block main %}{% endblock %}</main>
  <aside class="rail rail-right">{% block rail %}{% endblock %}</aside>
</div>
</div>
</body>
</html>
```

- [ ] **Step 6: Write `login.html` (standalone)**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in — CENTER-KB</title>
<link rel="stylesheet" href="/ui/static/style.css">
</head>
<body>
<div class="login-card">
  <span class="brand-mark">KB</span>
  <h1>Sign in to CENTER·KB</h1>
  <p class="lede">Paste the access token from
    <code class="inline">CENTER_KB_HTTP_TOKEN</code> to continue.</p>
  {% if error %}<div class="error-banner">{{ error }}</div>{% endif %}
  <form method="post" action="/ui/login">
    <label style="display:flex; flex-direction:column; gap:6px">
      <span class="kicker">Access token</span>
      <input type="password" name="token" placeholder="••••••••••••••••" autofocus required>
    </label>
    <button type="submit">Sign in</button>
  </form>
  <p class="meta-line">The same token authorizes /api and /mcp.</p>
</div>
</body>
</html>
```

- [ ] **Step 7: Write `error.html`**

```html
{% extends "base.html" %}
{% block main %}
<div class="stack-md">
  <div class="page-head">
    <p class="kicker accent">{{ code }}</p>
    <h1>{{ heading }}</h1>
    <p class="lede">{{ message }}</p>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 8: Rewire `ui.py`**

Add imports: `from center_kb.web import templating, uidata`. Add helpers (replace `_template` and `_page` — leave the old ones in place until Task 10 removes the last user):

```python
def _shell_ctx(config: ServerConfig, screen: str, q: str = "") -> dict:
    hub = api.hub_handle(config)
    if hub is None:
        return {"screen": screen, "hub_ok": False, "q": q,
                "repo_count": 0, "catalog": [], "tags": []}
    return {
        "screen": screen, "hub_ok": True, "q": q,
        "repo_count": uidata.store_stats(hub).repos,
        "catalog": uidata.catalog(hub),
        "tags": uidata.all_tags(hub),
    }


def _render_page(
    template: str, config: ServerConfig, screen: str,
    status: int = 200, q: str = "", **ctx,
) -> HTMLResponse:
    shell = _shell_ctx(config, screen, q=q)
    return HTMLResponse(
        templating.render(template, shell=shell, **ctx), status_code=status
    )


def _error_page(
    config: ServerConfig, code: int, heading: str, message: str
) -> HTMLResponse:
    return _render_page(
        "error.html", config, screen="", status=code,
        title=heading, code=str(code), heading=heading, message=message,
    )
```

Rewrite login handlers to pass **plain text** errors (autoescape handles the rest):

```python
    async def login_get(request: Request) -> HTMLResponse:
        return HTMLResponse(templating.render("login.html", error=""))

    async def login_post(request: Request) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        # Checked before the token compare: a brute-forcer must not learn of
        # a hit inside the lockout window.
        if not limiter.allow(client_ip):
            logger.warning("login rate-limited for %s", client_ip)
            return HTMLResponse(
                templating.render(
                    "login.html", error="Too many attempts — try again later."
                ),
                status_code=429,
            )
        form = await request.form()
        submitted = str(form.get("token", ""))
        if hmac.compare_digest(submitted, token):
            resp = RedirectResponse("/ui", status_code=303)
            resp.set_cookie(COOKIE_NAME, submitted, httponly=True, samesite="lax")
            return resp
        # never log the submitted value — it may be a near-miss of the token
        logger.warning("failed login attempt from %s", client_ip)
        return HTMLResponse(
            templating.render("login.html", error="Invalid token — check for trailing spaces.")
        )
```

Remove the xfail marker from `tests/test_web_templating.py::test_render_reads_from_package`.

- [ ] **Step 9: Run tests**

Run: `python -m pytest tests/test_web_ui.py tests/test_web_templating.py -v`
Expected: login tests + templating PASS. `test_shell_header_and_left_rail_on_docs_page` still FAILS (docs.html not converted yet) — mark it `@pytest.mark.xfail(reason="docs.html converts in Task 7", strict=True)` and remove the marker in Task 7. Existing login regression tests (`test_login_*`) must PASS unchanged — if one asserts old markup (e.g. `<p class="error">`), update the assertion to the new marker (`error-banner`), keeping the intent.

- [ ] **Step 10: Commit**

```bash
git add src/center_kb/templates/web src/center_kb/web/ui.py tests/
git commit -m "feat: jinja shell (base + rails + login + error pages)"
```

---

### Task 5: Overview screen

**Files:**
- Create: `src/center_kb/templates/web/overview.html`
- Modify: `src/center_kb/web/ui.py` (`home` handler dispatch)
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `_render_page`, `uidata.store_stats/review_queue/last_publish`, `_partials/status.html`.
- Produces: `/ui` without `q`/`tags` → Overview. `home` handler splits: overview / search / tag-browse.

- [ ] **Step 1: Write the failing tests**

```python
def test_ui_root_without_query_renders_overview(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui")
    assert resp.status_code == 200
    assert "Store overview" in resp.text
    assert "Review queue" in resp.text
    assert "Documents" in resp.text  # stat card


def test_overview_queue_lists_unreviewed_sections(fed_hub):
    # fed_hub fixture ships at least one non-reviewed section
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui")
    assert "badge-pending" in resp.text or "badge-summarized" in resp.text


def test_ui_root_hub_down_shows_offline(tmp_path, monkeypatch):
    resp = _client(tmp_path, str(tmp_path / "nope")).get("/ui")
    assert resp.status_code == 200
    assert "hub offline" in resp.text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_web_ui.py -k overview -v` → FAIL.

- [ ] **Step 3: Write `overview.html`**

```html
{% extends "base.html" %}
{% from "_partials/status.html" import status %}
{% block main %}
<div class="stack-lg">
  <div class="page-head">
    <p class="kicker accent">Hub federation</p>
    <h1>Store overview</h1>
    <p class="lede">Everything searchable lives in the hub's
      <span class="mono">federation/</span> mirror. Local
      <span class="mono">.kb/</span> drafts are never queried.</p>
  </div>
  <div class="stat-grid">
    <div class="stat-card"><span class="kicker">Documents</span>
      <span class="value">{{ stats.docs }}</span>
      <span class="note">across {{ stats.repos }} repos</span></div>
    <div class="stat-card"><span class="kicker">Sections</span>
      <span class="value">{{ stats.sections }}</span>
      <span class="note">L2 + L3 indexed</span></div>
    <div class="stat-card"><span class="kicker">L0 catalog</span>
      <span class="value">{{ stats.l0_tokens }} <span class="note">tk</span></span>
      <span class="note">whole-store index</span></div>
    <div class="stat-card accent"><span class="kicker">Saving / lookup</span>
      <span class="value">≥ 99%</span>
      <span class="note">vs. loading the full doc</span></div>
  </div>
  <div class="panel">
    <div class="panel-head">
      <h2>Review queue</h2>
      <span class="note">{{ pending_total }} sections pending across the store</span>
      <a class="link" href="/ui/docs">open catalog →</a>
    </div>
    {% for item in queue %}
    <div class="queue-row">
      <a class="cite" href="/ui/docs/{{ item.doc_id | urlencode }}/{{ item.section_id | urlencode }}?repo={{ item.repo | urlencode }}">{{ item.doc_id }} §{{ item.section_id }}</a>
      <span class="file">{{ item.title }}</span>
      {{ status(item.status) }}
    </div>
    {% else %}
    <div class="empty-state"><p>Nothing awaiting review.</p></div>
    {% endfor %}
  </div>
</div>
{% endblock %}
{% block rail %}
<div class="rail-block">
  <p class="kicker">Store health</p>
  <div class="health-item"><span class="dot {{ 'dot-ok' if shell.hub_ok else 'dot-err' }}"></span>hub {{ 'reachable' if shell.hub_ok else 'unreachable' }}</div>
  <div class="health-item"><span class="dot {{ 'dot-ok' if index_ok else 'dot-err' }}"></span>federation index {{ 'present' if index_ok else 'missing' }}</div>
  <div class="health-item"><span class="dot {{ 'dot-warn' if pending_total else 'dot-ok' }}"></span>{{ pending_total }} sections pending</div>
</div>
<div class="rail-block">
  <p class="kicker">Last publish</p>
  {% if publish.commit %}<div class="rail-kv"><span>Commit</span><span class="v">{{ publish.commit }}</span></div>{% endif %}
  {% if publish.published_at %}<div class="rail-kv"><span>Published</span><span class="v">{{ publish.published_at }}</span></div>{% endif %}
  {% if publish.repos %}<div class="rail-kv"><span>Repos</span><span class="v">{{ publish.repos | join(', ') }}</span></div>{% endif %}
  {% if not (publish.commit or publish.repos) %}<div class="rail-kv"><span>—</span><span class="v">no publish data</span></div>{% endif %}
</div>
<div class="rail-card accent">
  <p class="kicker" style="color:#1349a5">Layers</p>
  <span style="font-size:12px; color:#2c3744">L0 catalog · L1 manifest · L2 summary · L3 original</span>
</div>
{% endblock %}
```

- [ ] **Step 4: Rewrite the `home` handler in `ui.py`**

```python
    async def home(request: Request) -> HTMLResponse:
        q = request.query_params.get("q", "").strip()
        raw_tags = request.query_params.get("tags", "").strip()
        if q or raw_tags:
            return await _search_screen(request, q, raw_tags)  # Task 6
        hub = api.hub_handle(config)
        if hub is None:
            return _render_page(
                "overview.html", config, screen="overview", title="Overview",
                stats=uidata.StoreStats(0, 0, 0, 0), queue=[], pending_total=0,
                index_ok=False, publish=uidata.PublishInfo(),
            )
        stats = uidata.store_stats(hub)
        queue = uidata.review_queue(hub)
        pending_total = sum(
            1 for v in uidata.status_map(hub).values() if v == "pending"
        )
        return _render_page(
            "overview.html", config, screen="overview", title="Overview",
            stats=stats, queue=queue, pending_total=pending_total,
            index_ok=(hub.federation_dir / "index.yaml").exists(),
            publish=uidata.last_publish(hub),
        )
```

Until Task 6 exists, keep the old search path working: temporarily name the old body `_search_screen(request, q, raw_tags)` by extracting the current `q`-handling code (old `search.html` template still renders via the old `_template`/`_page` helpers).

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_web_ui.py -v`
Expected: overview tests PASS; old search tests still PASS through the extracted `_search_screen`.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/web/overview.html src/center_kb/web/ui.py tests/test_web_ui.py
git commit -m "feat: overview screen (stats, review queue, health, last publish)"
```

---

### Task 6: Search screen

**Files:**
- Rewrite: `src/center_kb/templates/web/search.html`
- Modify: `src/center_kb/web/ui.py` (`_search_screen`)
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `search()` (`query.py:139` — signature `search(hub, text, tags=None, budget=2000, semantic=False, embedder=None)`), `uidata.status_map`, `md_render`, `_render_page`.
- Produces: `/ui?q=…&tags=…&budget=…` renders result cards; tag-only renders doc cards (Task 7's macro); keeps the literal string `hub federation` in the meta line (existing test asserts it).

- [ ] **Step 1: Write the failing tests**

```python
def test_search_shows_result_card_with_status_and_score(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace"}
    )
    assert resp.status_code == 200
    assert "result-card" in resp.text
    assert "score-fill" in resp.text
    assert "badge-" in resp.text          # per-result status badge
    assert "hub federation" in resp.text  # scope note preserved


def test_search_budget_clamped_and_echoed(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui", params={"q": "airspace", "budget": "999999"}
    )
    assert resp.status_code == 200
    assert "8000" in resp.text  # clamped to the slider max


def test_search_no_results_empty_state(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui", params={"q": "zzzznotfound"}
    )
    assert "No matching section" in resp.text
```

- [ ] **Step 2: Run to verify FAIL** — `python -m pytest tests/test_web_ui.py -k "search_shows or budget_clamped or empty_state" -v`

- [ ] **Step 3: Write `search.html`**

```html
{% extends "base.html" %}
{% from "_partials/status.html" import status %}
{% block main %}
<div class="stack-md">
  <div class="page-head">
    <h1 style="font-size:22px">Results for “{{ q }}”</h1>
    <p class="meta-line">{{ results | length }} sections · budget {{ budget }} tk · scope hub federation</p>
  </div>
  {% if active_tags %}
  <div class="meta-line">
    <span class="kicker">Filter</span>
    {% for t in active_tags %}<span class="chip">{{ t }}</span>{% endfor %}
  </div>
  {% endif %}
  <div class="seg-row" data-density>
    <button type="button" class="seg on" data-density-btn="compact">Compact</button>
    <button type="button" class="seg" data-density-btn="full">Full text</button>
  </div>
  <div class="stack-md" style="gap:10px">
    {% for r in results %}
    <article class="result-card">
      <header>
        <a class="cite" href="{{ r.href }}">{{ r.citation }}</a>
        {{ status(r.status) }}
        <span class="badge badge-mode">{{ r.match_mode }}</span>
        <span class="tk">{{ r.tokens }} tk
          <span class="score-track"><span class="score-fill" style="width:{{ r.score_pct }}%"></span></span>
        </span>
      </header>
      <h2>{{ r.title }}</h2>
      <div class="body">{{ r.body_html | safe }}</div>
      <footer>
        <button type="button" data-toggle-card>expand</button>
        <span class="sep">|</span>
        <button type="button" data-copy-text="{{ r.citation }}">copy citation</button>
        <span class="sep">|</span>
        <a href="{{ r.href }}">open reader</a>
        <span class="file">{{ r.file }}</span>
      </footer>
    </article>
    {% else %}
    <div class="empty-state"><p>No matching section found.</p>
      <p>Try dropping tags or changing keywords.</p></div>
    {% endfor %}
  </div>
</div>
{% endblock %}
{% block rail %}
<div class="rail-block">
  <p class="kicker">Token budget</p>
  <form method="get" action="/ui">
    <input type="hidden" name="q" value="{{ q }}">
    {% if raw_tags %}<input type="hidden" name="tags" value="{{ raw_tags }}">{% endif %}
    <input type="range" name="budget" min="200" max="8000" step="100"
           value="{{ budget }}" style="width:100%; accent-color:#1349a5"
           onchange="this.form.submit()">
    <div class="rail-kv"><span>200</span><span class="v" style="color:#1349a5">{{ budget }} tk</span><span>8000</span></div>
    <noscript><button type="submit" class="seg" style="margin-top:6px">Apply</button></noscript>
  </form>
</div>
<div class="rail-block">
  <p class="kicker">Match modes</p>
  <p style="margin:0; font-size:11.5px; color:#98a0aa; line-height:1.5">
    Keyword (FTS5) and semantic (KNN) legs are fused with RRF when the
    embedder is installed. No model call happens at lookup time.</p>
</div>
<div class="rail-card">
  <p class="kicker">Shortcuts</p>
  <span class="rail-kv"><span>Focus search</span><span class="kbd">⌘K</span></span>
  <span class="rail-kv"><span>Copy citation</span><span class="kbd">C</span></span>
</div>
{% endblock %}
```

- [ ] **Step 4: Implement `_search_screen` in `ui.py`**

Replace the extracted legacy body:

```python
    def _budget(request: Request) -> int:
        try:
            b = int(request.query_params.get("budget", "2000"))
        except ValueError:
            b = 2000
        return max(200, min(b, 8000))

    async def _search_screen(request: Request, q: str, raw_tags: str) -> HTMLResponse:
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        hub = api.hub_handle(config)
        if hub is None:
            return _render_page(
                "search.html", config, screen="search", title="Search", q=q,
                results=[], budget=_budget(request), active_tags=tags,
                raw_tags=raw_tags,
            )
        if not q and tags:
            docs = api.list_docs(config) or []
            return _render_page(
                "docs.html", config, screen="search", title="Documents", q=q,
                docs=_match_tags(docs, tags), browse_tags=tags,
            )
        budget = _budget(request)
        terms = set(tokenize(q))
        found = search(hub, q, tags=tags or None, budget=budget)
        smap = uidata.status_map(hub)
        top = max((r.score for r in found), default=1.0) or 1.0
        results = [
            {
                "citation": r.citation,
                "title": r.title,
                "status": smap.get((r.source, r.doc_id, r.section_id), "pending"),
                "match_mode": r.match_mode,
                "tokens": r.tokens,
                "score_pct": round(100 * r.score / top),
                "body_html": md_render(r.content, terms=terms),
                "file": f"{r.doc_id}/{r.section_id}",
                "href": (
                    f"/ui/docs/{quote(r.doc_id)}/{quote(r.section_id)}"
                    f"?repo={quote(r.source)}"
                ),
            }
            for r in found
        ]
        return _render_page(
            "search.html", config, screen="search", title="Search", q=q,
            results=results, budget=budget, active_tags=tags, raw_tags=raw_tags,
        )
```

Note: the tag-only branch renders `docs.html`, which is rewritten in Task 7. Until then keep the legacy `_doc_cards` path for tag-only (`if not q and tags:` → old code) and switch it in Task 7 — or do Tasks 6+7 in one review cycle if the seam feels artificial.

- [ ] **Step 5: Run tests** — `python -m pytest tests/test_web_ui.py -v`; update legacy search-markup assertions (e.g. old `class="result"`) to the new markers, preserving intent.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: search screen (result cards, budget slider, status badges)"`

---

### Task 7: Documents list + doc detail

**Files:**
- Rewrite: `src/center_kb/templates/web/docs.html`, `doc.html`
- Create: `src/center_kb/templates/web/_partials/cards.html`
- Modify: `src/center_kb/web/ui.py` (`docs_page`, `doc_page`)
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `api.list_docs`, `api.load_manifest`, `uidata.doc_coverage`, `_render_page`, `_error_page`.
- Produces: `docs.html` expects `docs: list[dict]` (keys `id, repo, title, revision, summary, tags`); `doc.html` expects `doc_id, manifest, rid, coverage, filter_q, status_q, files` and supports server-side `?filter=&status=` fallback. Rows carry `data-row`, `data-status`, `data-text` for Task 9 JS.

- [ ] **Step 1: Failing tests**

```python
def test_doc_page_rows_carry_data_attrs_and_tokens(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb"}
    )
    assert resp.status_code == 200
    assert 'data-row' in resp.text
    assert 'data-status=' in resp.text
    assert "sec-grid" in resp.text


def test_doc_page_server_side_status_filter(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc", params={"repo": "demo-kb", "status": "reviewed"}
    )
    assert resp.status_code == 200
    # fixture section is pending/summarized → filtered out server-side
    assert "No section matches" in resp.text or 'data-row' not in resp.text


def test_docs_page_cards_show_repo_and_tags(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get("/ui/docs")
    assert "doc-card" in resp.text
    assert "demo-kb" in resp.text
    assert "chip" in resp.text
```

Adjust the fixture status expectation to what `make_fed_entry` actually writes (read `tests/conftest.py` first).

- [ ] **Step 2: Run to verify FAIL** — `python -m pytest tests/test_web_ui.py -k "data_attrs or server_side or cards_show" -v`

- [ ] **Step 3: `_partials/cards.html`**

```html
{% macro doc_card(d) %}
<article class="doc-card">
  <header>
    <a class="name" href="/ui/docs/{{ d.id | urlencode }}?repo={{ d.repo | urlencode }}">{{ d.title or d.id }}</a>
    {% if d.revision %}<span class="badge badge-summarized">{{ d.revision }}</span>{% endif %}
    <span class="badge badge-mode">{{ d.repo }}</span>
  </header>
  {% if d.summary %}<p class="summary">{{ d.summary }}</p>{% endif %}
  <p class="chips">
    {% for t in d.tags %}<a class="chip" href="/ui?tags={{ t | urlencode }}">{{ t }}</a>
    {% else %}<span class="chip" style="opacity:.6">no tags</span>{% endfor %}
  </p>
</article>
{% endmacro %}
```

- [ ] **Step 4: `docs.html`**

```html
{% extends "base.html" %}
{% from "_partials/cards.html" import doc_card %}
{% block main %}
<div class="stack-md">
  <div class="page-head">
    <p class="kicker accent">Catalog</p>
    <h1>Documents</h1>
    {% if browse_tags %}<p class="meta-line">filtered by
      {% for t in browse_tags %}<span class="chip">{{ t }}</span>{% endfor %}</p>{% endif %}
  </div>
  <div class="stack-md" style="gap:10px">
    {% for d in docs %}{{ doc_card(d) }}
    {% else %}
    <div class="empty-state"><p>No documents match those tags.</p>
      <p>Check the tag spelling or browse all documents.</p></div>
    {% endfor %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: `doc.html`**

```html
{% extends "base.html" %}
{% from "_partials/status.html" import status %}
{% block main %}
<div class="stack-md">
  <div class="page-head">
    <p class="crumbs"><a href="/ui/docs">Documents</a> <span class="sep">/</span> {{ doc_id }}</p>
    <h1 style="font-size:26px">{{ manifest.title }}</h1>
    <p class="meta-line">
      {% if manifest.revision %}<span class="badge badge-summarized">{{ manifest.revision }}</span>{% endif %}
      <span>repo {{ rid }}</span><span class="sep">·</span>
      {% if manifest.ingested %}<span>ingested {{ manifest.ingested }}</span><span class="sep">·</span>{% endif %}
      <span>{{ manifest.sections | length }} sections</span>
    </p>
  </div>
  <form class="filter-bar" method="get" action="">
    <input type="hidden" name="repo" value="{{ rid }}">
    <input type="search" name="filter" value="{{ filter_q }}" data-filter
           placeholder="Filter sections by id, title or summary…">
    <div class="seg-row">
      {% for s in ("all", "pending", "summarized", "reviewed") %}
      <button type="submit" name="status" value="{{ s }}"
              class="seg {{ 'on' if status_q == s else '' }}"
              data-status-btn="{{ s }}">{{ s | capitalize }}</button>
      {% endfor %}
    </div>
    <span class="shown" data-shown>{{ rows | length }} of {{ manifest.sections | length }} shown</span>
  </form>
  <div class="panel sec-table">
    <div class="sec-grid head">
      <span>Section</span><span>Title</span><span>One-line summary</span>
      <span>Status</span><span style="text-align:right">L2 tk</span>
    </div>
    {% for s in rows %}
    <div class="sec-grid" data-row data-status="{{ s.status }}"
         data-text="{{ (s.id ~ ' ' ~ s.title ~ ' ' ~ s.summary) | lower }}">
      <a class="sid" href="/ui/docs/{{ doc_id | urlencode }}/{{ s.id | urlencode }}?repo={{ rid | urlencode }}">§{{ s.id }}</a>
      <span class="title">{{ s.title }}</span>
      <span class="sum">{{ s.summary }}</span>
      <span>{{ status(s.status) }}</span>
      <span class="tk">{{ s.tokens.l2 }}</span>
    </div>
    {% else %}
    <div class="empty-state">No section matches that filter.</div>
    {% endfor %}
  </div>
</div>
{% endblock %}
{% block rail %}
<div class="rail-block">
  <p class="kicker">Coverage</p>
  <div style="display:flex; height:8px; border-radius:4px; overflow:hidden; border:1px solid #e8e5df">
    {% if coverage.reviewed %}<span style="flex:{{ coverage.reviewed }}; background:#1a6e3c"></span>{% endif %}
    {% if coverage.summarized %}<span style="flex:{{ coverage.summarized }}; background:#1349a5"></span>{% endif %}
    {% if coverage.pending %}<span style="flex:{{ coverage.pending }}; background:#92600a"></span>{% endif %}
  </div>
  <div class="rail-kv"><span>reviewed</span><span class="v">{{ coverage.reviewed }} / {{ coverage.total }}</span></div>
  <div class="rail-kv"><span>summarized</span><span class="v">{{ coverage.summarized }} / {{ coverage.total }}</span></div>
  <div class="rail-kv"><span>pending</span><span class="v">{{ coverage.pending }}</span></div>
</div>
<div class="rail-block">
  <p class="kicker">Source</p>
  {% if manifest.revision %}<div class="rail-kv"><span>Revision</span><span class="v">{{ manifest.revision }}</span></div>{% endif %}
  {% if manifest.ingested %}<div class="rail-kv"><span>Ingested</span><span class="v">{{ manifest.ingested }}</span></div>{% endif %}
  {% if manifest.source_sha256 %}
  <div style="font-size:12px; color:#66707c">source_sha256
    <code style="display:block; font:10.5px/1.5 var(--mono); color:#16202c; word-break:break-all">{{ manifest.source_sha256 }}</code></div>
  {% endif %}
</div>
<div class="rail-block">
  <p class="kicker">Files</p>
  <span style="font: 11px/1.6 var(--mono); color:#66707c">_manifest.yaml<br>{% for f in files %}{{ f }}<br>{% endfor %}</span>
</div>
{% endblock %}
```

- [ ] **Step 6: Rewrite `docs_page` and `doc_page` in `ui.py`**

```python
    async def docs_page(request: Request) -> HTMLResponse:
        docs = api.list_docs(config) or []
        return _render_page(
            "docs.html", config, screen="docs", title="Documents",
            docs=docs, browse_tags=[],
        )

    async def doc_page(request: Request) -> HTMLResponse:
        doc_id = request.path_params["doc"]
        repo = request.query_params.get("repo") or None
        try:
            found = api.load_manifest(config, doc_id, repo=repo)
        except AmbiguousDocError as exc:
            return _error_page(config, 400, "Ambiguous document", str(exc))
        if found is None:
            return _error_page(config, 404, "Not found", f"Unknown doc '{doc_id}'.")
        manifest, rid = found
        filter_q = request.query_params.get("filter", "").strip().lower()
        status_q = request.query_params.get("status", "all")
        if status_q not in ("all", "pending", "summarized", "reviewed"):
            status_q = "all"
        rows = [
            s for s in manifest.sections
            if (status_q == "all" or s.status == status_q)
            and (not filter_q or filter_q in f"{s.id} {s.title} {s.summary}".lower())
        ]
        files = sorted({s.file for s in manifest.sections})
        return _render_page(
            "doc.html", config, screen="doc", title=manifest.title,
            doc_id=doc_id, manifest=manifest, rid=rid, rows=rows,
            coverage=uidata.doc_coverage(manifest),
            filter_q=filter_q, status_q=status_q, files=files,
        )
```

Also switch the Task-6 tag-only branch to the new `docs.html` (drop the legacy `_doc_cards` call) and remove the Task-4 xfail on `test_shell_header_and_left_rail_on_docs_page`.

- [ ] **Step 7: Run tests** — `python -m pytest tests/test_web_ui.py -v`; update legacy docs/doc assertions to new markers (keep intent: repo text visible, section links carry `repo=`, 404/400 behavior).

- [ ] **Step 8: Commit** — `git add -A && git commit -m "feat: documents list and doc detail (filterable section table, coverage rail)"`

---

### Task 8: Reader (section screen)

**Files:**
- Rewrite: `src/center_kb/templates/web/section.html`
- Modify: `src/center_kb/web/ui.py` (`section_page`)
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes: `get_section` (`query.py:277`), `api.load_manifest`, `uidata.prev_next`, `md_render`.
- Produces: keeps `id="citation"` marker and `level=l2|l3` links (existing tests rely on them).

- [ ] **Step 1: Failing tests**

```python
def test_section_page_new_reader_shell(demo_doc_hub):
    resp = _client(demo_doc_hub / ".kb", str(demo_doc_hub)).get(
        "/ui/docs/demo-doc/1.1", params={"repo": "demo-kb"}
    )
    assert resp.status_code == 200
    assert "level-tabs" in resp.text
    assert 'id="citation"' in resp.text
    assert "level=l3" in resp.text


def test_section_page_title_xss_escaped(fed_hub):
    make_fed_entry(
        fed_hub / "federation", "demo-kb", "xss-doc",
        title="<script>alert(1)</script>", tags=[],
        summary="x", sec_id="1", sec_title="<script>alert(2)</script>",
        sec_summary="s", l2="## 1 T\n\nbody", l3="## 1 T\n\nbody",
    )
    resp = _client(fed_hub / ".kb", str(fed_hub)).get(
        "/ui/docs/xss-doc/1", params={"repo": "demo-kb"}
    )
    assert "<script>alert(2)</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text
```

- [ ] **Step 2: Run to verify FAIL** — `python -m pytest tests/test_web_ui.py -k "reader_shell or xss" -v`

- [ ] **Step 3: `section.html`**

```html
{% extends "base.html" %}
{% from "_partials/status.html" import status %}
{% block main %}
<div class="reader">
  <div class="page-head">
    <p class="crumbs"><a href="/ui/docs">Documents</a> <span class="sep">/</span>
      <a href="/ui/docs/{{ doc_id | urlencode }}?repo={{ repo | urlencode }}">{{ doc_id }}</a>
      <span class="sep">/</span> §{{ section_id }}</p>
    <h1 style="font-size:26px">{{ result.title }}</h1>
  </div>
  <div class="level-tabs">
    <a class="{{ 'on' if level == 'l2' else '' }}"
       href="/ui/docs/{{ doc_id | urlencode }}/{{ section_id | urlencode }}?level=l2&repo={{ repo | urlencode }}">L2 · summary</a>
    <a class="{{ 'on' if level == 'l3' else '' }}"
       href="/ui/docs/{{ doc_id | urlencode }}/{{ section_id | urlencode }}?level=l3&repo={{ repo | urlencode }}">L3 · original</a>
  </div>
  <article class="reader-body">{{ content_html | safe }}</article>
  {% if prev or next %}
  <div class="pager">
    {% if prev %}
    <a href="/ui/docs/{{ doc_id | urlencode }}/{{ prev.id | urlencode }}?repo={{ repo | urlencode }}">
      <span class="dir">← previous</span><span class="label">§{{ prev.id }} {{ prev.title }}</span></a>
    {% else %}<span></span>{% endif %}
    {% if next %}
    <a class="next" href="/ui/docs/{{ doc_id | urlencode }}/{{ next.id | urlencode }}?repo={{ repo | urlencode }}">
      <span class="dir">next →</span><span class="label">§{{ next.id }} {{ next.title }}</span></a>
    {% endif %}
  </div>
  {% endif %}
</div>
{% endblock %}
{% block rail %}
<div class="rail-block">
  <p class="kicker">Citation</p>
  <div class="cite-box">
    <code id="citation">{{ result.citation }}</code>
    <button type="button" data-copy="#citation">Copy citation</button>
  </div>
</div>
<div class="rail-block">
  <p class="kicker">Metadata</p>
  {% if entry %}
  <div class="rail-kv"><span>Status</span><span>{{ status(entry.status) }}</span></div>
  <div class="rail-kv"><span>Tokens L2</span><span class="v">{{ entry.tokens.l2 }}</span></div>
  <div class="rail-kv"><span>Tokens L3</span><span class="v">{{ entry.tokens.l3 }}</span></div>
  {% else %}
  <div class="rail-kv"><span>Tokens ({{ level }})</span><span class="v">{{ result.tokens }}</span></div>
  {% endif %}
  {% if revision %}<div class="rail-kv"><span>Revision</span><span class="v">{{ revision }}</span></div>{% endif %}
  <div class="rail-kv"><span>Repo</span><span class="v">{{ repo }}</span></div>
</div>
{% endblock %}
```

- [ ] **Step 4: Rewrite `section_page` in `ui.py`**

```python
    async def section_page(request: Request) -> HTMLResponse:
        doc_id = request.path_params["doc"]
        section_id = request.path_params["section"]
        level = request.query_params.get("level", "l2")
        if level not in ("l2", "l3"):
            level = "l2"
        repo = request.query_params.get("repo") or None
        hub = api.hub_handle(config)
        if hub is None:
            return _error_page(
                config, 503, "Hub unreachable",
                "The federation is the only read source.",
            )
        try:
            result = get_section(hub, doc_id, section_id, level=level, repo=repo)
        except AmbiguousDocError as exc:
            return _error_page(config, 400, "Ambiguous document", str(exc))
        if result is None:
            return _error_page(
                config, 404, "Not found", f"{doc_id} §{section_id} not found."
            )
        prev = nxt = entry = None
        revision = ""
        try:
            found = api.load_manifest(config, doc_id, repo=result.source)
        except AmbiguousDocError:
            found = None
        if found is not None:
            manifest, _ = found
            revision = manifest.revision
            prev, nxt = uidata.prev_next(manifest, result.section_id)
            entry = next(
                (s for s in manifest.sections if s.id == result.section_id), None
            )
        return _render_page(
            "section.html", config, screen="section",
            title=f"{doc_id} §{section_id}",
            doc_id=doc_id, section_id=result.section_id, repo=result.source,
            level=level, result=result, content_html=md_render(result.content),
            prev=prev, next=nxt, entry=entry, revision=revision,
        )
```

- [ ] **Step 5: Run tests** — `python -m pytest tests/test_web_ui.py -v`; fix legacy section assertions to new markers (keep: citation id, table verbatim render, 404/400/503, `repo=` in links).

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: reader screen (level tabs, prev/next, citation rail)"`

---

### Task 9: app.js interactivity

**Files:**
- Rewrite: `src/center_kb/templates/web/static/app.js`
- Test: `tests/test_web_ui.py`

**Interfaces:**
- Consumes DOM hooks produced by Tasks 4–8: `#global-search`, `[data-copy]`, `[data-copy-text]`, `[data-toggle-card]`, `[data-density-btn]`, `[data-filter]`, `[data-status-btn]`, `[data-row]`, `[data-status]`, `[data-text]`, `[data-shown]`.

- [ ] **Step 1: Failing test**

```python
def test_app_js_ships_interactivity_hooks(fed_hub):
    resp = _client(fed_hub / ".kb", str(fed_hub)).get("/ui/static/app.js")
    assert resp.status_code == 200
    for marker in ("global-search", "data-toggle-card", "data-filter", "data-copy"):
        assert marker in resp.text
```

- [ ] **Step 2: Run to verify FAIL** — placeholder has no markers.

- [ ] **Step 3: Write `app.js`**

```js
// CENTER-KB UI enhancements. Progressive only — every page works without this file.
"use strict";

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    const box = document.getElementById("global-search");
    if (box) { e.preventDefault(); box.focus(); box.select(); }
  }
});

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const old = btn.textContent;
    btn.textContent = "copied ✓";
    setTimeout(() => { btn.textContent = old; }, 1200);
  });
}

document.addEventListener("click", (e) => {
  const copySel = e.target.closest("[data-copy]");
  if (copySel) {
    const node = document.querySelector(copySel.getAttribute("data-copy"));
    if (node) copyText(node.textContent.trim(), copySel);
    return;
  }
  const copyTxt = e.target.closest("[data-copy-text]");
  if (copyTxt) {
    copyText(copyTxt.getAttribute("data-copy-text"), copyTxt);
    return;
  }
  const toggle = e.target.closest("[data-toggle-card]");
  if (toggle) {
    const card = toggle.closest(".result-card");
    card.classList.toggle("expanded");
    toggle.textContent = card.classList.contains("expanded") ? "collapse" : "expand";
    return;
  }
  const density = e.target.closest("[data-density-btn]");
  if (density) {
    const full = density.getAttribute("data-density-btn") === "full";
    document.querySelectorAll(".result-card").forEach((c) => {
      c.classList.toggle("expanded", full);
      const t = c.querySelector("[data-toggle-card]");
      if (t) t.textContent = full ? "collapse" : "expand";
    });
    document.querySelectorAll("[data-density-btn]").forEach((b) =>
      b.classList.toggle("on", b === density));
  }
});

// Live section-table filter (doc page). Buttons switch from submit to client
// filtering when JS is available.
const filterBox = document.querySelector("[data-filter]");
if (filterBox) {
  const state = { status: "all" };
  const rows = () => document.querySelectorAll("[data-row]");
  const apply = () => {
    const q = filterBox.value.trim().toLowerCase();
    let shown = 0;
    rows().forEach((r) => {
      const okStatus = state.status === "all" || r.dataset.status === state.status;
      const okText = !q || r.dataset.text.includes(q);
      const on = okStatus && okText;
      r.style.display = on ? "" : "none";
      if (on) shown += 1;
    });
    const label = document.querySelector("[data-shown]");
    if (label) label.textContent = `${shown} of ${rows().length} shown`;
  };
  filterBox.addEventListener("input", apply);
  document.querySelectorAll("[data-status-btn]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault(); // stop the form submit — filter client-side
      state.status = btn.getAttribute("data-status-btn");
      document.querySelectorAll("[data-status-btn]").forEach((b) =>
        b.classList.toggle("on", b === btn));
      apply();
    });
  });
}
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_web_ui.py -k app_js -v` → PASS.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: app.js progressive interactivity (cmdK, copy, live filter, expand)"`

---

### Task 10: Cleanup, dead code removal, full verification

**Files:**
- Modify: `src/center_kb/web/ui.py` (remove dead helpers)
- Modify: `tests/test_check_package.py` (assert fonts ship)
- Test: full suite

- [ ] **Step 1: Remove dead code from `ui.py`**

Delete now-unused: `_template`, `_page`, `_e`, `_status_span`, `_chips`, `_source_badge`, `_match_badge`, `_result_blocks`, `_doc_cards`, `HUB_DOWN_HTML`, `HUB_DOWN_PAGE` (grep first — delete only what has zero remaining references; `_match_tags` stays, the search tag-branch uses it). Remove `from string import Template` and the now-unused `html` import if nothing references them.

Run: `grep -n "_template\|_page(\|_result_blocks\|_doc_cards\|_status_span\|_chips\|_source_badge\|_match_badge" src/center_kb/web/ui.py` → only definitions you are deleting, no call sites.

- [ ] **Step 2: Packaging test**

In `tests/test_check_package.py`, extend the packaged-files assertion so the wheel must contain `templates/web/static/style.css`, `app.js`, and at least one `fonts/*.woff2` (follow the file's existing assertion style).

- [ ] **Step 3: Full verification**

```bash
python -m pytest -x -q
python -m ruff check src tests
python -m ruff format --check src tests 2>/dev/null || true
```

Expected: all tests pass, ruff clean. Fix anything that fails — do not skip.

- [ ] **Step 4: Manual smoke (optional but recommended)**

```bash
CENTER_KB_HTTP_TOKEN=dev kb serve --transport http 2>/dev/null &  # or the repo's serve command — check `kb --help`
# visit http://127.0.0.1:8321/ui — login, overview, search, doc, reader
```

Screenshot each screen at 1440px and compare against the design mock; fix visual drift in style.css only.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: drop string.Template render path, package static assets"
```

---

## Self-Review (completed at plan time)

- **Spec coverage:** 5 screens ✔ (T5 overview, T6 search, T7 docs+doc, T8 reader, T4 login); Jinja2 ✔ (T1); uidata ✔ (T2); fonts+static ✔ (T3); app.js ✔ (T9); responsive ✔ (CSS media queries T3); error handling ✔ (T4 error.html, hub-offline chip, uidata degrade); XSS/autoescape ✔ (T1, T8); packaging ✔ (T10). Spec deviations declared in Global Constraints (mode checkboxes, TOC, PR#) plus one addition: standalone login (no catalog leak pre-auth).
- **Placeholders:** none — all steps carry code/commands.
- **Type consistency:** `uidata` names checked against consumers (`store_stats().repos`, `CatalogDoc.done_pct`, `PublishInfo.commit/repos/published_at`, `prev_next` tuple, `status_map` key `(repo, doc_id, section_id)` matched by `smap.get((r.source, r.doc_id, r.section_id))` — `QueryResult.source` is the repo id, verified in `query.py`).

