# E1 + E2 — a machine-checked PR description gate and named TDD exemptions

**Status:** approved design, ready for an implementation plan
**Roadmap items:** E1 and E2 of
`docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md` (batch 7).
**Approach:** as approved on 2026-09-05 — one new text-only linter
(`kb pr lint`) enforced by one new scaffolded workflow, plus a scaffolded
reference document that names the TDD exemption categories. The
SHARED-HARD-RULES canon is not touched, `template_map()` gains three static
rows, and there is no MCP change, no schema change, no new MCP tool.

## Goal

E1 and E2 are the two remaining engine items before the E3 pilot. They close
the same hole from two sides: today nothing but reviewer goodwill stops a PR
that claims completion without evidence, and nothing names the change classes
where a red-test-first is impossible — so "no test here" is settled ad hoc,
mid-implementation, by the agent that wants to be done.

After this batch, a dev repo scaffolded by `kb init --kind dev` gets:

- a **PR description template** whose section list is the one `dev-handover`
  already assembles (E1),
- a **CI gate** that fails the PR when a required section is missing, is still
  the unfilled template, or — for the verification section — carries a
  completion claim with no pasted output (E1),
- a **`docs/tdd-exemptions.md`** reference naming four exemption categories
  and the substitute verification each one owes (E2),
- and dev-skill text that makes an exemption a **plan-time declaration**
  carried in the task block, never a mid-implementation decision (E2).

## Decisions taken during brainstorming (2026-09-05)

1. **E1 is enforced by machine, from day one.** The roadmap is internally
   inconsistent — the group heading says "củng cố kỷ luật bằng máy", the E1
   line says "quy ước reviewer từ chối". The heading wins: a template with no
   gate is decoration. No warning-first phase: unlike the A2 tag check there
   is no backlog of existing PR bodies to clean, and the check is a
   deterministic heading-presence test, not a judgement call.
2. **Kind `dev` only.** The E1 payload (AC→test map, verification output) is a
   Dev-side artifact. A BA repo already has its own gate,
   `.github/workflows/kb-ticket-lint.yml`. A single template stretched across
   hub/child/ba/dev would have to drop every section that gives it teeth.
3. **E2 lives in its own document, not in the hard rules.** The existing hard
   rule — *"No production code without a failing test observed first. No
   exception for small tickets, deadlines, or 'obvious' changes."* — stays
   byte-identical. Config, CI, docs and style changes are not production code,
   so naming them does not contradict the rule; the document defines what
   counts as production code. Rejected: adding a pointer line to
   SHARED-HARD-RULES (a 20-file byte-identical edit plus a deliberate break of
   `test_shared_hard_rules_were_not_touched_by_the_c5_round`, bought for a
   pointer); inlining the categories into two skills' prose (the duplicate that
   D3 had to solve for conventions).
4. **E2 reuses the E1 gate; no second engine.** The exemption becomes visible
   because the PR body must carry a `## TDD exemptions` section, which
   `kb pr lint` checks like any other. Rejected: a `kb plan lint` that parses
   `docs/impl/<id>-plan.md` — earlier detection, but a new parser over prose,
   and by far the most expensive engine in the batch.
5. **Drift is held by trip-wire tests, not by generating the template.** The
   required-section list exists in three places (the template resource, the
   linter module, the `dev-handover` prose). `REQUIRED_SECTIONS` in the module
   is canon; tests pin the other two against it. Rejected: rendering the
   template from code at init time — it breaks the "every row of
   `template_map()` is a static package resource" invariant and complicates
   the `--force` / protected-file path.
6. **center-kb does not dogfood this batch.** This repo is the package repo,
   not a scaffolded dev repo: it has no BA ticket and no `kb-context`, so five
   of the eight sections are meaningless here. Adopting a PR gate for this repo
   is its own batch with its own section list.

## Scope

**In:**

- `src/center_kb/prlint.py` — new module: the required-section canon and the
  body linter.
- `src/center_kb/cli.py` — new `pr` sub-app with one command, `kb pr lint`.
- `src/center_kb/initcmd.py` — three new rows in `DEV_TEMPLATES`.
- `src/center_kb/templates/init/` — 3 new resources
  (`pull-request-template.md`, `kb-pr-lint.yml`, `tdd-exemptions.md`) and
  1 edited resource (`QUICKSTART-dev.md`).
- Skill-text round, 3 skills × 4 wrappers: `dev-plan`, `dev-execute`,
  `dev-handover` — body prose only, outside every SHARED-* block.
- `tests/test_prlint.py` (new), `tests/test_templates.py`,
  `tests/test_init.py`.

**Out, and deliberately so:**

- **E3 (pilot).** Operations, not code; it consumes what this batch ships.
- **`kb usage merge`**, usage reporting in `ba-mission-plan`, `kb usage serve`,
  and a CI job that regenerates `report.html` — carried-over B-group items,
  unrelated to the gate.
- **A PR gate for this repo** (decision 6).
- **Any check of the *content* of the AC→test map** (that the named tests
  exist, that they map onto real ACs). Presence and non-emptiness only; content
  checking needs the ticket and the test suite, which is a different engine.
- **Any MCP surface change.** No sixth tool, no schema or docstring edit to the
  five existing ones; `tests-gate/golden` stays byte-identical.

## Evidence this design rests on

Verified in the tree at `d1969f4`:

- `dev-handover` already assembles the section list this template freezes —
  ticket id, kb-context refs, AC→test map, placeholder resolutions, `OPEN(...)`
  findings, verification output, KB gaps
  (`src/center_kb/templates/init/claude-skill-dev-handover.md:54-60`), plus the
  `## Usage` table added by B4 (same file, `:61-68`). The list is not new work;
  it has never been enforced.
- No PR template exists anywhere: not in this repo (`.github/` holds only
  `prompts/` and `workflows/`) and not among the 45 rows of `DEV_TEMPLATES`
  (`src/center_kb/initcmd.py:98-147`).
- `docs/ac-quality.md` (`src/center_kb/initcmd.py:86`) is the precedent for a
  scaffolded reference document a skill points at — `docs/tdd-exemptions.md`
  is its Dev-side twin.
- The three SHARED-* blocks are pinned byte-identical across 20 wrapper files
  against canon text (`tests/test_templates.py:286-311`, `:373-394`), and the
  hard-rules block additionally carries a no-touch test from the C5 round
  (`tests/test_templates.py:1217`). Keeping this batch's edits in wrapper
  *bodies* keeps both green with no canon re-extraction.
- `tests/test_init.py:1434` pins `len(expected_files("dev")) == 45`; three new
  rows make it 48. `PROTECTED_FILES` (`src/center_kb/initcmd.py:156-158`) holds
  only `.kb/index.yaml`, `.kb/config.yaml`, `.claude/settings.json`, so all
  three new files refresh normally on re-init.
- `kb-ticket-lint.yml` is the house pattern for a scaffolded required check:
  `pip install center-kb` (`:40`), a frozen workflow/job name because branch
  protection keys on it (`:7-11`), and **no `paths:` filter**, because GitHub
  never synthesises a passing status for a job that never started, so a
  path-filtered required check leaves unrelated PRs waiting forever
  (`:13-19`). All three carry over.
- `cli.py:21-41` is the sub-app pattern (`context`, `assets`, `ticket`,
  `mission`, `svc`, `usage`); `pr` joins it unchanged.

## Design

### §1 Engine — `src/center_kb/prlint.py` and `kb pr lint`

Pure text. No hub access, no git, no network, standard library only — so
**`uv.lock` does not change** and the T2 lock gate does not fire.

```python
REQUIRED_SECTIONS: tuple[str, ...] = (
    "Ticket",
    "kb-context",
    "AC→test map",
    "Placeholder resolutions",
    "Verification",
    "TDD exemptions",
    "Findings",
    "Usage",
)

SENTINEL_SECTIONS: frozenset[str] = frozenset({"TDD exemptions", "Findings"})
```

**Parsing.** Normalise CRLF, then split on level-2 ATX headings: a line
matching `^##[ \t]+(?P<name>.+?)[ \t]*$`. A section runs to the next `#` or
`##` heading, or to end of body. `###` and deeper are content, not section
boundaries — a sub-heading inside `## Verification` must not truncate it.
Heading names are compared after whitespace-stripping and are **case-sensitive**,
with one deliberate tolerance: `AC→test map` also matches the ASCII spelling
`AC->test map`, because the arrow is the only non-ASCII character in the
vocabulary and a hand-typed body will get it wrong. The template ships `→`.

**Findings.** Each is `(section, code, message)`; any finding means exit 1.

| code | condition |
|---|---|
| `missing-section` | no `##` heading with that name |
| `duplicate-section` | the name appears more than once |
| `empty-section` | the section's content is empty once HTML comments are stripped |
| `no-verification-output` | `## Verification` carries no fenced code block with a non-blank line inside |

**Emptiness is the load-bearing rule.** Content is measured *after* removing
`<!-- … -->` spans, non-greedy and across lines. An unterminated `<!--` is
treated as commented through the end of the section — the conservative
direction: it reads as empty and fails, rather than passing on text nobody can
see. Without this rule an untouched, copy-pasted template passes every check
and the gate is decoration; the test in §4 that asserts the *shipped template
itself fails the linter* exists to keep this rule honest.

**The sentinel.** In `TDD exemptions` and `Findings` — the two sections that
legitimately have nothing to report — content whose stripped text is `none`
(case-insensitive, optionally wrapped in backticks or emphasis) is valid and
explicit. It distinguishes "nothing to report" from "not filled in". Elsewhere
`none` gets no special handling.

**Rule `no-verification-output`** catches exactly the failure the hard rules
already forbid in prose ("Never claim done without showing the verification
output"): a `## Verification` section reading *"tests pass"* has content, so
emptiness would let it through; requiring a fenced block does not.

**CLI.**

```
kb pr lint <source> [--json]      # source: a file path, or '-' for stdin
```

Signature copied from `kb ticket lint` (`src/center_kb/cli.py:1529-1603`): a
positional source with `-` meaning stdin, an optional `--json` report, exit 0
clean and 1 on findings, and the same explicit `UnicodeDecodeError` / `OSError`
handling with the path in the message.

There is deliberately **no option that takes the body as a string**. A PR
description is attacker-controlled text; keeping a file and stdin as the only
ways in means no call site is tempted to interpolate it into a shell command.

### §2 The three template resources

**`pull-request-template.md` → `.github/pull_request_template.md`.** The eight
required headings in canon order, each followed by an HTML comment explaining
what belongs there and — for `TDD exemptions` and `Findings` — that `none` is a
valid answer. Because every section's only content is a comment, the shipped
file fails `kb pr lint` by construction. That is intended: a PR author who
deletes nothing and writes nothing gets a red check, not a green one.

**`kb-pr-lint.yml` → `.github/workflows/kb-pr-lint.yml`.**

```yaml
name: kb-pr-lint
on:
  pull_request:
    types: [opened, edited, synchronize, reopened]
permissions:
  contents: read
jobs:
  pr-lint:
    runs-on: ubuntu-latest
    env:
      PR_BODY: ${{ github.event.pull_request.body }}
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install center-kb
      - name: Check the PR description
        run: |
          printf '%s' "$PR_BODY" > "$RUNNER_TEMP/body.md"
          kb pr lint "$RUNNER_TEMP/body.md"
```

Four points, each of which is a comment in the shipped file:

- **`types:` must be spelled out.** The default set for `pull_request` is
  `opened, synchronize, reopened` — it does **not** include `edited`, and
  editing the description is precisely the event that must re-run this check.
- **No `paths:` filter**, for the reason frozen into `kb-ticket-lint.yml:13-19`.
- **The body reaches the script through `env:`, never through `${{ }}`
  inside `run:`.** Interpolating a PR description into a shell script is
  script injection with an attacker-supplied payload; the env indirection is
  the whole mitigation, and §4 pins it with a test.
- **No `actions/checkout`, no hub URL, no token.** The check is pure text, so
  it runs green on pull requests from forks, where `kb-ticket-lint`'s hub
  credentials would not be available. The job name `pr-lint` is frozen for
  branch protection.

**`tdd-exemptions.md` → `docs/tdd-exemptions.md`.** Opens with the boundary
rule, which governs the table beneath it:

> An exemption is a property of a **change class with no observable
> behaviour** — never of a ticket's size, a deadline, or how obvious the change
> looks. The moment a change alters behaviour an AC can see, no exemption
> applies, whatever the file extension. And an exemption is declared **when the
> plan is written**; it is never a decision taken mid-implementation.

| Slug | Covers | Substitute verification |
|---|---|---|
| `config` | config files, dependency bumps, scaffold changes | run the thing just configured and paste the output (build, `kb doctor`, service start) |
| `ci` | workflow, job, gate definitions | that workflow's own run on this PR — link and status |
| `docs` | README, QUICKSTART, prose, skill text | paste the diff and the link check; **not exempt where the repo has a test that pins that content** |
| `style` | formatting, renames, file moves with no behaviour change | the existing suite green before *and* after, plus the command that shows behaviour is unchanged |

The `docs` caveat is deliberately not an extension whitelist: this very
repository pins template text with canon tests, so a "docs" change here still
owes a test. The question is always *"is there a test that can observe this?"*,
never *"what is this file's extension?"*.

### §3 Skill text — 3 skills × 4 wrappers, plus QUICKSTART

Every edit lands in wrapper **bodies**. No SHARED-FRESHNESS, SHARED-HARD-RULES
or SHARED-NEXT-STEP block is touched, so `SHARED_BLOCK_TEXT` needs no
re-extraction and the C5 no-touch test stays green.

- **`dev-plan`** — a task with no test step must carry exactly one line,
  `Exempt: <config|ci|docs|style> — verified by <what>`, with the slug taken
  from `docs/tdd-exemptions.md`. Slugs are not invented; a change that fits
  none of the four is not exempt.
- **`dev-execute`** — the per-task subagent contract already hands over the
  task block and nothing else, so the declaration travels with the task. A
  block carrying `Exempt:` skips step 1 (write the test, observe it red) and
  **must instead run the declared substitute verification and show its
  output**. A block with no `Exempt:` line whose implementer believes no test
  is possible **stops and returns to `dev-plan`** — the same shape as the
  existing `OPEN(BA)` route, not a new mechanism, and specifically not a
  decision the implementer may take alone.
- **`dev-handover`** — the assemble step gains `## TDD exemptions`, collecting
  every `Exempt:` line from the plan, or the word `none`; and the assembled
  description is stated to be the eight canon sections, matching the scaffolded
  template.
- **`QUICKSTART-dev.md`** — one line telling the Dev to add `pr-lint` to the
  branch's required checks. `kb init` writes workflow files but cannot turn on
  branch protection, and a repo scaffolded before this batch gains the file on
  re-init while its protection settings stay untouched.

### §4 Tests and trip-wires

**`tests/test_prlint.py` (new)** — missing heading; duplicate heading;
comment-only content; the `none` sentinel accepted in the two sentinel sections
and unremarkable elsewhere; `## Verification` prose with no fence rejected and
with a fence accepted; CRLF input; trailing whitespace after a heading; `###`
not treated as a section boundary; the ASCII `AC->test map` spelling accepted;
an unterminated `<!--` reads as empty; an empty body reports all eight sections
missing rather than crashing.

**`tests/test_templates.py`** —

- the headings in `pull-request-template.md` equal `REQUIRED_SECTIONS`, in
  order (canon pin, place 1 of 3);
- every section name appears in all four `dev-handover` wrappers (place 2 of 3;
  place 3 is the module itself);
- **the shipped template fails `kb pr lint`** — the proof that the
  comment-stripping rule is real;
- the workflow lists all four `types:`, has no `paths:` key, and names the job
  `pr-lint`;
- the string `github.event.pull_request.body` does **not** appear inside the
  workflow's `run:` block — the injection mitigation pinned as a test rather
  than left as an intention;
- `tdd-exemptions.md` carries all four slugs and the boundary rule;
- the `dev-plan` and `dev-execute` wrappers name `docs/tdd-exemptions.md` and
  the `Exempt:` line shape, asserted against wrapper **bodies** so the shared
  blocks cannot satisfy the needle.

**`tests/test_init.py`** — `len(expected_files("dev"))` bumped 45 → 48
deliberately; the three new paths present for kind `dev` and absent for `hub`,
`child`, `ba`.

**Batch exit criteria** — the full suite green (1873 passed / 5 skipped before
this batch, plus the new tests), and
`git diff main...HEAD -- tests-gate/golden src/center_kb/mcp.py` **empty**.

## Error handling

- **A malformed body never crashes the linter.** Empty, whitespace-only, or
  heading-free input produces eight `missing-section` findings and exit 1.
- **An unreadable or non-UTF-8 source file** exits non-zero with the path in
  the message — worded distinctly from a lint failure, since in CI it means the
  workflow is broken, not the PR.
- **An unterminated HTML comment** fails closed (section reads empty).
- **A PR with an empty description** fails the gate. That is the intended
  behaviour, not an edge case to soften.
- **Existing dev repos** get the three files on the next `kb init`; nothing is
  protected, nothing is lost. Their branch protection is unchanged until a
  human follows the QUICKSTART line — the gate runs and reports, but is not
  required, until then.

## Sequencing

1. `prlint.py` + `tests/test_prlint.py` (engine first, no scaffolding yet).
2. `kb pr lint` wired into `cli.py`.
3. The three template resources + the `DEV_TEMPLATES` rows + the `test_init.py`
   bump.
4. The `test_templates.py` trip-wires, including the shipped-template-fails
   test and the injection pin.
5. The skill-text round (3 skills × 4 wrappers) + the QUICKSTART line.

Steps 1–2 and 3–4 are independent enough to review separately; step 5 depends
on §2's document existing, since it points at it.
