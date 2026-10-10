# Docs and business review fixes: copyrighted sources stay out of git, no credential in config, README matches the code

**Status:** approved design (decisions taken 2026-10-10)
**Source:** §3.2 / §3.3 / §4.4 and §8 đợt 1 item 3 of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`, plus §5.2
#8. This is batch 1c of that review's wave 1. 1a shipped in #80 (1.9.0) and
1b in #81 (1.10.0).
**Approach:** as chosen on 2026-10-10:
- Scaffold `source/` **and** `sources/` with an ignore-everything rule. An
  untouched old `*.pdf` file is upgraded in place. `kb doctor` warns on a
  tracked file in either folder.
- README §13 states what is machine-enforced and what is prompt-only.
- A credentialed hub URL lives in `STRATA_KB_HUB`, never in
  `.kb/config.yaml`. `kb doctor` warns on a tracked `config.yaml` whose
  `hub:` carries one.
- The `kb stats` example becomes an illustration inside the C2 budget,
  pinned by a test.

## Goal

The review scored business coverage at 90.0 % strict. Nearly every gap was
a README promise that drifted away from the code, plus one real risk:

| Row | Problem |
|---|---|
| H13 | README's quickstart puts PDFs in `sources/`, but the scaffold only writes `source/.gitignore` (`*.pdf`). Someone following the README has **no ignore rule at all**, so copyrighted documents can reach a shared repo. |
| #8 | `config-child.yaml` says "commit to git" next to `hub:` ("git URL"). README §4 and §9 talk about a credentialed `hub:` as normal. Followed literally, that puts a write token into every child repo's history. CI already passes the hub through `STRATA_KB_HUB`. |
| B17 / C22 | README §8's `kb stats` example shows an 11.1 % saving (L2 = 89 % of L3), which fails the product's own `--strict` budget. "Routinely a >90% reduction" has no measurement in the repo. |
| F1 / F2 / F8 | README §12 says `ba-ticket-author` has 8 steps (it has 9), that maturity review runs up to 3 rounds (the default is 1 since 1.5.0), and that `kb ticket check` reads local before hub (hub first since 1.4.0). It never says the review scores are self-reported. |
| G3 / G4 | README §13 says TDD is "Enforced throughout" (it is a prompt rule), that a small ticket's design "stays in chat", and that `design.md` exists for architectural tickets only. Every path writes `design.md` now. |
| E11 | "Deletions never propagate upstream" is only true for a wiped `federation/`. A partial deletion mirrors. |
| §4.4 | README does not document the `kb usage` subcommands, `kb ticket export` or `kb ticket check` in its command table, or about 15 flags. |
| v0.4 §14.1 | `rel.<name>` and the AST extractor were promised, never shipped, and never recorded as dropped. |

## Design

### 1. `source/` and `sources/` ignore everything (H13)

- **Template.** `templates/init/source-gitignore.txt` becomes:

  ```
  # Copyrighted source documents — never commit anything in this folder.
  *
  !.gitignore
  ```

- **Scaffold.** `COMMON_TEMPLATES` maps both `source/.gitignore` and
  `sources/.gitignore` to it, for hub and child kinds as today.
- **Upgrade.** An existing `source/.gitignore` or `sources/.gitignore` whose
  content is byte-for-byte the old shipped text is replaced without
  `--force` and reported as `updated`. The old text is
  `# Copyrighted source documents — never commit them.\n*.pdf\n`. Any other
  content is a file the maintainer edited: it is left alone, and a `note:`
  says to add `*` / `!.gitignore` by hand.
- **README.** It standardizes on `source/` (§1 quickstart, §7 `kb ingest`,
  §18 FAQ).
- **Doctor.** `doctor.check_source_dirs(repo_root)` warns once per folder
  (`source/`, `sources/`) holding git-tracked files other than
  `.gitignore`. The warning names up to 5 files and says
  `git rm --cached <file>`. It never errors, and it runs for every kind:
  a `ba` or `dev` repo with a tracked PDF there is the same leak.

### 2. No credential in `.kb/config.yaml` (#8)

- **Templates.** `config-child.yaml`, `config-hub.yaml`, `config-ba.yaml`
  and `config-dev.yaml` (where `hub:` appears) gain one comment line:
  `hub:` is committed, so never put a token in it; a credentialed URL goes
  in the `STRATA_KB_HUB` environment variable (it overrides this file).
- **Docs.**
  - README §4 (git 2.31 floor): "a `hub:` URL that carries a credential" →
    "a hub URL that carries a credential (`STRATA_KB_HUB` in CI)".
  - README §9 allowlist: keep the withholding, and reword the reason ("a
    `config.yaml` someone put a credential in"). It must not suggest a
    credentialed `hub:` is normal.
  - README §15: `hub` row says "no credential, since it is committed; see
    `STRATA_KB_HUB`".
  - QUICKSTART-child step 1 says the same.
- **Doctor.** `doctor.check_config_credentials(kb_dir, repo_root)` warns
  when `.kb/config.yaml` is tracked by git and its `hub:` or `intake:`
  carries a credential (`gitio.split_credentials` returns a token). It
  never prints the value. The fix line says: move it to `STRATA_KB_HUB`,
  rewrite `hub:` without it, commit, and **rotate the token**, because it
  is in history.

### 3. README §8 and §1: no unmeasured number (B17, C22)

- **§8 `kb stats` example.** Replaced by an illustration. Both rows sit
  inside the C2 budget (L2 ≤ 35 % of L3), and a caption says it is
  illustrative:

  | doc | L2 | L3 | saving |
  |---|---|---|---|
  | `hr-handbook` | 23 140 | 85 669 | 73.0 % |
  | `travel-policy` | 790 | 2 722 | 71.0 % |

- **The prose** says the saving column is L2 vs L3 for the whole document,
  that `kb build --strict` fails a section above 35 %, and that a query
  loads 1–4 sections, a slice of that.
- **§1.** "routinely a >90% reduction in tokens per call" becomes a
  statement without a number: "a few sections, not the document".
- **Test.** `test_readme` parses the `kb stats` console block and asserts
  every row's L2/L3 ≤ 0.35 and that the printed saving matches
  `1 − L2/L3` to 0.1 %. It also asserts README never says "routinely
  a >90%".

### 4. README §12 matches the BA skills (F1, F2, F8)

- **Pipeline.** `ba-ticket-author` is a **nine-step** pipeline, adding
  *Ground technical* (`sa-ticket-ground` as its own subagent, then
  `kb ticket check`).
- **Maturity review.** **One round by default.** Rounds 2–3 run on request
  or above 6 ACs, and stop early at ≥ 4 on both axes.
- **Scores are agent-reported.** `kb ticket lint` checks only the shape of
  `## Review record`.
- **`kb ticket check`.** It reads the **hub's** `<repo>-code` first, then
  falls back to a local `--kb-dir` copy with a `(local fallback — …)` note.
- **Test.** `test_readme` pins "nine-step", "one round by default", "hub
  first" and "agent-reported". It also counts the numbered `**Step**` lines
  of the packaged `claude-skill-ba-ticket-author.md` workflow, so a tenth
  step breaks the test.

### 5. README §13 matches the dev skills (G3, G4)

- **Enforcement.** "Enforced throughout: no production code without a
  failing test observed first…" is replaced by a short **Machine-enforced
  / Prompt-only** pair that mirrors `QUICKSTART-dev.md` §"What is enforced":
  - **Machine-enforced:** `kb pr lint`, meaning Ticket / Changes / Testing,
    a fenced `cmd.test` run and `Blocking: No`. Also `kb build` on
    `-svc` pending, and the context-cache check.
  - **Prompt-only:** test-first TDD, shown verification output, the
    approvals at GATE 1 and GATE 2, and the A1–A4 reviews.
- **Small tickets.** The "Small ticket … the design stays in chat" row
  becomes "the flow collapses itself; `design.md` is one paragraph".
- **`design.md`.** "(architectural tickets only)" goes. Every path writes it.
- **Not shipped.** A line under `kb code-ingest`: relationship sections
  (`rel.<name>`) and an AST extractor, planned in Architecture v0.4 §14.1,
  were not shipped. The extractors read build and contract files, not
  source syntax. The same line goes into CHANGELOG.
- **Test.** `test_readme` pins that "Enforced throughout" is gone and that
  "Prompt-only" is present.

### 6. Command reference catches up (§4.4, E11)

- **§6 table.** Gains `kb ticket check` and `kb ticket export`. `kb usage`
  gets its own subsection: `ingest-transcript` (`--hook-stdin`, `--ticket`),
  `note` (the hand-entered row and its required flags) and `report`
  (`--ticket`, `--md`, `--json`, `--out`).
- **Flags missing from README:**
  - `kb ticket lint --missions-dir`
  - `kb mission lint --tickets-dir`
  - `kb summarize --max-workers`
  - `kb resolve --status-only/--write-cache/--cache`
  - `kb doctor/build --no-refresh`
  - `kb reindex --force`
  - `kb init --lang/--assets/--force`
  - `kb mcp-setup --hub-url/--token/--no-verify`

  Each goes into the section that owns its command, one line each.
- **Test.** `test_readme` walks the typer app's registered commands and
  groups and asserts each top-level name appears in the §6 table, so the
  next new command cannot be left out.
- **E11.** §9 multi-tier: "An emptied local `federation/` will not
  propagate…" gets a second sentence: removing **some** entries does
  propagate, as a normal mirror, in a PR on the hub.

## Out of scope

- Measuring the real query-level saving or the L2/L3 ratio on a golden
  corpus (B17/C22's measurement half). The repo has no corpus. The README
  just stops claiming a number.
- `kb plan lint` (G3's machine half) and a scheduled `kb-doctor.yml` (H14).
  Both are wave 3 item 11.
- `docs/src/*.md` and their PDFs. The architecture doc no longer has a
  §14.1 to correct. Editing it would mean rebuilding 8 PDFs for one line,
  so the "not shipped" record goes to README and CHANGELOG.

## Testing

- **Init.**
  - A fresh hub or child gets both `.gitignore` files, with `*` and
    `!.gitignore`.
  - A repo with the old exact `*.pdf` text is upgraded and reported
    `updated`.
  - A hand-edited file is left alone, with a note.
  - `git check-ignore source/x.pdf sources/x.docx` matches both in a real
    repo.
- **Doctor.**
  - A tracked `source/a.pdf` warns, naming it.
  - A `sources/` folder holding only `.gitignore` is silent.
  - A tracked `config.yaml` with
    `hub: https://x-access-token:SECRET@…` warns, and `SECRET` never
    appears in the output.
  - An untracked one, or one without a credential, is silent.
- **README.** The pins listed in §3, §4, §5 and §6.

## Delivery

One PR, release **1.11.0** (new `kb doctor` warnings and a scaffold change,
both backward compatible). The CHANGELOG says:

- re-run `kb init` to get the new ignore rules;
- `kb doctor` now names tracked source files and a credential in
  `config.yaml`;
- `rel.<name>` and the AST extractor are recorded as not shipped.
