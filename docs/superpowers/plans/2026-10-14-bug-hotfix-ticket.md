# Bug / hotfix tickets — plan

Spec: `docs/superpowers/specs/2026-10-14-bug-hotfix-ticket-design.md` (binding).

## Global Constraints

- User-story tickets are untouched: every existing test passes unchanged;
  `ticket.REQUIRED_HEADINGS` and the story lint path do not change.
- A ticket's type comes only from a `> Type: <value>` line under the H1;
  values `bug`, `hotfix`; absent → story; any other value → lint error
  naming the allowed values.
- Bug id `BUG-<n>`; file `tickets/bugs/BUG-<n>.md`; attachments
  `tickets/bugs/BUG-<n>/<file>.png|webp`.
- Severity line `> Severity: S1|S2|S3|S4`, required on a bug.
- Optional `> Related ticket: <id|none>`; id must satisfy
  `planstatus.safe_name`.
- `BUG_REQUIRED_HEADINGS` in this order: `## Summary`, `## Environment`,
  `## Pre-conditions`, `## Steps to reproduce`, `## Expected result`,
  `## Actual result`, `## Attachments`, `## Impact`,
  `## Definition of Ready`. Recommended: `## Open questions`.
- Attachment images: PNG/WebP only, relative path inside `BUG-<n>/`, no
  `..`, no absolute, no `http(s)://`.
- No new MCP tool, no new MCP parameter; `tests-gate/golden/mcp_tools.json`
  changes only if a tool docstring changes.
- English headings fixed; repo conventions: ruff, pyright on `src`,
  pytest (`uv run pytest -n auto` or the repo's documented command).
- Version 1.25.0.
- Never edit CLAUDE.md / settings. Commit per task with a Conventional
  Commit message.

## Task 1: Bug type, bug lint, bug template

Files: `src/strata_kb/ticket.py`, new `src/strata_kb/buglint.py`,
`src/strata_kb/ticketlint.py` (dispatch only),
new `src/strata_kb/templates/init/bug-template.md`, tests
(`tests/test_buglint.py` new; a dispatch test in `tests/test_ticketlint.py`).

- `ticket.py`: `TYPE_RE` for `^>\s*Type:\s*(\S+)\s*$` (multiline),
  `TICKET_TYPES = ("story", "bug", "hotfix")`, `ticket_type(text) -> str`
  (absent → "story", value lower-cased; unknown returned as-is so lint can
  report it), `BUG_REQUIRED_HEADINGS`, `BUG_RECOMMENDED_HEADINGS`,
  `SEVERITY_RE`, `RELATED_TICKET_RE`, `SEVERITIES = ("S1","S2","S3","S4")`.
- `ticketlint.lint()`: first statement computes the type; `bug`/`hotfix`
  → `return buglint.lint(...)` with the same arguments; unknown type →
  a report with one error `unknown ticket type '<v>' — use one of: story
  (no Type line), bug, hotfix`; story → today's code path, untouched.
- `buglint.lint(text, hub, *, path=None, missions_dir=None,
  fail_on_stale=False, ticket_id=None, load_mission=None)` returns the
  same report type as `ticketlint.lint`. Reuse `lintcore` for headings,
  filled sections, recommended sections, the KB context block (ONLY when
  `## KB context` exists), revision (`planrev.check_revision`), and the
  DoR checklist presence. Bug-specific errors:
  - missing/invalid `> Severity:`;
  - `> Parent mission:` present → error "a bug links with `> Related
    ticket:`, not a parent mission";
  - `> Related ticket:` value not `none` and not a safe id;
  - `## Steps to reproduce` without at least one `1.`-style numbered item;
  - each image in `## Attachments` (markdown `![..](..)`): external URL,
    absolute path, `..`, path not under `<stem>/` (stem = `path.stem` or
    `ticket_id` when known; skip the folder check when neither is known),
    extension not png/webp → error; file missing on disk when `path` is
    known → error;
  - `## Attachments` with neither an image nor an `N/A — <reason>` line →
    error.
  The report's verdict line must read `DoR: PASS` / `DoR: FAIL` exactly
  like a story's so CI and skills need no change.
- `bug-template.md`: per spec "Header lines", "Sections", severity table
  as an HTML comment, bug DoR boxes verbatim from the spec, `## Change
  log` table identical to the story template's. The template file itself
  must lint with errors only for placeholder content (test: a filled
  example built from the template lints `DoR: PASS`).
- Tests: valid bug PASS; valid hotfix PASS; each error above; story
  ticket unaffected; unknown type error; MCP-style call (no path) on a
  bug with images → shape checks only.

## Task 2: Publish bugs with their attachments

Files: `src/strata_kb/planingest.py`, `src/strata_kb/web/gfmrender.py`,
`src/strata_kb/ticketfetch.py`, `src/strata_kb/cli.py` (ticket fetch
command only), tests.

- `planingest`: L2 prose for a bug = `Summary`, `Steps to reproduce`,
  `Expected result`, `Actual result` (pick by `ticket.ticket_type`).
  For each published bug, copy every image referenced in
  `## Attachments` (resolved against the bug file's directory, same
  validation as Task 1) to `<doc_dir>/assets/<sha256>.<ext>` and rewrite
  the reference to `assets/<sha256>.<ext>` in that bug's L2 and L3. After
  writing, delete files in `<doc_dir>/assets/` no published bug
  references. A missing file → skip the bug with a reason (lint already
  catches it; this is defence).
  `_check_owned` / rmtree logic must keep working with an `assets/`
  subfolder.
- `gfmrender.render`: an `image` token whose `src` matches
  `^assets/[0-9a-f]{64}\.(png|webp)$` gets `src="/assets/<name>"`;
  every other src unchanged.
- `ticketfetch`: a helper `assets_of(hub, ticket_ref) -> list[Path]`
  (the files under the plan doc's `assets/` that the fetched text
  references); CLI `kb ticket fetch` copies them to
  `docs/impl/<id>/assets/` next to `ticket.md`. MCP behaviour unchanged.
- Tests: plan-ingest publishes a bug with one PNG → asset file exists,
  sha-named, refs rewritten, a second run with the image removed from the
  ticket deletes the asset; gfmrender rewrite; fetch copies assets.

## Task 3: Skills and `kb init`

Files: `templates/init/bodies/ba-bug-report.md`,
`templates/init/bodies/dev-fix-bug.md`, four wrappers per skill
(`claude-skill-<s>.md`, `claude-command-<s>.md`, `copilot-<s>.prompt.md`,
`cursor-<s>.md`), `src/strata_kb/initcmd.py`, `tests/test_init.py`,
`tests/test_templates.py`, `tests/test_template_bodies.py` if needed.

- Wrappers follow the existing pattern exactly: copilot/cursor are
  frontmatter + `<!-- strata-kb:include bodies/<s>.md -->`; the claude
  skill and command follow the shape of `ba-ticket-author` /
  `dev-implement-ticket` (frontmatter `name`/`description`, or
  `description`/`argument-hint` for commands). Prefer making the claude
  skill an include stub too if the include mechanism and tests allow it.
- `ba-bug-report` and `dev-fix-bug` workflows, hard rules and the Dev
  `## Next step` block exactly as the spec's "Skills" section.
  `dev-fix-bug` stays OUT of `DEV_WORKFLOW_SKILLS` canon (like
  `dev-code-seed`) and gets its own canon pins in tests (the Iron Law
  line "No fix without a failing reproduction test first", the
  three-failed-hypotheses stop, `rootcause.md`).
- `initcmd`: BA templates get the 4 `ba-bug-report` rows and
  `docs/tickets/BUG-TEMPLATE.md` ← `bug-template.md`; the DEV loop tuple
  gets `dev-fix-bug`. Update every pinned count/list in tests
  (`expected_files("dev")` 55 → 59, the BA lists, wrapper lists).
- `cli.py` `kb init` printed next-steps that list skills: add the new
  ones where the sibling skills are listed.

## Task 4: Docs and release

Files: `README.md`, `templates/init/QUICKSTART-ba.md`,
`templates/init/QUICKSTART-dev.md`, `docs/src/guide-ba.{en,vi}.md`,
`docs/src/guide-dev.{en,vi}.md`, `CHANGELOG.md`, `pyproject.toml`,
`uv.lock` (version line of the project only).

- One short section per doc: what a bug ticket is, the template, the
  skill, attachments rule (PNG/WebP in `tickets/bugs/BUG-<n>/`). VI guides
  in Vietnamese, matching their siblings' tone.
- CHANGELOG `## 1.25.0 — 2026-10-14` in the existing format, ending with
  an `**Upgrade.**` bullet (`kb init --kind ba|dev` again to get the new
  skills and BUG-TEMPLATE).
- Rebuild the four guide PDFs with `docs/src/build_pdf.py` only if its
  toolchain runs here; otherwise leave the PDFs and say so in the report.
- `tests/test_readme.py` and QUICKSTART pins still pass.
