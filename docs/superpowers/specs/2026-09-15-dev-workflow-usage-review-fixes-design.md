# Dev workflow + usage review fixes — machine anchors for the rules the wrappers only promise

**Status:** approved design, ready for an implementation plan
**Source:** reviewer F of the 2026-09-08 full framework review,
`docs/superpowers/reviews/2026-09-08-full-framework-review/F-dev-workflow-usage.md`
(findings H1…H3, M1…M8, L1…L10), and §5 đợt 3 item 2 of
`docs/superpowers/reviews/2026-09-08-full-framework-review.vi.md`.
**Predecessor:** `2026-09-14-ba-gates-review-fixes-design.md` (reviewer E,
merged as PR #50). That batch made the BA gate read section bodies; this
batch gives the Dev side's three load-bearing promises — evidence in the PR,
state in files, pinned content in the cache — a machine anchor each, and
prices the models Claude Code actually writes.
**Approach:** as approved on 2026-09-15 — split ownership of the context
cache (CLI writes the resolved half, agent the placeholder half); `kb pr
lint` reads the plan file from the checkout for `cmd.test`; a design file on
every path, with `status:` carrying the gate; `kb init --lang` plus depth 3
for language detection.

## Goal

Reviewer F scaffolded a dev repo, built a real hub, resolved a real ticket,
ran 12 real Claude Code transcripts through the usage ledger and diffed all
24 dev wrappers against each other. The CLI half holds: `kb init` preserves
what it promises (C16 met), `kb svc note` meets its contract (C13 met), the
usage dedup avoids an 87.9 % over-count on real data, cost math never fakes
a zero, and the 20-wrapper SHARED-* canon has no semantic divergence.

What does not hold is every rule the wrappers state as a rule:

- **H1** — `QUICKSTART-dev.md` §"What is enforced" lists TDD, shown
  verification, verbatim values and ticket read-only as enforced. None is;
  they are prompt text in 24 files. (The review also reports E1/E2 unbuilt;
  that was true at its snapshot and is stale — PR #45 shipped `prlint.py`,
  the PR template and `kb-pr-lint.yml`. What remains from H1 is the wording
  plus the two hardening asks in §6.1 of the review: the exemption slugs
  live only in prose, and `no-verification-output` accepts any fence.)
- **H2** — `dev-design` writes no file on the bounded and spike paths, while
  `dev-implement-ticket` derives state from the design file's existence and
  the 2026-08-19 spec promises "the design, plan and progress live in
  files". A session that dies after GATE 1 on a bounded ticket leaves zero
  artifacts; a resumed one renders `design ⬜ · plan ✅`. Plan-deleted,
  PR-closed-unmerged, branch-renamed and two-tickets-in-flight have no
  vocabulary at all.
- **H3** — no code touches `docs/impl/<id>-context.md`. A hand-edited body
  with an unchanged `version:`, or another ticket's cache copied into place,
  passes every check, and the file is gitignored, so the artifact the code
  is built from is the one the PR reviewer never sees.
- **M1** — `kb resolve` tells the operator to run `kb diff`, the one command
  SHARED-FRESHNESS forbids; in a dev repo it fails and exits 0.
- **M3** — 11.5 % of real API calls (`claude-fable-5-1`, plus bare `opus` /
  `sonnet`) are unpriced against the shipped table.
- **M4** — `est` / `assistant` are stored and never reported.
- **M5–M8** — the Java preset contradicts itself on indentation, the Python
  and TS presets do not lint the rules their own prose states, depth-3
  monorepos and manifest-less repos get no pack and no `CLAUDE.md`, and
  `conventions-<lang>.md` ("exactly as shown") contradicts `dev-plan`
  ("scope so it passes on the untouched tree").

## Decisions taken during brainstorming (2026-09-15)

1. **Scope: HIGH + MEDIUM + cheap LOW.** H1–H3, M1–M8, L2, L3, L4, L7.
   Deferred: L5 (lexicographic `hist.*` sort), L6 (`|`→`/` in L3), L8
   (copilot/cursor escape hatch), L9 (`*-context.md` gitignore breadth), L10
   (preset nits). L1 is already closed — `cli.py:190-197` guards the
   `--force` hint by `PROTECTED_FILES`.
2. **Cache anchor: split ownership.** `kb resolve --write-cache` owns
   everything above a marker (header, ref list, sha256, resolved sections);
   the agent owns the `## Placeholder map` below it. This reverses only the
   "CLI never writes the file" half of the 2026-08-24 C1 ruling; the reason
   for that ruling — the placeholder map is agent-verified — still holds
   for the half the agent keeps. Rejected: validate-only (no hash, so the
   hand-edited-body hole stays open) and committing the cache (reverses the
   no-hub-content-in-dev-history decision). MCP `kb_resolve` is untouched:
   the golden pins it, and the CLI flag is the only surface that grows.
3. **`cmd.test` source: the plan file in the checkout.** `kb pr lint` takes
   the ticket id from `## Ticket`, reads `docs/impl/<id>-plan.md`, and
   requires a Verification fence to contain the plan's `cmd.test`. Plan
   absent, id unparsed or no `cmd.test:` line → warning, exit unchanged.
   Rejected: a config key nobody sets (inert until configured); skipping
   the check.
4. **Language detection: depth 3 plus `kb init --lang`.** The flag is
   recorded in `.kb/config.yaml` so a plain re-init reuses it. Rejected:
   source-extension sniffing (a stray `scripts/x.py` pulls in the whole
   Python pack; a full-tree walk on every init).
5. **Design file on every path; `status:` carries the gate.** Existence no
   longer means approved. Spike ends at the design file.
6. **`kb usage note` defaults flip**: `--est` defaults to true (a hand-typed
   row is self-reported by definition; `--measured` overrides),
   `--assistant` becomes required.
7. **M8 resolved toward the conventions file.** The preset is the target
   strength; narrowing on an untouched tree is allowed and each narrowed
   rule is a `## Findings` entry. `dev-plan` points at that section instead
   of restating it.
8. **L7 fixed in `review.py`**, not by doc kind: `approve_sections` with
   `section_ids=None` skips `hist.*` because the `hist.` prefix is already
   a framework rule (Hard rule 12), so no `-svc` special case is needed.
9. **Release 0.23.0** — three new CLI surfaces (`resolve --write-cache` /
   `--cache`, `pr lint --plan-dir`, `init --lang`), no new dependency.

## Scope

In:

- `prlint.py`, `cli.py pr_lint` — slugs, `cmd.test` fence check, warning
  level, `--plan-dir`.
- `resolve.py`, `cli.py resolve` — `--write-cache`, `--status-only --cache`,
  the stale hint (M1).
- `usage/prices.py`, `usage/report.py`, `templates/usage/report.html.j2`,
  `templates/usage-prices.yaml`, `cli.py usage note / doctor /
  ingest-transcript` — aliases + suffix fallback, `est`/`assistant`
  reporting, hook-log surfacing, markdown staleness warning, no-mkdir guard.
- `conventions.py`, `initcmd.py`, `config.py`, `cli.py init` — depth 3,
  `--lang`, `langs:` persistence.
- `review.py`, `cli.py approve` — `hist.*` skip.
- Templates: `QUICKSTART-dev.md`; `conventions-{python,ts,java,go,dotnet,php}.md`;
  SHARED-FRESHNESS canon (20 wrappers); `dev-design`, `dev-plan`,
  `dev-execute`, `dev-handover`, `dev-implement-ticket` × 4 hosts (State
  line, status headers, state table, Ground wording, `cmd.*` lines).
- `docs/superpowers/specs/2026-08-19-dev-agent-design.md` — dated
  amendment note at the "Design artifact" decision row.
- Version bump to 0.23.0; CHANGELOG entry.

Out (deferred, see decision 1): L5, L6, L8, L9, L10; `kb doctor` reading
the cache (no path convention, one consumer today); branch protection (a
GitHub setting `kb init` cannot write); any change to the MCP tool surface.

## Design

### 1. `kb pr lint` hardening (H1)

**Exemption slugs.** `prlint.py` gains
`EXEMPTION_SLUGS = frozenset({"config", "ci", "docs", "style"})`, the four
rows of `tdd-exemptions.md`. The visible body of `## TDD exemptions` must be
exactly `none` (case-insensitive, alone) or consist only of lines matching
`^-\s*(?P<slug>[a-z]+)\s*[:—-]\s*\S` with `slug` in the set. Any other
non-blank line produces `unknown-exemption-class`, error level, message
naming the four slugs. `## Findings` stays free text.

**`cmd.test` in the Verification fence.** `lint_body(body, *, plan_dir:
Path | None = None)`.

- Ticket id: first match of `\b[A-Z][A-Z0-9]*-\d+\b` in the visible text of
  `## Ticket`.
- Plan: `plan_dir / f"{ticket_id}-plan.md"`; `cmd.test` is the first line
  matching `^cmd\.test:\s*(?P<cmd>\S.*?)\s*$`, backticks stripped from both
  ends of `cmd`.
- Check: some fenced block inside `## Verification` contains `cmd`
  verbatim. Fails with `verification-missing-cmd`, error level, message
  quoting `cmd` and the plan path.
- Degradations, each a **warning** finding with its own code and never a
  failure: `plan_dir` is None (`plan-dir-unset`), no ticket id
  (`ticket-id-unparsed`), plan file absent (`plan-missing`), no `cmd.test:`
  line (`cmd-test-unset`). A spike or a bounded ticket without a plan stays
  green; the warning is visible in the CI log.

**Levels.** `Finding` gains `level: Literal["error", "warning"] = "error"`.
`PRLintReport.passed` is true when no error-level finding exists; `render`
prints warnings under a `warnings:` heading after errors; `--json` carries
`level` per finding. The existing five codes stay `error`.

**CLI.** `kb pr lint` gains `--plan-dir PATH` (default `docs/impl`; `--no-plan`
is not needed — an absent directory is the `plan-missing` warning). The
scaffolded `kb-pr-lint.yml` already checks out the branch, so the default
finds the plan without a workflow change.

**Plan header.** `dev-plan` (4 hosts) writes two literal lines directly
under the plan's title, and the skill text says so instead of "names the
commands":

```
cmd.test: <command>
cmd.lint: <command>
```

**QUICKSTART.** §"What is enforced" becomes two lists. *Machine-enforced*:
`kb pr lint` (eight sections, comment stripping, a Verification fence
holding `cmd.test`, exemption slugs), `kb build` refusing `pending` sections
via `kb-code.yml`, `kb ticket lint` on the BA side. *Prompt-only — a rule
the wrappers state and nothing measures*: TDD-first, verbatim standard
values with citation, ticket read-only, GATE 1 and GATE 2, the per-task
review checkpoint, `OPEN(BA)` escalation. The second list uses the
Model-tiering section's own sentence shape ("nothing in `kb` enforces or
measures compliance with it"). The E1 paragraph's "once a released
`center-kb` carries `kb pr lint`" caveat is dropped — 0.23.0 carries it.

### 2. Context cache machine anchor (H3, M1)

**`kb resolve --write-cache PATH`** (mutually exclusive with
`--status-only`; both given → exit 1 before any hub access). After the
normal resolve, writes:

```markdown
# Context cache — <PATH stem>
> Written by `kb resolve --write-cache`. Do not hand-edit above the marker;
> regenerated on every full resolve. Gitignored.

version: <ctx.version>
refs: <sorted, comma-separated `repo_id:doc_id§section_id` — repo_id omitted when the ref has none>
sha256: <hex digest of the resolved block, bytes between the "## Resolved sections\n" line and the marker line, exclusive>
resolved: <YYYY-MM-DD>

## Resolved sections
<render_resolved(results) verbatim>

<!-- kb:placeholder-map -->
## Placeholder map
| placeholder | verified value | evidence (file:line or ref) |
|---|---|---|
```

- If PATH exists and contains the marker, everything from the marker line
  to EOF is carried over byte-for-byte; the agent's map survives every
  regeneration. No marker → the stub table above.
- Written with `newline="\n"`, UTF-8, parent directory created.
- Exit codes unchanged (ok 0, stale 2, broken 1). On `broken` the file is
  still written — the pinned bytes travel with the failure, exactly as they
  do on stdout today — and the skill's `broken → STOP` rule applies to the
  verdict, not the file.
- stdout is the same `render_resolved` output as without the flag, so
  `--write-cache` is a pure side effect; nothing that parses stdout changes.

**`kb resolve --status-only --cache PATH`.** After the verdict lines, the
CLI validates PATH and appends at most one line:

| condition | line | exit |
|---|---|---|
| file absent | `!! cache-missing: <PATH>` | 1 |
| header unparseable (missing `version:`/`refs:`/`sha256:`, or no marker) | `!! cache-invalid: header` | 1 |
| `version:` ≠ `ctx.version` | `!! cache-invalid: version <cache> ≠ ticket <ticket>` | 1 |
| `refs:` ≠ the ticket's ref set (as sets, same string form) | `!! cache-invalid: refs differ — <missing>/<extra>` | 1 |
| recomputed digest ≠ `sha256:` | `!! cache-invalid: resolved block edited since written` | 1 |
| all match | *(nothing)* | unchanged (0 / 2 / 1 from the verdicts) |

Exit code rule: an invalid or missing cache → 1, whatever the verdicts
said (a stale ticket with a bad cache exits 1, not 2 — the skill must
re-resolve either way). A valid cache → the existing verdict exit (0 / 2 /
1). `--cache` without `--status-only` → exit 1 usage error.

**Parsing** lives in `resolve.py` as `read_cache_header(text) ->
CacheHeader | None` and `cache_digest(text) -> str | None`; the CLI only
compares. `refs` string form is one helper used by both writer and checker.

**M1.** `render_resolved`'s stale line becomes
``!! {reason} — run `kb get {doc_id} {section_id} --level l3` for the current hub version``.
The tests that pin the `kb diff` wording flip to the new text.

**SHARED-FRESHNESS canon** (20 wrappers, first and last lines unchanged,
≤ 900 characters, hard-rules block untouched):

```markdown
## Freshness re-check (run this FIRST, every time)

Cheap check first: run `kb resolve --status-only --cache docs/impl/<ticket-id>-context.md <ticket-file>` (no CLI → `kb_resolve`, full output, then compare its `version:` to the cache header yourself). Exit 0 → use the cache; do NOT re-pull pinned content. Any `cache-*` line, no cache, or a non-ok verdict → `kb resolve --write-cache docs/impl/<ticket-id>-context.md <ticket-file>` (no CLI → `kb_resolve` and write the file in the same layout), then fill `## Placeholder map` below the marker — never edit above it.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: the resolve gives the pinned content and the reason, `kb get <doc-id> <section> [--level l3]` the current hub version. Do NOT use `kb diff` — it compares the local `.kb/` worktree to a local git rev, not this repo to the hub.
- **ok** → continue.
```

The exact wording is tuned in the plan against the ceiling; the three
verdict bullets and the `kb diff` trap sentence are pinned by
`test_shared_freshness_keeps_the_kb_diff_trap_and_the_three_verdicts` and
stay verbatim.

**`dev-implement-ticket`** Resolve and Placeholders steps: the cache is
written by the command; the agent edits only below the marker. The C1 spec's
"Written once by the orchestrator" sentence is superseded by this section.

### 3. State derivation (H2)

**Design file on every path.** `dev-design` writes
`docs/impl/<ticket-id>-design.md` on spike, bounded and architectural.
Header directly under the title:

```
path: spike | bounded | architectural
status: draft
```

Bounded body = the same few paragraphs that went to chat. Spike body = the
question, what was tried, the recommendation, and the sentence "anything
built for this is throwaway". Architectural unchanged.

**`status:` carries the gate.** After the Dev approves at GATE 1 the
orchestrator flips `status: approved` and only then invokes `dev-plan`;
`dev-plan` reads the header and refuses a `draft` design in one line. The
plan file carries the same `status:` line under its `cmd.*` lines, flipped
at GATE 2 before `dev-execute`. Existence no longer means approved.

**Spike terminates at the design file.** `plan` and `execute` are skipped;
State renders `plan n/a (spike) · tasks n/a`; the next step is
`dev-handover`, which writes the recommendation into the PR body's
`## Findings` (or, with no code to open a PR for, into a ticket comment the
Dev pastes). No code is kept.

**State table** in `dev-implement-ticket` (4 hosts), each row a probe and
the token it renders:

| case | probe | State token / action |
|---|---|---|
| design present, `status: draft` | header | `design 📝 draft` → offer GATE 1 |
| design approved, plan absent, `git log --oneline <default>..HEAD` non-empty | commit count N | `plan ⚠ missing, N commits on branch` → ask before running `dev-plan` |
| plan present, `status: draft` | header | `plan 📝 draft` → offer GATE 2 |
| PR merged | `gh pr list --head <branch> --state merged` | `PR ✅ merged` → flow done |
| PR closed unmerged | `--state closed` | `PR ❌ closed` → next = re-handover or reopen; never silently terminate |
| no branch matches `*<ticket-id>*` and HEAD is the default branch | `git branch --list` | offer `git switch -c <ticket-id>` |
| current branch names a different `[A-Z][A-Z0-9]*-\d+` id | branch name | STOP: "two tickets in flight; switch branches first" |
| `gh` unavailable | command missing | `PR ? unknown (gh not installed)` |

**State line vocabulary**, all five dev skills × 4 hosts:

```
State: design <✅ approved|📝 draft|⬜ not written> · plan <✅ approved|📝 draft|⬜ not written|⚠ missing, N commits|n/a (spike)> · tasks <n>/<m> · PR <✅ opened|✅ merged|❌ closed|⬜ not opened|? unknown>
```

**Spec amendment.** `2026-08-19-dev-agent-design.md`, decision row "Design
artifact", gets a dated note: superseded 2026-09-15 by this spec — a
one-paragraph file is the resume point, not ceremony; the gate moved from
existence to `status:`.

### 4. Usage (M3, M4, L2, L3, L4)

**M3 — price resolution.** `PriceTable.aliases: dict[str, str] = {}`;
the packaged table ships `aliases: {opus: claude-opus-5, sonnet:
claude-sonnet-5, haiku: claude-haiku-4-5}`. `resolve_model(table, model) ->
str | None` tries, in order: exact key in `models`; `aliases[model]`; then
strips one trailing `-<digits>` segment at a time (`claude-fable-5-1` →
`claude-fable-5`, `claude-opus-5-2-1` → `claude-opus-5-2` → `claude-opus-5`)
and retries the exact/alias steps at each stage. `cost_of` uses it.
`Aggregate.priced_as: dict[str, str]` records every raw id that resolved to
a different table id; markdown and HTML footers list them as
`claude-fable-5-1 priced as claude-fable-5`. The override file
(`.kb/usage-prices.yaml`) merges `aliases` per key like `models`.
`by_model` keeps the raw id as its key.

**M4 — `est` / `assistant` reported.** `Bucket.est_rows: int = 0`;
`Aggregate.by_assistant: list[Bucket]`. Markdown: the total row gains
` (N estimated)` when `est_rows > 0`; an `assistant: <name>` row per
assistant follows the phase rows. HTML: the same suffix on the total and a
"By assistant" table. JSON: both fields via `model_dump`. `kb usage note`:
`--est/--measured` defaults to `--est`; `--assistant` has no default and is
required (typer `...`).

**L2 — no ghost ledger.** `_usage_log_error` no longer creates
directories: when `<kb_dir>/usage/` does not exist it returns without
writing. The wrong-cwd hook case therefore leaves nothing behind; there is
no correct place to write from the wrong directory.

**L3 — hook failures surface.** `kb doctor` on `ba` and `dev` kinds: when
`.kb/usage/ingest-errors.log` exists and is non-empty, one warning
`N hook ingest error(s) logged — last: <last line>; truncate the file once
handled`. `kb usage report` (markdown, HTML, JSON `hook_errors: N`) carries
the same count as a footer line.

**L4 — markdown staleness.** `render_markdown` prefixes its footer with
`**Warning: price table is N days old — update .kb/usage-prices.yaml.**`
when `agg.stale`; HTML and JSON already do.

### 5. Conventions (M5, M6, M7, M8)

**M5** `conventions-java.md`: `.editorconfig` `[*.java] indent_size = 2`;
`maxWarnings = 0` removed from the shipped checkstyle block, with the prose
"set `maxWarnings = 0` once the tree is clean" under the tightening rule.

**M6** `conventions-python.md` ruff `select` adds `"T20"` (print) and `"N"`
(naming). `conventions-ts.md` `eslint.config.mjs` adds
`{ rules: { "no-console": "error" } }` as the last config entry.

**M8** every `conventions-<lang>.md` Linting section (python, ts, java, go,
dotnet, php) replaces "creates the files below exactly as shown" with:

> The preset below is the target strength. The plan's first task creates
> these files and records the command as `cmd.lint`. Where `cmd.lint` fails
> on the untouched tree, narrow `select` / rules / warning caps to what
> passes, and list each narrowed rule under `## Findings` in the PR body as
> a tightening still owed.

`dev-plan` (4 hosts) drops its own "scope the initial config" sentence and
points at "the Linting section of `docs/conventions/<lang>.md`".

**M7** `detect_langs` prefixes become `("", "*/", "*/*/", "*/*/*/")`.
`kb init --lang <id>` (repeatable) validates against the `LANG_MANIFESTS`
ids and exits 1 naming them on an unknown id. `Config.langs: list[str] =
[]`; `initcmd` records the flag append-only into `.kb/config.yaml` as
`langs: [python, ts]` with the `_record_kind` shape (never rewrites user
content), and a plain re-init reads `langs:` back. `scaffold_conventions
(target, report, forced)` scaffolds the sorted union of detected and forced;
`ensure_claude_block` runs whenever that union is non-empty. The zero-lang
note ends "— or pass `--lang python`".

### 6. Ground wording (M2)

`dev-implement-ticket` Ground bullet (4 hosts), replacing the two "is
missing whenever" clauses:

> A document missing from the hub means either not yet generated
> (`kb code-ingest` for `-code`, `dev-code-seed` for `-svc`) or generated and
> not yet published — check `.kb/<repo_id>-code/` and `.kb/<repo_id>-svc/`
> locally. Present locally → say "generated, unpublished: run `kb publish`"
> in one line; absent → "not generated". Reads stay hub-only either way.

### 7. `kb approve` and `hist.*` (L7)

`approve_sections(section_ids=None)` skips section ids starting `hist.`
and returns them in a new `ApproveReport.skipped_machine` list; naming one
with `--section hist.api` still approves it. The CLI prints
`[note] §hist.api is machine-authored — skipped (pass --section to force)`.

### 8. Release

`pyproject.toml` 0.22.0 → 0.23.0. CHANGELOG entry listing the three new CLI
surfaces and the wrapper canon change. `expected_files('dev')` stays 49
(`tests/test_init.py:1736`; no new scaffold files) — the plan re-checks the
trip-wire after the template edits.

## Error handling

- `--write-cache` write failure (permission, missing parent that cannot be
  created) → red message, exit 1, after stdout already carried the resolve
  output.
- `--cache` file unreadable (OSError) → `cache-invalid: header`, exit 1.
- `pr lint --plan-dir` pointing at an unreadable plan file → treated as
  `plan-missing` warning, never a crash on CI.
- `--lang` unknown id → exit 1 before any file is written.
- `kb usage note` without `--assistant` → typer's own missing-option error.
- Hook path: unchanged contract — always exit 0, nothing on stdout.

## Testing

TDD per module; the checks below are the plan's red steps.

- `test_prlint.py`: slug accept (`none`, `- config: bumped ruff`, `- docs —
  README`), reject (`Exempt: deadline`, `- speed: …`); `cmd.test` present in
  fence passes, absent fails, backticked `cmd.test:` line stripped; each
  degradation is a warning and `passed` stays true; `--json` carries
  `level`.
- `test_cli_prlint.py`: `--plan-dir` default, warning rendering.
- `test_resolve.py`: `--write-cache` layout, marker carry-over
  byte-for-byte, digest recompute, each `cache-*` row of the table with its
  exit code, `--cache` without `--status-only` → 1, both flags → 1, M1 hint
  text.
- `test_templates.py`: SHARED-FRESHNESS ceiling ≤ 900 and needles; new
  needles for `--write-cache` / `--cache`; State-line vocabulary parity
  across the 20 dev wrappers; `status:` header text in dev-design and
  dev-plan; `cmd.test:` line in dev-plan; Ground wording; QUICKSTART two
  lists present and the four prompt-only rules named there; M8 sentence in
  all six conventions files; `test_init.py` trip-wire recount.
- `test_usage_prices.py`: alias hit, one- and two-step suffix strip,
  override merge of `aliases`, unknown still None. `test_usage_report.py`:
  `priced_as`, `est_rows`, `by_assistant` in all three renderers,
  markdown warning line when stale, `hook_errors`. `test_cli_usage.py`:
  `note` requires `--assistant`, defaults to est; L2 no-mkdir; doctor
  warning on a non-empty log.
- `test_conventions.py`: depth-3 hit, `--lang` union, `langs:` recorded and
  re-read, unknown id exits 1, `CLAUDE.md` written for a forced lang.
- `test_review.py` (or the approve suite): `hist.*` skipped by default,
  approved when named.
- Regression: full suite green, `uv lock --check` unchanged (no deps).

## Acceptance

1. A PR body whose `## TDD exemptions` reads `Exempt: deadline` fails
   `kb pr lint`; `- docs: README only` passes.
2. With `docs/impl/T-7-plan.md` containing `cmd.test: pytest -q`, a
   Verification fence without `pytest -q` fails; with it, passes; with no
   plan file the lint passes and prints a `plan-missing` warning.
3. `kb resolve --write-cache docs/impl/T-7-context.md T-7.md` then
   `kb resolve --status-only --cache … T-7.md` exits 0; editing one byte
   above the marker → `cache-invalid: resolved block edited`, exit 1;
   copying `T-8-context.md` over it → `cache-invalid: refs differ`, exit 1;
   editing the placeholder map → still 0.
4. The stale hint names `kb get … --level l3`, never `kb diff`.
5. `kb init --kind dev` on a bounded ticket's repo: `dev-design` produces
   `docs/impl/<id>-design.md` with `path: bounded` / `status: draft`; the
   State line renders `design 📝 draft` until GATE 1.
6. Pricing the reviewer's 12 transcripts: `claude-fable-5-1` calls priced
   at the `claude-fable-5` rate and listed under "priced as"; `opus` /
   `sonnet` rows priced; `unpriced` only for genuinely unknown ids.
7. `kb usage report --md` shows `(N estimated)` after one `kb usage note
   --assistant copilot` row, and a bold warning line once the table is
   over 90 days old.
8. `apps/web/frontend/package.json` alone → `['ts']`; `kb init --kind dev
   --lang python` on a manifest-less repo scaffolds the Python pack and
   `CLAUDE.md`, and a plain re-init keeps it.
9. `kb approve <repo>-svc` reports `§hist.api` skipped; `kb approve
   <repo>-svc --section hist.api` approves it.
10. QUICKSTART-dev's "What is enforced" names no rule that `kb` does not
    check.
