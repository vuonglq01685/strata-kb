# Changelog

All notable changes to Strata are recorded here. This project follows
[Semantic Versioning](https://semver.org/).

## 1.22.0 — 2026-10-13

`kb ticket check` has an MCP twin, and `kb_ticket_lint` checks the parent-mission back-link over MCP, so the BA and SA skills no longer need a local hub clone for either gate.

- **MCP `kb_ticket_check`.** A seventh MCP tool runs the SA grounding gate, the same engine as `kb ticket check`: ids, columns, routes, commands and files against the hub's `-code` document, and a moved `Grounded on:` revision judged from the hub's history. `[NEW: D<n>]` reads the parent mission from `mission_markdown` (the client passes the local mission file's text whenever there is one; it wins over the hub copy), else from the hub's plan. `heading: "## Services & order"` checks a mission plan. Over MCP the `-code` document comes from the hub only; the CLI's local `--kb-dir` fallback stays CLI.
- **`kb_ticket_lint` back-link checks.** New optional `ticket_id` (the ticket file name without `.md`) and `mission_markdown`. With `ticket_id`, the `> Parent mission:` checks (the mission exists, the story is in its backlog) run over MCP against `mission_markdown`, else the mission on the hub's plan. Without `ticket_id` they are skipped with a note, as before; with it, a mission neither passed nor on the hub is an error, like the CLI's missing mission file. Existing calls behave as before.
- **Skills: ticket check MCP first.** `sa-ticket-ground`, `ba-ticket-author` and `ba-mission-plan` run `kb_ticket_check` and fall back to the CLI; `ba-ticket-author` passes `ticket_id` and `mission_markdown` to `kb_ticket_lint` instead of a final CLI lint. `dev-implement-ticket` stays CLI first (it wants the local fallback) and names `kb_ticket_check` as the no-CLI path.
- **Concurrent cold search index builds (release gate v1.21.0).** Several `kb query` / MCP searches starting on a hub with no `search.db` could fail with `database is locked`: switching the new file to WAL needs an exclusive lock, and SQLite returns `SQLITE_BUSY` immediately (without waiting the busy timeout) while another cold build holds its write lock. The switch now retries until the 5-second busy timeout. This failed the v1.21.0 release gate (ubuntu, Python 3.11), so 1.21.0 never reached PyPI; 1.22.0 carries both releases.
- **Upgrade.** Re-run `kb init` in `ba` and `dev` repos to pick up the skills. Restart the MCP server so clients see the new tool.

## 1.21.0 — 2026-10-12

`/mcp` works behind a reverse proxy, a dev repo's publish job can succeed, the skills reach the hub through MCP first, and `kb mission next` has an MCP twin.

- **`STRATA_KB_ALLOWED_HOSTS` (#101).** `/mcp` behind a reverse proxy at a real host name answered `421 Invalid Host header`: the MCP SDK's DNS-rebinding check accepted only a localhost `Host`. The HTTP server now reads `STRATA_KB_ALLOWED_HOSTS` (comma-separated host names, e.g. `kb.example.com`) and accepts each one, with any port and over `http` and `https`, as `Host` and `Origin`, besides localhost. The check stays on; an unlisted host is still `421` and an unlisted origin `403`. A scheme, port or path in an entry stops the server at startup. Unset, nothing changes. The proxy-side `header_up Host localhost:8321` workaround is no longer needed. `env.example` and the deploy guide name the variable.
- **Dev publishing is `kb publish` (#100).** `kb-code.yml` ran `kb ci-publish` on every push to `main`/`master`, but the intake accepts an OIDC token only from a `refs/tags/kb-publish/*` ref, so the job always failed with HTTP `403`. The template now publishes only on a `kb-publish/*` tag (pushed by `kb publish`), like the `ba` template; `pull_request` still validates only, and `workflow_dispatch` publishes only when run on such a tag. All publish runs share one concurrency group. A push to the default branch publishes nothing: run `kb publish` after a merge. `kb doctor`'s hub-lag warning says so. QUICKSTART-dev, the `dev-implement-ticket` skill and the README are updated.
- **Skills: hub access, MCP first.** Every skill that reads the hub (`ba-ticket-author`, `ba-mission-plan`, `sa-ticket-ground`, `dev-design`, `dev-plan`, `dev-execute`, `dev-handover`, `dev-implement-ticket`) states the rule and follows it: `kb_search`, `kb_get_section`, `kb_resolve`, `kb_context_new` and `kb_ticket_lint` first, the matching CLI command only when the client has no MCP tool or the server cannot be reached. The ticket lint loop runs on `kb_ticket_lint`; a ticket with a `> Parent mission:` line still gets one CLI `kb ticket lint` before handover, because MCP skips the back-link checks. Commands with no MCP tool, or that write a file with a fixed layout, stay CLI: `kb ticket fetch`, `kb ticket check`, `kb mission lint`, `kb resolve --cache` / `--write-cache`, `kb publish`; BA skills keep `kb mission next` on the CLI because it reads the repo's unpublished `missions/` and `tickets/`. `dev-handover` and `dev-implement-ticket` tell the Dev to run `kb publish` after the merge, so the `-code` and `kb svc note` rows reach the hub.
- **MCP `kb_mission_next`.** A sixth MCP tool gives the `kb mission next --from-hub` report over MCP: every story of the plans published on the hub as done / ready / not ready (no published ticket) / blocked, then the next one (`repo` limits it to one BA repo). The CLI and the tool share one implementation.
- **Upgrade.** Re-run `kb init --kind dev` to pick up the new `kb-code.yml` and skills, and `kb init` in `ba` repos for the skills. Behind a reverse proxy, set `STRATA_KB_ALLOWED_HOSTS` on the hub and drop any `Host` rewrite for `/mcp`.

## 1.20.0 — 2026-10-12

The hub shows documents, tickets and code in separate menus, and search can be limited to one of them.

- **Hub kinds.** Every repo on the hub has one kind: `kb` (from a `hub` or `child` repo), `ba` or `dev`. The kind is recorded in the leaf's `_meta.yaml` and decides the menu. A leaf with no recorded kind has it inferred when read: a generated plan document (plan title plus the `plan`/`generated` tags) is `ba`, a `-code` or `-svc` document with the `code` tag (code-ingest sets it) is `dev`, anything else is `kb`. Nothing moves under `federation/`.
- **Menus.** The Web UI rail is Overview · **Document** (`kb`) · **Ticket** (`ba`) · **Code** (`dev`). Each menu has its own search box, which is a real search limited to that kind, and its own tag cloud. The Plans menu is now Ticket: `/ui/plans…` answers `301` to `/ui/tickets…`. `/ui/code` lists `-code` and `-svc`. Overview counts documents per kind. The `?filter=` substring box on Documents is replaced by the menu search (`?q=`).
- **Top search = all kinds.** One ranked list with a kind badge on every hit and chips (All, Document, Ticket, Code, with counts; `?kind=`) to narrow it. The chip filters the one budgeted search the top box ran, so a menu search can list more hits than the chip. An unknown `?kind=` shows an empty state.
- **Kind filter on search.** `kb query --kind <kb|ba|dev>` (repeatable), MCP `kb_search(kinds=[...])` and REST `/api/search?kind=` (an unknown kind is `400` `unknown_kind`; the CLI and MCP print the error). No filter returns what it returned before. REST search results and `/api/docs` entries carry `kind`. The search index schema is bumped, so the cache rebuilds itself once.
- **Registry `kind:`.** A `federation/registry.yaml` entry may be `{repo_id, kind, workflow?}`; a plain string entry is still valid. On a governed hub the registry kind wins and the publisher's kind is only checked against it. A clash is refused: `kb publish` errors and the intake answers `403`, both naming the two kinds and pointing at `kind:` in `federation/registry.yaml` or the repo's `.kb/config.yaml`.
- **`kb publish` and kind.** It records the kind in `_meta.yaml`, prints `kind: <kind> → hub menu: <menu>` before sending anything, and refuses a repo whose kind is not recorded in `.kb/config.yaml` (`kb init --kind …`).
- **Child hubs send only `kb` upward.** A child hub still accepts `ba` and `dev` publishes and has all three menus. Publishing to its parent, it sends only `kb` leaves (its own and nested ones) and prints a `skipped` line for each other leaf. **`ba` and `dev` leaves a child hub pushed to its parent earlier are removed from the parent on its next publish** (owner-approved; git history keeps them and the child hub still has them). A non-`kb` leaf nested under a child hub on a parent is not served by the UI or search, and `kb doctor` names it.
- **`kb doctor`.** Hub: registry entries without a kind (warning), a leaf whose recorded kind is unknown or clashes with the registry, and nested non-`kb` leaves (errors). Child: an `info` line with the hub menu the repo lands in, a warning when the hub registry has no kind for it and an error when it holds a different one. `kb doctor` gains the `info` level.
- **`kb init --kind hub` fills registry kinds.** For each entry without a kind it proposes one from what the repo has published (a child-hub namespace is `kb`), asks for the ones it cannot infer, shows the diff and asks before writing; `--yes` writes without asking and exits `1` when an entry cannot be inferred. It edits `registry.yaml` line by line so comments survive, never commits, and exits `1` on an invalid registry.
- **Skills pass the kind they need.** BA skills search `--kind kb --kind dev`; `dev-implement-ticket` searches `--kind dev` for its own code, with separate `--kind ba` and `--kind kb` lookups; `sa-ticket-ground` searches `--kind dev`; `kb-code-sync` searches `--kind kb`. The `/kb-publish` confirm step shows the kind line and stops on an unrecorded kind. Re-run `kb init` to pick them up.
- **Docs.** README gains "Menus", "Registry kinds and the 1.20.0 upgrade" and the `--kind` flag; the hub guide shows `kind:` in the registry example; every "Plans menu" and `/ui/plans` mention is now Ticket and `/ui/tickets`. The PDFs under `docs/` are not rebuilt by this release.
- **Upgrade.** Upgrade the hub (and its intake service) first. Then upgrade every publisher that reads the registry itself (local or direct `kb publish`, and child hubs) **before** running `kb init --kind hub` and committing the registry kinds: an older strata-kb rejects a registry with `kind:`. Publishers on the intake route are unaffected. Old clients keep publishing meanwhile (the registry kind wins and the leaf kind is inferred until its next publish that carries a kind, which records it with a `_meta.yaml`-only PR even when content is unchanged). A child hub's next publish, once upgraded, removes its `ba` and `dev` leaves from the parent. `kb init --kind hub` on a hub whose registry has kind-less entries asks to fill them: decline until the publishers are upgraded; a non-interactive run without `--yes` prints a warning naming the entries, writes nothing and exits `0` (re-run with `--yes` once publishers are upgraded). Until the registry is filled, `kb doctor` on the hub warns per entry and the UI is already right through inference.

## 1.19.0 — 2026-10-11

Hub documents that name code can be kept in step with the code docs, with a daily scan and a rolling review PR.

- **`authored` tag and `kb authored`.** `kb authored <doc>` (`--off` to clear) tags a hub document whose markdown is now the master. `kb ingest` refuses an `authored` document, full and `--sections`, before docling runs. `kb summarize --redo` stays allowed. No schema change: it is an index tag, like `generated`.
- **`kb code-sync scan`.** Hub only, deterministic, no LLM, never writes the worktree. It compares the `-code` / `-svc` documents between the baseline commit and the tip of the default branch (`origin/HEAD`; HEAD only for a hub with no remote) and lists the hub sections that name something added, removed or changed, grouped by document and section. A hit inside an image description is labelled `image`. `--md` is the work order, `--json` the machine form, `--baseline <sha>` overrides the baseline. Exit `0` nothing to do, `2` findings, `1` error. A `note:` names each hub document that is not `authored`; the tag `code-sync-skip` leaves a document out. Same inputs give byte-identical output.
- **Findings by category.** Each finding is `removed`, `changed`, `added` or `image` (a name found only in a picture's description). `scan --json` gives every finding a `category` and the output a `counts` object; `--md` and the issue group findings under one heading per category, in that order, then by document and section.
- **`kb code-sync issue [--json]`.** Hub only, needs `gh`. The job's issue body now starts with an identity marker (`<!-- kb-code-sync work-order v1 scan:<sha> baseline:<sha> -->`) and still ends with the digest. The command lists the open `kb-code-sync` issues and judges each: `current` (its baseline is the recorded one and a local scan gives its digest), `stale` (its baseline or findings differ from a local scan), `duplicate` (older than a newer job issue), `foreign` (no marker, digest or baseline, or a baseline outside the default branch's history). Exit `0` a current or stale issue exists, `2` none, `1` error; `--json` names it as `usable` and gives the baseline recorded in git as `baseline_sha` (the issue's own claim is `issue_baseline_sha`, informational). Issue text is never trusted: nothing is taken from it to drive a scan. The job itself only rewrites or closes an issue that carries the identity marker.
- **`kb code-sync baseline [--at <sha>]`** records the commit the sync is current at in `kb-code-sync.yaml` at the hub root (default: the scan sha). **`kb code-sync run [--issue] [--loop]`** is one scan plus the issue update, or that forever.
- **`hub-sync` compose service.** A second service in `docker-compose.yml` and the hub template runs `kb code-sync run --issue --loop` every `STRATA_KB_CODE_SYNC_INTERVAL` seconds (default `86400`, minimum `60`). It never pulls, commits or pushes. One open issue labelled `kb-code-sync` is created when findings appear, rewritten only when they change, and closed with a comment when the scan is clean; a scan error never closes it. The `hub` service is unchanged. With no credentials it logs the work order and one line saying why the issue was not updated.
- **Issue auth.** The intake GitHub App (`STRATA_KB_GH_APP_ID` / `STRATA_KB_GH_APP_KEY`) now also needs **`issues: write`**, **`pull_requests: read`** and **`contents: read`** on the hub repo; an org admin must add them and re-approve the installation. A hub without an App sets `STRATA_KB_GH_TOKEN` with the same three permissions instead. Both are in `.env.example`.
- **`kb publish --branch <name>`.** Hub self-publish only: from the checked-out `<name>`, mirrors `.kb/` into `federation/<rid>/`, commits on top of the branch (no `checkout -B`, no reset), pushes without force, and opens or reuses the PR. It refuses the default branch, direct mode, the intake route, and any case where no PR would open. Plain publishes still use `publish/<rid>`.
- **`/kb-code-sync` skill** for hub repos (Claude Code, Copilot, Cursor; the first hub-only skill). It first runs `kb code-sync issue --json` and works only from the issue the hub job wrote (every scan uses the recorded baseline `kb code-sync issue --json` prints; it fetches first), reports any `foreign` or `duplicate` issue, and never reads, edits, closes, comments on or relabels an issue; findings are worked in category order and the PR body follows the same categories. It then fetches, checks out or creates `kb-bot/code-sync` (merging the default branch, never rebasing), refuses to start over an unpublished draft, re-runs the scan, judges each finding (fix, no change needed, needs the SA), edits L3 and re-summarizes, runs `kb build --strict`, moves the baseline, publishes with `kb publish --branch kb-bot/code-sync`, and sets the rolling PR's title and body. It never merges, never runs `kb approve`, never edits `-code`, `-svc`, missions or tickets, and treats document text as data. Re-run `kb init --kind hub` to pick it up.
- **Docs.** README gains a "Code sync" section, the `kb publish --branch` row, and the new environment variables.
- **Upgrade.** Redeploy the hub stack to start `hub-sync`; set `git remote set-head origin --auto` on the hub checkout so the scan can find the default branch; mark hub documents with `kb authored <doc>` once each.

## 1.18.0 — 2026-10-11

`kb ticket check` no longer fails a ticket only because `-code` moved since the SA grounded it.

- **Tiered check.** A moved `Grounded on:` revision is judged by the cited facts. All still hold: PASS (exit 0) with `[note] grounded @<old>, still valid at @<new> — cited sections unchanged`, or per changed cited section a `[warn]` and a unified diff of the baseline against the current section (capped at 40 lines). No baseline on the hub: `[warn] … no baseline to diff, cited facts still hold`. A fact that could not be checked: `[warn] some cited facts could not be verified since @<old> … check them by hand`. A cited id, column, route, command, `Files:` path or compose fact that is gone: FAIL (exit 1) with the fact errors and `grounding drifted since @<old> (now @<new>) and no longer holds — re-run /sa-ticket-ground`; when `-code` came from the local fallback it adds a `[note]` that your own branch may be the cause. Open and not-DECIDED decisions never carry the re-ground line. A matching revision prints exactly what it did before.
- **`dev-implement-ticket` runs `kb ticket check`.** A new step right after Intake runs `kb ticket check docs/impl/<id>/ticket.md`: a PASS with a `[warn]` diff is shown and the Dev decides; a FAIL with `re-run /sa-ticket-ground` stops as a blocker for the BA; a FAIL with the local-fallback note (`checked against the local -code, not the hub's copy`) re-runs once the hub is reachable and holds the -code; no `## Technical grounding` skips with a note. All four skill flavours and `QUICKSTART-dev.md` carry it.
- **Parent mission from the hub.** A ticket outside a BA repo (such as `docs/impl/<id>/ticket.md` in a Dev repo) reads its parent mission's decisions from the hub `<repo_id>-plan` document when no local `missions/` holds it, so `[NEW: D<k>]` rows are checked there too.
- **`ba-ticket-author` amend rule.** `kb ticket check` now runs on every amend, whatever the trigger. The SA still runs first for an `architecture` trigger; for any other trigger it runs only when the check FAILs with `re-run /sa-ticket-ground`, and the "re-run by hand" rule follows the same test instead of "when `-code` moves". `ba-mission-plan` is unchanged. `sa-ticket-ground` learns that a `[warn] grounded @…` is a PASS.
- **Public helpers.** `ticketstale.drift_refs` and `ticketstale.cited_ids` are now public: other modules may call them. `kb ticket stale`, its exit codes and `kb-doctor.yml` are unchanged.
- **Docs follow.** The BA, Dev and architecture guides (English and Vietnamese), `QUICKSTART-ba.md`, `QUICKSTART-dev.md` and the README describe the tiered check, the Dev-side Check step and the split amend rule (tickets check on every amend; missions only for `architecture`).

## 1.17.0 — 2026-10-11

BA repos can publish their plan to the hub, and missions and tickets can be amended in place.

- **Plan publishing.** New `kb plan-ingest` builds `.kb/<repo_id>-plan/` from the missions and tickets that are ready: lint passes, every Definition of Ready box is ticked, and `kb mission next` would not demote the ticket. It is deterministic and offline. Anything left out prints as `skipped: <file> — <reason>`. In a `ba` repo, `kb publish` runs `kb plan-ingest` and `kb build` first, then tags, and CI sends `<repo_id>-plan` to the hub through the intake as a child repo's publish does. `kb doctor` now advises `kb publish` for a drifted `-plan`.
- **`kb init --kind ba` scaffolds publishing.** It writes the `kb-publish` workflow, the `kb-publish` skill and `.gitattributes`, and gitignores `.kb/*-plan/` and `.kb/index.yaml`, since both are generated. `config.yaml` gains an empty `intake:` key.
- **Revision and change log.** Missions and tickets carry `> Revision: <N>` and an append-only `## Change log` (`Rev | Date | Trigger | What changed | Affected | Review`). `kb mission lint` and `kb ticket lint` fail unless a revision above 1 has exactly one row per revision `2..N`, in order, each with a known trigger (`kb-context`, `architecture`, `scope`, `delivery`). A missing `Revision` reads as 1 with a warning, so old files still pass.
- **Amend modes.** `/ba-mission-plan --amend M-<slug>` and `/ba-ticket-author --amend <ticket>` read the file and its `kb ticket stale --md` findings, re-pin `## KB context` (the full ref list, one block), bump the revision and append the change-log row. The SA and `kb ticket check` run only for an `architecture` trigger. Done stories are frozen, a mission's `Affected` cell lists full story ids (`M-<slug>-US<n>`), and amendment scores go in the row's `Review` cell. The agent never ticks Definition of Ready, commits or pushes.
- **Superseded decisions.** A `DECIDED` row in `## Technology decisions` is never edited: a new row says `Supersedes D<k>` and `D<k>` becomes `SUPERSEDED`. `kb ticket check` rejects a `[NEW: D<k>]` that names a `SUPERSEDED` row and points at the superseding one. `kb mission next` judges a `SUPERSEDED` blocker by the row that supersedes it, so a story is not blocked for ever.
- **Tickets follow their mission.** A ticket's parent line may be `> Parent mission: M-<slug> @ rev <N>` (absent `@ rev` means 1). When the mission's revision is higher and a later change-log row lists the story in `Affected`, `kb mission next` reports the ticket `draft` with reason `parent mission rev <M> affects this story`.
- **Architecture drift in `kb ticket stale`.** Besides KB-context citations, it now compares the `svc.*` ids in a mission's `## Services & order` and the ids in a ticket's `## Technical grounding` with the `-code` document they were grounded on. A changed section is `stale`, a removed one `broken`, and a `Grounded on:` revision the hub does not have is one `stale` finding, `baseline not on hub`. The report gains a `Kind` column (`kb-context` or `architecture`); `--json` carries `kind`. Exit codes and `kb-doctor.yml` are unchanged.
- **`kb ticket fetch <id>`.** A dev takes a ticket by id from the hub (`<id>` or `<repo>:<id>`); it restores the ticket to its source shape and writes `docs/impl/<id>/ticket.md`. The dev skills (`dev-implement-ticket` and the others) now read the hub first and fall back to a pasted ticket. `kb init --kind dev` gitignores `*/ticket.md` under `docs/impl/`. An id that would escape its directory is refused.
- **Intake fix: the old PR branch is gone.** When `publish/<rid>` survived on the hub's clone but its remote branch had been deleted (PR closed or merged), a resend either opened no PR or carried the closed PR's history. The intake now checks the remote and starts a fresh branch. **Redeploy the hub's intake service to get this fix.**
- **Plan status on the hub.** `kb mission next --from-hub [--repo <ba-repo>] [--json]` reports every story from the hub alone, with no `missions/` or `tickets/` read: `done` from the Dev repo's `-svc` history (found from the mission's `Grounded on:` line), `ready` when the ticket is published, `blocked` with its reasons, and `to-draft` shown as `not ready (no published ticket)` (`--json` keeps `to-draft`). A missing `-svc` or `Grounded on:` is a `note:` line, never an error. The hub web UI gains a **Plans** menu beside Documents: `/ui/plans` (`?repo=<id>` for one repo), `/ui/plans/<mission>?repo=<id>` (backlog with status, reasons and ticket links) and `/ui/plans/<mission>/<story>?repo=<id>` (the ticket); the repo is a query parameter so nested federation ids work, and `repo` may be left out when only one repo publishes that id. Status is derived and read-only; nothing new is stored. Generated plan documents no longer appear under Documents, in the overview counts or in the tag rail, and a search hit in one links to its Plans page.
- **Publish and plan details.** In a `ba` repo, `kb publish` refuses when `missions/` or `tickets/` has uncommitted or untracked changes, because CI publishes the tagged commit and `.kb/` is gitignored there. Only documents `kb plan-ingest` generated (title ending `— plan`, tags `plan` and `generated`) are treated as plans: a hand-ingested `release-plan` stays under Documents. Plan readers skip a symlinked document folder. `kb ticket stale` no longer reports architecture drift for a story already done in the Dev repo's `-svc` history, nor for a mission whose whole backlog is done, and a bare `[NEW]` row is no longer reported.
- **Existing BA repos need three manual steps.** Add `intake: <url>` to `.kb/config.yaml`, ask the hub maintainer to register the repo in the hub's `federation/registry.yaml` (key `owner/repo`, mapped to your `repo_id`; leave `workflow:` unset), then re-run `kb init --kind ba` to pick up the workflow, skill, `.gitattributes` and gitignore lines. Until then `kb publish` takes the snapshot route (direct or a PR on the hub, no CI or intake).

## 1.16.3 — 2026-10-11

Internal cleanup. No command output, message, exit code or JSON shape changes, except the two `kb doctor` hub-lag heading cases named below.

- **No import cycle left, even through function-level imports.** The 20-module loop that lazy imports had been hiding is gone. Three things moved, and their old import paths still work:
  - The Markdown masking helpers (`FENCE_RE`, `HTML_COMMENT_RE`, `visible_body` and two private helpers) now live in a new leaf module, `strata_kb.mdmask`. `lintcore` re-exports them. `ticket`, `kbcontext` and `prlint` now use it, so `kbcontext` and `prlint` drop their own copies of the HTML-comment regex.
  - `_fed_tree_digest` moved from `doctor` into `federation`.
  - `AmbiguousDocError` moved from `query` into `errors`.
- **New guards in `tests/test_layering.py`:**
  - any import cycle fails the suite, function-level imports included;
  - `prlint` and `mdmask` may import only the standard library;
  - every module must import cleanly as the first module in a fresh interpreter.
- **One required-section check.** `kb ticket lint` and `kb mission lint` now share `lintcore.check_required_filled`, instead of two copies of the same function.
- **`kb doctor` hub-lag reads section ids with the standard heading grammar.** It uses `mdutils.HEADING_RE` instead of parsing them by hand. Two edge cases change, and `kb code-ingest` writes neither:
  - a `## ` line with no id is now body text of the section above it;
  - a tab before the title is no longer part of the id.
- **Closed as intended, no code change:**
  - `prlint` keeps its own scanner. It handles `~~~` and unclosed fences, an unterminated comment, and tab-separated headings, and it must stay standard-library only.
  - The heading regexes in `web/mdrender`, `prlint` and `planwaves` parse different grammars.
  - `prlint.Finding`, `doctor.Issue` and `quality.Finding` stay three separate types, because their levels, keys and JSON contracts differ.
- The duplicate `_ENTRY_SEGMENT_RE` definition in `doctor/checks/hub.py` is gone.

## 1.16.2 — 2026-10-11

Contributor tooling only. Nothing in the installed package changes.

- **The test suite runs in parallel.** `pytest-xdist` is in the `dev` extra. CI's T1 and `scripts/gate.sh` run `pytest -n auto`. Locally, on 4 cores, the full suite went from 325 s to 96 s with the same results.
- **Faster Windows CI.** The Windows T1 jobs also turn off Defender real-time scanning on the throwaway runner. They were taking about 25 minutes, against about 2.5 for the Ubuntu jobs.
- **No more download race.** CI and `gate.sh` fetch the tiktoken file once, before the workers start, so parallel workers never race to download it.
- **Slowest tests shown.** T1 prints its 15 slowest tests (`--durations=15`).

## 1.16.1 — 2026-10-11

Comments and docstrings only. No behaviour or exit code changes.

- **Every module under `src/strata_kb` has a docstring.** Each one says what the module owns and what a reader must know before touching it. 40 modules had none, among them `cli.py`, `publish.py`, `intake.py` and `searchdb.py`.
- **Comments no longer point at internal reviews.** Tags like "F-D9 finding 2", "wave I-1 round 4", "fix round 1, Important 3" and "spec 2026-09-25 §4.1" are gone from comments and docstrings. The rationale they carried stays: what the code does, why, and the failure it prevents. Git history keeps the old wording.
- **Two error messages are shorter.** A truncated asset record and the `.kb-work/` warning from `kb doctor --hub` dropped the same kind of tag from their text.
- **New test:** `tests/test_source_hygiene.py` fails on a module with no docstring, and on a comment that cites an internal review again.

## 1.16.0 — 2026-10-11

- **Merged tickets are re-checked.** New `kb ticket stale [PATH...]` lists every ticket and mission (default: `tickets/` and `missions/`) whose citations the hub has moved since they were pinned. `--md` gives an issue body and `--json` gives data. It exits 0 when everything is current, 2 when citations are only stale, and 1 when any is broken. `ba` and `dev` repos now get `.github/workflows/kb-doctor.yml`, which runs it daily. While anything is stale or broken it keeps one open issue, labelled `kb-stale-citations`, up to date; once everything is current it closes that issue. Re-run `kb init` to pick up the workflow.
- **A ticket's cost, end to end.** `kb usage report --with <other .kb>` adds another repo's ledger, typically the BA repo's clone, so `--ticket T` covers both the BA phases and the Dev phases. It is read-only, and a row read twice counts once.
- **Cost is back in the PR.** `kb usage report --ticket T --summary` prints a short `## Usage` block: the total and the costliest phases. `dev-handover` pastes it into the PR, and the PR template has an optional `## Usage` section. `kb pr lint` still requires only Ticket, Changes and Testing.
- **`kb svc note` sorts by number.** It orders ticket ids numerically, so `T-2` comes before `T-10`.
- **New test for unpublished documents.** A document in the hub's own `.kb/` that was never published must not come back from `kb query`/`kb get`, MCP, the REST API or the Web UI. This was already true; the test now guards it.

## 1.15.2 — 2026-10-11

- Skill templates: a skill's Copilot and Cursor copies, and for seven skills its Claude skill too, now share one body under `templates/init/bodies/`. Each copy keeps only its own frontmatter and intro. `kb init` writes exactly the same files as 1.15.1, byte for byte; an edit to a shared skill is now made once.

## 1.15.1 — 2026-10-10

Internal structure only; no behaviour, message or exit-code change.

- `codeingest/types.py` holds the types extractors receive and return, and `codeingest/localgit.py` the code-ingest git helper. `codeingest.core` imports its extractor registry at the top of the module instead of at the bottom to dodge an import cycle. `core.CodeSection` and friends still resolve.
- `serving/` holds what the MCP server, the Web UI/REST app and the intake routes share: `ServerConfig`, bearer/session auth and rate limiting (moved from `web/auth.py` and `web/ratelimit.py`). `web` no longer imports `mcp`, and `intake` no longer imports `web`. `strata_kb.mcp.ServerConfig` and `BearerAuthMiddleware` still resolve.
- `doctor` is a package: `doctor/issues.py` and one module per concern under `doctor/checks/` (local, usage, assets, context, hub, dev). `from strata_kb.doctor import check_hub` and the other names still work.

## 1.15.0 — 2026-10-10

- A git, search-index, code-ingest, `kb svc note` or LLM-runner error that a command did not handle now ends that command with one red line and exit 1, like every other operational error, instead of a Python traceback. `GitError`, `IndexBusyError`, `CodeIngestError`, `SvcNoteError` and `RunnerError` joined the `KbError` family, and the root `kb` command catches that family once.
- Internal: the route `kb publish` takes (hub-to-hub, intake, or a snapshot of `.kb/`) is decided by `publish.plan()`, and the `kb doctor` checks run in `doctor.run()`. Both are library calls now, tested directly. Messages and exit codes are unchanged.
- `.git-blame-ignore-revs` lists the 1.14.1 reformat. `git config blame.ignoreRevsFile .git-blame-ignore-revs` makes local `git blame` skip it; GitHub does so on its own.

## 1.14.1 — 2026-10-10

- The search index's embedding backfill refuses an embedder that returns fewer vectors than it was given texts. Before, the unmatched sections were silently left without a vector while the index still recorded full coverage, so they were never embedded on later syncs either.
- The intake server's GitHub App client reports a GitHub reply that is valid JSON but not an object as its usual one-line error, instead of a bare `TypeError`.
- Development: CI's T0 tier (and `scripts/gate.sh`) now runs `ruff check .` with the B, I, UP and SIM rules on, `ruff format --check .`, and `pyright` in basic mode on `src/`. The repo is formatted with `ruff format` (line length 88). `pyright==1.1.414` joins the `dev` extra. No other behaviour changes.

## 1.14.0 — 2026-10-10

- `kb resolve`, `kb_resolve` and the ticket lint's citation check read every pinned file through one `git cat-file --batch` process, instead of four git processes per citation: 5 citations went from 22 git processes (199 ms) to 3 (113 ms) on a 2,000-section hub.
- `kb summarize` writes results every 25 sections instead of only when the whole run finishes, so a crash or Ctrl-C keeps everything already summarized (and paid for); re-run to continue. Document (L0) summaries now run in parallel like sections.
- At the default `effort: high`, the Claude thinking budget scales with the prompt (about twice its tokens, between 4,000 and 31,999) instead of 31,999 for every section; short sections, most of them, cost less. `effort: medium`/`low` are unchanged.

## 1.13.0 — 2026-10-10

- Each `.md` / `.raw.md` is split into sections once instead of once per section (`mdutils.section_map`; `slice_section` returns exactly what it did). The search index's cold sync of 2,000 sections at 500 per file went from 4.2 s to 0.33 s, and `kb build`, `kb summarize` and the search index read each file once per document.
- Token counting no longer needs the Internet after the first run, and never crashes without it. tiktoken is imported only when a count is needed, and its `cl100k_base` file is cached in `~/.strata-kb/tiktoken` (it used to sit in the system temp dir, which a reboot or a new container empties). A file already cached in the old place is still found. When the encoding cannot be loaded at all, counts become an estimate (~4 characters per token) and one warning says so: this affects the `~Ntk` display, budgets and `kb stats`, never content. `TIKTOKEN_CACHE_DIR` still wins when set.
- A publish hashes only the repo it wrote: the other entries in `federation/index.yaml` keep the `content_sha256` they were published with, instead of the whole hub being re-hashed on every publish. This also keeps an in-place edit to another entry visible to `kb doctor` rather than re-recording it. `kb reindex` still recomputes everything.

## 1.12.0 — 2026-10-10

- The hub server no longer freezes. Every Web UI / REST route except `/api/health` now runs off the event loop (Starlette's threadpool), so a slow page never holds up MCP or other requests: on a 2,000-section hub, `/api/health` took 7.9 s while `/ui` rendered and now stays under ~110 ms. `resolve_hub` takes a per-cache lock around clone/pull, since web routes now resolve the hub from worker threads as MCP tools already did.
- YAML is parsed with libyaml (`CSafeLoader`, falling back to the pure-Python loader) and each parsed file is cached by `(mtime, size, ctime, inode)`. A file changed in the last 2 seconds is always re-read. Callers get a fresh model each time. Measured with the new `scripts/perf_web_bench.py` (2,000 sections): `load_federation` 861 → 8 ms, `/api/docs*` ~0.9 s → 8–12 ms, `/ui` 7.9 s → 53 ms, `/ui?q=` 3.4 s → 41 ms, section page 3.6 s → 23 ms; at 10,000 sections every route stays under 270 ms. Writing YAML is unchanged (still the pure-Python dumper), so committed files are byte-identical.

## 1.11.0 — 2026-10-10

- `kb init` (hub, child) writes `source/.gitignore` **and** `sources/.gitignore`, each ignoring every file in its folder (`*`, `!.gitignore`). Before, only `source/` was covered, and only for `*.pdf`, while README's quickstart put documents in `sources/` — whoever followed it had no ignore rule. Re-run `kb init` to pick it up; README now says `source/` throughout.
- `kb doctor` warns, on every kind, about files git tracks under `source/` or `sources/` (naming up to five, with `git rm --cached`), and about a tracked `.kb/config.yaml` whose `hub:` or `intake:` URL carries a credential (never printing it; move it to `STRATA_KB_HUB`, commit, rotate the token). The config templates say so next to `hub:`.
- README matches the code: `ba-ticket-author` is nine steps with one maturity round by default and agent-reported scores; `kb ticket check` reads the hub's `-code` first; §13 separates machine-enforced checks from prompt-only rules (TDD is prompt-only); every ticket writes `design.md`; the `kb stats` example sits inside the 35 % L2 budget and the unmeasured ">90 %" claim is gone; `kb ticket check`, `kb ticket export` and the `kb usage` subcommands are in the command reference with the flags that were missing. `tests/test_readme.py` pins each of these, plus "every top-level command is in the §6 table".
- Recorded as not shipped: relationship sections (`rel.<name>`) and an AST extractor, planned in Architecture v0.4 §14.1. `kb code-ingest` reads build, deploy and contract files, never source syntax.

## 1.10.0 — 2026-10-10

- `kb_get_section`, `kb get`, `/api/docs/<doc>` and `/ui/docs/<doc>` refuse a doc id outside the doc grammar (`[A-Za-z0-9][A-Za-z0-9._-]*`) or one that resolves outside its repo (a symlink). `kb_get_section(doc="../../.kb/<doc>")` used to read the hub's own unpublished `.kb/` and cite it as another repo's. An invalid id reads as not found.
- `POST /ui/login` caps the body at 8 KiB however it is sent. A chunked request with no `Content-Length` used to reach `request.form()` unbounded, so one unauthenticated request could run the service out of memory. A non-ASCII form token is a failed login, not a 500.
- `/intake/status` without a token answers `{state, pr_url}`; `detail` goes only to the caller presenting that repo-id's OIDC token. **Dev-machine `kb publish` through `intake:` works again** — it had polled a route that demanded OIDC and timed out after 600 s even when the hub PR was open. Against an older hub it now fails at once and says to check the Actions run and upgrade the hub. An intake error without detail names the Actions run for the tag.
- `/intake/manifest` and `/intake/status` share a 120/minute per-caller limit, checked before any JWT work.
- **Breaking for operators:** the http server refuses to start when `STRATA_KB_HTTP_TOKEN` is `change-me`, shorter than 32 characters, or not printable ASCII. Fix: `kb docker-setup --force` (writes a 48-character token) or set `STRATA_KB_HTTP_TOKEN` to `python -c "import secrets; print(secrets.token_hex(24))"`, then update the token in every `kb mcp-setup` client.
- The intake worker's `git pull` and pushes time out after 300 s with prompts off, so a hung remote no longer holds the publish lock for every repo.
- `/assets/<name>` serves only from `federation/`, never the hub's own `.kb/`.

## 1.9.0 — 2026-10-10

- `kb usage` counts subagents. Claude Code writes each subagent's transcript to `<session-id>/subagents/`, which the `Stop` hook never read: on the session measured for the 2026-10-10 review, the hook had seen 33 % of the cost. A new `SubagentStop` hook ingests each finished subagent, and `Stop` sweeps the folder, holding back each subagent's possibly in-flight last call. Rows are tagged `sidechain`; the HTML report's "Main thread vs subagents" table splits the cost. `kb init --kind ba|dev` scaffolds both hooks. Existing repos: add the `SubagentStop` hook to `.claude/settings.json` — `kb doctor` warns when `Stop` is there and `SubagentStop` is not; until then the `Stop` sweep still records subagents, minus each one's last call. An older `kb` reads a `SubagentStop` payload as another `Stop` and records no subagent call.
- Known limitation: Claude Code's subagent transcripts carry each call's output count from the start of the stream (2–21 tokens measured), never the final one, so subagent **output** tokens are a lower bound. Input and cache tokens, the bulk of the cost, are complete.
- `kb usage ingest-transcript <main.jsonl>` includes that session's subagents, and a `subagents/agent-*.jsonl` path finds its parent for attribution. A manual ingest holds nothing back, so run it only after the session has ended.
- The ledger append holds a lock on `.kb/usage/.lock`, so a `Stop` and a `SubagentStop` finishing at the same moment cannot both store a call. `.kb/usage/.gitignore` (written next to it) keeps the lock out of git; commit that file.
- Price table re-verified 2026-10-10: `claude-sonnet-5` is 2/10 (the 3/15 increase did not happen); new rows for `claude-fable-5-1` (cache read 0.25), `claude-opus-5-5`, `claude-sonnet-5-5` and `claude-haiku-5-5` (with its over-100k-token tier). Reports on existing ledgers change on the next `kb usage report`.
- A model id with no price row is now `unpriced`; it no longer inherits its family's price. Add a row to `.kb/usage-prices.yaml`. Bare `opus`/`sonnet`/`haiku` aliases point at the 5.5 generation.
- A streamed call is recorded with its largest `output_tokens`, not the first row's partial count. Rows already in a ledger keep their old count; delete the ledger file and re-ingest to correct it.
- Ledger rows record `inference_geo`, `speed`, `service_tier` and web searches. US-only inference (×1.1) and web search (10 USD / 1,000) are priced; a fast-mode call is priced at the standard rate and flagged, so a total containing one is a lower bound. Any other geo, speed or service tier (`batch`, `priority`) is priced as standard and flagged as an unrecognised modifier.
- `kb usage report` states the unattributed share of cost, or of tokens when nothing is priced.

## 1.8.1 — 2026-10-07

- `kb build --strict` and `kb approve` no longer apply the summary quality rules (brief verbatim, fixed L1 label, invented codes, L2 budget, empty L2) to content the tool writes itself: every section of a `generated` document (`kb code-ingest`) and every `hist.*` section (`kb svc note`). Table and hash checks still run. A `-code` document can be approved again.
- `kb pr lint` reads a mission user-story id (`M-<slug>-US<n>`) in `## Ticket`, so the plan's `cmd.test` check runs for mission tickets too.
- `kb publish --pr` opens a new PR when the last PR on `publish/<repo-id>` was already merged or closed, instead of returning that old PR's link.

## 1.8.0 — 2026-10-07

- Dev repos: each ticket's work lives in one folder — `docs/impl/<ticket-id>/{design.md, plan.md, context.md, review/}` instead of flat `docs/impl/<ticket-id>-*`. New `kb impl tidy` moves a flat layout (idempotent, never overwrites, skips a name whose id is not a plain folder name such as `..-plan.md`, no git); `kb init --kind dev` runs it, and `dev-implement-ticket` runs it at Intake. `kb pr lint` reads `docs/impl/<id>/plan.md` and, on a flat plan, says to run `kb impl tidy`; `kb resolve --write-cache` titles a `<id>/context.md` cache by its folder; the usage ledger follows the new paths.
- Migration for an existing dev repo: re-run `kb init --kind dev`, then commit the renames. A PR opened before the move gets a `plan-missing` warning (not a failure) until its branch is tidied.

## 1.7.0 — 2026-10-04

- The HTTP hub server (`python -m strata_kb.mcp --transport http`) pulls its hub checkout every 5 minutes (`git pull --ff-only`) and re-syncs the search index when HEAD moved — a merged hub PR used to stay invisible until the next intake publish or a manual pull. `STRATA_KB_HUB_PULL_INTERVAL` sets the period in seconds; `0` turns it off. A diverged or hand-edited checkout is left untouched and logged as a warning. Stdio MCP and the CLI are unchanged (they keep `STRATA_KB_HUB_TTL`).
- **Breaking for dev repos on re-init.** The PR body `dev-handover` writes, and `kb pr lint` requires, is now `## Ticket` / `## Changes` / `## Testing`, plus an optional `## Notes` (out of scope, not handled, findings). Testing carries the AC→test line, a fence with the `cmd.test` command and its summary lines, and A5's `Blocking: No`. kb-context, placeholder resolutions, TDD exemptions, the usage table and A5's finding table leave the PR — the branch already carries them (ticket, context cache, plan, ledger, `merge-risk.md`). `kb-pr-lint.yml` pins the strata-kb version, so a dev repo keeps the old nine-section lint until `kb init --kind dev` re-scaffolds the template, the wrappers and the pin together; an open PR written against the old template must be rewritten.

## 1.6.0 — 2026-09-29

- `kb mission next` reports five states: `done` (hub `hist.*` row), `ready` (ticket file with every `## Definition of Ready` box ticked), `draft` (ticket file with an unticked box — reason `DoR n/m ticked` — or no DoR section), `to-draft` (no ticket, dependencies done, D-rows DECIDED) and `blocked`. `Next:` names the first `to-draft` story. **Breaking** for scripts reading the JSON `status`: `drafted` is gone, `ready` changed meaning, `draft` and `to-draft` are new.
- `kb mission next` reads a comma-separated `Grounded on:` line (`<x>-code @ <rev>, <x>-svc @ <rev>`, as `sa-ticket-ground` writes it) and derives the `-svc` document from the `-code` entry — a mission grounded that way used to read `done: unknown (no repo id)` and every merged story as `drafted`. `kb mission lint` warns when no `Grounded on:` line parses.
- Tickets live at `tickets/<mission-id>/<ticket-id>.md`. New `kb ticket tidy` moves a flat `tickets/` into that layout by each file's `> Parent mission:` line (`--into <folder>` for the rest); `kb mission next`, `kb mission lint` coverage, `kb ticket lint` and the usage ledger read both layouts.
- `kb ticket lint`: an NFR `Target` of `N/A — <reason>` passes — the KB holds no number for that concern; a bare `N/A` or a mood still fails.
- BA repos: `ba-ticket-author` runs `kb ticket tidy` at Intake, prints every `note:` line of `kb mission next` verbatim, proposes the first `to-draft` story and saves into the mission folder (or a BA-named one). `QUICKSTART-ba.md` updated. Re-run `kb init --kind ba` to pick up the new text.

## 1.5.0 — 2026-09-29

- Ticket template split into **core** and **extended** sections. Core: Summary, User Story, Background, Acceptance Criteria, Use cases, Business flow, Dependencies, Out of scope, Technical grounding, Open questions, KB context. Extended — kept only when the story needs them, deleted otherwise: Sequence diagram, Non-functional requirements, UI / presentation spec, Test data & verification. `## Sequence diagram` leaves `REQUIRED_HEADINGS` (a relaxation: every older ticket still passes); a code-level sequence is the Dev's to draw at `dev-design`. `kb ticket lint` warns when the story's own words (load, a screen, records, an integration — EN and VI) call for an extended section that is missing, when one is present but empty, and when `## Sequence diagram` is a placeholder; a filled one still gets the mermaid gate.
- Acceptance criteria are Given/When/Then (`Giả sử … khi … thì …`): `kb ticket lint` reports, as one warning, every AC that is not; the error-level floor (a measurable value or an owned `OPEN(<owner>)`) is unchanged. `docs/ac-quality.md` gains the shape section.
- `kb ticket export <file> [--out <path>]`: the ticket for the tracker — guidance comments and the BA-internal `## Definition of Ready` / `## Review record` dropped; `## KB context`, `## Dependencies`, `## Technical grounding` kept.
- `kb ticket lint`, `kb mission lint` and `kb ticket check` fail on a `## ` heading that appears twice — an SA appending a second `## Technical grounding` instead of replacing it used to pass the gate on the stale first copy. `sa-ticket-ground` gains a mandatory step 4, **Verify the write** (`grep -n '^## ' <file>`), before the gate.
- BA repos: `ba-ticket-author` drafts core sections, keeps an extended one only on need, writes Given/When/Then ACs, runs **one** maturity round by default (rounds 2–3 on request or above 6 ACs), and names `kb ticket export` as what goes into Jira; the review rubric and the ticket template say the same. `QUICKSTART-ba.md` and both BA guides updated. Re-run `kb init --kind ba` to pick up the new text.

## 1.4.0 — 2026-09-28

- `<repo_id>-code` is derived on demand and never committed. `kb init --kind dev` adds `.kb/*-code/` to `.gitignore`; `kb svc note`, `kb build` and `kb publish` (dev repos) regenerate it from the working tree first when it is missing, older than `HEAD`, or tracked files changed (`--no-refresh` on `svc note` and `build`). The PR job's `kb build` therefore validates what the merge would publish. `-code`'s revision moves from `index.yaml` to its manifest only, so the committed index no longer churns; the hub reads the manifest.
- Recommended on the hub and on every reader machine: an older reader still indexes `-code` with an empty revision, so `kb query` / `kb_search` citations drop the `(<rev>)` suffix (grounding itself is unaffected — it reads the manifest, not the citation).
- `kb ticket check` reads the hub copy of `-code` first — the copy the SA grounded on — and falls back to the local one with a `(local fallback — …)` note.
- `code_ingest:` in `.kb/config.yaml` (`db`, `tags`) is the one ingest configuration local runs and CI share; `--db`/`--tags` replace it for a run and say so. `kb-code.yml` no longer carries `--db` flags.
- `kb doctor` (dev repos) refreshes `<repo_id>-code` from the working tree first, the same as `svc note`/`build` (`--no-refresh` to check it as is — this is also what recovers a fresh clone or a teammate's pull of the migration's `git rm --cached` commit, where `index.yaml` still lists `-code` but the directory is not there yet). It warns on `--db` flags left in `kb-code.yml`, on an installed strata-kb that differs from `kb-code.yml`'s pin, on a still-tracked `.kb/<repo_id>-code`, and when the hub's `-code` lags `origin/<default>` — judged by regenerating `-code` at that ref and comparing L3, naming the sections that differ; when `origin/HEAD` is not set it reports "origin/HEAD is not set — run `git remote set-head origin --auto`" instead of guessing a branch. Configured `code_ingest.db` files are copied into the temporary worktree so labels match CI. Its published-snapshot check leaves `-code` out for dev repos.
- `kb ci-publish` writes `hub PR: <url>` / `no content change on the hub` / the error to the GitHub Actions job summary, for every failure exit including an unreadable config or a missing intake URL, collapsed to one line.
- `kb summarize` never touches a generated (`-code`) document: `--redo --all` skips it with a note, `kb summarize <repo_id>-code` exits 1. A hub copy summarized earlier returns to deterministic L1/L2 on the next CI publish.
- `kb code-ingest`: `cmd.*` no longer comes from workflows `kb init` scaffolds (`kb-code.yml`, `kb-pr-lint.yml`, `kb-publish.yml`, `kb-ticket-lint.yml`); compose files using `!reset` / `!override` parse instead of being skipped; the k8s reader skips compose-named files (`compose*.y*ml`, `docker-compose*.y*ml`) so a nested compose file is never double-read.
- Migration for an existing dev repo: move `--db` flags to `code_ingest.db`, re-run `kb init --kind dev`, then `git rm -r --cached .kb/<repo_id>-code` and commit — in one PR. `kb doctor` walks you through it.
- `kb mission next`: read-only report of every backlog story across `missions/` as `done` / `drafted` / `ready` / `blocked`, ending with `Next: <us-id> — <title>`. `done` is derived from the hub's `-svc` history tables (the rows `kb svc note` writes at dev-handover and CI publishes on merge) — never from a status column; `ready` needs every `Depends on` story done and every `## Technology decisions` row that `Blocks` the story `DECIDED`; `Depends on` may name a story of another mission. `Decision` rows now carry their `Blocks` ids; `lintcore.table_column` is the shared header-name column lookup. Exit 0 after a report (1 only for a bad directory flag) — it is a query, not a gate. A hub that is not configured or unreachable, or a `-svc` that is not published, is reported as a `done: unknown (…)` note, never a red line. The `-svc` document id is derived from the grounded `-code` document (`mid/repo-x:repo-x-code` → `repo-x-svc`), so a nested federation repo id and an unqualified `Grounded on:` line both resolve.
- BA repos: `ba-mission-plan` asks for the architecture document's doc-id at Intake, makes the first story of a skeleton repo the **foundation slice**, and stops at a new step 5b (**Decide**) to show the whole `## Technology decisions` table once — the SA now cites the architecture document in every greenfield D-row it supports, and the BA flips the cited rows to `DECIDED` there, not ticket by ticket; `ba-ticket-author` with no argument runs `kb mission next` first and proposes the first `ready` story; `dev-handover` says `kb svc note` is what marks a story done on the BA side. Mission template: cited D-row example, cross-mission `Depends on`, a decided-rows Definition of Ready item. `QUICKSTART-ba.md` and both BA guides gain *Which ticket next* and *decide the D-rows once*. Re-run `kb init --kind ba` (and `--kind dev` for the handover wrapper) to pick up the new text.
- `kb plan waves` `<plan-file>`: the dependency waves of a `docs/impl/<ticket-id>-plan.md` — wave n holds the tasks whose every `Depends on:` task sits in an earlier wave — and an exit-1 error for a file shared by two tasks with no dependency path, a cycle, an unknown task, or a task with no `Depends on:` line. Deterministic; `dev-execute` runs it before parallelising. Dev repos: `dev-plan` writes a `Depends on:` line per task (derived from Interfaces and shared files) and its A2 review asks a fifth question and runs `kb plan waves`; `dev-execute` runs a wave of independent tasks in git worktree lanes (at most 3 at a time, merged back with `--no-ff`, a conflict returned to `dev-plan`). `QUICKSTART-dev.md` gains *Waves and lanes*. Re-run `kb init --kind dev` to pick up the new text.

## 1.3.0 — 2026-09-24

- `kb code-ingest`: every compose `svc.*` record now carries `volumes` (named volumes only, sorted), `healthcheck` (the `test` command as one line, `none`, or `disabled`, cut at 200 characters) and `devices` (`<driver>:<caps>` from `deploy.resources.reservations.devices`), in the L2 property table and the L3 YAML block. Dockerfile/k8s records leave them empty. The document changes on the next CI run — that new revision is what the SA re-grounds on.
- `kb ticket check` verifies three new `## Technical grounding` lines — `Volumes:`, `Healthchecks:`, `Devices:` — against those rows, as it already verifies routes and columns: a value the service does not have is an error, `[NEW: D<n>]` exempts a value the ticket creates, a whole-line `none` while the service has volumes is a warning. Tickets written before 1.3.0 (no such lines) get one warning, never an error; a `-code` document generated before 1.3.0 makes the three checks skip with a note.
- `kb ticket lint` warns when an acceptance criterion prescribes a shell command (`docker compose …`, `curl …`, `grep …`, or chains commands with `&&`). An AC states the observable outcome; the command belongs in `## Test data & verification` or the Dev's plan. Suppressed on a line with an owned `OPEN(<owner>)`. `docs/ac-quality.md` gains the row.
- BA repos: `sa-ticket-ground` copies the three new lines and may no longer fold a value the document lacks into an AC — `[NEW: D<n>]` or `Open decisions`, nothing else; `ba-ticket-author` writes outcome-level ACs and never changes a maturity score in a round with no reviewer; the review rubric's Dev axis checks every compose literal in an AC against the grounding; the ticket template's Definition of Ready says the same. Re-run `kb init --kind ba` to pick up the new template text.

## 1.2.0 — 2026-09-22

- `kb ticket check` verifies `[NEW: D<n>]` markers against the parent mission's `## Technology decisions`: the row must exist and be `DECIDED` (an `OPEN` row fails, naming its owner). Greenfield tickets ground code that does not exist yet through a decided design row instead of parking it under `Open decisions`. New `--missions-dir` (default: the sibling `missions/`, as `kb ticket lint`) and `--heading "## Services & order"` to check a mission plan's SA section against its own table.
- BA repos: `/sa-ticket-ground` now runs **inside** the BA pipelines — `ba-ticket-author` step 7 (Ground technical, after `DoR: PASS`) and `ba-mission-plan` step 5 (Ground services, after the backlog is confirmed) — instead of being a manual follow-up, and its handover ends with a fixed `## Needs input` block naming every decision still waiting for a human. The SA proposes an `OPEN` row in the parent mission's `## Technology decisions` for anything the code does not have yet and references it as `[NEW: D<n>]`; only a human flips `OPEN` to `DECIDED`. Ticket and mission templates, the review rubric, `QUICKSTART-BA.md` and both BA guides updated to match. Re-run `kb init --kind ba` to pick up the new skill and template text.
- `kb ticket lint` fails a ticket with more than 10 acceptance criteria, or with more than one `As a … I want … so that …` story under `## User Story`. Both are scope errors, not formatting ones: the fix is to split the ticket, never to merge two conditions into one AC to fit under the cap. The ticket template's Definition of Ready, the `ba-ticket-author` wrappers, the review rubric's Business-coverage axis, `QUICKSTART-BA.md` and both BA guides say the same thing. Exit codes are unchanged (`1` on failure). Re-run `kb init --kind ba` to pick up the new template text.
- `kb init --kind dev` scaffolds a **conventions pack** alongside each `docs/conventions/<lang>.md`: five language-agnostic files under `docs/conventions/common/` (coding style, patterns, security, testing, hooks) and five language-specific ones under `docs/conventions/<lang>/` that extend them. `docs/conventions/<lang>.md` becomes the entry file — it keeps **Citation comments** and **Linting (preset)** and links the ten pack files; its Naming / Module structure / Error handling / Logging sections now live in `<lang>/coding-style.md` and its Testing section in `<lang>/testing.md`. `docs/conventions/<lang>.local.md` still overrides everything and is still never rewritten. The dev wrappers, the Cursor `.mdc` and Copilot `.instructions.md` pointers, and the `CLAUDE.md` block all name the pack. Re-run `kb init --kind dev` to pick it up.

## 1.1.0 — 2026-09-21

- Ingest keeps code blocks (fenced, line breaks and Vietnamese diacritics read back from the PDF text layer), bullet lists, and single-spaced words in L3; text drawn inside a figure becomes the image's alt text instead of loose paragraphs. Re-ingest to pick this up.
- Hub reader renders fenced code and bullet lists, styles headings/figures/code like a markdown preview, and shows the previous/next pager above the article as well as below.

## 1.0.2 — 2026-09-21

- Left-rail section rows truncate long slug ids so titles no longer wrap into a one-word column.
- T4 Windows hub clone uses `core.autocrlf=false` / `core.eol=lf` (same as `gitio.clone`), so the legacy-KB publish mirror check is not poisoned by Git for Windows CRLF rewriting.
- Golden corpus is a synthetic handbook; copyrighted ARINC/ICAO extracts are gone.

### BA repos — the SA grounding layer

- **`/sa-ticket-ground`** (new skill on `ba` repos; Claude Code, Copilot and
  Cursor wrappers) fills the SA-owned `## Technical grounding` section of a
  ticket — or, with `--mission`, `## Services & order` of a mission plan — from
  the hub's `<repo>-code` document. Ids only: every line names a section id
  that exists in the document, or carries `[NEW: <reason>]`, or is parked
  under `Open decisions`. It has no repository access and never infers.
- `docs/tickets/TEMPLATE.md` gains `## Technical grounding` (a recommended
  section — `kb ticket lint` warns when it is missing; legacy tickets keep
  passing); `docs/missions/TEMPLATE.md` gains `## Services & order`. Neither
  has a `Flow` or `Failure modes` field: the code document cannot prove them.
- `ba-ticket-author` and `ba-mission-plan` no longer read `<repo>-code` /
  `<repo>-svc`; they write `%%TODO: verify against codebase%%` and hand off to
  the SA skill.
- **`kb ticket check <file>`** — the machine gate for `## Technical grounding`:
  every `svc.* / db.* / api.* / int.* / cmd.*` id must exist in the
  `<repo>-code` document (read from `--kb-dir` when present, otherwise from
  the hub federation), `Grounded on: <repo-id>:<doc-id> @ <revision>` must
  match the document's manifest revision, columns / routes / commands must
  match its own tables, `Files:` must appear in `struct.tree` (paths beyond
  the depth or line cap degrade to a warning), and `Open decisions` must be
  empty. Exit `0` PASS, `1` FAIL; `--json` for CI. Every error that points at
  a ticket line names it. No MCP tool yet.

Re-run `kb init --kind ba` to pick up the new templates and wrappers.

## 1.0.1 — 2026-09-19

First release of **Strata** (`strata-kb`) — Knowledge Base as Code for large
reference documents, in any domain.

### The model

- **Four layers per store.** L0 `index.yaml` (master catalogue) → L1
  `_manifest.yaml` (per-document contents with ≤ 25-word section summaries) →
  L2 `.md` (condensed prose, tables verbatim, in the source's own language) →
  L3 `.raw.md` (full extracted original). A lookup walks down only as far as it
  needs to, which is where the token saving comes from.
- **Tables never pass through a model.** They are machine-extracted at both L2
  and L3, and `kb build` diffs every L2 table against its L3 original after
  normalising whitespace and alignment only. A table altered, dropped,
  duplicated, reordered or invented fails the build in either direction.
- **Everything is files in Git.** No database, no runtime state. The review
  surface is an ordinary pull request.

### Repo kinds

`kb init --kind hub|child|ba|dev` scaffolds a repo and records the choice in
`.kb/config.yaml`. A `hub` hosts `federation/` and the shared service; a `child`
authors documents and publishes them; a `ba` drafts tickets and mission plans
grounded in the KB; a `dev` implements those tickets and publishes knowledge
about its own source code. Re-running `kb init` refreshes scaffolding and
preserves data unless `--force`.

Slash commands are scaffolded for Claude Code, GitHub Copilot and Cursor, and
MCP client wiring ships as `.mcp.json` and `.cursor/mcp.json` on every kind —
but with `${STRATA_KB_HUB_URL}` and `${STRATA_KB_HTTP_TOKEN}` placeholders
that nothing sets on their own. **`kb mcp-setup`** connects a `child`, `ba` or
`dev` repo to the hub's HTTP MCP service: it writes both values into `.env`,
makes sure git ignores it, and verifies them against `GET /api/health` (no
token) and `GET /api/docs` (token), so a wrong URL and a rejected token give
different errors. Values resolve flag → environment → the value already in
`.env` → hidden prompt, so a bare re-run verifies again without retyping.
`/kb-mcp-setup` wrappers ship for Claude Code, Copilot and Cursor; they never
take the token in chat. `kb docker-setup` run against a `ba` or `dev` repo
names the actual kind and points at `kb mcp-setup` instead.

### Authoring

- `kb ingest` splits a PDF by its own outline (or by heading pattern with
  `--no-bookmarks`), writes L3, scaffolds L1/L2, and extracts every embedded
  image once as a content-addressed asset. Descriptions come from the source —
  the image's own caption, falling back to OCR — never generated. Re-ingest is a
  full replace by default and a surgical per-chapter rewrite with `--sections`.
  The report names every sectioning decision, so nothing is silent.
- `kb summarize` fills L1/L2 blanks through a headless LLM CLI (`claude` →
  `copilot`, auto-detected), and runs automatically inside `kb ingest`.
  `/kb-summarize` is the manual fallback when no CLI is installed. Supports
  `--redo`, `--print-prompt`, and verbatim copy for sections under 200
  characters.
- `kb build` gates the store: no leftover blanks, full table integrity, and
  quality rules (`--strict` turns warnings into errors). It also fails when L3
  changed after summarization or L2 changed after approval, and never writes a
  manifest while reporting an error. `--allow-pending` validates work in
  progress.
- `kb approve` records `reviewed: {by, at, l2_sha256}` per section behind a
  clean tree and a passing strict build.
- `kb status`, `kb stats`, `kb doctor` report what is left, what it costs, and
  what is broken.

### Search

- `kb query` runs hybrid search — SQLite FTS5 keyword plus optional semantic
  KNN, fused with RRF — over the hub's `federation/`, returning L2 sections
  within a token budget with `<repo-id>:<doc-id> §<section> (<revision>)`
  citations. No model call happens during a lookup.
- `kb get` fetches one section at a chosen level; `kb tags` lists the published
  tag vocabulary.
- Sections are never cut mid-way, which is what keeps returned tables verbatim;
  `--budget` is therefore advisory and the first result always comes back whole.

### Hub and federation

- `kb publish` mirrors a store's full `.kb/` (L0→L3) into
  `federation/<repo-id>/` on the hub and rebuilds the aggregate index. It copies
  `.kb/` **artefacts only** and names anything withheld — config files and
  dotfiles never reach the hub.
- `kb ci-publish` publishes from a child's own GitHub Actions job using OIDC, no
  secrets. Uploaded paths are capped at 110 UTF-16 code units so
  `federation/<repo-id>/<path>` stays inside a Windows client's `MAX_PATH`. Its
  urllib wrapper lives in `strata_kb.httpio` with a `timeout` parameter, so the
  `file://` scheme guard is shared across its callers rather than duplicated
  per caller (the dev-machine intake flow in `publish.py` keeps its own copy
  by design).
- **Multi-tier federation:** a hub may publish its own `federation/` upward into
  another hub, unbounded in depth, with cycle detection. Scope a search by
  choosing which hub you query.
- **Optional S3 asset offloading** (`asset_store: {mode: s3, bucket: …}`) keeps
  large images out of git and serves them from the bucket with a local cache.
- `kb reindex` repairs a drifted `federation/index.yaml`;
  `federation/index.yaml` records `content_sha256` per snapshot so `kb doctor`
  detects content modified in place on the hub.
- All git operations (clone, fetch, pull, push) pass credentials through the
  credential helper — tokens never appear in `remote.origin.url` or in any log
  line. This is what sets the git ≥ 2.31 floor for a credentialed `hub:` URL.

### MCP server and Web UI

- One process serves both: stdio for a local agent, or HTTP with a bearer token
  for a shared deployment — `/mcp` for agents, `/api/…` for REST, `/ui` for
  people.
- Five MCP tools: `kb_search`, `kb_get_section`, `kb_context_new`, `kb_resolve`,
  `kb_ticket_lint`. `kb_search` caps each ranking leg at 50 results before
  fusion and says so when matches were dropped; it flags cross-repo duplicates,
  exact score ties, and hybrid-confirmed near-ties.
- A hub is mandatory — the server refuses to start without one, and never
  queries its own working `.kb/`.
- Security headers on every response (CSP `script-src 'self'`,
  `X-Frame-Options: DENY`, nosniff, `Referrer-Policy`, `Permissions-Policy`;
  HSTS on https). The `/ui` session cookie is a signed, expiring value derived
  from the token, never the token itself; `POST /ui/logout` ends a session.
  Failed `Authorization` attempts share the login form's rate-limit bucket, so
  the lockout cannot be side-stepped through the header. A corrupt published
  snapshot renders a 503 error page, not a bare 500.

### Citations that pin a version

`kb context new` writes a `kb-context` block pinned at the hub's current commit;
`kb resolve` answers `ok`/`stale`/`broken` by walking the hub's history at that
commit; `kb diff` reports what an amendment changed between two revisions —
titles, L1 summaries, the L2 slice, the L3 original, added and removed sections,
and manifest reorders. `kb doctor --context` runs the same check in CI.

### BA repos

`ba-ticket-author` and `ba-mission-plan` run grounded, human-gated pipelines that
produce Markdown only — the agent never pushes to a tracker. Two
Definition-of-Ready gates, `kb ticket lint` and `kb mission lint`, check required
structure, diagrams, backlog well-formedness, and that every citation resolves at
its pinned commit. Mission lint is CLI-only by design: its checks need
filesystem access to the sibling `tickets/` directory that a shared MCP server
does not have.

### Dev repos

- A five-command agent workflow (`/dev-implement-ticket` plus design, plan,
  execute, handover) with four human gates, resumable across sessions from
  artifacts alone — no sidecar state file. No production code without a failing
  test observed first; no completion claim without shown verification output.
- Five independent review subagents in front of those gates — A1 (design), A2
  (plan), A3 (per task), A4 (branch), A5 (merge-risk) — so the agent that
  writes an artifact never judges it. A shared `## Review dispatch contract`
  in every phase wrapper keeps author and reviewer in separate contexts; only
  A5 is machine-checked.
- `docs/pr-review-rubric.md` and its create-once
  `docs/pr-review-rubric.local.md` override, scaffolded by `kb init --kind
  dev`, hold the pre-code and merge-risk axes and the BLOCKER/SUGGESTED/
  NOTE/NITS severity ladder every review uses.
- `kb code-ingest` extracts a codebase's structure into `.kb/<repo_id>-code/`,
  deterministically and with no LLM, through seven extractors organised by
  artifact kind rather than language: services, deps, commands, tree, schema,
  integrations, api. Dependency detection covers Python, JavaScript, Java,
  .NET, Go, PHP, Rust, Swift and Dart ecosystems, and framework detection
  includes Playwright e2e suites. It refuses a destination it did not write, and
  exits 1 when no extractor other than `tree` found anything.
- **Two security properties, not conveniences:** the `integrations` extractor
  emits keys and never values (the only env file it opens is
  `.env.example`/`.sample`/`.template`, and its regex has no capture group
  around the value at all), and SQLite schema input is `--db`-only and never
  inferred, so a stray scratch database cannot become published company
  knowledge.
- `kb svc note` appends an idempotent row to `<repo_id>-svc §hist.<service>`;
  `/dev-code-seed` bootstraps the curated `-svc` document once per repo.
  `-code` and `-svc` are deliberately separate documents — overwrite versus
  accumulate, `pending` versus clean build, auto-merge versus review — joined by
  the `svc.<name>` section id so a C4 `Container(...)` can be filled from both.

### Measurement, linting, and operations

- `kb usage` ingests agent transcripts, records rows and renders a token/cost
  report.
- `kb pr lint` checks that a pull-request description carries its evidence,
  across nine required sections including `## Review`, which fails the PR on
  a missing verdict line or on `Blocking: Yes`.
- `kb assets migrate` / `verify` operate a hub's asset store.
- `kb docker-setup` prepares a hub (`.env`, token, `docker compose up -d`) or a
  child (pull the ingest image). Release tags publish to PyPI and push
  `ghcr.io/vuonglq01685/strata-kb`.

### Platform support

Python 3.11, 3.12 and 3.13 on Linux and Windows, gated on every release. `kb`
forces UTF-8 on stdin/stdout/stderr at startup on every OS. Git ≥ 2.31 is
required on any machine whose `hub:` URL carries a credential.

### Known limitations

- **HTTP authentication stops at a bearer token** — one fixed secret, no OAuth
  or SSO. Adequate for an internal network; not ready for the public internet.
- **A governed hub that `gh` cannot open a pull request on has no publish
  route.** Against a hub carrying a non-empty `federation/registry.yaml` whose
  remote `gh repo view` cannot answer for, `kb publish`, `--pr` and `--direct`
  all exit 1. `kb ci-publish` is not a fourth route: it runs only inside a
  child's own GitHub Actions job, the intake accepts only GitHub Actions OIDC
  tokens, and it lands content through `api.github.com` — GitHub at both ends.
  What is available, in order:
  - *Hub on GitHub or GitHub Enterprise, `gh` merely not set up here:* install
    and authenticate `gh` for that host (`GH_HOST=<host>` for Enterprise) until
    `gh repo view` succeeds inside the hub clone, then publish with `--pr`. This
    is the ordinary fix and the common case.
  - *Hub on github.com, publisher is a child repo's CI:* wire the child to the
    intake service and publish from its Actions job with `kb ci-publish`. This
    does not exist for an **intermediate hub** publishing upward — hub-to-hub
    publish gets the same refusals, and `kb ci-publish` tars `.kb/`, not
    `federation/`. For an intermediate hub the only route is `--pr` with a
    working `gh`, on any host.
  - *Hub not on GitHub at all (GitLab, Gitea, self-hosted):* no route in this
    release. The only lever is the hub owner removing
    `federation/registry.yaml`, which restores `--direct` for every publisher
    and gives up the governance the registry was added for.
- **The registry is a mistake guard, not a security boundary.** A child's remote
  URL is self-asserted, so the check cannot authenticate anyone, and the
  remote-less exemption is a convenience for a purely local hub. Branch
  protection on the hub, plus the OIDC intake, are the controls that actually
  hold.
- **Summarization is triggered, not scheduled.** It runs inside `kb ingest` or
  on demand; there is no unattended background pass.
- **`status: reviewed` is never set automatically.** `kb approve` is a
  deliberate human action. The operative gate is the pull request `kb publish`
  opens on the hub.
- **PDF extraction is not perfect.** A small share of sections in a complex
  document can come through malformed and need a human cross-check against the
  source.
