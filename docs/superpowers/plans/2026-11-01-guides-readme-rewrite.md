# Role Guides, Quickstarts and README Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the four role guides (hub, child, ba, dev; EN + VI), the four scaffolded quickstarts and the README as short, daily-work documents that are correct for strata-kb 1.34.0, then rebuild the PDFs.

**Architecture:** Code is the source of truth. A fact map built from the code and from every security statement in today's docs (Task 2) drives each guide. Doc-lint tests (Task 1) keep the docs honest: every `kb …` command and `/…` slash command they name has to exist, no version history may appear, and the PDF title table has to match the Markdown files. Each later task rewrites one document family and updates the existing tests that pin its text.

**Tech Stack:** Markdown, pytest, Typer (`strata_kb.cli.app`), `docs/src/build_pdf.py`.

**Spec:** `docs/superpowers/specs/2026-11-01-guides-readme-rewrite-design.md`

## Global Constraints

- Baseline is 1.34.0. No version history: no "since 1.x", "before 1.x" or "upgrade from 1.x" text, and no `1.N.N` strings in guides or quickstarts.
- Version rule, stated once in each guide's setup: every repo runs the hub's strata-kb version. Upgrade the hub first, then run `kb doctor` in each child/ba/dev repo that has the hub's MCP configured. `kb doctor` installs the hub's version, sets the `strata-kb==X` CI pins and refreshes skills and commands. It skips this in CI and reports the mismatch there instead.
- Guide shape, in this order:
  1. Who this is for
  2. First-time setup
  3. Daily work ("task → command → expected result")
  4. Automation modes
  5. Troubleshooting (a table: symptom → fix)
  6. Appendix (short, for this kind only)
- EN first. VI is a faithful translation with the same headings and section order. Commands and identifiers stay verbatim.
- Slash commands work in Claude Code, Copilot and Cursor. Each guide says so once.
- Cross-kind facts go into the appendix of every guide whose reader acts on them. The hub guide owns the full MCP tool list, hub accounts and Q&A storage. No security warning may be dropped (Task 2 map).
- The child guide owns the authoring flow: ingest → L3 check / AI fix → summarize → build → approve → publish. The hub guide links to it.
- Quickstarts are one page of about 60–120 lines: setup checklist, daily commands, auto on/off, and a link to the full guide. They never carry detail the guide lacks.
- README is English only, roughly 200–300 lines, in this order:
  1. The problem
  2. The method (four layers, verbatim tables, federation)
  3. Install
  4. Repo kinds
  5. Lifecycle (a few lines)
  6. Compact command table (one line per top-level command or group)
  7. Links to the guides and the architecture doc
  8. A short "Development" section
- `architecture.*.md`: correctness fixes and history removal only. Do not rewrite it.
- No product-code or skill changes. Templates change only for the quickstarts. When a code bug or a skill that contradicts the code turns up, add it to `## Follow-ups` in the Task 2 fact map. Do not fix it.
- Doc-pinning tests: keep each still-true fact and point the test at its new home. Rewrite or drop only wording that the rewrite removes. Never skip a test to get green.
- No version bump. Rebuild with `uv run --extra docs python docs/src/build_pdf.py`. The build must be warning-free.
- Every dispatched subagent prompt starts with a line telling it to run in ponytail + caveman mode. Implementers use model `sonnet`; reviewers use model `opus`.

## Review Focus

- A flag, config key, env var or default that the docs state but the code does not have. The doc lint checks command names only, so the reviewer of each guide task checks every flag, key and env var against `--help` and the source.
- A security warning silently lost in the rewrite. Examples: admin-rights merge in auto mode, branch protection with "include administrators", "never put a token in `hub:`", "never commit `.kb-qa/`", a token of ≥ 32 characters. Task 9's check walks the Task 2 map row by row.
- VI drifting from EN: a missing section, or a command changed in translation. Pinned by `test_vi_guides_mirror_en_headings` (Task 1).
- A quickstart that tells the reader something its guide does not say, or that contradicts it. The reviewer of Task 7 diffs the two.
- A broken pointer to a guide section after a rename. Examples: a quickstart's link to the automation section, README links. Pinned by `test_doc_links_resolve` (Task 1).

---

### Task 0: Record the test baseline

**Files:** none committed. Write the baseline to `<scratchpad>/baseline-failures.txt`.

- [ ] **Step 1:** Run `.venv/bin/python -m pytest -q -n auto -p no:cacheprovider 2>&1 | grep ^FAILED | sed 's/ - .*//' | sort > <scratchpad>/baseline-failures.txt`. Expected: the 19 known failures in `test_sectioner.py`, `test_ingest_seam.py`, `test_ingest_cli.py` and `test_cli_errors.py`, which predate this branch.

### Task 1: Doc-lint tests

**Files:**
- Create: `tests/test_doc_lint.py`

**Interfaces:**
- Produces: the module-level constant `DOCS: list[Path]`. It holds `README.md`, `docs/src/*.md` and `src/strata_kb/templates/init/QUICKSTART-*.md`. Later tasks add nothing to it, because it uses globs.

- [ ] **Step 1: Write the tests.**
  - `test_docs_name_only_real_kb_commands`:
    - Collect every `` `kb <name>`` and `` `kb <group> <sub>`` in `DOCS` with the regex `` r"`kb ([a-z][a-z0-9-]*)(?: ([a-z][a-z0-9-]*))?" ``.
    - Assert that `<name>` is a non-hidden top-level command or group of `strata_kb.cli.app`. Build the name set the way `test_readme_command_table_lists_every_top_level_command` does.
    - When `<name>` is a group and `<sub>` is present, assert that `<sub>` is in that group's `typer_instance.registered_commands`.
    - The failure message lists `(file, token)`.
  - `test_docs_name_only_real_slash_commands`:
    - Collect every `` `/<name>`` whose name starts with `kb-`, `ba-`, `dev-` or `sa-`.
    - Assert each name is in `{re.sub(r"^claude-(skill|command)-|\.md$", "", p.name) for p in (SRC/templates/init).glob("claude-*.md")}`.
  - `test_guides_and_quickstarts_carry_no_version_numbers`: `docs/src/guide-*.md`, `docs/src/architecture.*.md` and `QUICKSTART-*.md` contain no match of `r"\b1\.\d{1,2}\.\d{1,2}\b"`.
  - `test_vi_guides_mirror_en_headings`: for each `docs/src/*.en.md`, the matching `.vi.md` exists and has the same count of `#`, `##` and `###` headings, in the same level order.
  - `test_pdf_titles_match_sources`: load `docs/src/build_pdf.py` the way `tests/test_build_pdf.py` does, and skip if `xhtml2pdf` is missing. Assert `set(TITLES) == {p.stem for p in (docs/src).glob("*.md")}`.
  - `test_doc_links_resolve`:
    - For relative Markdown links `](path)` and `](path#anchor)` in `DOCS`, assert the target file exists in the repo.
    - For `#anchor` links, assert the anchor matches a heading slug in the target. Use GitHub's slug rules: lowercase, drop punctuation except `-`, spaces become `-`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_doc_lint.py -q`. Expected: `test_guides_and_quickstarts_carry_no_version_numbers` FAILS on today's guides (for example `1.28.0` in `guide-ba.en.md`). Record the failures for the other tests too. They form the defect list that the rewrite clears.
- [ ] **Step 3:** Mark the tests that fail on today's docs with `pytest.mark.xfail(strict=True, reason="cleared by the guides rewrite")`. The last task that touches the offending files removes the mark. `strict=True` turns an unexpected pass red, so a forgotten mark cannot hide.
- [ ] **Step 4:** Commit: `test: doc lint for commands, slash commands, versions, VI parity, links`.

### Task 2: Fact map and security inventory

**Files:**
- Create: `docs/superpowers/plans/2026-11-01-guides-fact-map.md`

**Interfaces:**
- Produces: a fact map with these sections:
  - `## Per kind` with `### hub`, `### child`, `### ba` and `### dev`. Each lists:
    - What `kb init --kind <k>` scaffolds, from `src/strata_kb/initcmd.py`.
    - Its slash commands.
    - The `kb` commands its reader runs daily.
    - Config keys and env vars it reads.
    - Its automation (auto mode for ba/dev, with prerequisites from `src/strata_kb/autorun/` preflight).
  - `## Security statements`: a table with columns # | Statement (quoted) | Source file:line | New home (guide/section).
  - `## Cross-kind facts`: a table with columns Fact | Kinds that need it.
  - `## Follow-ups`: code or skill contradictions found.

  Tasks 3–8 consume this map.

- [ ] **Step 1:** Build the per-kind facts from the code only: `kb <cmd> --help`, `initcmd.py`, `templates/init/*` and the config loaders. Use README and the old guides only as leads, and check each lead against code.
- [ ] **Step 2:** Grep `README.md`, `docs/src/*.md` and `QUICKSTART-*.md` for security statements. Patterns: `(?i)security|token|secret|never commit|admin|branch protection|include administrators|bearer|cookie|csrf|oidc|deny list`. Fill the security table.
- [ ] **Step 3:** Commit: `docs: fact map for the guides rewrite`.

### Tasks 3–6: One guide per kind (dev, ba, child, hub)

The four tasks run in order and share the same steps. Each task's reviewer uses model `opus` and checks every command, flag, key and env var against the code.

| Task | Files (Create/Modify, EN + VI) | Also |
|---|---|---|
| 3 dev | `docs/src/guide-dev.{en,vi}.md` (rewrite) | — |
| 4 ba | `docs/src/guide-ba.{en,vi}.md` (rewrite) | — |
| 5 child | Create `docs/src/guide-child.{en,vi}.md` | Owns the authoring flow; add `guide-child.{en,vi}` to `TITLES` in `build_pdf.py` (keeps `test_pdf_titles_match_sources` green) |
| 6 hub | Create `docs/src/guide-hub.{en,vi}.md`. Delete `docs/src/guide-hub-child.{en,vi}.md` and `docs/strata-guide-hub-child.{en,vi}.pdf` | Add `guide-hub.{en,vi}` to `TITLES`, drop `guide-hub-child.*`; link `docs/deploy-remote-mcp.md` |

- [ ] **Step 1:** Write the EN guide in the six-part shape from the Task 2 map. Place every security row whose new home is this guide.
- [ ] **Step 2:** Write the VI translation.
- [ ] **Step 3:** Run `.venv/bin/python -m pytest tests/test_doc_lint.py tests/test_readme.py tests/test_template_bodies.py -q`.
  - Fix doc-lint failures in this guide.
  - For a doc-pinning test that now fails, move the assertion to the new text when the fact is still true. When the fact moved, point the test at the file that carries it now. Note each change in the commit body.
- [ ] **Step 4:** Commit: `docs: rewrite the <kind> guide for daily work`.

### Task 7: Quickstarts

**Files:**
- Modify: `src/strata_kb/templates/init/QUICKSTART-{hub,child,ba,dev}.md`
- Modify (tests that pin them): `tests/test_init.py`, `tests/test_templates.py`, `tests/test_template_bodies.py`, `tests/test_devcodeseed.py`, `tests/test_readme.py`

- [ ] **Step 1:** Rewrite each quickstart as a one-page card.
  - Contents: setup checklist, daily commands, auto on/off (ba and dev only), and "Full guide: …".
  - The guide link points to the guide in the strata-kb repo, using the URL form that today's templates already use for README links (grep `github.com/.*/strata-kb` in the templates).
  - Every pointer to README "Full-auto mode" or "On Claude Code cloud" becomes a pointer to the BA or Dev guide's automation section.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_init.py tests/test_templates.py tests/test_template_bodies.py tests/test_devcodeseed.py tests/test_readme.py tests/test_doc_lint.py -q`. Update the pinning assertions under the keep-the-fact rule.
- [ ] **Step 3:** Commit: `docs: quickstarts become one-page cards linking the guides`.

### Task 8: Architecture review and README

**Files:**
- Modify: `docs/src/architecture.{en,vi}.md` (fixes and history removal only)
- Modify: `README.md` (rewrite)
- Modify: `tests/test_readme.py`, `tests/test_cli_mission.py`, `tests/test_cli_planwaves.py`, `tests/test_cli_ticket_check.py`, `tests/test_template_bodies.py` (README pins)
- Modify: `tests/test_doc_lint.py` (remove the xfail marks)

- [ ] **Step 1:** In the architecture docs, remove version history and fix statements that the code contradicts. Leave the structure as it is.
- [ ] **Step 2:** Rewrite the README in the order from Global Constraints. The compact command table sits under a stable heading. Update the heading string in `test_readme_command_table_lists_every_top_level_command` and `test_readme_documents_the_usage_and_ticket_subcommands` to that heading.
- [ ] **Step 3:** Remove every `xfail` mark from `tests/test_doc_lint.py`. Run `.venv/bin/python -m pytest tests/test_doc_lint.py tests/test_readme.py tests/test_cli_mission.py tests/test_cli_planwaves.py tests/test_cli_ticket_check.py tests/test_template_bodies.py -q`. Expected: all pass.
- [ ] **Step 4:** Commit: `docs: short README; architecture without version history`.

### Task 9: Verify, rebuild PDFs, security walk

- [ ] **Step 1:** Run the full suite, then compare it with the baseline: `.venv/bin/python -m pytest -q -n auto -p no:cacheprovider 2>&1 | grep ^FAILED | sed 's/ - .*//' | sort | comm -13 <scratchpad>/baseline-failures.txt -`. Expected: empty output, meaning no new failures.
- [ ] **Step 2:** Run `.venv/bin/ruff check . && .venv/bin/ruff format --check .`. Expected: clean.
- [ ] **Step 3:** Run `uv run --extra docs python docs/src/build_pdf.py`. Expected: 10 PDFs (`architecture`, `guide-{hub,child,ba,dev}`, each `.en` and `.vi`) and no error.
- [ ] **Step 4:** Walk the Task 2 security table. For each row, grep the quoted fact in its new home and mark it ✓ in the fact map.
- [ ] **Step 5:** Commit: `docs: rebuild guide PDFs` (with the fact map update), then push.
