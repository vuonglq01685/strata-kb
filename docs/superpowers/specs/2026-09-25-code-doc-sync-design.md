# `-code` in sync: one producer, no committed copy, a visible hub lag — Design

**Date:** 2026-09-25
**Status:** Proposed design — not yet implemented
**Builds on:** `docs/superpowers/specs/2026-08-19-dev-agent-design.md` (Phase 5: `kb code-ingest`, `<repo>-code`, `kb-code.yml`), `docs/superpowers/specs/2026-09-20-sa-grounding-design.md` (`kb ticket check`, `Grounded on:` revision), `docs/superpowers/specs/2026-09-23-compose-facts-grounding-design.md` (compose facts)

## 1. Problem

Field evidence from the MyFlix dev repo, two reports on 2026-09-25.

**Report 1 — the committed copy is stale.** `kb-code.yml` regenerates
`.kb/myflix-code` inside the runner and publishes it to the hub; it never
writes back to the repo (by design). The committed copy dates from
2026-09-22 (`e52d3d6`). Consequences:

- `kb svc note` validates a service against the stale local copy, so a
  service the ticket just added reads as "unknown service". The error text
  in `svcnote.py:330-351` already names this cause — the framework knows
  the gap and only advises around it.
- The PR job (`kb-code.yml` `validate`) runs `kb build` on the committed,
  stale `-code` — it validates something other than what the push will
  publish.
- `kb ticket check` reads the local copy first (`cli.py:2503`) and errors
  on a revision mismatch (`ticketcheck.py:393`). It passes in MyFlix today
  only because the stale committed copy happens to equal the hub copy the
  SA grounded on.
- The hub PR diff was large (`services.md` −80 lines, `integrations.md`
  −24). The report attributed this to the stale committed copy; that is
  wrong. `kb ci-publish` uploads the runner's freshly ingested tree, so the
  committed copy never reaches the hub. The diff was large because the
  hub itself still held the 09-22 content: no publish reached the hub
  between 09-22 and this ticket. **The hub lags main, and nothing reports
  it.**

**Report 2 — `-code` has two producers, and an extractor reads strata's own
workflows.**

- The 09-22 hub copy was produced locally: `kb code-ingest`, then
  `/kb-summarize` (manifest `provenance: prompt_sha 141999d58ae6`). The CI
  copy is `kb code-ingest` only — deterministic, no model. Short sections
  flip between a verbatim-L3 L2 (summarize's brief rule) and code-ingest's
  own L1/L2. L3 is unchanged; L1/L2 churn with whoever published last.
- `cmd.build` became `kb build` (from `kb-publish.yml`) and `cmd.lint`
  became `kb pr lint "$RUNNER_TEMP/body.md"` (from `kb-pr-lint.yml`). The
  CI-workflow reader of `commands.py` does not skip the workflows `kb init`
  scaffolds. `/dev-plan` copies `cmd.*` into plans, so the next ticket
  inherits a wrong lint command. Hidden until MyFlix committed `.github/`.
- `code-ingest` warned it could not read
  `infra/compose/docker-compose.cpu.yml`: the compose readers use
  `yaml.safe_load`, which rejects Compose's `!reset` tag. Harmless there
  (decision D1 keeps that file out of the topology), but a real defect.

One cause underlies most of this: the same machine-derived document exists
in several places — committed in the repo, generated in the runner, and on
the hub — and it can come from two different producers. Nothing keeps
them equal, and nothing reports when they drift.

## 2. Goals

- The repo holds no copy of `<repo_id>-code` that can go stale. Every local
  reader sees `-code` derived from the working code it runs against.
- The PR job validates the `-code` that the merge would publish.
- `kb ticket check` judges grounding against the copy the SA grounded on
  (the hub), not against a local derivative.
- For the same commit, local and CI produce byte-identical `-code` content,
  or the tool says why they may not.
- `-code` has exactly one producer: deterministic `kb code-ingest`.
- A dev can see when the hub's `-code` lags main — locally via `kb doctor`,
  and in CI via the job summary.
- `cmd.*` never comes from a strata-scaffolded workflow; Compose's `!reset`
  and `!override` tags parse.

## 3. Non-goals

- A CI step that commits `-code` back to the repo. It needs
  `contents: write`, a branch-protection bypass or a second PR, and loop
  guards, and it only shortens the gap instead of removing it.
- Server-side changes to the intake or hub (e.g. reporting "PR pending
  since commit X"). The CI job summary (§4.3b) surfaces the same symptom
  with client-only changes; the hub needs no redeploy.
- `kb doctor` running `git fetch`. It compares against the local
  `origin/<default>` ref and says so.
- Making `-svc` derived. `-svc` stays committed human content.

## 4. Design

### 4.1 `-code` is derived on demand, never committed

**Gitignore.** `kb init --kind dev` adds `.kb/*-code/` to the repo's
`.gitignore` (idempotently, the same way `kb mcp-setup` manages `.env`).
A glob, not `.kb/<repo_id>-code/`: `repo_id` is often still unset when
`kb init` runs, and `-code` is a reserved suffix a dev repo only ever
uses for its own document. `-svc` stays committed.

**`index.yaml` stops carrying `-code`'s revision.** Today
`_upsert_index_entry` (`codeingest/core.py:688`) writes `revision` into the
committed `.kb/index.yaml`, and the hub reads it (`federation.py:323`).
With `-code` gitignored, that line would churn on every local ingest and
move the gap into `index.yaml`. New rule: the `-code` index entry keeps
only stable fields (`id`, `title`, `tags`, `summary`) and an empty
`revision`. `federation.load_federation` fills an empty index-entry
`revision` from the document's own `_manifest.yaml` — one place, which
covers both readers of `IndexEntry.revision` (`build_federation_index`
and `searchdb._sync_repo`; `web/uidata.py` already reads the manifest).
The `-svc` entry is unchanged.

**`ensure_code_fresh(kb_dir, repo_root)`** — one helper in
`codeingest/`, used by every local reader that needs working-code facts.
It runs `code-ingest` (same options as §4.2) when any of these holds:

- `.kb/<repo_id>-code/_manifest.yaml` does not exist;
- the manifest's `revision` differs from `git rev-parse --short HEAD`;
- `git status --porcelain --untracked-files=no -- . ':(exclude)<kb_dir>'`
  is non-empty (changes under `.kb/` never affect `-code`; excluding them
  also stops an unmigrated, still-tracked `-code` from re-triggering
  itself).

Otherwise it is a no-op. Callers expose `--no-refresh` to skip it. It
never passes `--scaffold-svc`. In a non-git directory it always
regenerates (no revision to compare). `kb build` and `kb publish` call it
only when the repo already has a `-code` document (an `index.yaml` entry
`<repo_id>-code` or the directory exists), so a dev repo that has not run
`/dev-code-seed` yet builds as before.

**Readers, split by the question they answer.**

| Reader | Question | Source after this change |
|---|---|---|
| `kb svc note` | Does this service exist in the code I am handing over? | `ensure_code_fresh()`, then local |
| `kb build` (repo `kind: dev`) | Is what I would publish valid? | `ensure_code_fresh()`, then local |
| `kb publish` (repo `kind: dev`) | What goes to the hub? | `ensure_code_fresh()`, then local (see §4.4) |
| `kb ticket check` | Was this ticket grounded on the current published `-code`? | **hub first**; local only when the hub is unreachable, with a `[note]` naming the local fallback |
| `kb mission next` | Which story is done? | unchanged — reads `-svc` |

Because `kb build` refreshes, the PR job needs no workflow change: on a PR
checkout `-code` is absent, so `kb build` generates it from the merge ref
and validates exactly what would be published. In the publish job,
`kb code-ingest` has already run, so the refresh is a no-op.

**Dev skills.** `dev-plan`, `dev-implement-ticket` and `dev-handover`
(all four wrapper flavours) drop the "run `kb code-ingest` first" advice
the helper now makes redundant. `svcnote.py`'s "committed copy is a
snapshot" error text is rewritten: with the refresh in place, an unknown
service is a typo or an untracked file (see §4.2), not staleness.

### 4.2 Local and CI share one ingest configuration

**`code_ingest:` block in `.kb/config.yaml`.**

```yaml
code_ingest:
  db: [data/app.sqlite]   # explicit only — same rule as --db today
  tags: [payments]
```

- `KBConfig` gains an optional `code_ingest` model (`db: list[str]`,
  `tags: list[str]`), both default empty.
- `kb code-ingest` reads it. A `--db` or `--tags` flag given on the command
  line **replaces** the corresponding config list for that run, and the run
  prints a note that its output will differ from CI's.
- `ensure_code_fresh()` uses the config block, so local `db.*` sections
  match CI's.
- The `kb-code.yml` template drops its `--db` comment block and points to
  `code_ingest.db`. Re-running `kb init --kind dev` (which overwrites the
  workflow) no longer loses ingest configuration.

**Migration of `--db` flags.** `kb doctor` (repo `kind: dev`) scans
`.github/workflows/kb-code.yml` for `kb code-ingest … --db` and warns:
move them to `code_ingest.db` **before** re-running `kb init`, which
overwrites the workflow.

**Version drift.** `kb-code.yml` pins `strata-kb=={version}` from
`kb init` time; a dev machine may run a newer package with different
extractors.

- `kb doctor` (repo `kind: dev`) parses the pin from `kb-code.yml` and
  warns when it differs from `strata_kb.__version__`.
- `code-ingest` prints the same one-line note, so a dev running
  `kb svc note` sees it without running doctor.
- Nothing rewrites the pin; upgrading stays a `kb init` decision.

**Tracked files only.** The tree extractor lists files with
`git ls-files` and reads their working-tree content; this stays. Local
`-code` therefore means "what CI would see if the tracked files were
committed now". A new file appears after `git add`. Docs say so.

### 4.3 The hub's lag behind main is visible

Constraints found in the code:

- `/intake/status` accepts only a CI OIDC token (`intake_routes.py:219`);
  a dev machine cannot ask the intake about the last publish.
- When content is unchanged the intake opens no PR (`cipublish.py:183`),
  so the hub's recorded source commit can legitimately trail main.
  Comparing commits would report false lag.
- `kb doctor` compares the whole local `.kb` digest with the hub snapshot
  and advises "run `kb publish`" (`doctor.py:854`). For a dev repo after
  §4.1 that is wrong twice: local `-code` is branch-specific, so the check
  would always fire; and dev repos publish through CI.

**(a) `kb doctor` compares content, not commits** (repo `kind: dev`).

1. Resolve `origin/<default>` from local refs (no fetch). Report the
   ref's commit date so the user knows how fresh the comparison is.
2. Create a temporary `git worktree` at that commit; run code-ingest with
   the §4.2 config. `db` paths resolve against the real checkout (they are
   data, not code).
3. Compare the result's L3 (`*.raw.md`, split per `## <section-id>`)
   with `federation/<repo_id>/<repo_id>-code` in the hub cache, ignoring
   the `> Generated by kb code-ingest at <commit>` banner. L3 is the
   machine fact; comparing L1/L2 would flag a summarized hub copy
   (§4.4) as lag.
4. Report exactly one of:
   - **in sync**;
   - **hub lags main** — list the differing section ids (e.g. `svc.x`,
     `int.y`) and advise: check for a pending `-code` PR on the hub, or
     the latest `kb-code.yml` run;
   - **cannot judge** — with the reason: package version differs from the
     CI pin (§4.2), no `origin/<default>` ref, hub unreachable, or
     worktree creation failed. Never a guess.
5. Remove the worktree in a `finally`.

The existing digest check is adjusted for repo `kind: dev`: it excludes
`<repo_id>-code`, and its advice for the remaining docs reads "merge to
the default branch; CI publishes" instead of "run `kb publish`".

**(b) `kb ci-publish` writes a job summary.** When `$GITHUB_STEP_SUMMARY`
is set, append one line: `hub PR: <url>`, `no content change on the hub`,
or the error. Repeated runs showing the same PR URL mean the hub PR is
pending — MyFlix's case becomes visible on the Actions page without anyone
running doctor. When the variable is unset, nothing is written.

### 4.4 `-code` has one producer

- `kb summarize` refuses generated documents — those whose `index.yaml`
  entry carries the `generated` tag, which code-ingest always writes for
  `-code`. The route that reached MyFlix's `-code` is
  `kb summarize --redo --all`: `plan_redo` resets every non-reviewed row,
  including code-ingest's `summarized` rows, to `pending` without a
  prompt, and the run then summarizes them. With no document argument,
  `plan_redo` and `collect_pending` skip generated documents and the CLI
  prints a `[note]` naming them. With `kb summarize <doc>` on a generated
  document it exits 1: "`<doc>` is generated by `kb code-ingest` and is
  never summarized". `-svc` is summarized as before.
- `kb publish` in a repo of `kind: dev` calls `ensure_code_fresh()` before
  snapshotting, so a hand publish (e.g. seed step 7, `kb publish --pr`)
  sends the same `-code` CI would send for that commit.
- A repo whose hub copy was summarized (MyFlix) sees its L1/L2 return to
  the deterministic form on the next CI publish — once. The guide says
  so, so a hub reviewer does not read that diff as lost information.

### 4.5 Extractor fixes

**`cmd.*` ignores strata-scaffolded workflows.** The CI reader in
`codeingest/extractors/commands.py` skips every workflow file whose path
is a `.github/workflows/` key in any of `initcmd.py`'s template maps
(today `kb-code.yml`, `kb-pr-lint.yml`, `kb-publish.yml`). `initcmd.py`
exposes that set as one constant so the list has one source. Filtering by
file name, not by "command starts with `kb`", keeps a repo's own `kb`
tool (if any) visible and makes the rule explainable. A renamed scaffold
file is the user's to own.

**Compose `!reset` / `!override` parse.** The compose readers
(`extractors/services.py`, `extractors/integrations.py`) load YAML through
one shared `SafeLoader` subclass that registers constructors for Compose's
`!reset` and `!override` tags. `!override` yields the tagged node's plain
value; `!reset` yields the empty value of the node's kind (`None`, `[]`,
or `{}`), matching Compose's merge semantics. Other readers keep
`yaml.safe_load`.

## 5. Migration

For an existing dev repo, in order:

1. `kb doctor` warns on `--db` flags in `kb-code.yml` (§4.2) and on a
   tracked `.kb/<repo_id>-code/` — "run
   `git rm -r --cached .kb/<repo_id>-code`" (a gitignore line does not
   untrack files).
2. Move `--db` flags to `code_ingest.db`.
3. Re-run `kb init --kind dev` — adds the gitignore line, refreshes
   `kb-code.yml` and the dev skills.
4. `git rm -r --cached .kb/<repo_id>-code` and commit, in one PR.
5. The next CI publish normalises the hub's L1/L2 once (§4.4).

A repo that upgrades the package without migrating keeps working: the
refresh rewrites the tracked copy, which shows as modified files, and
doctor explains why.

## 6. Testing

TDD per behaviour, with the existing fixtures (`tests/test_cli_codeingest.py`,
`test_svcnote.py`, `test_ticketcheck.py`, `test_doctor_checks.py`,
`test_init.py`, `test_templates.py`). New coverage:

- `ensure_code_fresh`: regenerates on missing / revision ≠ HEAD / tracked
  change; no-op otherwise; untracked file alone does not trigger;
  `--no-refresh` skips.
- `index.yaml` is byte-identical across two ingests at different commits;
  federation reads `-code`'s revision from the manifest.
- `kb svc note` finds a service added in the working tree without a prior
  manual ingest.
- `kb ticket check` reads the hub copy when both exist; falls back to local
  with the note when the hub is unreachable.
- `code_ingest:` config: used when no flag; a flag replaces it and prints
  the note.
- `kb doctor` (dev): version-pin mismatch; `--db` in workflow; tracked
  `-code`; lag check returns each of in sync / hub lags main / cannot
  judge; worktree removed on failure; digest check excludes `-code`.
- `kb ci-publish` writes the summary line only when
  `$GITHUB_STEP_SUMMARY` is set.
- `kb summarize` skips / refuses `-code`, including the reset path.
- `kb publish` in a dev repo refreshes `-code` first.
- `commands.py`: a `kb-pr-lint.yml` and `kb-publish.yml` alongside a real
  `ci.yml` yield `cmd.lint`/`cmd.build` from `ci.yml`.
- Compose with `!reset` and `!override` parses without a warning and
  yields the Compose-merged values.

The full suite takes 10–19 minutes: run focused tests per task, the full
suite once at the end.

## 7. Documentation

- `docs/src/guide-dev.{en,vi}.md`: §1.2 table (`-code` is not committed),
  §2.4 (path-scoped auto-merge on `.kb/<repo_id>-code/**` is the primary
  defence against hub lag), §8.1 rewritten for the derived model, a
  troubleshooting row "hub lags main", the tracked-files-only rule, and the
  one-time L1/L2 normalisation.
- `docs/src/architecture.{en,vi}.md`: `-code` lifecycle.
- `QUICKSTART-dev.md` template and `CHANGELOG.md`.

## 8. Verified while writing the plan

- `IndexEntry.revision` is read by `federation.build_federation_index`
  and `searchdb._sync_repo`, both through `load_federation`;
  `web/uidata.py` reads `Manifest.revision`. Hence the fallback lives in
  `load_federation` (§4.1).
- code-ingest has written `-code` rows as `summarized` since it was
  introduced; the route to an LLM summary is `kb summarize --redo --all`
  (§4.4).
- `kb build` reports `<id>: missing _manifest.yaml` as an error when
  `index.yaml` lists a document with no directory — the refresh in §4.1
  runs before it, so a fresh clone builds.

## 9. Release

Minor release `1.4.0`: behaviour changes are additive or guarded, and an
unmigrated repo keeps working (§5). CHANGELOG lists the migration steps.
