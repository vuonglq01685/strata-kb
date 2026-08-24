# `kb usage` — token and cost measurement for a ticket's lifecycle

**Status:** approved design, ready for an implementation plan
**Roadmap item:** batch 2 (B1 + B2 + B3) of `docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md`
**Supersedes nothing.** Extends the framework; changes no existing behaviour.

## Goal

For any ticket, answer: **how many tokens did it cost, on which model, in which
phase, on the BA side or the Dev side** — and let a BA or a Dev see the answer by
opening a file in their own repository, without asking anyone.

Measurement comes before optimisation. Roadmap section C (token reduction) is
deliberately ordered *after* this, because C's priorities should be chosen from
measured data rather than from static reading.

## Scope

**In:** an append-only usage ledger committed to git; automatic capture from
Claude Code transcripts; a static self-contained HTML report; a default price
table with a repo override.

**Out, and deliberately so:**

- **B4** (`dev-handover` and `ba-ticket-author` reporting usage in their
  handover output) — every skill-text edit costs the same four wrappers plus two
  canon assertions, so B4 joins the shared template round with A4/C2/C3/C4. This
  batch edits **no** skill wrapper.
- **Copilot / Cursor self-reported rows.** The ledger reserves `assistant` and
  `est` fields so that path needs no format change, but nothing writes them yet.
  Those assistants have no hook, so their only option is an agent's own estimate,
  which cannot be verified.
- `kb usage merge` (joining the BA repo's ledger with the Dev repo's for one
  ticket id), `kb usage serve`, and any CI job that regenerates the report.
- Everything in roadmap section C.

## Evidence this design rests on

Measured on this machine, 2026-08-23, against real transcripts under
`~/.claude/projects/`. Each number below changed a decision.

**1. Transcript rows carry real usage, per row, with the model.**
`~/.claude/projects/<slug>/<session-id>.jsonl`; a row with
`message.usage` also carries `message.model`, and the row itself carries
`uuid`, `sessionId`, `timestamp`, `cwd`, `gitBranch`, `isSidechain`.

```
CENTER-KB/096a41ed   305 usage rows   claude-opus-5
                     in 610  out 433,409  cache_read 76,847,719  cache_write 914,048
                     gitBranch: feat/kb-context-tag-integrity 251, main 54
```

One session spans two branches, so attribution must be per row, never per
session.

**2. `cache_read` dominates cost, and cache writes are split by TTL.**
`usage.cache_creation` carries `ephemeral_5m_input_tokens` and
`ephemeral_1h_input_tokens` separately. In both repos measured, **every** cache
write was 1h and none was 5m. Priced at Opus 5 rates the session above is
**$58.40**, of which `cache_read` alone is **$38.42**. A price table with a
single "cache write" rate understates that component by ~37%; a table without a
`cache_read` rate is off by more than half the bill.

**3. `gitBranch` is unusable as the primary attribution key.**
In the BA repo (`KS-BA`, which is not a git repository) every row reads
`gitBranch: "HEAD"`. Roadmap B2 proposed attributing by branch name; that fails
outright on the BA side.

**4. The ticket-file path is a strong signal; the ticket id convention is not.**

```
KS-BA/bfd16d39  212 rows  sonnet-5  tickets/: open-new-flight ×57, TEMPLATE ×2
KS-BA/bdcc8be4  175 rows  opus-5    tickets/: remove-witness-crew-stock-transfer ×56,
                                              open-new-flight ×2, stock-transfer-remove-crew-id ×1
M-<slug>-US<n> ids: absent from every session measured
```

`mission.us_id_re` (`src/center_kb/mission.py:88`) defines a ticket id as
`<mission-id>-US<n>` and `missionlint.check_coverage`
(`src/center_kb/missionlint.py:282`) requires `tickets/<us-id>.md` — but the real
tickets are named `open-new-flight.md`. **The ledger key is therefore the file
stem, and is never validated against that pattern.** Validating would discard
every real ticket. `TEMPLATE` must be excluded.

**5. Counting skill-name mentions cannot identify a phase.**

```
KS-BA/bfd16d39      <command-name>: /clear ×1, /ba-ticket-author ×1
                    name mentions: ba-ticket-author ×94, ba-mission-plan ×9, kb-summarize ×1
CENTER-KB/9d037817  <command-name>: /model ×1, /superpowers:subagent-driven-development ×1
                    name mentions: dev-handover ×339, dev-implement-ticket ×290, dev-plan ×178
```

A session that *edits* the dev skills mentions `dev-handover` 339 times. The
clean signals are the `<command-name>` marker (exactly once per session in both
BA sessions) and a `Skill` tool call's `input.skill`.

**6. Parsing is cheap; starting the CLI is not.**

```
full-parse transcript 6.1MB (2560 rows, 685 usage)    60.4 ms
kb --version (CLI startup)                           680 ms
kb tags (startup + load federation)                  528 ms
```

So: no incremental byte-offset cursor (it would optimise 60 ms while paying
600 ms), and the hook costs ~0.6 s per turn — a number the QUICKSTART states
outright rather than letting a dev discover it.

**7. `kb init` overwrites any file not in `PROTECTED_FILES`.**
`src/center_kb/initcmd.py:257-264` writes over an existing file and records it as
`updated`; `PROTECTED_FILES` (`initcmd.py:145`) holds only `.kb/index.yaml` and
`.kb/config.yaml`. A scaffolded `.claude/settings.json` outside that set would
destroy a dev's own hook configuration on the next `kb init`.

## Architecture

New package `src/center_kb/usage/`, following the precedent that a multi-concern
feature gets a package (`codeingest/`, `ingest/`) while a single-concern feature
gets one module (`svcnote.py`).

| Module | Responsibility | Must not know about |
|---|---|---|
| `usage/ledger.py` | The row model; append with de-duplication; resolve a ticket id to its ledger path. The only module that knows the on-disk shape. | transcripts, prices, HTML |
| `usage/transcript.py` | Parse a transcript JSONL; run the two attribution cursors; yield ledger rows. | prices, HTML, where rows are stored |
| `usage/prices.py` | Load the package default price table and merge a repo override; return a rate set or `unpriced`. | transcripts, ledger layout |
| `usage/report.py` | Aggregate committed ledger rows and render HTML / Markdown / JSON. | transcripts |

CLI surface, as a `usage_app` sub-typer registered the way `svc_app` and
`ticket_app` are (`src/center_kb/cli.py:35-36`):

- `kb usage ingest-transcript [<path>] [--hook-stdin] [--ticket <id>] [--kb-dir] [--json]`
- `kb usage note --ticket <id> --phase <p> --model <m> --tokens-in N --tokens-out N [--cache-read N] [--cache-write-1h N] [--cache-write-5m N] [--est] [--assistant <a>] [--kb-dir]`
- `kb usage report [--ticket <id>] [--md] [--json] [--out <path>] [--kb-dir]`

Two argument rules, so neither command has an undefined state.
`ingest-transcript` takes **exactly one** of a positional path or
`--hook-stdin`. Passing neither, or both, is a usage error: exit 2 for a plain
invocation, but whenever `--hook-stdin` is present the always-exit-0 rule below
wins and the complaint goes to `.kb/usage/ingest-errors.log` — a broken hook
line must not be able to freeze a session.
`report` writes HTML to `--out` (default `.kb/usage/report.html`); `--md` and
`--json` print to stdout instead and ignore `--out`.

**No MCP tool is added and no existing tool's signature or docstring changes**,
so `tests/test_mcp.py` and its `mcp_tools.json` golden must pass untouched. A
golden break is a defect signal, never a reason to regenerate the golden.

## Data model

One transcript row carrying `message.usage` becomes one ledger row.

```json
{"uuid": "a1b2…", "ts": "2026-08-23T09:59:22.432Z", "session": "6c012668-…",
 "actor": "ba", "phase": "ba-ticket-author", "ticket": "open-new-flight",
 "model": "claude-sonnet-5", "tokens_in": 4, "tokens_out": 1837,
 "cache_read": 181392, "cache_write_5m": 0, "cache_write_1h": 3204,
 "sidechain": false, "branch": null, "assistant": "claude-code", "est": false}
```

Those are one row's numbers, not a session's. A 212-row session sums to the
totals in evidence 4; a single row is three or four orders of magnitude smaller.

Four fields differ from the roadmap's sketch, each for a measured reason:

- `cache_write_5m` / `cache_write_1h` instead of one `cache_write` — evidence 2.
- `uuid` — the de-duplication key, taken from the transcript row.
- `sidechain` — from `isSidechain`, so subagent cost is separable from main-thread
  cost.
- `branch` — from `gitBranch`; cheap to record, and the only fallback when a
  cursor misses. `null` when the value is absent or `"HEAD"` (evidence 3), so a
  useless value is never mistaken for a real branch.

`actor` is derived from `kind:` in `.kb/config.yaml` — one of `ba`, `dev`,
`child`, `hub` — never self-declared by an agent. The hook only runs in `ba` and
`dev` repos, but backfill and `kb usage note` work anywhere, so all four values
are possible.

`assistant` is `claude-code` and `est` is `false` on every row the ingest path
writes. `kb usage note --est` is the only way to produce `est: true`, and
nothing in this batch calls it: the CLI door exists, the skill text that would
walk through it belongs to the shared template round.

### Storage

- `.kb/usage/<ticket-stem>.jsonl` — one file per ticket.
- `.kb/usage/<mission-id>.jsonl` — mission-level work, same shape.
- `.kb/usage/_unattributed.jsonl` — rows with `ticket: null`.
- `.kb/usage/ingest-errors.log` — see "the hook must never break a session".

Committed to git, so a ticket's cost travels with the ticket's history and a PR
carries its own number. One file per ticket rather than one per session
specifically so that the file name *is* the ticket id, which is what makes B4's
"the PR carries its own cost" possible later.

A BA repo that is not a git repository (as `KS-BA` is not today) still gets a
working ledger — it just has no history. The QUICKSTART says so plainly rather
than implying otherwise.

## Capture

### The hook

`.claude/settings.json` is scaffolded **for kinds `ba` and `dev` only**, with a
single entry on the `Stop` event whose command is:

```
kb usage ingest-transcript --hook-stdin
```

- **Added to `PROTECTED_FILES`.** Written only when absent; a repo that already
  has one is skipped and the QUICKSTART explains the manual merge. Without this,
  evidence 7 says `kb init` would overwrite a dev's own hooks.
- **No shell script.** The hook payload arrives as JSON on stdin, so the CLI
  reads it directly and there is no `.sh`/`.ps1` to keep portable.
- **`Stop`, not `SessionEnd`.** B4 will have `dev-handover` report usage from
  *inside* the session that produced it; with `SessionEnd` the ledger would still
  be empty at that moment. Ingest is idempotent, so adding `SessionEnd` later is
  safe.
- **Not scaffolded for `hub` / `child`.** Those repos author no tickets, so every
  row would land in `_unattributed` — 0.6 s per turn for noise.

**Implementation note, do not guess:** the exact JSON shape of the `hooks` block
(the `matcher` / `hooks` nesting) must be confirmed against Claude Code's
documentation or the `/hooks` UI before the template is written. A malformed
hook silently never fires, which looks identical to "no usage yet".

### The hook must never break a session

In `--hook-stdin` mode the command **always exits 0**. A `Stop` hook exiting 2
blocks Claude from ending its turn; an ingest failure must never freeze a dev's
session. Failures append a line to `.kb/usage/ingest-errors.log` and are
otherwise silent.

### Attribution: two cursors, one pass

Rows are walked in file order. Both cursors depend only on rows *before* the
current one — which is what makes re-ingestion stable (invariant I1).

**Ticket cursor.** One cursor, not two: it is set by whichever of
`tickets/<stem>.md`, `missions/<stem>.md`, or
`docs/impl/<stem>-{design,plan}.md` was mentioned most recently, so a mission
stem and a ticket stem never both hold. `TEMPLATE` is excluded. The stem is the
key verbatim; it is **not** matched against `M-<slug>-US<n>` (evidence 4). A
`usage` row takes the cursor's current value; rows before the first hit get
`ticket: null`.

**The stem becomes a filename, so it is constrained.** A stem is accepted only
if it matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$` and is not `.` or `..`.
Anything else is treated as no mention at all and leaves the cursor unchanged —
the stem is read out of transcript *content*, which is not trusted input, and
`.kb/usage/<stem>.jsonl` must never be able to escape `.kb/usage/`.

**Phase cursor.** Two sources only: a `<command-name>` marker in a user message,
and a `Skill` tool call's `input.skill`. Only names in the workflow families
(`ba-*`, `dev-*`, `kb-*`) set a phase. `/clear` **resets** the phase to
`unknown`, because it clears the context the phase was running in. Any other
command (`/model`, `/status`, …) leaves the cursor unchanged.

**Explicitly forbidden:** inferring a phase from skill names appearing anywhere
in message content. Evidence 5 shows a session mentioning `dev-handover` 339
times while running something else entirely. A plan or implementation that does
this is wrong even though its output looks plausible.

**Overrides.** `--ticket <id>` forces every row in the run, for the case where a
cursor is wrong. `kb usage note` appends a row by hand.

### Backfill

`kb usage ingest-transcript <path>` ingests any transcript file directly, so the
whole existing history under `~/.claude/projects/<slug>/` can be loaded at once.
The dashboard has data on day one instead of accumulating from zero.

## Pricing

Package default at `src/center_kb/templates/usage/usage-prices.yaml` — package
data, **not** part of `initcmd`'s scaffold map, so it contributes no pinned-count
change. Repo override at `.kb/usage-prices.yaml`.

```yaml
effective_date: "2026-06-24"
currency: USD
unit: per_mtok
models:
  claude-opus-5:    {input: 5.0,  output: 25.0, cache_read: 0.50, cache_write_5m: 6.25, cache_write_1h: 10.0}
  claude-sonnet-5:  {input: 3.0,  output: 15.0, cache_read: 0.30, cache_write_5m: 3.75, cache_write_1h:  6.0}
  claude-haiku-4-5: {input: 1.0,  output:  5.0, cache_read: 0.10, cache_write_5m: 1.25, cache_write_1h:  2.0}
  claude-fable-5:   {input: 10.0, output: 50.0, cache_read: 1.00, cache_write_5m: 12.5, cache_write_1h: 20.0}
  claude-opus-4-8:  {input: 5.0,  output: 25.0, cache_read: 0.50, cache_write_5m: 6.25, cache_write_1h: 10.0}
  claude-opus-4-7:  {input: 5.0,  output: 25.0, cache_read: 0.50, cache_write_5m: 6.25, cache_write_1h: 10.0}
  claude-opus-4-6:  {input: 5.0,  output: 25.0, cache_read: 0.50, cache_write_5m: 6.25, cache_write_1h: 10.0}
  claude-sonnet-4-6:{input: 3.0,  output: 15.0, cache_read: 0.30, cache_write_5m: 3.75, cache_write_1h:  6.0}
```

Three rules:

- **Explicit rates, never multipliers.** `cache_read: 0.50`, not "0.1 × input".
  A multiplier convention rots silently the day one model prices its cache
  differently.
- **Standard rates ship, not promotional ones.** Sonnet 5 has an introductory
  price of 2.0/10.0 that expires 2026-08-31; shipping 3.0/15.0 is right on every
  day except those, and a repo needing that window overrides it. A comment in
  the file records this.
- **An override merges per model.** A repo correcting one model's price keeps the
  rest of the table.

An unknown model is reported as `unpriced` with its token totals, and is **never
priced at zero**. Silent zeros are the failure mode that makes a dashboard worse
than no dashboard. The report always prints `effective_date`, and warns when the
table is more than 90 days old.

Cost formula, per row, per rate: `tokens / 1_000_000 × rate`, summed over
`tokens_in`, `tokens_out`, `cache_read`, `cache_write_5m`, `cache_write_1h`.

## Report

`kb usage report` writes `.kb/usage/report.html` by default: static,
self-contained, no CDN and no JavaScript — open it in a browser, no server. The
Jinja template lives at `templates/usage/report.html.j2` behind its own
`PackageLoader`, mirroring `src/center_kb/web/templating.py:8`. Tables only, no
charts: a self-contained chart means shipping a library, and a table survives a
git diff. `jinja2` is already a dependency; **this batch adds no dependency**.

Sections: total per ticket · by phase · by model · by actor · main vs sidechain ·
`unattributed` · `unpriced` · `effective_date` and generation time.

`--md` prints a compact Markdown table for a PR body — the call B4 will make.
`--json` prints the aggregate for any other consumer.

**Deviation from the roadmap, stated deliberately:** the roadmap describes
`report.html` as committable. This design does **not** commit it by default. It
is fully derivable from the ledgers, which *are* committed, and a regenerated
HTML file is diff noise on every run. The ledger is the source of truth in git.
If the decision is reversed, the render must become deterministic — fixed sort
order and exactly one timestamp line — so the diff stays small.

## Invariants, each with its own test

- **I1 — Re-ingesting never changes or duplicates a row.** Both cursors depend
  only on preceding rows, so ingesting a longer transcript yields identical
  results for the rows already present; a ledger file only grows. Test: ingest a
  prefix, ingest the full file, assert the leading bytes are identical and no
  `uuid` repeats.
- **I2 — A row lands in exactly one file.** No `uuid` appears both in a ticket
  ledger and in `_unattributed.jsonl`.
- **I3 — Token counts are copied, never computed.** Every row the ingest path
  writes has `est: false`; there is no estimation anywhere in the Claude Code
  path. `est: true` is reachable only through `kb usage note --est`.
- **I4 — The ticket key is a file stem, never validated against
  `M-<slug>-US<n>`.** The test fixture uses the two real KS-BA ticket names,
  which are exactly the non-conforming case.
- **I5 — An unknown model reports as `unpriced`, never as $0.** A row with model
  `claude-nonexistent-9` appears in the report's `unpriced` section with its
  tokens, and the money total does not silently absorb it.

## Tests and trip-wires

New: `tests/test_usage_ledger.py`, `tests/test_usage_transcript.py`,
`tests/test_usage_prices.py`, `tests/test_usage_report.py`,
`tests/test_cli_usage.py`.

Fixtures are **synthetic transcript JSONL written by hand**, under
`tests/fixtures/transcripts/`. A real transcript must never be committed — it
contains real session content.

Deliberate bump: `tests/test_init.py`'s pinned scaffold count **+1 for kinds `ba`
and `dev`** (`.claude/settings.json`); `hub` and `child` unchanged.

Must pass untouched: `tests/test_mcp.py` (`mcp_tools.json` byte-identical) and
`tests/test_templates.py` (skill-wrapper canon — this batch edits no skill text).

## Risks

| Risk | Mitigation |
|---|---|
| The `hooks` JSON shape is guessed wrong and the hook never fires | Verify against Claude Code docs / `/hooks` before writing the template; the plan makes this a step with an expected observable outcome, not an assumption |
| Prices drift | `effective_date` printed on every report, staleness warning past 90 days, per-model repo override |
| The ticket cursor mis-attributes a multi-ticket session | `_unattributed` makes gaps visible instead of guessing; roadmap C can add an explicit marker if the data shows it is needed. **Corrected after implementation:** the two repair paths this row originally claimed do not work once the hook is live. `--ticket` cannot move a row the hook has already ingested — global uuid de-duplication (invariant I2) makes the second ingest a no-op — and `kb usage note` *appends*, so using it as a repair double-counts the tokens. The repair that works is editing the stored row in `.kb/usage/*.jsonl` and re-running `kb usage report`; both QUICKSTARTs and the CLI say so. |
| 0.6 s per turn is felt as slowness | Stated in the QUICKSTART with the measured number; hook scaffolded only for `ba`/`dev` |
| Ledger churn in git | Append-only, rows in transcript order, so a diff is always a pure append |
