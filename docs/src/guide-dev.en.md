# 1. Who this guide is for

You write product code. Tickets reach you already grounded in the organisation's
knowledge base, with citations pinned to a specific version of a specific
document, and you implement them.

Strata does two things for you.

**It tells you what the source actually said.** Not "check the handbook": the
exact section, at the exact revision the analyst was reading, with a warning if
it has changed since.

**It publishes what your codebase is**, so analysts, other teams and future you
can search your services, dependencies, endpoints and schema without reading
your repository.

| A dev repo does | A dev repo does not |
|---|---|
| Read the hub's published knowledge, including the BA's published tickets | Ingest documents from outside the repo |
| Publish knowledge about **its own code** | Publish domain knowledge |
| Run an implementation workflow of slash commands | Merge or ship anything by itself (unless you turn on auto mode, section 4) |

It publishes two documents:

| Document | Origin | Needs review |
|---|---|---|
| `<repo_id>-code` | `kb code-ingest`, deterministic, no model. Regenerated on demand from the working tree, never committed | no |
| `<repo_id>-svc` | drafted by a model from that evidence, corrected by you | always |

`-code` is machine fact: services, technologies, dependencies, commands,
endpoints, schema, folders. `-svc` is human claim: what each service is
*responsible for*. They share section ids (`svc.<name>` exists in both), so an
analyst drawing a C4 container gets the alias, label and technology from `-code`
and the description from `-svc`.

**Slash commands.** Every slash command in this guide exists for Claude Code,
GitHub Copilot and Cursor, with these exceptions:

- `/kb-summarize` has no Copilot prompt. Copilot loads
  `.github/instructions/kb-summarize.instructions.md` while you work in `.kb/**`.
  Cursor also has a rule, `.cursor/rules/kb-summarize.mdc`.
- `/kb-publish` is a skill in Claude Code (`.claude/skills/kb-publish/`), not a
  file in `.claude/commands/`. You still type `/kb-publish`.
- A dev repo has no `/kb-ingest`, `/kb-init` or `/kb-l3-fix`: it never ingests
  outside documents.

---

# 2. First-time setup

## 2.1 Install and scaffold

```bash
pip install "strata-kb[code]"
kb init --kind dev
```

The `code` extra (`tree-sitter` plus `tree-sitter-language-pack`, about 184 MB) is
what lets `kb code-ingest` read routes, pages, jobs and symbols out of source
code. Without it those sections are reported as `not scanned`, jobs stay
`partial`, the SA has to ask you about them, and `kb doctor` warns. CI
(`kb-code.yml`) installs the extra for you.

`kb init --kind dev` writes the config, the MCP wiring, the slash commands and
skills for all three assistants, the CI workflows (`kb-pr-lint.yml`, `kb-code.yml`,
`kb-doctor.yml`), `docs/impl/`, the PR template and a conventions pack for each
detected language. Use `--lang <name>` (repeatable) for a language it cannot
detect from a manifest. Re-running `kb init` creates missing files and refreshes
scaffold files; `.kb/config.yaml`, `.kb/index.yaml` and `.claude/settings.json`
are protected (`--force` replaces them; `.claude/settings.json` is merged
otherwise), and your `*.local.md` files are never touched.

**One version for every repo.** Every repo runs the hub's strata-kb version.
Upgrade the hub first. Then run `kb doctor` in this repo: it installs the hub's
version, sets the `strata-kb==<hub version>` pins in `.github/workflows/`, and
refreshes the skills and commands. It does not do this in CI; there it reports a
mismatch as an error. The files under `.github/instructions/` and `.cursor/rules/`
(the Copilot and Cursor `kb-summarize` files and the per-language coding rules)
refresh only through `kb init`. An unpinned `pip install strata-kb` in a job that
holds `id-token: write` would let every run pick up whatever PyPI serves, in a
job able to write to the hub; that is why the workflows are pinned.

## 2.2 Point at the hub and register the repo

```yaml
# .kb/config.yaml
kind: dev
repo_id: payments
hub: https://github.com/acme/kb-hub.git
intake: https://kb-intake.acme.com
```

- **`hub`** is the read source for `kb query`, `kb get`, `kb resolve` and the PR
  and lint gates.
- **`intake`** is how CI publishes: `kb publish` pushes a `kb-publish/<ts>` tag
  and `kb-code.yml` runs `kb code-ingest`, `kb build`, `kb ci-publish`, which
  authenticates to the intake with GitHub Actions OIDC. No secret lives in this
  repo.
- **`repo_id`** must equal this repo's id in the hub's `federation/registry.yaml`.
  Ask the hub maintainer to add the repo under `repos:`; publishing is refused
  until they do. Branch protection on the hub plus the OIDC intake are the actual
  security boundary.

**Never put a token in `hub:` or `intake:`.** The file is committed, so the token
lands in history. `kb doctor` warns; rewrite the URL, pass the credentialed URL
in the `STRATA_KB_HUB` environment variable (it overrides the file), and rotate
the token. Any machine that uses a credentialed hub URL needs Git 2.31 or newer.

`hub:` and `STRATA_KB_HUB_URL` are different values: `hub:` is the git URL or
path of the hub repo; `STRATA_KB_HUB_URL` is the hub's HTTP base URL, used by
MCP, claims and the auto runner.

If the KB should carry a SQLite schema or extra index tags, say so here, not in
`kb-code.yml`, so every local refresh and CI run ingest the same way:

```yaml
code_ingest:
  db: [data/app.sqlite]   # explicit only
  tags: [payments]
```

## 2.3 Connect your assistant

`.mcp.json` (Claude Code) and `.cursor/mcp.json` (Cursor) point at the hub
through two placeholders, `${STRATA_KB_HUB_URL}` and `${STRATA_KB_HTTP_TOKEN}`.
Run `kb mcp-setup` (in your assistant: `/kb-mcp-setup`). It asks for the hub's
HTTP base URL and token, writes both into `.env`, makes sure git ignores that
file, and verifies them against the hub, so a wrong URL and a rejected token
come back as different errors. Get the token from the hub maintainer.

Prefer the hidden prompt or the `STRATA_KB_HTTP_TOKEN` variable over `--token`.
That flag leaves the token in your shell history and in the process listing that
other users on the machine can read. `kb mcp-setup` also warns when the URL is
plain `http://` to a non-loopback host, because the token then crosses the
network in clear.

The MCP config reads those variables from your environment, not from `.env`, at
the moment your assistant starts. Load the file (`set -a; source .env; set +a`,
or use direnv) and restart the assistant.

## 2.4 Turn on the PR gate and the daily sweep

`kb init` writes `.github/workflows/kb-pr-lint.yml` but cannot enable branch
protection. Add **`pr-lint` to the branch's required checks**. Lint running in CI
does not block a merge by itself; requiring the check does.

> Decide this knowingly. Unlike the BA repo's gate, this one never self-skips.
> Once required, it blocks **every** pull request lacking the required
> sections, including bot pull requests such as a dependency bump or a revert.

`kb-doctor.yml` sweeps your tickets' citations once a day and keeps one
`kb-stale-citations` issue. It needs the Actions **variable** `STRATA_KB_HUB` and,
for a private hub only, the Actions **secret** `KB_HUB_TOKEN` (a read token).

## 2.5 Ask whether the hub auto-merges your repo

Auto-merge is a per-repo switch on the hub's Registry page, turned on by a hub
admin. Ask your hub maintainer whether it is on, and know what it does:

> `kb ci-publish` opens **one** hub pull request per push, not one per document.
> The intake keys the publish branch by repository id and reuses it while a PR is
> pending, so a push carrying a regenerated `-code` alongside an already-merged
> `-svc` amend lands **both** in that PR.
>
> With the switch on, the hub merges the **whole** PR right after opening it,
> `-svc` content included. The `-svc` review therefore happens locally, in
> `/dev-code-seed` step 4, before the section reaches `reviewed`, never at the hub.

If the merge fails, the PR stays open for the hub maintainer and the publish still
counts as done. `kb publish` and `kb ci-publish` print "merged" when it merged.
With the switch off, every push adds to one pending hub PR that someone has to
merge, and `kb doctor` reports when the hub's `-code` lags.

## 2.6 Seed `-svc` for an existing project (once)

Your repository already has services doing real work. Do not document them from a
blank page: run the one-time seed.

```bash
/dev-code-seed
```

| # | Step | Who |
|---|---|---|
| 1 | **Preflight**: `hub:`, `repo_id:`, `intake:` set, repo registered on the hub, clean tree | agent |
| 2 | **Extract**: `kb code-ingest --scaffold-svc` regenerates `-code` and creates a `pending` `svc.<name>` per detected service | agent |
| 3 | **Draft**: `kb summarize <repo_id>-svc` writes a responsibility paragraph for each | agent |
| 4 | **Review**: walk every draft against its code evidence and correct it | **you** |
| 5 | **Approve**: `kb approve <repo_id>-svc` flips the corrected sections to `reviewed` | you |
| 6 | **Flows** (optional): add `flow.<name>` sections for business flows across services | you |
| 7 | **Validate and publish**: `kb build` without `--allow-pending`, then `kb publish --pr` | you |

> **The model's draft is a draft, not a fact.** It can name the wrong flow, miss
> a responsibility or over-claim one. Never approve a section you have not read
> and corrected: approving it unread defeats the gate. Where a responsibility
> touches a domain standard, cite `doc-id §section` from the hub instead of
> restating the rule.

Budget 10 to 15 minutes per service for step 4. It is a one-time cost; after the
seed, `-code` regenerates itself and `-svc` accrues a few lines per ticket. Skip
step 6 freely: a missing flow beats a guessed one. Use `kb publish --pr` for this
first publish: no merge has happened yet, so there is no tag for `kb-code.yml` to
react to, and plain `kb publish` would wait up to ten minutes for a CI run that
never starts. A hub analyst or architect reviews that PR like any other hub
content, unless the hub auto-merges your repo (section 2.5).

---

# 3. Daily work

## 3.1 Implement a ticket

All entry points are slash commands. Pick the one that matches where the work
stands; every phase resumes cold, because state lives in `docs/impl/<id>/`, the
branch and the PR, never in the conversation.

| Situation | Run | Result |
|---|---|---|
| New ticket, nothing started | `/dev-implement-ticket <ticket>` | claims the ticket, fetches it, checks it, then walks design, plan, execute, handover |
| Small ticket, obvious change | `/dev-implement-ticket <ticket>` | the flow collapses itself; a bounded design is still written |
| Design approved, no plan yet | `/dev-plan <id>` | `docs/impl/<id>/plan.md` |
| Plan approved, or execution in progress | `/dev-execute <id>` | code, task by task |
| Code written by hand, needs a PR write-up | `/dev-handover <id>` | the PR body, the `kb svc note` history rows |
| Lost track of where a ticket stands | `/dev-implement-ticket <id>` | detects how far it got and offers the next step |
| A technical question needing evidence | `/dev-sa <question>` | a decision with `path:line` / `doc §section` evidence |
| Just checking a citation | `kb resolve <file>` | `ok`, `stale` or `broken` per reference |

A ticket id is enough. Intake gets the ticket **from the hub**: the BA publishes
every ready ticket in a `<repo_id>-plan` document, so the hub is the source of
truth.

```bash
kb ticket fetch M-checkout-US3          # or <repo>:<id> if several repos publish it
kb claim take M-checkout-US3            # one Dev per ticket; exit 3 = taken
```

`kb ticket fetch` writes `docs/impl/<id>/ticket.md` (`--out` to change it) and
overwrites it on every fetch. The copy is derivable from the hub, so
`docs/impl/.gitignore` ignores it: never commit it and never edit it. If the
ticket is wrong, the BA amends it in the BA repo. It exits `1` when no published
plan has the id (ask the BA to publish) or when several do (qualify it as
`<repo>:<id>`). The hub copy has no `## Definition of Ready`: being on the hub
means the BA ticked every box.

Right after Intake the flow runs `kb ticket check docs/impl/<id>/ticket.md` (skipped
when the ticket has no `## Technical grounding`):

| Output | Meaning | What to do |
|---|---|---|
| PASS, `[note] ... still valid` | Nothing the ticket cites changed | Carry on |
| PASS, `[warn] ... review the diff` | A cited section changed, every cited name still holds | Read the diff; carry on unless it changes the ticket's meaning |
| FAIL, `re-run /sa-ticket-ground` | A cited id, column, route, command or file is gone | Stop. It is a blocker for the BA, whose SA re-grounds the ticket |
| FAIL, `checked against the local -code` | The hub was unreachable or lacks `-code`; your branch may be the cause | Re-run when the hub is reachable |
| FAIL, no re-ground line | An open decision or an undecided `[NEW: D<k>]` | Report it to the BA and stop |

The hub's Ticket menu (`/ui/tickets`) and `kb mission next --from-hub [--repo <ba-repo>]`
show each story as **done**, **ready**, **not ready** or **blocked**. Pick a
**ready** one. A `draft` ticket whose reason says the parent mission was amended is
not published: wait for the BA, and do not implement from an older copy.

## 3.2 Four human gates, five agent reviews

```
/dev-implement-ticket <ticket>     intake, questions, check, resolve, ground
        |
        +-> dev-design    -- A1 review -- GATE 1: you approve the design
        +-> dev-plan      -- A2 review -- GATE 2: you approve the plan
        +-> dev-execute      A3 per task, A4 at the end (repeatable, resumable)
        +-> dev-handover  -- A5 merge-risk review -- GATE 3: you open the PR
                                                    GATE 4: you merge it
```

Nothing merges or ships without a human. The agent never opens the PR or merges.
Before each of the first three gates a different agent has read the work back in
a context of its own, never the agent that produced it:

| | Where | What it looks at |
|---|---|---|
| A1 | `dev-design`, before GATE 1 | does the design match the ticket |
| A2 | `dev-plan`, before GATE 2 | is the plan test-first and runnable |
| A3 | `dev-execute`, per task | does the diff meet its spec, and is the code good |
| A4 | `dev-execute`, after the last task | does the finished branch round out the ticket |
| A5 | `dev-handover`, before GATE 3 | is merging into the default branch safe |

Criteria live in `docs/pr-review-rubric.md`, overridden by
`docs/pr-review-rubric.local.md`. A3, A4 and A5 allow at most three fix passes;
a BLOCKER or SUGGESTED finding still standing after round 3 stops the flow and
hands it to you. A1 and A2 stop after one review plus one verification round.
Where your assistant cannot dispatch subagents (the default for the Copilot and
Cursor wrappers) the review runs as a single pass and is a **report, not a gate**:
the phase stops and hands you the result.

The `plan.md` tasks carry `Depends on:` lines; `kb plan waves docs/impl/<id>/plan.md`
turns them into waves and fails on a shared file without a dependency, a cycle, an
unknown task, a missing `Depends on:` line or an empty `Serial resource:`.
`dev-execute` runs it for you and runs a multi-task wave in parallel git worktree
lanes, at most three at a time.

## 3.3 Questions for the BA

`dev-design` and `dev-plan` never settle a doubt by guessing. Each doubt is tagged
`business` or `technical`:

- **Technical** (how to build it, where it goes) goes to `dev-sa`, the solution
  architect of this repo. It reads the source and the hub's `-code`, `-svc` and
  domain documents, and the decision lands in the draft as
  `- SA-<n>: <decision> — why — evidence`. You can call it yourself:
  `/dev-sa <question>`.
- **Business** goes to the BA through hub Q&A (MCP `kb_question_ask`) and appears as
  `- Q<id> — <question> — blocks: <AC ids|none>`. The BA answers with
  `/ba-answer-questions`.

A question that blocks an acceptance criterion stops the gate: the skill gives you
the hub's Q&A link to paste in chat. A question that blocks nothing does not.
On every entry `/dev-implement-ticket` reads the ticket's questions
(`kb_question_list`) and shows the state in the Next-step block as
`BA-Q: none | open Q<ids> | waiting Q<ids>`. An *answered* question is applied to the
draft (re-fetch the ticket, mark the line `answered rev N`, redraft); a *waiting* one
(answered, but the BA's new ticket revision is not on the hub yet) is information
only; an *open* blocking one stops the flow.

Q&A works only when MCP points at the hub's HTTP server (`kb mcp-setup`).

## 3.4 Fix a bug

A bug the BA published is `BUG-<n>`. It has no story and no acceptance criteria:
it is done when its steps no longer reproduce the wrong result.
`/dev-fix-bug BUG-<n>` runs it in the style of systematic debugging:

1. **Intake**: `kb ticket fetch BUG-<n>` writes `docs/impl/<id>/ticket.md` and
   copies the bug's screenshots to `docs/impl/<id>/assets/`. Branch `fix/<BUG-id>`,
   or `hotfix/<BUG-id>` from the production line you name.
2. **Reproduce**: a failing test that shows the Actual result. No fix without it.
3. **Root cause**: written hypotheses in `docs/impl/<id>/rootcause.md`. Three failed
   hypotheses stop the flow for an architecture talk with you.
4. **Fix**: one change at the root cause, full suite green.
5. **Handover**: `/dev-handover` with bug rules; the reproduction test and the root
   cause replace the design and plan.

## 3.5 Several Devs on one repo: claims

A **ticket claim** on the hub keeps two Devs off the same ticket.
`/dev-implement-ticket` and `/dev-fix-bug` run `kb claim take <id>`, and every later
phase refreshes it.

- The claim names its holder (`<git user.name>@<hostname>`, or `STRATA_KB_CLAIM_AS`
  or `--as`) and a phase: `claimed`, `design`, `plan`, `execute`, `handover`,
  `waiting-qa`, `review`, `publishing`. A second Dev gets
  `taken by <holder> (<phase>, updated <x> ago)` and exit `3`: pick another ticket or
  ask a hub admin to release it.
- It expires after 4 hours without an update. Once you have opened the PR, run
  `/dev-handover <id>` again: it finds the PR and sets `review` with its URL. A claim
  in `review` or `publishing` with a PR, or one the auto runner marked `stopped`,
  never expires.
- After an expiry or release, the next Dev who claims the ticket and finds its branch
  on `origin` continues on it. If your own claim is released while you work, the next
  update exits `3` (`lost: <reason> by <who>`) and the skill stops without pushing.
- `kb claim list [--json]` shows what is held; `kb claim release <ticket> [--reason TEXT]`
  gives yours back; `kb claim update <ticket> --phase <p>` sets the phase by hand.
  A hub admin can release anyone's claim from the ticket page.
- The commands need `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN`.

## 3.6 Publish after the merge

A push to the default branch publishes nothing; the intake accepts a publish only
from a `kb-publish/*` tag. After your PR merges, publish from the default branch:

```bash
git fetch origin && git switch main && git pull --ff-only origin main
kb publish
```

In a dev repo `kb publish` refuses to run from a checkout that is behind
`origin/<default>`, because the snapshot would drop another machine's newer `hist`
row. The messages are `behind origin/<default> — pull, then kb publish`,
`no origin remote — ...` and `could not fetch origin/<default>: ...`. A squash merge leaves
the ticket branch behind, which is why you switch first. The hub reflects the commit
once its PR merges. `kb publish` and `kb ci-publish` warn how many sections ship
unreviewed (`--require-reviewed` makes that fatal).

## 3.7 Work with citations

```bash
kb resolve tickets/ABC-123.md    # ok | stale | broken, per ref
kb diff hr-handbook --against <rev>
kb get hr-handbook 4.12 --level l3
```

| Status | Meaning | What to do |
|---|---|---|
| `ok` | The pinned content still matches what is published | Implement against it |
| `stale` | The source was amended after the ticket was written | Run `kb diff`, then ask the analyst whether the acceptance criteria still hold. **Do not silently implement the new version.** |
| `broken` | The reference no longer resolves | Escalate. The ticket is not implementable as written |

Every entry point re-checks freshness first, because the hub may have published
since your last session. When a value in your code comes from a standard (a format,
an enum, a threshold, a length), take it from the resolved section at the pinned
version and leave a citation comment next to it.

## 3.8 Keep knowledge current

Neither document needs new per-ticket discipline from you.

- **`-code` needs nothing.** It is never committed (`.gitignore` carries
  `.kb/*-code/`). `kb svc note`, `kb build`, `kb doctor` and `kb publish` regenerate
  it first when it is missing, older than `HEAD`, or your tracked files changed (a new
  file counts once it is tracked with `git add`). `--no-refresh` skips that. Its only
  producer is `kb code-ingest`; `kb summarize` refuses it. `--scaffold-svc` is
  deliberately never passed in CI, because CI must never create `pending` content that
  would fail its own build.
- **`-svc` accrues at handover.** `dev-handover` runs, for every service a ticket touched,
  `kb svc note payments-api --ticket ABC-123 --title "Add refund endpoint" --refs "payments-spec §4.2"`.
  It appends one row to `hist.<service>`, idempotently per ticket. Never edit `hist.*`
  by hand; those rows are facts and need no review. It exits `1` on an unknown service
  (a typo must not invent one), a missing `-svc` or `-code`, or an unreadable manifest.
- **Responsibility text can drift, and the system reports rather than repairs.** When
  `kb code-ingest --scaffold-svc` refreshes the evidence of a `reviewed` service and
  anything beyond whitespace changed, it prints `stale-risk: svc.<name>`. It never
  touches the summary; it flags that a human should look.

---

# 4. Automation modes

**Full-auto mode (optional).** A switch per `ba` and `dev` repo that lets the two repos
run on their own, on your machine, until every ticket on the hub is done. No step waits
for a person: the agent reviews its own work, approves GATE 1 and GATE 2, picks the best
option, writes down why in `docs/impl/<id>/auto-decisions.md` (copied into the PR's
`## Notes`), opens the PR, fixes CI until it is green, merges and runs `kb publish`.
It is built for **one BA repo and one Dev repo per hub**. Nothing changes while the
switch is off.

## 4.1 Security: read this first

The permission deny list that `kb init` writes (appendix) is defence in depth, not a
boundary. An unattended run merges its own pull requests and publishes to the hub with no
human review. A ticket the agent misreads goes straight to `main` and to the hub.
`kb auto on` prints this itself: "Auto mode merges pull requests as admin, with no
review. Turn it on only for a repo where that is acceptable."

It merges with `kb pr merge` (GitHub REST), using the rights of your `gh` login;
`--admin` is accepted for `gh` compatibility and changes nothing. If that login is a
repo admin and branch protection does not include administrators, those merges bypass
the protection. So, before you run it, the repo owner **must** enable GitHub branch
protection on `main`:

- block force pushes and deletions;
- **include administrators**;
- keep the CI check as a **required status check**: the `test-<lang>` job(s) of
  `kb-test.yml` (or of the workflow carrying the `kb-test` marker). Branch protection
  picks checks by job name. Without a required check, "green CI" is only a convention
  the agent follows;
- do **not** require approving reviews: the agent cannot approve its own PR, and the
  merge is then refused. If you require reviews anyway, exclude administrators from that
  rule and accept that the agent bypasses it on `main`.

The deny list also cannot see the current branch: the agent's working tree must never
sit on `main` with commits on it. The skills branch first; the runner does not guard it.
The runner never uses `--dangerously-skip-permissions` or `bypassPermissions`.

## 4.2 Set up once

1. A mission and its tickets are on the hub (the BA side, by hand or in auto mode).
2. `intake:` is set in `.kb/config.yaml`, and the hub's Registry page has **auto-merge on**
   for this repo, so the `hist` row lands and stories reach `done`. This applies to the
   BA repo too.
3. Re-run `kb init --kind dev`. It merges the permission allowlist, including the test,
   install, lint and build commands for the `langs:` recorded in `.kb/config.yaml`, into
   `.claude/settings.json`, and refreshes the skills and `/dev-test-workflow`.
4. Export `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN`, and have the `claude` CLI on
   the `PATH`, **logged in with a Claude subscription**. The runner never uses an API key.
5. Keep `main` as the default branch; the skills run `git fetch origin main`.

## 4.3 Run and stop

| Task | Command | Result |
|---|---|---|
| Turn the switch on | `kb auto on` | prints the warnings, flips `auto.enabled` |
| Commit it | commit and push `.kb/config.yaml` and `.claude/settings.json` to the default branch | `kb auto run` refuses until you do |
| Start the loop | `kb auto run` (`--once`, `--model`, `--effort`), or `/kb-auto run` | `/kb-auto run` does all three steps and starts the loop detached; log in `.kb/auto/run.log` |
| See where it is | `kb auto status [--json]`, `/kb-auto status` | switch, task, attempts, questions waited on, stop reason |
| Stop it | `kb auto off`, `/kb-auto off` | stops after the current task |
| Wait for a result | `kb auto wait [--max 6600] [--interval 30]` | one line, used by the cloud watcher |

`kb auto run` refuses, and prints every reason, when the switch is off, `.kb/config.yaml`
or `.claude/settings.json` is untracked or dirty, `auto.enabled: true` is missing from the
default branch's copy of the config, `intake:` is empty, or the hub registry cannot be
read, does not list this repo, or lacks `auto_merge: true` for it. Exit codes: `0` done,
`2` stopped, `1` refused or error, `130` interrupted.

## 4.4 What it does and when it stops

One fresh `claude -p` process per task. In order:

1. If no workflow runs the repo's tests, `/dev-test-workflow` writes and merges
   `kb-test.yml`, so "green CI" means tests ran.
2. Bugs first (`/dev-fix-bug`).
3. The first `ready` ticket that has no mission and is not a bug (`/dev-implement-ticket`).
4. The first `ready` story in mission order whose dependencies are `done`.

When a business question blocks a ticket, the Dev asks the BA through hub Q&A and
waits; once every question is answered, the same ticket resumes in a fresh process.
The loop holds the claim and refreshes it every `auto.claim_heartbeat` seconds.

It stops after two failed attempts at one ticket (a red CI after two fix rounds stops it
at once); fix the cause and run `kb auto run` again. A command outside the allowlist ends
the task `failed command-denied <command>`: add it to `permissions.allow` in
`.claude/settings.json` by hand. A usage-limit wait (15, 30, 60 minutes) is not a failure.
It finishes, exit `0`, when every story, unparented ticket and bug is `done`.

A task process carries `STRATA_KB_AUTO_TASK=1`, under which `kb auto on`, `off` and `run`
refuse (`status` still works), so a task can neither flip the switch nor start a second
loop.

## 4.5 Claude Code cloud

`/kb-auto run` also works in a Claude Code cloud session (detected from
`CLAUDE_CODE_REMOTE`; `STRATA_KB_CLOUD=1|0` forces it). Set `STRATA_KB_HUB_URL` and
`STRATA_KB_HTTP_TOKEN` in the cloud environment. The hub is read live through its API and
nothing is cloned; other hub-reading `kb` commands refuse and point at the `strata-kb`
MCP tools. `kb pr` talks to the GitHub REST API instead of `gh pr`, because GraphQL is
blocked there. Because nobody can click "trust this folder", `kb auto run` there marks
the repo root trusted in `~/.claude.json`.

The session branch cannot push to the default branch. When the default branch's switch is
off, `/kb-auto run` opens an `auto/switch` PR that flips only `auto.enabled`, waits for green
checks, and then **merges that PR itself, telling you first**, with
`kb pr merge auto/switch --squash --admin --delete-branch`. The same branch-protection
advice as in 4.1 applies: that merge has no review either. **The session must stay open**
for the whole run. Not yet verified on real cloud: a session lasting over three hours,
pushing `auto/*` branches, and a merge past a required review.

---

# 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `kb code-ingest` exits 1: nothing detected | Only `tree` and the source readers found anything | Check that compose files, manifests or CI workflows are where the extractors look; name a `--db` if schema is the point |
| `kb code-ingest` exits 1: destination refused | A hand-curated document sits at that doc id | Move it, or use `--doc-id` |
| `kb doctor`: "strata-kb[code] is not installed" | The `code` extra is missing | `pip install "strata-kb[code]"` |
| `kb doctor` warns a tracked `.kb/config.yaml` carries a credential in `hub:` or `intake:` | A token was committed | Rewrite the URL without it, pass it in `STRATA_KB_HUB`, rotate the token (it is in git history) |
| `kb doctor`: "every repo on a hub uses the hub's version" | The installed strata-kb, or a CI pin, differs from the hub's | Upgrade the hub, then run `kb doctor` locally. In CI it only reports |
| `kb doctor`: "hub `<repo>`-code lags origin/main" | The last `-code` publish has not merged on the hub, or the last `kb-code.yml` run failed | Open the hub PR named in the job summary and merge it, or fix the run; `kb publish` re-publishes |
| `kb doctor`: "kb-code.yml passes --db" | Ingest configuration lives in the workflow | Move the paths to `code_ingest.db` in `.kb/config.yaml`, then `kb init --kind dev` |
| `kb doctor`: "`.kb/<repo>-code` is tracked by git" | `-code` was committed | `git rm -r --cached .kb/<repo>-code` and commit |
| `kb doctor`: "hub lag not judged — ..." naming `origin/HEAD` | `origin/HEAD` was never set | `git remote set-head origin --auto` |
| `kb build` fails in CI on a `-svc` section | A `pending` section was committed | Finish the seed: summarize, review, `kb approve` |
| `kb svc note`: "unknown service" | A typo, or the new service's files are not tracked yet | Copy the id from `services.md`; `git add` the new files and retry |
| `kb publish` hangs, then fails citing the Actions run | Plain `kb publish` on a repo whose CI has no tag trigger (the seed) | Use `kb publish --pr` |
| `kb publish`: "behind origin/..." | The checkout is behind the default branch | Pull the default branch, then `kb publish` |
| `kb ci-publish` refused, or HTTP 403 | The repo is not in the hub's `federation/registry.yaml`, `repo_id` differs from the registered id, or the run was not on a `kb-publish/*` tag | Ask the hub maintainer to register it; fix `repo_id`; publish with `kb publish` (the intake accepts only `refs/tags/kb-publish/*`) |
| `dirty_tree` warning | Uncommitted changes while the manifest revision comes from HEAD | Harmless locally; CI always runs clean |
| `pr-lint` fails on a Dependabot PR | The gate never self-skips once required | Expected. Decide whether to keep it required for bot PRs |
| `pr-lint` fails: `no-review-verdict` | The `## Testing` section has no `Blocking:` line | Run A5 (`dev-handover`'s merge-risk review) and record its verdict, even `Blocking: No` |
| `pr-lint` fails: `review-blocking` | The `## Testing` section says `Blocking: Yes` | Fix the BLOCKER findings and re-review |
| `kb ticket fetch`: "is not on the hub" | The BA has not published it, or left it out of the plan | Ask the BA to `kb publish`; or pass the ticket file or paste the body |
| `kb ticket fetch`: "published by several repos" | Two BA repos publish the same id | `kb ticket fetch <repo>:<id>` |
| `kb ticket fetch` cannot reach the hub | `hub:` unset or unreachable | Fix `hub:` in `.kb/config.yaml` (or `STRATA_KB_HUB`) |
| `kb ticket check` fails with `re-run /sa-ticket-ground` | A fact the ticket cites is gone from `-code` | Stop; the BA's SA re-grounds it |
| A citation resolves `stale` mid-implementation | The hub published after the ticket was written | `kb diff`, then ask the analyst. Do not reinterpret the AC |
| `kb claim` exits 3: `taken by ...` | Another Dev holds the ticket | Pick another ticket or ask a hub admin to release it |
| `kb claim`: "hub server has no /api/claims" | The hub is older than this CLI | Upgrade the hub, then run `kb doctor` here |
| `Q&A needs the shared hub server — point MCP at it (kb mcp-setup)` | MCP points at a local cache clone, a stdio server or any target other than the hub's HTTP server | Run `kb mcp-setup` and restart the assistant |
| MCP server unreachable | `STRATA_KB_HUB_URL` or `STRATA_KB_HTTP_TOKEN` unset or wrong | Re-run `kb mcp-setup` (`/kb-mcp-setup`); it says which one. A bare re-run re-verifies without retyping |
| `kb mcp-setup`: "token was rejected" after you got a fresh token | A bare re-run reads the *old* token from `.env` | `STRATA_KB_HTTP_TOKEN=<new-token> kb mcp-setup`, or delete that line from `.env` and re-run |
| `kb auto run` refuses | See the reasons it printed (4.3) | Fix each; commit and push `.kb/config.yaml` and `.claude/settings.json` |
| Auto task ends `failed command-denied <command>` | The command is not in `permissions.allow` | Add it to `.claude/settings.json` by hand |
| `/kb-summarize` does nothing in Copilot | Copilot has instructions, not a prompt | Work inside `.kb/**` so the instructions apply |

The hub-lag check runs a full `code-ingest` in a temporary worktree on every
`kb doctor`; expect it to take real time. On Windows a glob-casing difference can make
an unchanged repo compare as `lags`; a verdict that disappears on Linux (CI) is that,
not drift.

---

# 6. Appendix

## 6.1 Config keys and environment variables

| Key or variable | Meaning |
|---|---|
| `kind`, `hub`, `repo_id`, `intake` | see 2.2. Never put a token in `hub:` or `intake:` |
| `langs` | languages for the conventions pack and the auto-mode allowlist; set by `--lang` or detection |
| `code_ingest.db`, `code_ingest.tags` | SQLite files (explicit only) and extra index tags for every `-code` refresh |
| `auto.enabled`, `auto.qa_interval`, `auto.idle_interval`, `auto.hotfix_base`, `auto.claim_heartbeat` | auto mode; `claim_heartbeat` is seconds between claim refreshes, default `900` |
| `.kb/index.yaml` `llm:` | `runner` (`auto`, `claude`, `copilot`, `none`), `model`, `effort`, `max_workers`, `timeout`, used by `kb summarize <repo_id>-svc` |
| `STRATA_KB_HUB` | overrides `hub:`; carries a credentialed URL in CI (an Actions variable) |
| `STRATA_KB_HUB_URL`, `STRATA_KB_HTTP_TOKEN` | the hub's HTTP base URL and bearer token: MCP, claims, the auto runner |
| `KB_HUB_TOKEN` | Actions secret, a read token, private hub only (`kb-doctor.yml`) |
| `STRATA_KB_CLAIM_AS` | claim holder name |
| `STRATA_KB_AUTO_TASK` | set by the runner on task processes; `kb auto on/off/run` refuse under it |
| `STRATA_KB_CLOUD`, `CLAUDE_CODE_REMOTE` | Claude Code cloud detection |

Exit codes: `0` ok, `1` error, `2` stale citation (or a usage error), `3` claim taken or
lost, `8` `kb pr checks` still pending. `kb auto run`: `0` done, `2` stopped, `1` refused,
`130` interrupted.

## 6.2 Work folders and what is git-ignored

| Path | Holds | Committed |
|---|---|---|
| `docs/impl/<id>/design.md`, `plan.md` | the design and the plan, each with a `## Review record` table | yes |
| `docs/impl/<id>/ticket.md` | the ticket fetched from the hub | no, never edit |
| `docs/impl/<id>/context.md` | resolved-context cache | no |
| `docs/impl/<id>/review/` | review rounds, per-task diffs, the merge-risk report | no |
| `docs/impl/<id>/assets/` | bug screenshots (may show personal data) | no |
| `.kb/*-code/`, `.kb/auto/` | derived `-code` and the auto runner's state | no |
| `.env` | `STRATA_KB_HUB_URL`, `STRATA_KB_HTTP_TOKEN` | no |

`kb init` and `kb impl tidy` move an old flat layout (`docs/impl/<id>-plan.md`, ...) into
`docs/impl/<id>/` without overwriting; commit the renames. Never commit `.kb-qa/`: it
is the hub's Q&A store, and it is git-ignored on the hub.

## 6.3 What `kb code-ingest` extracts

```bash
kb code-ingest                          # defaults are usually right
kb code-ingest --db data/app.sqlite     # name a database explicitly
kb code-ingest --json                   # machine-readable report
```

Eleven extractors, organised by artefact kind rather than language. The first seven read
build, deploy and contract files; the last four read source with tree-sitter.

| Extractor | Section prefix | Reads |
|---|---|---|
| `services` | `svc.<name>` | compose files, Dockerfiles, k8s manifests, solution and workspace files |
| `deps` | `dep.<ecosystem>` | manifests for Python, JavaScript, Java, .NET, Go, PHP, Rust, Swift, Dart |
| `commands` | `cmd.<purpose>` | package scripts, Makefiles, tox, shell scripts, CI run steps |
| `tree` | `struct.tree` | the files Git tracks, so an ignored virtualenv never appears |
| `schema` | `db.<table>` | SQL migrations, Prisma, Alembic, EF, and explicitly named SQLite files |
| `integrations` | `int.<name>` | environment-variable **keys** only |
| `api` | `api.<tag>` | in-repo OpenAPI and Swagger contracts |
| `routes` | `route.<slug>` | HTTP routes declared in source (needs `[code]`) |
| `pages` | `page.<slug>` | UI page routes (file-system routers work without `[code]`) |
| `jobs` | `job.<slug>` | scheduled jobs of framework schedulers (needs `[code]`) |
| `symbols` | `sym.<slug>` | exported names, enum and object members, CSS custom properties (needs `[code]`) |

`tree` also writes `struct.files.<dir>` (every tracked file under one top-level
directory), and every extractor reports into `struct.coverage`. `kb code-ingest` exits `1`
when none of `services`, `deps`, `commands`, `schema`, `integrations` and `api` found
anything: a folder listing alone is a misconfiguration, not knowledge.

Supported frameworks:

- **Routes:** NestJS, Express, Next.js, Nuxt, Spring Boot, Quarkus, Micronaut, ASP.NET Core,
  FastAPI, Flask, Django, Gin, Laravel, Symfony, Actix Web, Axum, Rocket, Vapor.
- **Pages:** Next.js, Nuxt, SvelteKit, Angular, Vue, React (react-router), Flutter (go_router).
- **Jobs:** NestJS, Spring / Quarkus / Micronaut, Hangfire, Quartz and .NET hosted services,
  Celery, Laravel, Symfony, node-cron, BullMQ, robfig/cron, tokio-cron-scheduler,
  Kubernetes `CronJob`.

The four source-reading extractors cover JS/TS, Java/Kotlin, C#, Python, PHP, Go, Rust, Swift
and Dart, plus CSS/SCSS custom properties. The `tree-sitter-language-pack` pin is exact so
the same commit gives the same bytes on every machine. Only names are emitted; env values,
constant values and enum member values never are.

**Two security properties.** (1) The integrations extractor emits **keys, never values**: the
only env file it opens is `.env.example`, `.sample` or `.template`, never a real `.env`, and
its pattern has no capture group around the value, so there is nothing to leak. Compose
`environment:` blocks are read, but only the key survives. (2) SQLite schema input is
**`--db`-only, never inferred**: a stray `.db` or `.sqlite` in the repo is never read unless
you name it, so it cannot become published company knowledge by accident.

**`struct.coverage`** tells the SA how far to trust an absence: one table,
`Area | Scope | Framework/language | Status | Detail`, for `routes`, `pages`, `jobs`,
`symbols`, `files` and `schema`.

| Status | Meaning |
|---|---|
| `complete` | Every recognised form in that scope was resolved |
| `partial` | Something was seen but not resolved (a dynamic route path, a file that does not parse); each site is named as `file:line` |
| `not scanned` | Nothing was looked at; the detail says why (extra missing, no adapter) |

`jobs` is never `complete`: a job can live where no adapter looks (`pg_cron`, a hand-written
`setInterval`, a crontab), so its row is always `partial` with the detail `jobs outside
framework schedulers are not detectable`. For a route, page, symbol, file or a table's
partition, index or primary key, the SA writes a new thing as new only when that scope is
`complete`: `<thing> in <path> [NEW: D<n>]` for a route, page or symbol, and `<path> [NEW: D<n>]`
as its own `Files:` entry for a file. Otherwise it is an `Open decisions` item that quotes the
status, and `kb ticket check` enforces it.

Stated limits: `schema` replays `CREATE TABLE`, `ALTER TABLE ... ADD COLUMN` and index and key
statements in sorted filename order and implements no SQL dialect; a statement it cannot apply
makes the scope `partial` and names `file:line`; EF Core migrations are recognised by table name
only; `build.gradle` is matched by regex. If `.kb/<doc_id>/` already holds a document that
`kb code-ingest` did not write, it exits 1 and writes nothing (no override flag; move the
document or pick another `--doc-id`). Re-running on the same commit and platform produces
byte-identical files; the manifest revision comes from `HEAD`, so a dirty tree prints a
`dirty_tree` warning.

## 6.4 What is enforced, and what is only asked

| Rule | Enforced by |
|---|---|
| The PR carries its evidence | `kb pr lint` in `kb-pr-lint.yml` on every PR: `## Ticket`, `## Changes`, `## Testing` filled in, the pasted test command, a `Blocking: No` line |
| Unreviewed knowledge cannot reach the hub | `kb build` exits 1 while any `-svc` section is `pending` |
| The context cache is CLI-owned | `kb resolve --status-only --cache` refuses a cache whose version, refs or block differ |

`kb pr lint` takes a file or stdin and never a string option: a PR description is
attacker-controlled text, and keeping it out of argv stops a caller from interpolating it into
a shell command.

Everything else is prompt discipline that nothing in `kb` measures; the check is you, at the gate.
Test-first (exemptions in `docs/tdd-exemptions.md`), shown verification, pinned values copied
verbatim, a read-only ticket, GATE 1 and GATE 2, `OPEN(BA)` escalation of an ambiguous
acceptance criterion, and the reviews A1 to A4. Only A5 has teeth, through the `Blocking:` line.

## 6.5 Auto-mode permissions

`kb init --kind dev` writes `.claude/settings.json` (merged into your file). **Allowed:** `git`
add, commit, status, diff, log, fetch, pull, switch to `auto/*`, `fix/*` and `hotfix/*`, branch
creation, worktree, merge and `push -u origin HEAD`; `gh pr` and `gh run`; `Read`, `Edit`, `Write`;
the `strata-kb` MCP tools; many `kb` subcommands; and the test, install, lint and build commands
of your `langs`. **Denied:** any `git push` that names `main` or `master`, force-push, `+` and `:`
refspecs and `--delete`; `git checkout`, `switch` and `branch` forms that move onto, create,
rename or delete `main` or `master`; `git reset --hard`; `gh repo delete`, `gh run delete`;
`kb init`; `rm -rf /*`; and editing `.claude/settings.json`, `.claude/settings.local.json` and
`.git/**`. The same file registers the `Stop` and `SubagentStop` hooks that run
`kb usage ingest-transcript --hook-stdin` for cost reports (`kb usage report`).

## 6.6 Hub Q&A rules that touch you

Questions and answers live in the hub's Q&A store, written only through `kb_question_ask`
(Dev) and `kb_question_answer` (BA). `asked_by` and `answered_by` are names the caller types
(the skills pass `git config user.name`): tracking, not authentication. Any other target than
the hub's HTTP server is refused. Limits: question and answer 4000 characters, context 1000,
names 100, at most 50 open questions per ticket. The MCP tools your skills call are
`kb_search`, `kb_get_section`, `kb_context_new`, `kb_resolve`, `kb_ticket_lint`,
`kb_ticket_check`, `kb_ticket_fetch`, `kb_question_ask` and `kb_question_list`.

## 6.7 Reserved names

`<repo_id>-code` and `<repo_id>-svc` are reserved for this repository's own code knowledge; a
domain document must never take either suffix. Section prefixes are a published contract:

| Prefix | Document | Owner |
|---|---|---|
| `struct.tree`, `struct.files.<dir>`, `struct.coverage`, `db.<table>`, `dep.<eco>`, `int.<name>`, `api.<tag>`, `route.<slug>`, `page.<slug>`, `job.<slug>`, `sym.<slug>`, `cmd.<purpose>` | `-code` | extractor |
| `svc.<name>` | `-code` and `-svc` | extractor (evidence) and you (model-drafted responsibility) |
| `flow.<name>` | `-svc` | you |
| `hist.<name>` | `-svc` | `kb svc note` only |

`svc.<name>` collides across the two documents on purpose: it is the join key that lets a C4
`Container(alias, label, technology, description)` take the first three from `-code` and the
fourth from `-svc`.
