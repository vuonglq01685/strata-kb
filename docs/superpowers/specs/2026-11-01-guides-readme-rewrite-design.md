# Role guides and README rewrite — design

Date: 2026-11-01 · Size: project

## Intent

The role guides (`docs/src/guide-*.{en,vi}.md`) and the README grew release by
release. They now carry history ("a `-code` document from before 1.28.0…",
"the hub must be 1.29.0 or later"), mix reference detail with how-to, and
the BA and Dev guides last tracked 1.29/1.31 while the code is at 1.34.0. The
README is 2,317 lines and does not even link the guides.

The user wants 1.34.0 treated as the baseline: say what the product does
*now*, drop the history, and make each guide something a person follows in
their daily work. The README becomes the short front door: the problem, the
method, how to use the framework, and where each role's guide is.

## Goals

- One daily-work guide per repo kind: **hub**, **child**, **ba**, **dev**
  (EN + VI each), correct and complete for 1.34.0.
- Each guide follows the same shape:
  1. Who this is for; what this repo does and does not do (a few lines).
  2. **First-time setup** (once): `kb init --kind …`, hub pointer, assistant
     / MCP wiring, CI gate, GitHub prerequisites (branch protection,
     secrets/OIDC) as that kind needs.
  3. **Daily work**, written as "task → command or slash command → expected
     result".
  4. **Automation modes**: for `ba` and `dev`, full-auto (`/kb-auto
     on|off|status|run`, `kb auto …`), its prerequisites, the security
     warning (unattended `gh pr merge --admin`, branch protection required),
     and running on Claude Code cloud. For `hub` and `child`, their own
     automation (auto-summarize, L3 AI fix, Docker / shared server, CI
     publish via OIDC, code-sync) — whatever applies to that kind.
  5. **Troubleshooting**: a short table, symptom → fix.
  6. **Appendix (short)**: reference detail that applies to that kind only —
     gate errors/warnings, config keys, environment variables, exit codes,
     stated limits.
- `architecture.{en,vi}.md` stays the system explainer: reviewed for
  correctness against 1.34.0 and stripped of version history, not
  rewritten.
- README rewritten short: problem → method (four layers, verbatim tables,
  federation) → how to use it (install, pick a repo kind, the lifecycle in a
  few lines) → links to the four guides and the architecture doc.
- PDFs rebuilt from the new sources with `docs/src/build_pdf.py`.

## Non-goals

- No changes to product code, skills or scaffold templates. If writing a
  guide exposes a code bug or a skill that contradicts the code, record it
  for a follow-up; do not fix it here.
- No new doc tooling (no generated command tables).
- `QUICKSTART-dev.md` (scaffolded into dev repos) and
  `docs/deploy-remote-mcp.md` are not rewritten; guides link to them where
  useful, and any contradiction found is listed as a follow-up.
- No version bump.

## Anti-goals

- A guide that states a command, flag, slash command, config key or default
  that the 1.34.0 code does not have. Wrong is worse than missing.
- Version history in guides or README ("since 1.x", "before 1.x", "upgrade
  from…"). The CHANGELOG owns history. Exception: a genuine upgrade step the
  reader must still perform today (e.g. `kb init` refresh) is stated as a
  present-tense instruction, without version numbers.
- Guides that duplicate each other's material at length. Shared concepts
  (citations, kb-context blocks, the four layers) are explained once in the
  architecture doc or README and linked.
- A README that is a reference manual again.

## Constraints

- Source of truth is the code at 1.34.0: `kb --help` and each subcommand's
  `--help`, `src/strata_kb/initcmd.py` (what `kb init --kind` scaffolds per
  kind), `src/strata_kb/templates/init/*` (skills and slash commands), config
  loaders, env-var reads. README / CHANGELOG / old guides are leads only;
  every claim they offer is checked against code before it is used.
- Slash commands exist for Claude Code, GitHub Copilot and Cursor; guides
  name the command once and note it works in all three.
- EN is written first; VI is a faithful translation with the same headings
  and section order, technical terms and commands verbatim.
- File set after the change: `guide-hub`, `guide-child`, `guide-ba`,
  `guide-dev`, `architecture` × `{en,vi}`; `guide-hub-child.*` (md and pdf)
  are deleted. `build_pdf.py` `TITLES` updated to match.
- Tests that pin doc text (`tests/test_readme.py`, the guide references in
  `tests/test_template_bodies.py`) are updated: invariants that are still
  true (e.g. fourteen MCP tools listed, no doc claims "eleven MCP tools",
  version strings consistent) are kept and pointed at the file that now
  carries the fact; assertions that pin wording the rewrite removes are
  rewritten against the new wording or dropped if the fact moved out of
  scope. No test is skipped or deleted just to get green.
- Rebuild uses `uv run --extra docs python docs/src/build_pdf.py`; the build
  must be warning-free (the guard fails otherwise).

## Approaches

1. **Rewrite from scratch, code as source of truth** — *chosen by the user.*
   Per guide: build a fact sheet from the code (commands, flags, slash
   commands, scaffolded files, config, auto-mode prerequisites), write EN in
   the agreed shape, translate to VI, then an independent reviewer checks
   every command/flag/key against the code. Most accurate; most effort
   (nine new Markdown files plus README).
2. Edit the existing guides in place — faster, but keeps the reference-style
   structure and leaves old errors in place because nothing re-checks the
   whole text against code.
3. Generate reference parts from code, hand-write the rest — the appendix
   would never drift, but it needs new tooling, which is out of proportion
   for a one-time rewrite.

## Decided with the user

- Guides are daily-work how-tos, short, plus first-time setup, plus how to
  use the automation modes.
- Reference detail goes to a short appendix at the end of each guide.
- Hub and Child get separate guides.
- Approach 1.
- PDFs are rebuilt by hand (already possible on any OS after the
  cross-platform PDF change on branch `claude/cross-platform-pdf`).

## My calls (not discussed — correct me)

- README stays English-only, as today.
- README target: roughly 200–300 lines. Contributor material (dev setup,
  tests, release) shrinks to a short "Development" section at the end.
- Order of work: fact sheets → guide-dev, guide-ba, guide-child, guide-hub
  (EN then VI each) → architecture review → README last (it links to the
  others) → test updates → PDF rebuild.
- The work lands on the same branch as the PDF change, after it.
- **Cross-kind reference** (Ticket Q&A rules, MCP tools, hub accounts and
  `STRATA_KB_BOOTSTRAP_*`, security rules such as "never put a token in
  `hub:`" and "never commit `.kb-qa/`", exit codes, env vars, config): each
  fact goes into the appendix of every guide whose reader acts on it — a
  short, relevant subset per kind, repeated where needed. The hub guide owns
  the full MCP tool list, accounts and Q&A storage. **No security warning
  is dropped**: the plan lists every security statement in today's README
  and guides and maps each to its new home.
- **README keeps a compact command table** (one line per top-level command
  or group) under a stable heading, so the drift guard
  `test_readme_command_table_lists_every_top_level_command` keeps working.
  Test scope is every test that pins README or guide text, including
  `tests/test_cli_mission.py`, `tests/test_cli_planwaves.py`,
  `tests/test_cli_ticket_check.py` and `tests/test_template_bodies.py`
  (README and guide references), not only `tests/test_readme.py`.
- **Scaffolded quickstarts** (`QUICKSTART-dev.md`, `QUICKSTART-ba.md`, and
  any other template that points at a README section): the only template
  change allowed is fixing those pointers to the new home (the BA / Dev
  guide's automation section). Facts pinned by
  `test_docs_describe_full_auto_mode` (admin-rights merge, include
  administrators, `STRATA_KB_HUB_URL` / `STRATA_KB_HTTP_TOKEN`, …) move to
  the BA and Dev guides and the test follows them.
- **Authoring flow lives in the child guide.** The hub guide covers operator
  work (service, Docker, accounts, Registry, merging publish PRs, CI publish
  via OIDC, multi-tier, S3 assets, code-sync) and links to the child guide
  for ingest → L3 check / AI fix → summarize → build → approve → publish,
  noting that a hub repo can author with the same steps.

## Left to the builder

- Exact headings and wording inside the agreed shape.
- Which troubleshooting rows and appendix items each kind needs, as long as
  each is backed by code.
- How the fact sheets are kept (scratch notes are fine; they are not
  committed).
