# Reviewer F — Dev side: 5-skill workflow, `kb init` scaffold, conventions pack, C1 cache, `kb svc note`, usage measurement, E1/E2

Criteria in scope: **C11, C13, C14, C16** (with side observations touching C1/C2/C7).
Repo read-only throughout; every experiment ran in
`…/scratchpad/F/` (`devrepo`, `svcrepo`, `hub`, `nolang`, `mono`, `crlf`).

---

## 1. Scope & method

Exercised, not merely read:

| What | How |
|---|---|
| Scaffold + overwrite policy (C16) | fresh git repo with `pyproject.toml` + `package.json` + `src/`, `kb init --kind dev`, five hand-edits, plain re-init, `--force`; plus a no-language repo, a 3-level monorepo, and a CRLF `CLAUDE.md` with no trailing newline |
| `detect_langs()` | 13 synthetic trees (depth 0–3, skip-dirs, hidden dirs, dir-named-like-a-manifest, `requirements-dev.txt`, `.kts`); symlink loop not creatable (Windows privilege) |
| Skill discipline | read all 6 claude-skill files as the executing model; machine-diffed all 4 wrappers × 6 skills after frontmatter strip + line-unwrap + emphasis strip |
| C1 cache | built a real federation hub, resolved a real ticket, ran `kb resolve` and `--status-only` (ok / stale / broken / no-block), traced every `-context.md` reference in `src/` |
| Usage (C14) | synthetic 12-row transcript with all 9 requested cases; ingest → re-ingest → `--md` → HTML → `--json`; hook via stdin (good payload, garbage payload, wrong cwd); **plus 12 real Claude Code transcripts (56 308 rows) priced offline** |
| `kb svc note` (C13) | scratch repo with `docker-compose.yml`, `code-ingest --scaffold-svc`, 5 notes, unknown service, `--refs`, pipe-in-title, both desync directions, `kb build` before/after fill and approve |
| E1/E2 (C11) | grep for every artifact the 2026-09-05 spec names; `len(expected_files('dev'))` |
| Regression | `tests/test_init.py test_conventions.py test_svcnote.py test_devcodeseed.py test_cli_context.py` → **192 passed, 4 skipped**; `test_templates.py` + 5 usage suites → **239 passed** (foreground, ~62 s total) |

---

## 2. Verified good

1. **Scaffold count matches the trip-wire.** `kb init --kind dev` created **54** files = the 45 rows pinned at `tests/test_init.py:1434` + 8 conventions files (python + ts × 4) + `CLAUDE.md`. No stray files, no missing wrapper.
2. **C16 preservation is exactly as advertised.** After hand-editing five files and re-running `kb init --kind dev`, SHA-256 was unchanged for `.kb/config.yaml`, `.kb/index.yaml`, `.claude/settings.json`, `docs/conventions/python.local.md` and `CLAUDE.md`; only the package-owned wrapper (`.claude/skills/dev-design/SKILL.md`) was refreshed — and `QUICKSTART-dev.md:265-266` warns about exactly that in advance. `--force` then replaced `config.yaml` + `settings.json` and **still** refused `*.local.md` and `CLAUDE.md`.
3. **`ensure_claude_block` is idempotent and byte-preserving.** On a `CLAUDE.md` written as CRLF with no trailing newline, the appended block is LF and every pre-existing byte survives (`od -c`: `…newline)\n\n<!-- kb:conventions -->`); two further `kb init` runs left the SHA identical.
4. **`kb resolve --status-only` works and is genuinely cheap.** Verdicts and exit codes correct in all four states: ok→0, stale→2 (after a real hub commit), broken→1, missing block→1 with `no 'kb-context:' block found in the text`. Content suppressed, header + reason retained.
5. **Usage dedup is load-bearing and correct.** On 12 real transcripts: 5 625 rows carrying `usage` collapse to **2 993 unique API calls** — keying on the row would over-count by **87.9 %** (the spec measured 55.8 %; the real figure here is worse, so the fix matters more, not less). Every row had a `requestId`.
6. **Usage attribution hardening holds.** A `<command-name>dev-handover</command-name>` and a `tickets/EVIL.md` path planted inside a `tool_result` moved neither cursor; `tickets/../../etc/passwd.md` was rejected outright; a `Skill` call naming `superpowers:brainstorming` did not set a phase. Sidechain flagged; `usage`-less rows skipped; `_unattributed` bucket populated; second ticket separated into its own ledger.
7. **Cost arithmetic is right and never fakes a zero.** Hand-checked against `usage-prices.yaml`: sonnet-5 row = \$0.03675, opus-5 = \$0.06125, haiku-4-5 = \$0.01225 → reported T-1 \$0.11, T-2 \$0.06, total \$0.21. An unknown model shows `(+1 unpriced)`, never \$0.00.
8. **HTML report escapes hostile input.** A model id of `<script>alert('xss-model')</script>` renders as `&lt;script&gt;…`; `grep -c "<script" report.html` = **0**.
9. **Re-ingest is idempotent**: `0 new row(s), 6 already recorded`, files byte-unchanged.
10. **`kb svc note` (C13) meets its contract.** Idempotent per (ticket, service) — `created` then `updated`, `notes: 1`. Unknown service → **exit 1** with a genuinely actionable message (names where to copy the id, warns about the 6-hex suffix, points at the CI-snapshot cause). L3 is a fenced `text` stanza with **no pipe table**. `--refs` preserved verbatim in L2. Manifest→file desync detected (`exit 1`) *and* `kb build` fails on it; the reverse desync (manifest entry deleted, heading kept) recovers gracefully, re-parsing and preserving all 4 existing rows.
11. **`kb build` gate on `-svc` works**: exit **1** while `svc.*` are `pending`, **0** after L2 bodies are filled, **0** after `kb approve` — the "unreviewed knowledge cannot reach the hub" claim is real.
12. **The 20-wrapper SHARED-* canon genuinely holds.** A normalised diff of all four wrappers for all six dev skills found **no semantic divergence** in the Freshness, Hard-rules or Next-step blocks. The only differences are host-tool naming (`kb_search`/`kb_get_section` vs `kb query`/`kb get`) and the `claude-command` shims' condensed restatement — with one exception, see L8.
13. **Price table keys match this environment's real transcripts** for the dominant model (`claude-opus-5`, 4 779 rows) — the alias-vs-dated-id trap I expected is not present. (But see M3.)

---

## 3. Findings

### HIGH

---

**H1 — No dev "Hard rule" is machine-enforced, yet `QUICKSTART-DEV.md` asserts four of them are "enforced". (C11)**

A repo scaffolded by `kb init --kind dev` contains exactly **one** CI workflow and **one** hook:

```
$ ls .github/workflows/        →  kb-code.yml     # validates the KB, not the code discipline
$ cat .claude/settings.json    →  one Stop hook: kb usage ingest-transcript --hook-stdin
                                  (always exits 0, never blocks)
```

No pre-commit hook, no PR template, no plan linter, no test-count gate. The 14-line `## Hard rules` block repeated in all 24 dev wrappers (`claude-skill-dev-execute.md:81-96` et al.) is pure prompt.

`src/center_kb/templates/init/QUICKSTART-dev.md:165-176` is headed **"What is enforced"** and lists TDD, shown verification, verbatim pinned values and ticket read-only. None is enforced by anything. The same file's Model-tiering section (`:356`) shows the project knows how to be honest about this — *"A recommendation, not a rule — nothing in `kb` enforces or measures compliance with it."* — so the calibration gap in §"What is enforced" is a wording choice, not an oversight of vocabulary.

E1/E2 would close part of this and are **confirmed unbuilt**: no `src/center_kb/prlint.py`, no `pull-request-template.md`, no `tdd-exemptions.md`, no `kb pr lint`, and `len(expected_files('dev'))` is still **45** (the spec says it becomes 48).

---

**H2 — State derivation is broken for the `bounded` and `spike` paths — the paths small tickets take. (C11)**

- `claude-skill-dev-design.md:39-41`: bounded → *"the output is a few sentences to a few short paragraphs **in chat** — no design file."*
- `claude-skill-dev-implement-ticket.md:69-72`: *"On re-entry, detect state from `docs/impl/<ticket-id>-design.md`, `docs/impl/<ticket-id>-plan.md`, the ticked-checkbox ratio…"*
- `docs/superpowers/specs/2026-08-19-dev-agent-design.md:140`: *"State is derived, never stored… the design file's existence, the plan file's existence… are the complete state."*
- Same spec `:34`: *"The flow survives interruption. A ticket takes days; the design, plan, and progress live in files."*

Consequences, all deterministic from the text:

1. A session that dies **after GATE 1 but before the plan** on a bounded ticket leaves **zero artifacts**. The approved design is gone with the conversation, and `/dev-implement-ticket <id>` re-runs `dev-design` from scratch — the exact failure the "state lives in files" claim exists to prevent.
2. A resumed bounded ticket with a plan present must render `State: design ⬜ not written · plan ✅ approved` — self-contradictory, and it invites the orchestrator to "fill the gap" by re-running phase 1.
3. `:540` justifies the missing file as avoiding *"ceremony that gets skipped"*; nothing anywhere reconciles that with `:140`/`:34`.

Other ambiguous cases the rules simply do not cover (I checked the spec and all 24 wrappers):

| Case | What the rules say | Actual behaviour |
|---|---|---|
| design file exists, plan deleted | "detect from design.md, plan.md, checkboxes, branch, PR" | reads as `plan ⬜`; re-plans work that may already be committed — no cross-check against `git log` |
| plan fully ticked, no PR | covered | → `/dev-handover`, correct |
| **PR closed unmerged** | only "whether a PR exists" | reads as `PR ✅ opened`; flow terminates, no "rejected, resume" state |
| **branch renamed** | branch is a state input, but nothing maps branch→ticket | agent cannot tell whether an isolated workspace exists; may create a second branch |
| **two tickets in flight** | not addressed | nothing stops `/dev-execute T-2` while checked out on `T-1`'s branch |
| `docs/impl/` gitignored? | only `*-context.md` (`impl-gitignore.txt:3`) | design + plan **are** committed, so state does survive a fresh clone of that branch ✅ |

---

**H3 — The C1 context cache is unvalidated, gitignored, and keyed on one field. (C11)**

`grep -rn "context.md" src/**/*.py` returns **nothing** — every hit is inside template prose. No CLI command reads, writes, validates or invalidates `docs/impl/<id>-context.md`; `kb doctor --context <ticket>` ignores it entirely (verified: printed `kb doctor: OK` with a poisoned cache sitting next to the ticket). The spec accepts this (`2026-08-24-c1-context-cache-design.md:47`: *"the CLI cannot own the file"*), but the consequences are load-bearing:

| Adversarial case | Detected? |
|---|---|
| cache `version:` older than the ticket's block | **Yes** — the skill compares them, then a full re-resolve runs |
| ticket pinned to an old commit, hub advanced, cache matches | **Yes** — `--status-only` compares pinned vs hub worktree and returns `stale` (verified, exit 2) |
| **cache body hand-edited, `version:` unchanged** | **No.** No hash, no length, no re-derivation. The "verbatim standard value" the code is built from can be anything |
| **another ticket's cache copied to `<this-id>-context.md`** | **No.** Nothing compares the cache's ref list to the ticket's `refs:`; two tickets in the same sprint pin the same commit, so `version:` matches and `--status-only` (run against the *ticket*, not the cache) returns all-ok |

And the file is **gitignored** (`git check-ignore -v` → `docs/impl/.gitignore:3:*-context.md`), so the artifact that carries the pinned content into the implementation is the one artifact the SME PR review can never see. The only residual defence is the `# per doc §sec @ rev` citation comment in the code plus a reviewer who re-resolves it.

Compounding: the cache has **no writer**, so its format is re-invented by whichever model/assistant writes it. `version:` is parsed out of a model-authored file by another model.

### MEDIUM

**M1 — `kb resolve` tells the operator to run the one command all 20 dev wrappers forbid.**
`src/center_kb/resolve.py:163-167` appends to every `stale` verdict:
`!! … — run \`kb diff arinc-424 --against a0c805a\` to see the changes`.
SHARED-FRESHNESS in all 24 wrappers says the opposite: *"Do NOT use `kb diff` — it compares the local `.kb/` worktree to a local git rev, not this repo to the hub."* In a dev repo the suggested command **fails and exits 0**:
`doc 'arinc-424' is not in the worktree (…devrepo\.kb\arinc-424\_manifest.yaml)` → `exit=0`.
Known and deferred (`2026-08-24-c1-context-cache-design.md:41-43`: *"Pre-existing text, other tests pin it, not this batch"*), but it is a tool actively steering the agent into a forbidden, silently-failing action.

**M2 — The Ground step misdiagnoses the most common reason its own `-code`/`-svc` documents are missing. (C11 × C7)**
`claude-skill-dev-implement-ticket.md:56-60` says `<repo_id>-code` is missing *"whenever `kb code-ingest` has not run yet"* and `-svc` *"whenever this repo has not run `dev-code-seed`"*. Reads are hub-only, so the real and far more common cause is **generated but not yet published**. In `svcrepo`, with both documents present in `.kb/` and a hub configured:

```
$ kb query "api service http surface"   → No matching section found.   (exit 0)
$ kb get svcrepo-svc svc.api            → Not found: svcrepo-svc §svc.api  (exit 0)
```

The agent will report "code-ingest hasn't run" — false — and, per the skill, *"say so in one line rather than reporting it as a KB gap"*, so the misdiagnosis is designed to be quiet.

**M3 — The shipped price table misses model ids Claude Code actually writes: 11.5 % of real API calls are `unpriced`. (C14)**
Offline pricing of 12 real transcripts (`center_kb.usage.transcript` + `prices.cost_of`, package table):

```
deduped API calls: 2993   priced: 2648   unpriced: 345  (11.5%)
  'claude-opus-5'      calls=2648  tokens=587,406,867  priced=True
  'claude-fable-5-1'   calls= 345  tokens= 82,329,784  priced=False
```

`usage-prices.yaml:24` has `claude-fable-5`; transcripts write `claude-fable-5-1`. A raw scan of the same files also shows `"model":"opus"` (135) and `"model":"sonnet"` (93) — bare aliases, also absent. 12.3 % of tokens carry no price. The `unpriced` handling is correct (never \$0), so the failure is visible rather than silent — but a PR's `## Usage` table will routinely read `0.xx USD (+N unpriced)` for a same-family point release.

**M4 — `est` / `assistant` are stored and never reported. (C14)**
`ledger.py:53-56` states the purpose: *"a dashboard must be able to tell a measured row from an estimated one."* `Aggregate`/`Bucket` (`report.py:24-49`) carry no such field; `report.html.j2` slices by ticket/phase/model/actor/sidechain only; `render_markdown` likewise; `--json` likewise. Meanwhile `kb usage note` (`cli.py:1001-1004`) defaults `--est false` and `--assistant claude-code`, so a hand-entered Copilot estimate lands indistinguishable from a measurement. The spec defers the Copilot/Cursor path (`2026-08-23…:29-31`), so this is an incomplete promise rather than a bug — but as written, C14's "`est: true` for self-reported" is stored-only.

**M5 — The Java conventions preset contradicts itself. (C11)**
`conventions-java.md:116-130` ships `.editorconfig` with `[*.java] indent_size = 4`, while `:87-95` of the *same section* ships spotless `googleJavaFormat()` and checkstyle `google_checks.xml` — both of which mandate **2-space** indentation. An editor honouring the shipped `.editorconfig` writes code the shipped `cmd.lint` rejects. Additionally `checkstyle { maxWarnings = 0 }` with `google_checks.xml` (severity=warning on nearly everything) will fail an untouched real repo on day one.

**M6 — The lint presets do not enforce the rules the same document states, where the linter easily could. (C11)**
`conventions-python.md:40` — *"never `print()` in committed code"* — but the shipped `ruff.toml` (`:76`) selects `["E","F","W","I","B","UP","SIM"]`: no `T20` (flake8-print) and no `N` (pep8-naming), so the entire **Naming** section and the print ban stay prose. `conventions-ts.md:40` bans `console.log`, but the shipped `eslint.config.mjs` is `js.configs.recommended` + `tseslint.configs.recommended`, neither of which enables `no-console`. The pack's own tier-1 ("machine catches machine") value is left on the table.

**M7 — Monorepo and manifest-less repos get *no* conventions at all, and no `CLAUDE.md`. (C11/C16)**
`conventions.py:42` globs only `("", "*/", "*/*/")`. Measured:

```
depth1  apps/package.json               -> ['ts']
depth2  apps/web/package.json           -> ['ts']
depth3  apps/web/frontend/package.json  -> []        ← very common monorepo layout
py-src-only-no-manifest (src/*.py)      -> []
```

And in `initcmd.py:286-289`, `ensure_claude_block` runs **only if `langs` is non-empty** — so such a repo gets no `CLAUDE.md`, no `.cursor/rules/coding-*.mdc`, no Copilot instructions, and only a one-line note at init time that nothing repeats:

```
$ kb init . --kind dev          # apps/web/frontend/package.json, services/api/backend/pyproject.toml
  note  no language manifests detected — conventions skipped; re-run kb init after adding code
kb init (dev): 45 created, 0 updated, 0 skipped.
CLAUDE.md exists? NO
```

**M8 — `conventions-<lang>.md` and `dev-plan` give contradictory, both-normative instructions for the same task.**
`conventions-python.md:66` (and every sibling): *"the first task of a dev plan creates the files below **exactly as shown**"*.
`claude-skill-dev-plan.md:164-167`: *"**Scope the initial config so `cmd.lint` passes on the untouched tree**… and record tightening it to full strength as a finding."*
On any pre-existing repo the shipped `select`/`maxWarnings` will not pass untouched, so the two cannot both be obeyed and the model must pick one silently.

### LOW

- **L1** — `cli.py:186-190` appends `(protected data — use --force to overwrite)` to *every* skipped entry, including `docs/conventions/<lang>.local.md`, which `--force` does **not** overwrite (`conventions.py:134-139` enforces its own skip). Verified: after `--force`, `python.local.md` was byte-identical. The message is actively wrong and could push a user to run `--force` — losing `config.yaml` and `settings.json` for nothing.
- **L2** — The hook's wrong-directory guard creates the ghost it exists to prevent. `cli.py:894-898` skips ingest when `<kb_dir>/config.yaml` is absent, then calls `_usage_log_error`, which `mkdir(parents=True)`s `<cwd>/.kb/usage/` and writes `ingest-errors.log` there. Verified in `devrepo/sub/deep`: the only file created was `./.kb/usage/ingest-errors.log`.
- **L3** — Hook failures are permanently invisible. `--hook-stdin` always exits 0, prints nothing, and **no command reads `ingest-errors.log`** (`grep -rn ingest-errors src/` → only the writer). `kb doctor` does not check it. Garbage stdin: `exit=0`, one log line, no other signal.
- **L4** — `render_markdown` never prints a staleness warning. With `effective_date: 2026-01-01` the MD footer read `Prices effective 2026-01-01 (250 days old)` — no warning word — while HTML said *"The price table is out of date (250 days)"* and JSON set `stale: true`. `--md` is the surface `dev-handover` pastes into the PR. (With the shipped `2026-06-24` and today = 2026-09-08 the table is **76 days** old, so the 90-day warning does not fire yet; it will on 2026-09-23.)
- **L5** — `hist.*` rows sort lexicographically: `T-1, T-10, T-2`. Deterministic, but wrong for any numeric ticket scheme (`PROJ-2` after `PROJ-10`).
- **L6** — `svcnote._l3_safe` substitutes `|` → `/` in the L3 stanza, so `-svc` L3 is not byte-faithful: title `Refactor | with pipe` is stored in L2 as `Refactor \| with pipe` (faithful) and in L3 as `Refactor / with pipe` (altered). A deliberate trade-off (Ruling R5, documented at `svcnote.py:92-104`), but it makes L3 *less* faithful than L2 — inverted from the C2 layer contract, and a domain ref containing `|` would be silently rewritten in published knowledge.
- **L7** — `kb approve <repo>-svc` with no `--section` also flips the machine-authored `hist.*` sections to `reviewed` (observed: `4 section(s) → reviewed: §svc.api, §svc.db, §hist.api, §hist.db`).
- **L8** — The **only** semantic divergence between wrapper variants is an escape hatch. `copilot-/cursor-dev-implement-ticket`: *"run the **/dev-design** prompt (**or follow `docs/impl/` conventions inline if prompts are unavailable**)"*. The claude-skill variant has no such clause. A model that judges the prompts "unavailable" may inline all four phases and take the gates with them.
- **L9** — `docs/impl/.gitignore`'s `*-context.md` would also swallow a legitimately authored `docs/impl/api-context.md`.
- **L10** — Preset nits: `go install …/cmd/golangci-lint@latest` (no `/v2`) pins to EOL v1.64.x, which is what the v1-shaped `.golangci.yml` needs — consistent, but frozen on an unmaintained major. The TS preset installs `typescript-eslint` in any repo detected by `package.json`, including plain-JS ones. `conventions-python.md` never mentions type hints, mutable default arguments, or `from __future__ import annotations` — the highest-value non-lintable Python rules.

---

## 4. Enforcement-class table

Read as the executing model would: what actually stops me if I skip this?

| Instruction (source) | Enforcement class | Failure mode if the model skips it |
|---|---|---|
| Intake bounce on missing `kb-context` (`…implement-ticket.md:41-42`) | **command-assisted, prompt-gated** — `kb resolve` exits 1 `no 'kb-context:' block found`; nothing makes the agent run it first | Implements from current hub state or memory; the whole pinning guarantee is bypassed and nothing downstream notices |
| Freshness re-check at every entry (SHARED-FRESHNESS, 24 files) | **command-assisted, prompt-gated** — `--status-only` returns correct ok/stale/broken + exit 0/1/2 | A hub amendment mid-implementation surfaces at review, not at the desk; stale standard value ships |
| Verbatim-with-citation for standard values (Hard rule 5) | **prompt-only** | A remembered value enters code under a citation comment that looks correct; only a reviewer who re-resolves catches it |
| TDD failing-test-first (Hard rule 3; `dev-execute` step 1) | **prompt-only** | Test written after the code, green on first run, proving nothing — indistinguishable in the diff |
| Per-task review checkpoint (`dev-execute` step 3) | **prompt-only, and self-review by construction** (prior assessment R3, unaddressed) | The only independent check is the human at GATE 4 |
| `OPEN(BA)` escalation (Hard rule 8) | **prompt-only** | Agent silently picks a reading of an ambiguous AC and ships it |
| No completion claim without pasted output (Hard rule 4) | **prompt-only** (E1's `no-verification-output` designed, unbuilt) | "All tests pass" with nothing behind it; the PR body has no required shape |
| The 4 human gates | **prompt-only for 1–2**; 3–4 rest on GitHub branch protection *if configured* — `kb init` cannot set it | Design presented and plan started in one turn; agent opens/merges its own PR wherever permissions allow |
| Plan checkbox ticked per commit (`dev-execute` step 5) | **prompt-only** | The resume point drifts from reality; a later session redoes or skips tasks |
| Handover PR body: AC→test map, Usage, findings (`dev-handover:171-185`) | **prompt-only** (E1 designed, unbuilt) | PR ships with none of it; reviewer has no AC→test map |
| `kb svc note` per touched service (`dev-handover:162-170`) | **prompt-only to invoke**; the command itself is machine-safe (idempotent; unknown service → exit 1) | `hist.*` quietly stops accruing; nothing detects the hole |
| Never modify a `reviewed` `-svc` section (Hard rule 11) | **partially machine** — `--scaffold-svc` emits `stale-risk`; `kb build` catches manifest/file desync | A well-formed hand-edit that keeps the file valid passes `kb build` |
| Never publish `pending` knowledge (`dev-code-seed`) | **machine-enforced** — `kb build` exit 1 (verified), run by `kb-code.yml` on PR **and** push | (enforced) |
| Context-cache freshness via `version:` (SHARED-FRESHNESS) | **prompt-only; no code touches the file** | Poisoned or foreign cache used as pinned content — and gitignored, so invisible in the PR |

---

## 5. Criteria scorecard

| Criterion | Verdict | Why (one line) |
|---|---|---|
| **C11 Dev workflow** | **partially met** | Grounding, freshness, the 4 gates, resumable design/plan files and the conventions pack all exist and the CLI half works, but **every discipline rule is prompt-only** (H1), state derivation fails on the bounded/spike paths the design itself prefers for small tickets (H2), the C1 cache is unvalidated and unreviewable (H3), and E1/E2 are confirmed unbuilt (`prlint.py` absent, `expected_files('dev') == 45`). |
| **C13 `kb svc note`** | **met** | Idempotent per (ticket, service); unknown service → exit 1 with an actionable message; `hist.*` L3 carries no pipe table; `-code`/`-svc` remain separate documents joined by `svc.<name>`; desync detected by both `kb svc note` and `kb build`. Only nits: lexicographic ticket sort (L5) and `|`→`/` in L3 (L6). |
| **C14 Usage measurement** | **partially met** | One row per API call (dedup verified at 87.9 % real-world inflation avoided), phase from `<command-name>`/`Skill` only, `_unattributed` bucket, static escaped HTML, correct cost math, idempotent re-ingest, `Stop`-only hook scaffolded for ba/dev only — all verified. Shortfalls: 11.5 % of real calls unpriced (M3), `est`/`assistant` never reported (M4), no staleness warning in the `--md` PR surface (L4), and hook failures permanently silent (L2, L3). |
| **C16 Docs-as-code & re-init** | **met** | `.kb/index.yaml`, `.kb/config.yaml`, `.claude/settings.json` and every `*.local.md` survive a plain re-init byte-identically; `*.local.md` survives even `--force`; `CLAUDE.md` injection is idempotent and byte-preserving; `test_init.py:1434` and `test_templates.py` trip-wires are real and green (431 tests). Only the misleading skip message (L1) and the silent loss of hand-edited wrappers — which QUICKSTART does warn about — sit against it. |

---

## 6. Top 3 recommendations

1. **Ship E1/E2, and make the gate harder than the current spec.** The 2026-09-05 design is sound (env-indirection against injection, comment-stripping so the blank template fails, `no-verification-output`) but two gaps let it be gamed: the exemption **slugs live only in prose**, so `kb pr lint` would accept `## TDD exemptions` reading `Exempt: deadline` — put the four slugs in `prlint.py` and reject anything else; and `no-verification-output` accepts *any* fenced block, so require the fence to contain the plan's recorded `cmd.test` string. Separately, rewrite `QUICKSTART-dev.md:165-176` to split **machine-enforced** from **prompt-only**, the way the Model-tiering section already does — today it over-claims (H1).
2. **Fix state derivation before the E3 pilot.** Make `dev-design` always write `docs/impl/<id>-design.md` — one paragraph on the bounded path is not ceremony, it is the resume point the whole architecture rests on (H2) — and extend the state rules to name the ambiguous cases: plan deleted with commits on the branch, PR closed-unmerged, branch renamed, two tickets in flight. Right now the orchestrator's `State:` line has no vocabulary for any of them.
3. **Give the context cache a machine anchor, and price the models people actually run.** Add `kb resolve --write-cache <path>` so the CLI owns the file's format, and have it record the resolved **ref list plus a content hash** alongside `version:`; then make `--status-only` refuse a cache whose ref set differs from the ticket's — that kills both the copied-cache and hand-edited-cache holes (H3) at the cost of one flag. In the same pass add `claude-fable-5-1` and the bare `opus`/`sonnet` aliases to `usage-prices.yaml` (or normalise trailing point-release suffixes), which today leaves 11.5 % of real calls and 12.3 % of real tokens unpriced (M3).
